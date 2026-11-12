# hirou/listen.py - listens to what the PC is playing, cuts it into lines and transcribes them with Whisper.
# Audio is only kept in memory until Whisper has read it; just the text is saved.
import glob
import json
import logging
import os
import queue
import re
import sys
import threading

import numpy as np
import pyaudiowpatch as pyaudio
from PyQt6.QtCore import QObject, pyqtSignal

from hirou import winaudio
from hirou.config import SESSION_DIR, config

logger = logging.getLogger(__name__)

SR = 16000  # what Whisper wants
CHUNK_SECONDS = 10
HALLUCINATION = re.compile('ご視聴ありがとう|チャンネル登録')  # Whisper's classic inventions over music and silence


def quietest_cut(audio: np.ndarray, rate: int, search_seconds: float = 4, window_seconds: float = 0.1) -> int:
    """Where to cut `audio`: the middle of its quietest window in the last `search_seconds`, so words aren't split."""
    win, step = int(rate * window_seconds), int(rate * window_seconds / 2)
    start = max(0, len(audio) - int(rate * search_seconds))
    energy = np.convolve(audio[start:] ** 2, np.ones(win), 'valid')[::step]
    return start + int(np.argmin(energy)) * step + win // 2


def to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    """Band-limited resample to 16 kHz: dropping the FFT bins above 8 kHz means nothing aliases."""
    n = int(len(audio) * SR / rate)
    return (np.fft.irfft(np.fft.rfft(audio)[:n // 2 + 1], n) * n / len(audio)).astype(np.float32)


def load_lines() -> list[dict]:
    """Lines heard in earlier sessions: {'text'}."""
    path = os.path.join(SESSION_DIR, 'transcript.jsonl')
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def _add_cuda_dlls():
    """The pip nvidia-cublas/cudnn wheels (and their copies inside the .exe) aren't on the DLL search path."""
    base = sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.join(sys.prefix, 'Lib', 'site-packages')
    for d in glob.glob(os.path.join(base, 'nvidia', '*', 'bin')):
        os.add_dll_directory(d)
        os.environ['PATH'] = d + os.pathsep + os.environ['PATH']


class Listener(QObject):
    """Listens to one app (or everything the default speakers play) and turns each ~10 s of speech into a line of text."""
    status = pyqtSignal(str)  # speech model / error messages
    heard = pyqtSignal(dict)  # a new line: {'text'}
    busy = pyqtSignal(int)  # lines waiting to be transcribed
    level = pyqtSignal(float)  # audio peak, for the meter
    listening = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        os.makedirs(SESSION_DIR, exist_ok=True)
        self.pending = 0
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._pa = None
        self._stop_capture = None
        self.target = 'your speakers'
        self._buf, self._len = [], 0
        threading.Thread(target=self._transcribe_loop, daemon=True, name='Whisper').start()

    @property
    def is_listening(self):
        return self._stop_capture is not None

    def start(self, pid=None, name=None):
        """Listen to app `pid` (with its child processes), or without one to everything the default speakers play."""
        if self._stop_capture:
            return
        self.target = name or 'your speakers'
        self._buf, self._len = [], 0
        try:
            if pid:
                self._rate = winaudio.RATE
                self._stop_capture = winaudio.ProcessLoopback(pid, self._on_audio).stop
            else:
                self._pa = self._pa or pyaudio.PyAudio()
                dev = self._pa.get_default_wasapi_loopback()
                self._rate, channels = int(dev['defaultSampleRate']), dev['maxInputChannels']

                def on_block(data, *_):  # PortAudio's thread
                    self._on_audio(np.frombuffer(data, np.float32).reshape(-1, channels).mean(axis=1))
                    return None, pyaudio.paContinue

                self._stop_capture = self._pa.open(format=pyaudio.paFloat32, channels=channels, rate=self._rate,
                                                   input=True, input_device_index=dev['index'],
                                                   frames_per_buffer=self._rate // 10, stream_callback=on_block).close
        except Exception as e:
            logger.exception('Could not start listening')
            self._stop_capture = None
            return self.status.emit(f'⚠ Could not listen to {self.target}: {e}')
        logger.info(f'Listening to {self.target}')
        self.listening.emit(True)

    def stop(self):
        if not self._stop_capture:
            return
        self._stop_capture()
        self._stop_capture = None
        self._flush(final=True)
        self.level.emit(0.0)
        self.listening.emit(False)

    def _on_audio(self, mono):
        # the capture thread: keep it quick, the slow work happens on the Whisper thread
        self.level.emit(float(np.abs(mono).max(initial=0)))
        self._buf.append(mono)
        self._len += len(mono)
        if self._len >= self._rate * CHUNK_SECONDS:
            self._flush(final=False)

    def _flush(self, final):
        audio = np.concatenate(self._buf) if self._buf else np.zeros(0, np.float32)
        cut = len(audio) if final else quietest_cut(audio, self._rate)
        chunk, rest = audio[:cut], audio[cut:]
        self._buf, self._len = ([rest] if len(rest) else []), len(rest)
        if not len(chunk) or np.sqrt(np.mean(chunk ** 2)) < 0.001:  # silence: Whisper invents text on it
            return
        self._set_pending(+1)
        self._queue.put(to_16k(chunk, self._rate))

    def _set_pending(self, delta):
        with self._lock:
            self.pending += delta
            n = self.pending
        self.busy.emit(n)

    def _load_model(self):
        from faster_whisper import WhisperModel  # slow import, kept off the startup path
        _add_cuda_dlls()
        self.status.emit('Loading speech model (the first start downloads ~1.6 GB)…')
        try:
            model = WhisperModel(config['model'], device='cuda', compute_type='float16')
            list(model.transcribe(np.zeros(SR, np.float32), language='ja')[0])  # cuDNN loads lazily: fail here, not mid-episode
            where = 'GPU'
        except Exception as e:
            logger.warning(f'GPU speech model failed ({e}), using the CPU instead')
            model = WhisperModel(config['model'], device='cpu', compute_type='int8')
            where = 'CPU'
        logger.info(f"Speech model {config['model']} ready on the {where}")
        self.status.emit(f'Speech model ready ({where}).')
        return model

    def _transcribe_loop(self):
        try:
            model = self._load_model()
        except Exception as e:
            logger.exception('Could not load the speech model')
            return self.status.emit(f'⚠ Could not load the speech model: {e}')
        while True:
            pcm = self._queue.get()
            try:
                segments, _ = model.transcribe(pcm, language='ja', vad_filter=True, condition_on_previous_text=False)
                text = re.sub(r'(.+?)\1{3,}', r'\1', ''.join(s.text for s in segments).strip())  # collapse "((((…" loops
                if text and not HALLUCINATION.search(text):
                    self.heard.emit(self._save_line(text))
            except Exception as e:
                logger.exception('Transcription failed')
                self.status.emit(f'⚠ Transcription error: {e}')
            finally:
                self._set_pending(-1)

    @staticmethod
    def _save_line(text) -> dict:
        line = {'text': text}
        with open(os.path.join(SESSION_DIR, 'transcript.jsonl'), 'a', encoding='utf-8') as f:
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
        logger.info(f'Heard: {text}')
        return line
