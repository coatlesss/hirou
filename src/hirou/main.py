# hirou/main.py
import logging
import os
import signal
import sys

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon
from pynput import keyboard

from hirou.config import APP_NAME, APP_VERSION, RESOURCES, config
from hirou.listen import Listener
from hirou.window import Window


def to_pynput_hotkey(hotkey: str) -> str:
    """'alt+l' -> '<alt>+l', 'f8' -> '<f8>'"""
    return '+'.join(f'<{k}>' if len(k) > 1 else k for k in hotkey.lower().replace(' ', '').split('+'))


class Hotkey(QObject):
    pressed = pyqtSignal()  # emitted on pynput's thread, handled on Qt's


def _icon(name, app):
    path = os.path.join(RESOURCES, name)
    return QIcon(path) if os.path.exists(path) else app.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, datefmt='%H:%M:%S',
                        format=f'%(asctime)s - [%(levelname)-5s] - [{APP_NAME}] - %(message)s')
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    listener = Listener()
    window = Window(listener)

    icon_on, icon_off = _icon('icon.ico', app), _icon('icon.inactive.ico', app)
    tray = QSystemTrayIcon(icon_off)
    tray.setToolTip(APP_NAME)
    menu = QMenu()
    menu.addAction(f'Open {APP_NAME}').triggered.connect(window.open)
    listen_action = menu.addAction('')
    listen_action.triggered.connect(window.toggle_listening)
    menu.addSeparator()
    menu.addAction('Quit').triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and window.open())

    def show_listening(on, announce=True):
        tray.setIcon(icon_on if on else icon_off)
        listen_action.setText(f"{'Stop' if on else 'Start'} listening ({config['hotkey']})")
        if announce:
            tray.showMessage(APP_NAME, f'Listening to {listener.target}' if on else 'Stopped listening')

    listener.listening.connect(show_listening)
    show_listening(False, announce=False)
    window.notify.connect(lambda message: tray.showMessage(APP_NAME, message))
    tray.show()

    def on_error(kind, value, tb):
        # without this, PyQt closes the whole app on an error in a button handler, without a word
        logging.error('Unexpected error', exc_info=(kind, value, tb))
        tray.showMessage(APP_NAME, f'Something went wrong: {value}', QSystemTrayIcon.MessageIcon.Warning)

    sys.excepthook = on_error

    hotkey = Hotkey()
    hotkey.pressed.connect(window.toggle_listening)
    try:
        keyboard.GlobalHotKeys({to_pynput_hotkey(config['hotkey']): hotkey.pressed.emit}).start()
    except ValueError:
        logging.error(f"Invalid hotkey '{config['hotkey']}' in config.ini. Use e.g. 'alt+l', 'ctrl+shift+e' or 'f8'.")

    window.open()
    print(f"\n    {APP_NAME} {APP_VERSION} is running. Press {config['hotkey']} to start/stop listening.\n"
          f"    Right-click the tray icon to open it or quit. Ctrl+C here also quits.\n")
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # lets Python see Ctrl+C while Qt's loop runs
    timer.start(500)
    code = app.exec()
    listener.stop()
    sys.exit(code)


if __name__ == '__main__':
    main()
