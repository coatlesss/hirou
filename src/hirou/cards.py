# hirou/cards.py - which JLPT words were heard
import csv
import os
import re

from hirou.config import RESOURCES

# Tokens that are never vocab cards: particles, auxiliaries, punctuation, fillers,
# dependent forms (the いる in 見ている), numbers and suffixes.
SKIP_POS = {'助詞', '助動詞', '記号', 'フィラー'}
SKIP_DETAIL = {'非自立', '数', '接尾'}


def keys(expression: str) -> list[str]:
    """'やはり; やっぱり' -> both spellings; 'ございます (かん)' -> drop the note; '～円' affixes are skipped."""
    expression = re.sub(r'\(.*?\)|（.*?）', '', expression)
    return [k.strip() for k in re.split('[;；]', expression) if k.strip() and not re.search('[～〜]', k)]


def load_level(level: int) -> list[dict]:
    """The JLPT word list for N`level` (from github.com/jamsinclair/open-anki-jlpt-decks)."""
    with open(os.path.join(RESOURCES, 'jlpt', f'n{level}.csv'), encoding='utf-8-sig', newline='') as f:
        return [{'word': r['expression'], 'reading': r['reading'], 'meaning': r['meaning']} for r in csv.DictReader(f)]


def make_cards(tokenizer, lines: list[str], rows: list[dict]) -> list[dict]:
    """One card per word from `rows` heard in `lines`, most heard first. Each card keeps the spelling that matched
    (`key`), how it was written in the line (`surface`) and the index of the first line it was heard in (`line`)."""
    by_key = {k: r for r in rows for k in keys(r['word'])}
    found = {}
    for i, line in enumerate(lines):
        for t in tokenizer.tokenize(line):
            pos, detail = t.part_of_speech.split(',')[:2]
            if pos in SKIP_POS or detail in SKIP_DETAIL:
                continue
            key = t.base_form if t.base_form in by_key else t.surface
            row = by_key.get(key)
            if not row:
                continue
            card = found.setdefault(id(row), {**row, 'key': key, 'surface': t.surface, 'line': i, 'count': 0})
            card['count'] += 1
    return sorted(found.values(), key=lambda c: -c['count'])
