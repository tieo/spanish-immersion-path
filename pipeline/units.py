"""The catalog of units the next-unit picker chooses from.

Input: data/order.json (videos with their level score, from levels.py), the videos'
Spanish captions and build/vocab.json (the words that have Anki notes).
Output: data/units.json with
- "lemmas": every lemma spoken in any unit, with its Zipf frequency in Spanish and the
  key of its Anki note ("lemma|POS") when it has one;
- "units": per unit its kind, title, channel, series, length, level, whether it works as
  audio only, its number of spoken words and how often each lemma occurs in it (as
  [lemma index, count] pairs), from which the picker computes how much of the unit a
  learner's known words cover.

A video's series is its title without the episode number and the level: Dreaming
Spanish titles end in "- Beginner Spanish - Personal Stories #45", Easy Spanish numbers
"Super Easy Spanish 135" and "Easy Spanish 168". Episodes of one series reuse their
words, which helps them stick (Rodgers & Webb 2011), so the picker prefers to stay in
a series for a while.

Whether a video works as audio only is a first guess from the title: talk formats
(podcasts, conversations, interviews) do, and everything at intermediate
level and above does, while easier videos lean on what is shown. The learner's
feedback corrects it per unit.
"""

import collections
import json
import re
import sys

import spacy
from wordfreq import zipf_frequency

from captions import load_chunks, speech
from config import BUILD, DATA

AUDIO_WORDS = re.compile(r"podcast|conversation|conversación|interview|entrevista|charla|"
                         r"\btalk|opinion|debate", re.I)
LEVEL_WORDS = re.compile(r"\b(super ?beginner|beginner|intermediate|advanced|super easy|easy)\b"
                         r"( spanish)?|\(?a1-a2\)?|\bspanish (for|with)\b.*$", re.I)
AUDIO_LEVEL = 2.0
# Cards made from sound annotations that are not left out with the bracketed sound tags:
# "Ovaciones." written without brackets, and the noun "lloro" ([lloros]), whose
# spoken form is only ever the verb ("casi lloro"), which the llorar card teaches.
UNSPOKEN = {"ovación", "lloro"}


def series(row):
    title = row["title"]
    m = re.match(r"^(.*?)\s+\d+$", title.split(" | ")[-1].strip())
    if " | " in title and m:
        return m.group(1)
    parts = [p.strip() for p in re.split(r" - | \| ", title)]
    tail = [p for p in parts[1:] if not LEVEL_WORDS.fullmatch(p) and not re.fullmatch(r".*spanish", p, re.I)]
    if tail:
        return f"{row['channel']}: {re.sub(r'\s*#?\d+$', '', tail[-1])}"
    return row["channel"]


def main():
    order = json.load(open(DATA / "order.json"))
    notes = {e["lemma"]: f"{e['lemma']}|{e['pos']}" for e in json.load(open(BUILD / "vocab.json"))
             if e["lemma"] not in UNSPOKEN}
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    index, lemmas, units = {}, [], []
    for k, v in enumerate(order):
        counts = collections.Counter()
        # Sound tags of the captions ([música], [resoplido]) are not spoken.
        for tok in nlp(" ".join(speech(" ".join(c for _, c in load_chunks(v["id"])).split()))):
            if not tok.is_alpha or tok.pos_ == "PROPN":
                continue
            lemma = tok.lemma_.lower()
            if lemma not in index:
                index[lemma] = len(lemmas)
                lemmas.append({"lemma": lemma, "zipf": zipf_frequency(lemma, "es"),
                               "note": notes.get(lemma)})
            counts[index[lemma]] += 1
        units.append({
            "id": v["id"], "kind": "video", "title": v["title"], "channel": v["channel"],
            "series": series(v), "duration": v["duration"], "level": round(v["score"], 3),
            "audio": bool(AUDIO_WORDS.search(v["title"])) or v["score"] >= AUDIO_LEVEL,
            "words": sum(counts.values()), "lemmas": sorted(counts.items()),
        })
        print(f"\r{k + 1}/{len(order)} units", end="", file=sys.stderr)
    print(file=sys.stderr)
    json.dump({"lemmas": lemmas, "units": units}, open(DATA / "units.json", "w"),
              ensure_ascii=False, separators=(",", ":"))
    by_series = collections.Counter(u["series"] for u in units)
    print(f"{len(units)} units, {len(lemmas)} lemmas, {sum(1 for l in lemmas if l['note'])} with notes, "
          f"{sum(u['audio'] for u in units)} audio-only, {len(by_series)} series; biggest:",
          by_series.most_common(8))


if __name__ == "__main__":
    main()
