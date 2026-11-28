"""The catalog of units the next-unit picker chooses from.

Input: build/order.json (videos with their level score, from levels.py), the lemmas
measure.py counted in each video and build/note_fields.json (the words that have Anki
notes, from deck.py).
Output: build/catalog.npz, which publish.py copies to the app, with
- "meta", UTF-8 JSON: "lemmas", every lemma spoken in any unit, with its Zipf frequency
  in Spanish (see general_zipf; an expression's from these videos), the key of its Anki
  note ("lemma|POS") when it has one, further notes showing the same word ("same", see
  carded_words), and whether the learner understands it on first hearing
  (build/obvious.json, from obvious.py), and "units",
  per unit its kind, title, channel, topic, series, length, level, whether it works as
  audio only and its number of spoken words;
- how often each lemma, or fixed expression with a card (build/expressions.json, from
  pool.py; a "lemma" with spaces, its count scaled by the share of its examples that use
  it in the card's sense, build/senses.json from sense.py), occurs in each unit, as one sparse matrix in rows (unit k's
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
import math
import re
from array import array

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
ARTICLE = re.compile(r"^(el/la|los/las|el|la|los|las) ")


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


def carded_words(fields):
    """The notes by the lemma they are counted under, the further notes that show the same
    word, and the lemmas to count as another. A single-word note is counted under the word
    it shows, which its translator wrote in dictionary form where the lemmatizer slipped
    ("quiniento" shows quinientos); a word two notes show ("queréis" and "querer" both
    show querer) gets one entry, under the note whose lemma is that word or else the
    first. Expressions are counted under their own lemma, as pool.py found them."""
    shown = collections.defaultdict(list)
    for key, f in fields.items():
        lemma, pos = key.rsplit("|", 1)
        if lemma in UNSPOKEN:
            continue
        word = ARTICLE.sub("", f["Word"].lower())
        if pos == "EXPR" or " " in word:
            word = lemma
        shown[pos == "EXPR", word].append(key)
    notes, same, alias = {}, {}, {}
    for (_, word), keys in shown.items():
        keys.sort(key=lambda k: k.rsplit("|", 1)[0] != word)
        notes[word] = keys[0]
        if len(keys) > 1:
            same[keys[0]] = keys[1:]
        for k in keys:
            if k.rsplit("|", 1)[0] != word:
                alias[k.rsplit("|", 1)[0]] = word
    # A lemma that is itself a card's word keeps its own occurrences.
    return notes, same, {lemma: word for lemma, word in alias.items() if lemma not in notes}


def general_zipf(lemma, fields):
    """How common a word is in Spanish (Zipf scale): for a word with a note, of all the
    forms the videos say it in together, so a verb mostly heard conjugated ("me apetece")
    is not rated by its rare infinitive; the lemma alone otherwise."""
    if not fields:
        return zipf_frequency(lemma, "es")
    forms = {lemma, *(f.strip().lower() for f in fields["HeardAs"].split(",") if f.strip())}
    return round(math.log10(sum(10 ** zipf_frequency(f, "es") for f in forms)), 2)


def main():
    order = json.load(open(ORDER))
    measured = measure.Measured()
    topics = {c["name"]: c.get("topic") for c in json.load(open(DATA / "channels.json"))}
    # The words with a note: deck.py made one, the translators kept the word and no
    # other lemma's card teaches the same headword.
    fields = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    notes, same, alias = carded_words(fields)
    expressions = load(BUILD / "expressions.json", {})
    obvious = load(BUILD / "obvious.json", {})
    # The share of an expression's examples that use it in its card's sense (sense.py): its
    # words also occur without forming it, and those occurrences are not the expression.
    senses = load(BUILD / "senses.json", {})
    fit = {lemma: sum(senses[key]) / len(senses[key]) if senses.get(key) else 1.0
           for lemma, key in notes.items() if key.endswith("|EXPR")}
    index, lemmas, units = {}, [], []
    offsets, idx, cnt = [0], array("i"), array("H")
    for v in order:
        counts = collections.Counter()
        for lemma, n in measured[v["id"]]["lemmas"]:
            counts[alias.get(lemma, lemma)] += n
        carded = [(lemma, round(n * fit[lemma])) for lemma, n in expressions.get(v["id"], [])
                  if lemma in notes and round(n * fit[lemma])]
        for lemma, n in list(counts.items()) + carded:
            if lemma not in index:
                index[lemma] = len(lemmas)
                note = notes.get(lemma)
                lemmas.append({"lemma": lemma, "zipf": general_zipf(lemma, note and fields[note]), "note": note,
                               **({"same": same[note]} if note in same else {}),
                               **({"obvious": True} if obvious.get(note) else {})})
            idx.append(index[lemma])
            cnt.append(min(n, 65535))
        offsets.append(len(idx))
        units.append({
            "id": v["id"], "kind": "video", "title": v["title"], "channel": v["channel"],
            "series": series(v), "topic": topics.get(v["channel"]),
            "duration": v["duration"], "level": round(v["score"], 3),
            "audio": bool(AUDIO_WORDS.search(v["title"])) or v["score"] >= AUDIO_LEVEL,
            "words": sum(counts.values()),
        })
    # An expression's frequency is how often it is said in these videos: wordfreq rates a
    # phrase by its words, as if "en funciones" were as common as "funciones".
    spoken = np.bincount(np.asarray(idx), weights=np.asarray(cnt, dtype=float), minlength=len(lemmas))
    total = sum(u["words"] for u in units)
    for i, l in enumerate(lemmas):
        if " " in l["lemma"]:
            l["zipf"] = round(float(np.log10(max(spoken[i], 0.5) / total * 1e9)), 2)
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
