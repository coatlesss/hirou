# python tests/test_cards.py
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from janome.tokenizer import Tokenizer

from hirou.anki import build_note, context_html
from hirou.cards import keys, levels, load_level, make_cards
from hirou.listen import quietest_cut, to_16k

rows = load_level(5)
assert rows[0] == {'word': 'ああ', 'reading': 'ああ', 'meaning': 'Ah!, Oh!', 'level': 5}
assert len(rows) == 718
assert keys('やはり; やっぱり') == ['やはり', 'やっぱり'] and keys('ございます (かん)') == ['ございます'] and keys('～円') == []

cards = make_cards(Tokenizer(), ['昨日、友達に会った。', '友達と映画を見ている', 'やっぱり、いいね'], rows)
words = [c['key'] for c in cards]
assert cards[0]['key'] == '友達' and cards[0]['count'] == 2 and cards[0]['line'] == 0
for w in ['昨日', '会う', '映画', '見る', 'いい']:
    assert w in words, w
assert not any(c['surface'] == 'いる' for c in cards), 'auxiliary いる skipped'
assert context_html('友達に<会った>', '会っ') == '友達に&lt;<b>会っ</b>た&gt;'
assert build_note(cards[0], {'text': '友達'}, 'D')['tags'] == ['HIROU', 'JLPT_N5']

assert levels(3, 'only') == [3] and levels(3, 'harder') == [3, 2, 1] and levels(3, 'easier') == [3, 4, 5]
assert levels(1, 'harder') == [1] and levels(5, 'harder') == [5, 4, 3, 2, 1]
shared = [{'word': '友達', 'reading': 'ともだち', 'meaning': m, 'level': n} for m, n in (('n3 row', 3), ('n5 row', 5))]
assert make_cards(Tokenizer(), ['友達'], shared)[0]['level'] == 3, 'a word on two lists keeps the chosen level'

rate = 1000
audio = np.ones(rate * 10, np.float32)
audio[8000:8200] = 0  # a pause 2 s before the end
assert 8000 <= quietest_cut(audio, rate) <= 8200

t = np.arange(48000) / 48000
low = to_16k(np.sin(2 * np.pi * 1000 * t).astype(np.float32), 48000)  # 1 kHz speech-band tone survives
assert len(low) == 16000 and abs(np.abs(low[1000:-1000]).max() - 1) < 0.01
high = to_16k(np.sin(2 * np.pi * 12000 * t).astype(np.float32), 48000)  # 12 kHz can't fold back into the band
assert np.abs(high).max() < 0.01

print('ok', words)
