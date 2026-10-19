"""The Anki package: one sub-deck per video, in watching order.

Input (build/): vocab.json from words.py, translations.json from translate.py, ipa.json,
audio.json and media/ from ipa.py and audio.py; data/order.json for the video titles.
Output: build/deck.apkg.

Note GUIDs derive from "lemma|POS", and the note type and deck ids are fixed (a deck's id
from its video id), so a rebuild updates notes in place on re-import and the learner keeps
their scheduling. Sub-deck names start with the watching position, zero-padded, so Anki
lists them in order. Each note is tagged with the position of every video the word is
heard in (v001, v002, ...), for a custom study session after watching a video.
"""

import hashlib
import json
import os
import re

import genanki

from config import BUILD, DATA
from translate import headword

MODEL_ID = 1729384001
ROOT = "Spanish Immersion Path"
POS_NAMES = {
    "NOUN": "noun", "VERB": "verb", "AUX": "verb", "ADJ": "adjective", "ADV": "adverb",
    "ADP": "preposition", "PRON": "pronoun", "DET": "determiner", "CCONJ": "conjunction",
    "SCONJ": "conjunction",
}

CSS = """
.card { font-family: system-ui, sans-serif; font-size: 22px; text-align: center;
        color: #222; background: #fafafa; }
.word { font-size: 40px; font-weight: 600; margin: 12px 0 4px; }
.pos { font-size: 15px; color: #888; }
.ipa { font-size: 19px; color: #555; font-family: "Charis SIL", "Doulos SIL", "Noto Sans", serif; }
.ipa small { font-size: 12px; color: #999; font-family: system-ui, sans-serif; }
.example { font-size: 20px; margin-top: 18px; color: #333; }
.example b { color: #c0392b; }
.meaning { font-size: 28px; margin: 14px 0; }
.example-en { font-size: 18px; color: #555; font-style: italic; }
.source { font-size: 14px; margin-top: 18px; }
.source a { color: #2980b9; }
.more { font-size: 16px; margin-top: 16px; text-align: left; }
.more summary { font-size: 15px; color: #2980b9; cursor: pointer; text-align: center; }
.more div { margin: 6px 0; }
.more b { color: #c0392b; }
.more a { color: #2980b9; font-size: 13px; }
.nightMode .card, .card.nightMode { color: #eee; background: #222; }
.nightMode .example { color: #ddd; }
.nightMode .example-en { color: #aaa; }
"""

MODEL = genanki.Model(
    MODEL_ID,
    "Spanish Immersion Word",
    fields=[
        {"name": "Key"},
        {"name": "Word"},
        {"name": "PartOfSpeech"},
        {"name": "Meaning"},
        {"name": "Example"},
        {"name": "ExampleEnglish"},
        {"name": "Source"},
        {"name": "MoreExamples"},
        {"name": "HeardAs"},
        {"name": "HeardIn"},
        {"name": "IPA"},
        {"name": "AudioSpain"},
        {"name": "AudioLatinAmerica"},
    ],
    templates=[
        {
            "name": "Spanish to English",
            "qfmt": (
                '<div class="word">{{Word}}</div>{{AudioSpain}}'
                '<div class="example">{{Example}}</div>'
            ),
            "afmt": (
                '<div class="word">{{Word}}</div>'
                '{{#IPA}}<div class="ipa">{{IPA}}</div>{{/IPA}}{{AudioLatinAmerica}}'
                '<div class="pos">{{PartOfSpeech}}{{#HeardAs}} · heard as {{HeardAs}}{{/HeardAs}}</div>'
                '<div class="meaning">{{Meaning}}</div>'
                '<div class="example">{{Example}}</div>'
                '<div class="example-en">{{ExampleEnglish}}</div>'
                '<div class="source">{{Source}}</div>'
                '{{#MoreExamples}}<details class="more"><summary>{{HeardIn}}</summary>'
                '{{MoreExamples}}</details>{{/MoreExamples}}'
            ),
        }
    ],
    css=CSS,
)


