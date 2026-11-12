# HIROU (拾う) - pick up japanese words from whatever you're listening to

HIROU sits in the tray and listens to the app you pick: a video, a stream, a podcast, a game. it writes down the japanese it hears, and when you stop it turns the words for your jlpt level (n5 to n1) into flashcards. study them right there, or send them to anki with one key.

it's a companion to [ankipop](https://github.com/coatlesss/ankipop): it works the same way (tray icon, hotkeys, notifications) and its anki cards use the same note type, so they sit with your ankipop cards.

## features

* **listens to one app:** pick the window you're watching in, and HIROU hears that app only, not discord or notification sounds. or pick **everything** to hear all your speakers play.
* **writes it down as you go:** speech recognition runs locally with whisper (large-v3-turbo) on your gpu. a new line shows up about every 10 seconds.
* **flashcards for your level:** pick n5 to n1. every word of that level that was heard becomes a card with its reading, meaning, the line it was heard in, and how many times it was heard. the most heard words come first.
* **study until you know them:** **know** moves a card to the known list, **don't know** keeps it coming back. **quiz me again** starts over as often as you like.
* **one key to anki:** cards go to the deck you pick, without duplicates.
* **nothing recorded:** audio is only kept in memory until it's been turned into text. HIROU saves the text of what it heard and nothing else; no audio files, no screenshots.

## requirements

* windows 10 (version 2004 or newer) or windows 11
* an nvidia gpu is recommended. without one HIROU uses the cpu, which is much slower (about 9 s per 10 s line on a ryzen 9 5900x, against 0.3 s on an rtx 3070)
* [anki](https://apps.ankiweb.net) with the [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on, only for sending cards to anki
* python 3.10+ to run from source or build the .exe

## installation

### run from source

```bash
git clone https://github.com/coatlesss/mirou.git
cd mirou
python -m venv .venv
.venv\Scripts\activate
pip install -e .
hirou
```

### build HIROU.exe

with the environment above activated:

```bash
pip install pyinstaller
pyinstaller --noconfirm hirou.win.x64.spec
```

the result is the folder `dist\HIROU\` (about 2.3 GB, mostly nvidia's cuda libraries). run `HIROU.exe` inside it, and copy the whole folder if you move it. it's a folder rather than one file because a one-file .exe would unpack those libraries again on every start.

the first start downloads the speech model (about 1.6 GB), so it takes a minute.

## how to use

1. start HIROU. its window opens and a 拾 icon appears in the tray. wait for **speech model ready**.
2. in **listen to**, pick the window you're watching in. HIROU remembers the app, so this keeps working after a restart.
3. press `alt+l` (or **start listening**). the icon turns teal, the **audio heard** bar moves, and the **heard** tab fills in.
4. press `alt+l` again when you're done. the flashcards for the chosen level are made straight away. after changing the level, press **make flashcards**.
5. study in the **flashcards** tab.

closing the window keeps HIROU running in the tray. click the tray icon to open it again, right-click it to quit.

heard lines are kept until you press **clear heard lines**, so you can change the level, or close HIROU and come back later.

### keys

| key | what it does |
|-----|--------------|
| `alt+l` | start/stop listening (works anywhere, changeable in the settings) |
| `space` | show the answer |
| `1` | don't know: the card comes back later |
| `2` | know: moves the card to the known list |
| `a` | send the card to anki |

## anki cards

1. keep anki open with AnkiConnect installed.
2. pick a deck in the box next to **send to anki**, or type a new name.
3. press `a` on a card.

cards use the `ankipop` note type (HIROU creates it if you don't have it): the word, its reading and meaning, and the line it was heard in with the word in bold. a word that's already in anki, from HIROU or ankipop, is caught and not added twice.

## settings

`%LOCALAPPDATA%\hirou\config.ini`. the level, deck and app to listen to are also saved from the window.

| key | default | what it does |
|-----|---------|--------------|
| `hotkey` | `alt+l` | start/stop listening, e.g. `ctrl+shift+l` or `f8` |
| `listen_to` | (empty) | app to listen to, e.g. `chrome.exe`; empty = everything the speakers play |
| `level` | `3` | jlpt level for the flashcards (5 = n5 ... 1 = n1) |
| `deck` | `HIROU` | anki deck |
| `model` | `large-v3-turbo` | whisper model; `small` is lighter but worse at japanese |

the heard lines are in `%LOCALAPPDATA%\hirou\session\transcript.jsonl`.

## limits

* windows only lets programs listen per **app**, not per window or tab: picking a chrome window hears all of chrome's tabs.
* with **everything**, switching speakers or headphones while listening needs a stop and start.
* sites that copy-protect their audio may come through silent; the audio bar stays flat then.
* words are matched by their dictionary form (会った → 会う), against the jlpt lists. words outside the lists, and compound words the tokenizer splits in two, don't get cards.
* speech recognition makes mistakes, mostly over loud music or with several people talking at once.

## how it works

1. the audio of the chosen app is captured with windows' process loopback (`src/hirou/winaudio.py`), or of the speakers with wasapi loopback.
2. every ~10 seconds of sound is cut at its quietest moment, so words aren't split, and transcribed with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (`src/hirou/listen.py`).
3. the lines are split into words with [janome](https://github.com/mocobeta/janome), reduced to their dictionary form, and matched against the jlpt list for your level (`src/hirou/cards.py`).

## tests

```bash
python tests/test_cards.py
```

## credits

jlpt word lists from [open-anki-jlpt-decks](https://github.com/jamsinclair/open-anki-jlpt-decks) (based on the lists at tanos.co.uk). speech recognition by [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and openai's whisper, japanese tokenizing by [janome](https://github.com/mocobeta/janome).
