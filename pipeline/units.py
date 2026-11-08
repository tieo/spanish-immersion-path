"""The catalog of units the next-unit picker chooses from.

Input: build/order.json (videos with their level score, from levels.py), the lemmas
measure.py counted in each video and build/note_fields.json (the words that have Anki
notes, from deck.py).
Output: build/catalog.npz, which publish.py copies to the app, with
- "meta", UTF-8 JSON: "lemmas", every lemma spoken in any unit, with its Zipf frequency
  in Spanish and the key of its Anki note ("lemma|POS") when it has one, and "units",
  per unit its kind, title, channel, topic, series, length, level, whether it works as
  audio only and its number of spoken words;
- how often each lemma, or fixed expression with a card (build/expressions.json, from
  pool.py; a "lemma" with spaces), occurs in each unit, as one sparse matrix in rows (unit k's
  lemmas are "lemma"[offsets[k]:offsets[k+1]], spoken "count" times), from which the app
  computes how much of each unit a learner's known words cover.

A video's series is its title without the episode number and the level: Dreaming
Spanish titles end in "- Beginner Spanish - Personal Stories #45", Easy Spanish numbers
"Super Easy Spanish 135" and "Easy Spanish 168". Episodes of one series reuse their
words, which helps them stick (Rodgers & Webb 2011), so the picker prefers to stay in
a series for a while.

Whether a video works as audio only is a first guess from the title: talk formats
(podcasts, conversations, interviews) do, and everything from AUDIO_LEVEL up (the middle
of A2 to B1, where Dreaming Spanish's intermediate videos sit) does, while easier videos lean on what
is shown. The learner's
feedback corrects it per unit.
"""

import collections
import json
import re

import numpy as np
from wordfreq import zipf_frequency

import measure
from config import BUILD, CATALOG, DATA, ORDER
from translate import load

AUDIO_WORDS = re.compile(r"podcast|conversation|conversación|interview|entrevista|charla|"
                         r"\btalk|opinion|debate", re.I)
LEVEL_WORDS = re.compile(r"\b(super ?beginner|beginner|intermediate|advanced|super easy|easy)\b"
                         r"( spanish)?|\(?a1-a2\)?|\bspanish (for|with)\b.*$", re.I)
AUDIO_LEVEL = 1.5
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
    order = json.load(open(ORDER))
    measured = measure.load()
    topics = {c["name"]: c.get("topic") for c in json.load(open(DATA / "channels.json"))}
    # The words with a note: deck.py made one, the translators kept the word and no
    # other lemma's card teaches the same headword.
    notes = {key.split("|")[0]: key for key in json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
             if key.split("|")[0] not in UNSPOKEN}
    expressions = load(BUILD / "expressions.json", {})
    index, lemmas, units = {}, [], []
    offsets, idx, cnt = [0], [], []
    for v in order:
        counts = measured[v["id"]]["lemmas"]
        for lemma, n in counts + expressions.get(v["id"], []):
            if lemma not in index:
                index[lemma] = len(lemmas)
                lemmas.append({"lemma": lemma, "zipf": zipf_frequency(lemma, "es"), "note": notes.get(lemma)})
            idx.append(index[lemma])
            cnt.append(min(n, 65535))
        offsets.append(len(idx))
        units.append({
            "id": v["id"], "kind": "video", "title": v["title"], "channel": v["channel"],
            "series": series(v), "topic": topics.get(v["channel"]),
            "duration": v["duration"], "level": round(v["score"], 3),
            "audio": bool(AUDIO_WORDS.search(v["title"])) or v["score"] >= AUDIO_LEVEL,
            "words": sum(n for _, n in counts),
        })
    meta = json.dumps({"lemmas": lemmas, "units": units}, ensure_ascii=False, separators=(",", ":"))
    with open(CATALOG, "wb") as fh:
        np.savez_compressed(fh, meta=np.frombuffer(meta.encode(), dtype=np.uint8),
                            offsets=np.array(offsets, dtype=np.int64),
                            lemma=np.array(idx, dtype=np.int32), count=np.array(cnt, dtype=np.uint16))
    by_series = collections.Counter(u["series"] for u in units)
    print(f"{len(units)} units, {len(lemmas)} lemmas, {sum(1 for l in lemmas if l['note'])} with notes, "
          f"{sum(u['audio'] for u in units)} audio-only, {len(by_series)} series; biggest:",
          by_series.most_common(8))


if __name__ == "__main__":
    main()