def ipa_html(word, ipa):
    """Spain and Latin America, or one transcription where they sound the same."""
    head = re.sub(r"^(el/la|los/las|el|la|los|las) ", "", word)
    entry = ipa.get(head)
    if not entry:
        return ""
    if entry["es"] == entry["la"]:
        return f"/{entry['es']}/"
    return f"/{entry['es']}/ <small>Spain</small> · /{entry['la']}/ <small>Latin America</small>"


def deck_id(video):
    return 1_800_000_000 + int(hashlib.sha1(video.encode()).hexdigest()[:8], 16) % 100_000_000


def video_link(video, start, position, title):
    url = f"https://www.youtube.com/watch?v={video}&t={start}s"
    return f'<a href="{url}">#{position} {title}</a>'


def main():
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    trans = json.load(open(BUILD / "translations.json", encoding="utf-8"))
    ipa = json.load(open(BUILD / "ipa.json", encoding="utf-8"))
    audio = json.load(open(BUILD / "audio.json", encoding="utf-8"))
    titles = {v["id"]: v["title"] for v in json.load(open(DATA / "order.json"))}
    known = set(json.load(open(BUILD / "stats.json", encoding="utf-8"))["known_cut_words"])

    decks, media, notes = {}, set(), 0
    dropped, merged, missing, stale = [], [], [], []
    headwords = set()
    for entry in sorted(vocab, key=lambda e: e["watch_position"]):
        key = f"{entry['lemma']}|{entry['pos']}"
        tr = trans.get(key)
        if tr is None:
            missing.append(key)
            continue
        if tr.get("example_es") != entry["example_es"]:
            stale.append(key)
        head = headword(tr)
        if head is None:
            dropped.append(key)
            continue
        word = tr.get("word") or entry["lemma"]
        # Lemmas with attached pronouns (escribirlo, darte) come out of the tagger as
        # separate lemmas but share the corrected headword: the first one in watching
        # order gets the card. Headwords among the known core words stay out.
        if head in known or head in headwords:
            merged.append(key)
            continue
        headwords.add(head)
        video, pos = entry["video"], entry["watch_position"]
        if video not in decks:
            decks[video] = genanki.Deck(deck_id(video), f"{ROOT}::{pos:03d} · {titles[video]}")
        more = "".join(
            f"<div>{m['example_es']}<br>"
            f"{video_link(m['video'], m['start'], m['watch_position'], titles[m['video']])}</div>"
            for m in entry["more"]
        )
        n_more = len(entry["more"])
        sounds = audio.get(word, {})
        note = genanki.Note(
            model=MODEL,
            fields=[
                key, word,
                POS_NAMES.get(entry["pos"], entry["pos"].lower()),
                tr["meaning"], entry["example_es"], tr.get("example_en", ""),
                video_link(video, entry["start"], pos, titles[video]),
                more,
                ", ".join(f for f in entry["forms"] if f != head),
                f"Heard again in {n_more} more video" + ("s" if n_more != 1 else "") if n_more else "",
                ipa_html(word, ipa),
                f"[sound:{sounds['es']}]" if "es" in sounds else "",
                f"[sound:{sounds['la']}]" if "la" in sounds else "",
            ],
            guid=genanki.guid_for(key),
            tags=[f"v{p:03d}" for p in entry["all_positions"]] + [POS_NAMES.get(entry["pos"], "other")],
        )
        decks[video].add_note(note)
        media.update(sounds.values())
        notes += 1
    package = genanki.Package(list(decks.values()))
    package.media_files = sorted(str(BUILD / "media" / m) for m in media)
    package.write_to_file(BUILD / "deck.apkg")
    sizes = sorted(len(d.notes) for d in decks.values())
    print(f"notes {notes} in {len(decks)} videos (per video min {sizes[0]}, "
          f"median {sizes[len(sizes) // 2]}, max {sizes[-1]}); audio files {len(media)}")
    print(f"dropped {len(dropped)}, merged {len(merged)}, untranslated {len(missing)}, "
          f"translated from an older example {len(stale)}")
    # Cards per video for the progress page.
    per_video = {}
    for video, d in decks.items():
        per_video[video] = len(d.notes)
    json.dump(per_video, open(BUILD / "cards_per_video.json", "w"), indent=1)


if __name__ == "__main__":
    main()
