# hirou/config.py
import configparser
import os
import sys

from platformdirs import PlatformDirs

APP_NAME = 'HIROU'
APP_VERSION = '0.1.0'

DIRS = PlatformDirs('hirou', appauthor=False, ensure_exists=True)
CONFIG_PATH = os.path.join(DIRS.user_config_dir, 'config.ini')
SESSION_DIR = os.path.join(DIRS.user_data_dir, 'session')  # transcript.jsonl: the heard lines, text only
RESOURCES = (os.path.join(sys._MEIPASS, 'hirou', 'resources') if getattr(sys, 'frozen', False)
             else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'resources'))

_parser = configparser.ConfigParser()
_parser.read_dict({'HIROU': {
    'hotkey': 'alt+l',               # start/stop listening
    'listen_to': '',                 # app to listen to, e.g. chrome.exe ('' = everything the speakers play)
    'level': '3',                    # JLPT level the flashcards are made for (5 = N5 ... 1 = N1)
    'level_range': 'only',           # only that level, or with the levels 'harder' (up to N1) or 'easier' (down to N5)
    'deck': 'HIROU',                 # Anki deck for "send to anki"
    'model': 'large-v3-turbo',       # faster-whisper model name
}})
_parser.read(CONFIG_PATH, encoding='utf-8')
config = _parser['HIROU']


def save_config():
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        _parser.write(f)
