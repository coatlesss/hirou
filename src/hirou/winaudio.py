# hirou/winaudio.py - windows only: list app windows, and record the audio of one app
# (WASAPI process loopback, windows 10 2004+ / windows 11), through plain ctypes so there's no extra dependency.
import ctypes
import os
import threading
import time
import uuid
from ctypes import wintypes as wt

import numpy as np

RATE = 16000  # asked for directly: windows converts, so no resampling needed

_user32, _kernel32, _dwmapi = ctypes.WinDLL('user32'), ctypes.WinDLL('kernel32'), ctypes.WinDLL('dwmapi')
_ole32, _mmdevapi = ctypes.OleDLL('ole32'), ctypes.WinDLL('Mmdevapi')
_user32.GetWindow.restype = wt.HWND
_user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
_kernel32.OpenProcess.restype = wt.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]
_mmdevapi.ActivateAudioInterfaceAsync.restype = ctypes.HRESULT
_mmdevapi.ActivateAudioInterfaceAsync.argtypes = [wt.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                                  ctypes.POINTER(ctypes.c_void_p)]


def _guid(s):
    return (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(s).bytes_le)


IID_IUNKNOWN = bytes(_guid('00000000-0000-0000-C000-000000000046'))
IID_IAGILEOBJECT = bytes(_guid('94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90'))
IID_COMPLETION_HANDLER = bytes(_guid('41D949AB-9862-444A-80F6-C261334DA5EB'))
IID_IAUDIOCLIENT = _guid('1CB9AD4C-DBFA-4C32-B178-C2F568A703B2')
IID_IAUDIOCAPTURECLIENT = _guid('C8ADBD64-E71E-48A0-A4DE-185C395CD317')


def exe_name(pid: int) -> str:
    handle = _kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ''
    try:
        buf, size = ctypes.create_unicode_buffer(260), wt.DWORD(260)
        return os.path.basename(buf.value) if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)) else ''
    finally:
        _kernel32.CloseHandle(handle)


def list_windows() -> list[tuple[str, int, str]]:
    """Visible app windows with a title, as (title, pid, exe name), in z-order (most recently used first)."""
    found, own_pid = [], os.getpid()

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(hwnd, _):
        cloaked = wt.DWORD()
        _dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)  # DWMWA_CLOAKED: hidden store-app windows
        length = _user32.GetWindowTextLengthW(hwnd)
        if _user32.IsWindowVisible(hwnd) and not _user32.GetWindow(hwnd, 4) and not cloaked.value and length:  # 4 = GW_OWNER
            title = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, title, length + 1)
            pid = wt.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != own_pid:
                found.append((title.value, pid.value, exe_name(pid.value)))
        return True

    _user32.EnumWindows(visit, 0)
    return found


def _method(obj, index, *argtypes, restype=ctypes.HRESULT):
    """Method `index` of COM interface pointer `obj`. With the HRESULT restype a failure raises OSError."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return lambda *args: ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])(obj, *args)


class _Blob(ctypes.Structure):
    _fields_ = [('cbSize', wt.ULONG), ('pBlobData', ctypes.c_void_p)]


class _PropVariant(ctypes.Structure):
    _fields_ = [('vt', wt.USHORT), ('r1', wt.WORD), ('r2', wt.WORD), ('r3', wt.WORD), ('blob', _Blob)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [('ActivationType', ctypes.c_int), ('TargetProcessId', wt.DWORD), ('ProcessLoopbackMode', ctypes.c_int)]


class _WaveFormatEx(ctypes.Structure):
    _pack_ = 1
    _fields_ = [('wFormatTag', wt.WORD), ('nChannels', wt.WORD), ('nSamplesPerSec', wt.DWORD),
                ('nAvgBytesPerSec', wt.DWORD), ('nBlockAlign', wt.WORD), ('wBitsPerSample', wt.WORD), ('cbSize', wt.WORD)]


class _CompletionHandler:
    """The smallest COM object ActivateAudioInterfaceAsync accepts: it has to say it's agile (IAgileObject)."""

    def __init__(self):
        self.done = threading.Event()
        qi = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
        ref = ctypes.WINFUNCTYPE(wt.ULONG, ctypes.c_void_p)
        completed = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
        # shortcut: AddRef/Release don't count; the owner keeps this object alive for the whole capture
        self._funcs = [qi(self._query_interface), ref(lambda this: 1), ref(lambda this: 1),
                       completed(lambda this, op: self.done.set() or 0)]
        self._vtable = (ctypes.c_void_p * 4)(*[ctypes.cast(f, ctypes.c_void_p) for f in self._funcs])
        self._object = ctypes.c_void_p(ctypes.addressof(self._vtable))  # a COM object starts with its vtable pointer
        self.pointer = ctypes.addressof(self._object)

    @staticmethod
    def _query_interface(this, riid, out):
        if ctypes.string_at(riid, 16) in (IID_IUNKNOWN, IID_IAGILEOBJECT, IID_COMPLETION_HANDLER):
            out[0] = this
            return 0
        out[0] = None
        return -2147467262  # E_NOINTERFACE


