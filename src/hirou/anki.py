# hirou/anki.py - cards use ankipop's note type, so they sit with (and look like) your ankipop cards
import html
import logging

import requests

from hirou.config import APP_NAME

logger = logging.getLogger(__name__)

ANKI_CONNECT_URL = 'http://127.0.0.1:8765'

# Same note type as ankipop (E:\desktop\meikiproj\src\meikipop\anki.py): keep these in step with it
MODEL_NAME = 'ankipop'
FIELDS = ['Word', 'Reading', 'Meaning', 'Sentence', 'SentenceMeaning', 'Picture', 'Audio', 'Frequency', 'Context']
FRONT = '<div class="word">{{Word}}</div>'
BACK = """{{FrontSide}}
<hr id=answer>
<div class="reading">{{Reading}}</div>
{{Audio}}
<div class="meaning">{{Meaning}}</div>
{{#Context}}<div class="sentence">{{Context}}</div>{{/Context}}
{{#Picture}}<div class="picture">{{Picture}}</div>{{/Picture}}
{{#Sentence}}<div class="example">{{Sentence}}</div><div class="translation">{{SentenceMeaning}}</div>{{/Sentence}}
{{#Frequency}}<div class="freq">frequency #{{Frequency}}</div>{{/Frequency}}"""
CSS = """.card { font-family: "Noto Sans JP", "Yu Gothic", "Hiragino Sans", "Meiryo", sans-serif; font-size: 20px; text-align: center; }
.word { font-size: 48px; }
.reading { font-size: 24px; opacity: 0.8; }
.meaning { margin: 12px 0; }
.meaning ol { display: inline-block; text-align: left; margin: 0; }
.sentence { font-size: 24px; margin-top: 16px; }
.example { font-size: 18px; margin-top: 16px; }
.translation { font-size: 16px; opacity: 0.6; }
.picture img { max-width: 100%; max-height: 360px; margin-top: 12px; border-radius: 6px; }
.freq { font-size: 12px; opacity: 0.5; margin-top: 8px; }"""


def anki_request(action: str, **params):
    response = requests.post(ANKI_CONNECT_URL, json={'action': action, 'version': 6, 'params': params}, timeout=15).json()
    if response.get('error'):
        raise RuntimeError(response['error'])
    return response.get('result')


def ensure_model():
    if MODEL_NAME not in anki_request('modelNames'):
        anki_request('createModel', modelName=MODEL_NAME, inOrderFields=FIELDS, css=CSS,
                     cardTemplates=[{'Name': 'Recognition', 'Front': FRONT, 'Back': BACK}])


def context_html(text: str, surface: str) -> str:
    """The heard line with the word in bold, like the sentence on an ankipop card."""
    word = html.escape(surface)
    return html.escape(text).replace(word, f'<b>{word}</b>', 1)


def build_note(card: dict, line: dict, deck: str) -> dict:
    word = card['key']
    note = {
        'deckName': deck,
        'modelName': MODEL_NAME,
        'fields': {
            'Word': word,
            'Reading': card['reading'] if card['reading'] != word else '',
            'Meaning': html.escape(card['meaning']),
            'Context': context_html(line['text'], card['surface']),
        },
        'options': {'allowDuplicate': False},
        'tags': [APP_NAME, f"JLPT_N{card['level']}"],
    }
    return note


def add_card(card: dict, line: dict, deck: str) -> tuple[bool, str]:
    """Adds `card` with the line it was heard in. Returns (in anki now, message to show). Blocks: call off the UI thread."""
    word = card['key']
    try:
        ensure_model()
        anki_request('createDeck', deck=deck)  # no-op if the deck exists
        note = build_note(card, line, deck)
        if not anki_request('canAddNotes', notes=[note])[0]:
            return True, f'{word} is already in Anki'
        anki_request('addNote', note=note)
        logger.info(f"Anki: added {word} to '{deck}'")
        return True, f'Added {word} to {deck}'
    except requests.ConnectionError:
        return False, 'Could not reach Anki. Is Anki open with AnkiConnect installed?'
    except Exception as e:
        logger.exception(f'Anki: failed to add {word}')
        return False, f'Could not add {word}: {e}'
