# hirou/window.py - the HIROU window: the lines it heard, and the flashcards made from them
import os
import shutil
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QListWidget, QMessageBox, QProgressBar, QPushButton,
                             QTabWidget, QVBoxLayout, QWidget)

from hirou import anki, winaudio
from hirou.cards import levels, load_level, make_cards
from hirou.config import APP_NAME, SESSION_DIR, config, save_config
from hirou.listen import load_lines


def _label(size=None, muted=False, bold=False, center=True):
    label = QLabel()
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if center:
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    style = ''.join([f'font-size: {size}px;' if size else '', 'color: gray;' if muted else '',
                     'font-weight: 600;' if bold else ''])
    label.setStyleSheet(style)
    return label


class _RefreshingCombo(QComboBox):
    """Re-reads the open windows every time it's opened."""

    def __init__(self, refresh):
        super().__init__()
        self._refresh = refresh

    def showPopup(self):
        self._refresh()
        super().showPopup()


class Window(QWidget):
    notify = pyqtSignal(str)  # shown as a tray notification
    _anki_done = pyqtSignal(object, bool, str)  # (card, in anki now, message), from the Anki thread
    _decks_loaded = pyqtSignal(list)

    def __init__(self, listener):
        super().__init__()
        self.listener = listener
        self.lines = load_lines()
        self.tokenizer = None  # janome, loaded on first use
        self.cards, self.queue, self.known = [], [], []
        self.levels_text = ''  # e.g. 'N3–N1': the levels the current cards were made for
        self.pending = 0
        self.build_when_idle = False
        self.told_about_tray = False
        self.setWindowTitle(APP_NAME)
        self.resize(640, 720)

        self.model_label = _label(muted=True, center=False)
        self.model_label.setText('Starting the speech model…')
        self.state_label = _label(bold=True, center=False)
        self.listen_btn = QPushButton()
        self.listen_btn.clicked.connect(self.toggle_listening)
        self.level_box = QComboBox()
        for n in range(5, 0, -1):
            self.level_box.addItem(f'N{n}', n)
        self.level_box.setCurrentIndex(max(0, self.level_box.findData(config.getint('level'))))
        self.level_box.currentIndexChanged.connect(self._level_changed)
        self.range_box = QComboBox()
        for text, scope in (('only', 'only'), ('and harder', 'harder'), ('and easier', 'easier')):
            self.range_box.addItem(text, scope)
        self.range_box.setCurrentIndex(max(0, self.range_box.findData(config['level_range'])))
        self.range_box.currentIndexChanged.connect(self._level_changed)
        make_btn = QPushButton('Make flashcards')
        make_btn.clicked.connect(self.make_cards)
        clear_btn = QPushButton('Clear heard lines')
        clear_btn.clicked.connect(self.clear)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setTextVisible(False)
        self.meter.setFixedHeight(8)

        self.target_box = _RefreshingCombo(self._refresh_targets)
        self.target_box.setMinimumWidth(380)
        self.target_box.activated.connect(self._target_chosen)
        self._refresh_targets()
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel('Listen to'))
        target_row.addWidget(self.target_box)
        target_row.addStretch()

        controls = QHBoxLayout()
        for w in (self.listen_btn, QLabel('Level'), self.level_box, self.range_box, make_btn, clear_btn):
            controls.addWidget(w)
        controls.addStretch()

        self.transcript = QListWidget()
        self.transcript.setWordWrap(True)
        self.transcript.setStyleSheet('font-size: 16px;')
        self.transcript.addItems(l['text'] for l in self.lines)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.transcript, 'Heard')
        self.tabs.addTab(self._study_tab(), 'Flashcards')

        layout = QVBoxLayout(self)
        layout.addWidget(self.model_label)
        layout.addWidget(self.state_label)
        layout.addLayout(target_row)
        layout.addLayout(controls)
        meter_row = QHBoxLayout()
        meter_row.addWidget(_label(muted=True, center=False))
        meter_row.itemAt(0).widget().setText('Audio heard')
        meter_row.addWidget(self.meter, 1)
        layout.addLayout(meter_row)
        layout.addWidget(self.tabs, 1)

        listener.status.connect(self.model_label.setText)
        listener.heard.connect(self._on_heard)
        listener.busy.connect(self._on_busy)
        listener.level.connect(lambda peak: self.meter.setValue(min(100, int(peak * 200))))
        listener.listening.connect(self._on_listening)
        self._anki_done.connect(self._on_anki_done)
        self._decks_loaded.connect(self._fill_decks)
        self._on_listening(False, build=False)
        self.show_card()
        threading.Thread(target=self._load_decks, daemon=True).start()

    def _study_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        self.count_label = _label(muted=True)
        self.word_label = _label(44)
        self.freq_label = _label(15, muted=True)
        self.context_label = _label(19)
        self.context_label.setTextFormat(Qt.TextFormat.RichText)
        self.reading_label = _label(22)
        self.meaning_label = _label(16)
        self.answer = QWidget()
        a = QVBoxLayout(self.answer)
        for w in (self.reading_label, self.meaning_label):
            a.addWidget(w)

        def button(text, key, slot):
            b = QPushButton(f'{text}  [{key}]')
            b.setShortcut(key)
            b.clicked.connect(slot)
            return b

        self.show_btn = button('Show answer', 'Space', lambda: self.answer.setVisible(True))
        self.anki_btn = button('Send to Anki', 'A', self.send_to_anki)
        self.nope_btn = button("Don't know", '1', self.dont_know)
        self.know_btn = button('Know', '2', self.know)
        self.deck_box = QComboBox()
        self.deck_box.setEditable(True)
        self.deck_box.setCurrentText(config['deck'])
        self.deck_box.currentTextChanged.connect(self._deck_changed)
        self.anki_label = _label(muted=True)

        self.card_buttons = QWidget()
        b = QVBoxLayout(self.card_buttons)
        for row in ((self.show_btn,), (self.nope_btn, self.know_btn),
                    (self.anki_btn, QLabel('to deck'), self.deck_box)):
            h = QHBoxLayout()
            h.addStretch()
            for w in row:
                h.addWidget(w)
            h.addStretch()
            b.addLayout(h)
        b.addWidget(self.anki_label)

        self.known_title = _label(bold=True, center=False)
        self.known_list = QListWidget()
        self.known_list.setMaximumHeight(140)
        repeat_btn = QPushButton('Quiz me again')
        repeat_btn.clicked.connect(self.repeat)
        known_row = QHBoxLayout()
        known_row.addWidget(self.known_title)
        known_row.addStretch()
        known_row.addWidget(repeat_btn)

        for w in (self.count_label, self.word_label, self.freq_label, self.context_label, self.answer, self.card_buttons):
            v.addWidget(w)
        v.addStretch()
        v.addLayout(known_row)
        v.addWidget(self.known_list)
        return tab

    # ---- listening ----
    def open(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if not self.told_about_tray:
            self.told_about_tray = True
            self.notify.emit(f'{APP_NAME} is still running in the tray. Right-click its icon to quit.')

    def toggle_listening(self):
        if self.listener.is_listening:
            return self.listener.stop()
        self._refresh_targets()  # the chosen app may have restarted with a new pid
        target = self.target_box.currentData()
        if config['listen_to'] and not target:
            message = f"{config['listen_to']} isn't open. Pick what to listen to in the HIROU window."
            self.model_label.setText('⚠ ' + message)
            return self.notify.emit(message)
        self.listener.start(*(target or (None, None)))

    def _refresh_targets(self):
        """Fills "listen to" with the open windows and keeps the chosen app selected. Audio is per app, not per
        window: every chrome window shares one capture, so matching by exe name is enough."""
        self.target_box.clear()
        self.target_box.addItem('Everything (all speakers)', None)
        for title, pid, exe in winaudio.list_windows():
            self.target_box.addItem(f'{title[:60]} — {exe}', (pid, exe))
        chosen = next((i for i in range(1, self.target_box.count())
                       if self.target_box.itemData(i)[1] == config['listen_to']), 0)
        self.target_box.setCurrentIndex(chosen)

    def _target_chosen(self, index):
        target = self.target_box.itemData(index)
        config['listen_to'] = target[1] if target else ''
        save_config()

    def _on_listening(self, on, build=True):
        self.listen_btn.setText(f"{'Stop' if on else 'Start'} listening ({config['hotkey']})")
        self.target_box.setEnabled(not on)
        self._show_state()
        if not on and build and self.lines:
            self.make_cards()  # the episode is over: cards are ready right away

    def _on_heard(self, line):
        self.lines.append(line)
        self.transcript.addItem(line['text'])
        self.transcript.scrollToBottom()
        self._show_state()

    def _on_busy(self, pending):
        self.pending = pending
        self._show_state()
        if not pending and self.build_when_idle:
            self.build_when_idle = False
            self.make_cards()

    def _show_state(self):
        state = f'Listening to {self.listener.target}' if self.listener.is_listening else 'Not listening'
        waiting = f' · {self.pending} waiting to be transcribed' if self.pending else ''
        self.state_label.setText(f'{state} · {len(self.lines)} lines heard{waiting}')

    def clear(self):
        if self.lines and QMessageBox.question(
                self, APP_NAME, f'Delete all {len(self.lines)} heard lines?'
        ) != QMessageBox.StandardButton.Yes:
            return
        shutil.rmtree(SESSION_DIR, ignore_errors=True)
        os.makedirs(SESSION_DIR, exist_ok=True)
        self.lines, self.cards, self.queue, self.known = [], [], [], []
        self.transcript.clear()
        self._show_state()
        self.show_card()

    def _level_changed(self):
        config['level'] = str(self.level_box.currentData())
        config['level_range'] = self.range_box.currentData()
        save_config()

    # ---- flashcards ----
    def make_cards(self):
        if self.pending:  # lines still being transcribed: build once they're in
            self.build_when_idle = True
            return
        ns = levels(self.level_box.currentData(), self.range_box.currentData())
        if self.tokenizer is None:
            from janome.tokenizer import Tokenizer
            self.tokenizer = Tokenizer()
        rows = [r for n in ns for r in load_level(n)]
        self.cards = make_cards(self.tokenizer, [l['text'] for l in self.lines], rows)
        self.levels_text = f'N{ns[0]}' + (f'–N{ns[-1]}' if len(ns) > 1 else '')
        self.queue, self.known = list(self.cards), []
        self.tabs.setCurrentIndex(1)
        self.show_card()
        self.notify.emit(f'{len(self.cards)} {self.levels_text} flashcards ready')

    def show_card(self):
        card = self.queue[0] if self.queue else None
        self.answer.setVisible(False)
        self.card_buttons.setVisible(card is not None)
        self.anki_label.setText('')
        self.freq_label.setText(f"N{card['level']} · heard {card['count']}×" if card else '')
        self.count_label.setText(f'{self.levels_text} · {len(self.queue)} to learn · {len(self.known)} known' if self.cards else '')
        self.known_title.setText(f'Known ({len(self.known)})')
        self.known_list.clear()
        self.known_list.addItems(f"{k['key']} 【{k['reading']}】 {k['meaning']}  · heard {k['count']}×" for k in self.known)
        if card is None:
            self.word_label.setText('You know them all!' if self.cards else 'No flashcards yet')
            self.context_label.setText('Press "Quiz me again" to go through them again.' if self.cards else
                                       'Listen to something, then press Make flashcards (or stop listening).')
            return
        line = self.lines[card['line']]
        self.word_label.setText(card['key'])
        self.context_label.setText(anki.context_html(line['text'], card['surface']))
        self.reading_label.setText(card['reading'] if card['reading'] != card['key'] else '')
        self.meaning_label.setText(card['meaning'])
        self._show_anki_btn(card)
        self.show_btn.setFocus()

    def dont_know(self):
        if self.queue:
            self.queue.append(self.queue.pop(0))  # back of the line: it comes round again
            self.show_card()

    def know(self):
        if self.queue:
            self.known.append(self.queue.pop(0))
            self.show_card()

    def repeat(self):
        self.queue += self.known
        self.known = []
        self.show_card()

    # ---- anki ----
    def send_to_anki(self):
        if not self.queue or self.queue[0].get('sent'):
            return
        card = self.queue[0]
        line, deck = self.lines[card['line']], self.deck_box.currentText().strip() or 'HIROU'
        self.anki_btn.setEnabled(False)
        self.anki_label.setText('Sending to Anki…')
        threading.Thread(target=lambda: self._anki_done.emit(card, *anki.add_card(card, line, deck)),
                         daemon=True, name='AnkiExport').start()

    def _on_anki_done(self, card, in_anki, message):
        card['sent'] = card.get('sent') or in_anki
        self.notify.emit(message)
        if self.queue and self.queue[0] is card:
            self.anki_label.setText(message)
            self._show_anki_btn(card)

    def _show_anki_btn(self, card):
        self.anki_btn.setEnabled(not card.get('sent'))
        self.anki_btn.setText('In Anki ✓' if card.get('sent') else 'Send to Anki  [A]')

    def _deck_changed(self, deck):
        if deck.strip():
            config['deck'] = deck.strip()
            save_config()

    def _load_decks(self):
        try:
            self._decks_loaded.emit(anki.anki_request('deckNames'))
        except Exception:
            pass  # anki is closed: the box still takes a typed deck name

    def _fill_decks(self, decks):
        current = self.deck_box.currentText()
        self.deck_box.blockSignals(True)
        self.deck_box.clear()
        self.deck_box.addItems(decks)
        self.deck_box.setCurrentText(current)
        self.deck_box.blockSignals(False)