class ProcessLoopback:
    """Records what process `pid` and its child processes play (a browser plays audio from a child process),
    as 16 kHz mono float32 blocks passed to `on_audio`. Raises right away if windows won't capture it."""

    def __init__(self, pid: int, on_audio):
        self._on_audio = on_audio
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error = None
        self._thread = threading.Thread(target=self._run, args=(pid,), daemon=True, name='ProcessLoopback')
        self._thread.start()
        self._ready.wait()
        if self._error:
            raise self._error

    def stop(self):
        self._stop.set()
        self._thread.join()

    def _activate(self, pid):
        params = _ActivationParams(1, pid, 0)  # PROCESS_LOOPBACK, INCLUDE_TARGET_PROCESS_TREE
        prop = _PropVariant(vt=65, blob=_Blob(ctypes.sizeof(params), ctypes.addressof(params)))  # VT_BLOB
        self._handler = _CompletionHandler()
        self._operation = ctypes.c_void_p()
        _mmdevapi.ActivateAudioInterfaceAsync('VAD\\Process_Loopback', ctypes.addressof(IID_IAUDIOCLIENT),
                                              ctypes.addressof(prop), self._handler.pointer, ctypes.byref(self._operation))
        if not self._handler.done.wait(10):
            raise TimeoutError('windows did not answer the audio capture request')
        hr, client = ctypes.c_long(), ctypes.c_void_p()
        _method(self._operation, 3, ctypes.c_void_p, ctypes.c_void_p)(ctypes.byref(hr), ctypes.byref(client))  # GetActivateResult
        if hr.value < 0:
            raise ctypes.WinError(hr.value)
        return client

    def _run(self, pid):
        _ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
        try:
            client = self._activate(pid)
            fmt = _WaveFormatEx(1, 1, RATE, RATE * 2, 2, 16, 0)  # 16 kHz mono 16-bit PCM
            flags = 0x00020000 | 0x80000000 | 0x08000000  # LOOPBACK | AUTOCONVERTPCM | SRC_DEFAULT_QUALITY
            _method(client, 3, ctypes.c_int, wt.DWORD, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_void_p,
                    ctypes.c_void_p)(0, flags, 2_000_000, 0, ctypes.addressof(fmt), None)  # Initialize, 200 ms buffer
            capture = ctypes.c_void_p()
            _method(client, 14, ctypes.c_void_p, ctypes.c_void_p)(ctypes.addressof(IID_IAUDIOCAPTURECLIENT),
                                                                  ctypes.byref(capture))  # GetService
            _method(client, 10)()  # Start
        except Exception as e:
            self._error = e
            self._ready.set()
            _ole32.CoUninitialize()
            return
        self._ready.set()
        next_size = _method(capture, 5, ctypes.c_void_p)
        get_buffer = _method(capture, 3, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        release_buffer = _method(capture, 4, ctypes.c_uint32)
        packet, data, frames, buffer_flags = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_uint32(), wt.DWORD()
        try:
            while not self._stop.is_set():
                time.sleep(0.05)
                blocks = []
                next_size(ctypes.byref(packet))
                while packet.value:
                    get_buffer(ctypes.byref(data), ctypes.byref(frames), ctypes.byref(buffer_flags), None, None)
                    if buffer_flags.value & 2:  # AUDCLNT_BUFFERFLAGS_SILENT
                        blocks.append(np.zeros(frames.value, np.float32))
                    else:
                        raw = ctypes.string_at(data, frames.value * 2)
                        blocks.append(np.frombuffer(raw, '<i2').astype(np.float32) / 32768)
                    release_buffer(frames.value)
                    next_size(ctypes.byref(packet))
                if blocks:
                    self._on_audio(np.concatenate(blocks))
        finally:
            _method(client, 11)()  # Stop
            for obj in (capture, client, self._operation):
                _method(obj, 2, restype=wt.ULONG)()  # Release
            _ole32.CoUninitialize()
