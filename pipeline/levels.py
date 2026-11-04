"""Score every immersion video on the CEFR scale and write the order, easy to hard.

The scale is fitted to recordings whose CEFR level is known (graded.py): the official
DELE exam listening tasks and teachers' talks tagged with the level they are meant for.
Nine measures of each recording's speech are fitted to its level (ridge regression on
standardised measures), and the fit scores every video on the same scale; it is then
stretched piecewise so the median recording of each level from A1 to B2 lands on 0
(A1), 1 (A2), 2 (B1) and 3 (B2), the middle of that level on the scale the app shows.
C1 and C2 recordings are too few to anchor, and the scale runs on beyond B2 and below
A1 at the average slope. The measures:
- speaking rate: syllables per second of speech, pauses left out;
- the share of words at each level from A2 to C1, and of words not graded at all, by
  the level at which ELELex, a lexicon of the words in graded textbooks and readers
  per CEFR level (CENTAL, UCLouvain, CC BY-NC-SA 4.0, in build/ELELex.tsv from
  cental.uclouvain.be/cefrlex/elelex), first grades their lemma; one share per level
  rather than one cutoff, so a B2 word weighs more than an A2 one;
- subordinators (que, porque, cuando ... as clause markers) per word;
- share of verbs in a past tense;
- object clitics (lo, le, se ...) per word.
Each is a rate, so a short recording and an hour-long video compare. Pauses are measured
too (pause share, below) but left out of the fit, because a DELE recording's silences are
time left for answers. Dreaming Spanish's own labels (superbeginner to advanced) are not
used for the fit; how well the scale orders them is printed as an outside check.

Speaking rate and pauses are two measures because they are two things for a listener: a
story told fast with long pauses for pictures gives time between sentences, a steady slow
talk without pauses gives none. Both come from the word timings of YouTube's speech
recognition track; a word lasts until the next one starts, but at most its syllables at
the video's own median syllable length plus PAUSE seconds, and the rest of the gap is a
pause. Videos with only a plain transcript get the median of both.

Videos come from data/videos.json, kept when data/classes.json calls them immersion and
they are spoken in Spanish: YouTube's speech-recognition track of the video's own audio
("es-orig") exists only for Spanish audio, while a human Spanish subtitle track alone can
be the translation of an English video. Compilations of other videos are left out.

The videos' measures come from measure.py (build/measured.jsonl), which parses each video
once.

Output: build/order.json, one row per video in order of score, with its measures.
"""

import json
import re
import statistics
import sys
from collections import defaultdict

import numpy as np
import spacy

import graded
import measure
from config import BUILD, DATA, ORDER

LEVELS = {"superbeginner": 0, "beginner": 1, "intermediate": 2, "advanced": 3}
MEASURES = ["speaking_sps", "words_a2", "words_b1", "words_b2", "words_c1", "words_unlisted",
            "subordinators", "past", "clitics"]
RIDGE = 5.0
ELELEX = BUILD / "ELELex.tsv"
ELELEX_DOCS = 2
# Levels whose median recording sets the scale, A1 to B2; C1 and C2 have too few
# recordings to anchor.
ANCHORED = 4
BOILERPLATE = 5
REPEAT_SHARE = 0.5


def elelex():
    """The CEFR level of each lemma in ELELex, 0 (A1) to 4 (C1): the lowest level at which
    it occurs in at least ELELEX_DOCS of the graded textbooks and readers, so a word
    a single text happens to use early does not count as early. A lemma under several
    tags takes its lowest level."""
    levels = {}
    with open(ELELEX, encoding="utf-8") as fh:
        head = [h.strip('"') for h in fh.readline().rstrip("\n").split("\t")]
        docs = [head.index(f"nb_doc@{l}") for l in ("a1", "a2", "b1", "b2", "c1")]
        for line in fh:
            cells = [c.strip('"') for c in line.rstrip("\n").split("\t")]
            word = cells[0].lower()
            if "_" in word:
                continue
            level = next((k for k, i in enumerate(docs) if float(cells[i]) >= ELELEX_DOCS), None)
            if level is not None and level < levels.get(word, 5):
                levels[word] = level
    return levels


def label(row):
    if row["channel"] != "Dreaming Spanish":
        return None
    m = re.search("|".join(LEVELS), row["title"], re.I)
    return LEVELS[m.group(0).lower()] if m else None


def ridge(X, y):
    A = np.c_[X, np.ones(len(X))]
    penalty = RIDGE * np.eye(A.shape[1])
    penalty[-1, -1] = 0
    return np.linalg.solve(A.T @ A + penalty, A.T @ y)


def predict(X, w):
    return np.c_[X, np.ones(len(X))] @ w


def rank_correlation(a, b):
    return float(np.corrcoef(np.argsort(np.argsort(a)), np.argsort(np.argsort(b)))[0, 1])


def fit(recordings):
    """A function scoring rows on the recordings' level scale (raw, before calibrate), the
    rank correlation between each recording's level and its score from a fit without
    it (leave-one-out), and the weights."""
    X = np.array([[r[k] for k in MEASURES] for r in recordings])
    mean, std = X.mean(0), X.std(0)
    Z = (X - mean) / std
    y = np.array([r["cefr"] for r in recordings], dtype=float)
    held_out = np.array([predict(Z[[i]], ridge(np.delete(Z, i, 0), np.delete(y, i)))[0]
                         for i in range(len(y))])
    w = ridge(Z, y)
    score = lambda rows: predict((np.array([[r[k] for k in MEASURES] for r in rows]) - mean) / std, w)
    return score, rank_correlation(held_out, y), dict(zip(MEASURES, w))


def calibrate(raw, anchors):
    """Regression pulls every score towards the mean; stretch the scale piecewise so
    each anchor (the median raw score of a CEFR level's graded recordings) lands on its
    level, 0 for A1 to 5 for C2. Beyond the outer anchors the scale runs on at the
    average slope across all levels."""
    top = len(anchors) - 1
    out = np.interp(raw, anchors, list(range(len(anchors))))
    slope = top / (anchors[-1] - anchors[0])
    out[raw < anchors[0]] = (raw[raw < anchors[0]] - anchors[0]) * slope
    out[raw > anchors[-1]] = top + (raw[raw > anchors[-1]] - anchors[-1]) * slope
    return out


def recording_rows(nlp, graded_words):
    """The graded recordings measured like the videos."""
    rows = []
    for name, level in graded.recordings().items():
        words, end = graded.load(name)
        rows.append({"name": name, "cefr": level, **measure.speaking((words, end)),
                     **measure.measures(nlp(" ".join(w for _, w in words)), 0, graded_words)})
    return rows


def repeats(texts, durations):
    """Videos made of other videos of their channel, such as hour-long compilations, from
    {id: (channel, sampled 8-word runs)}. Longest first, a video goes when most of its
    distinctive runs occur in videos of its channel still kept; runs that many videos
    share (channel intros and outros) do not count."""
    owners = defaultdict(set)
    for vid, (channel, grams) in texts.items():
        for g in grams:
            owners[channel, g].add(vid)
    dropped = set()
    for vid in sorted(texts, key=lambda v: -durations[v]):
        channel, grams = texts[vid]
        own = [owners[channel, g] for g in grams if len(owners[channel, g]) <= BOILERPLATE]
        shared = sum(1 for o in own if len(o - dropped - {vid}) > 0)
        if own and shared / len(own) > REPEAT_SHARE:
            dropped.add(vid)
    return dropped


def video_rows():
    """Every immersion video spoken in Spanish that measure.py measured, without
    compilations, and what was skipped."""
    measured = measure.load()
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    rows, texts = [], {}
    skipped = {"lesson": 0, "not measured yet": 0, "no Spanish audio": 0, "repeat of other videos": 0}
    for v in json.load(open(DATA / "videos.json")):
        m = measured.get(v["id"])
        if kinds.get(v["id"]) != "immersion":
            skipped["lesson"] += 1
        elif not m:
            skipped["not measured yet"] += 1
        elif "skip" in m:
            skipped[m["skip"]] += 1
        else:
            row = {k: v.get(k) for k in ("id", "title", "channel", "duration")}
            row.update({k: m[k] for k in m if k not in ("id", "lemmas", "shingles")})
            row["label"] = label(row)
            rows.append(row)
            texts[v["id"]] = (v["channel"], m["shingles"])
    dropped = repeats(texts, {r["id"]: r["duration"] or 0 for r in rows})
    for r in rows:
        if r["id"] in dropped:
            print("repeat of other videos:", r["title"], file=sys.stderr)
    skipped["repeat of other videos"] = len(dropped)
    rows = [r for r in rows if r["id"] not in dropped]
    # Plain transcripts have no timestamps; they get the median speed and pauses.
    for key in ("wpm", "sps", "speaking_sps", "pause_share"):
        median = statistics.median(r[key] for r in rows if r[key])
        for r in rows:
            r[key] = median if r[key] is None else r[key]
    return rows, skipped


def main():
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    words = elelex()
    rows, skipped = video_rows()
    recordings = recording_rows(nlp, words)
    score, cv, weights = fit(recordings)
    by_level = defaultdict(list)
    for r, v in zip(recordings, score(recordings)):
        by_level[r["cefr"]].append(float(v))
    if any(k not in by_level for k in range(ANCHORED)):
        sys.exit("graded recordings missing for some levels: run graded.py transcribe")
    anchors = [float(np.median(by_level[k])) for k in range(ANCHORED)]
    if anchors != sorted(anchors):
        sys.exit(f"graded levels out of order on the fitted scale: {anchors}")
    scores = calibrate(score(rows), anchors)
    for r, v in zip(rows, scores):
        r["score"] = float(v)
    order = sorted(rows, key=lambda r: r["score"])
    for i, r in enumerate(order, 1):
        r["position"] = i
    json.dump(order, open(ORDER, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"{len(order)} videos in order; skipped {skipped}")
    print(f"{len(recordings)} graded recordings, leave-one-out rank correlation with their "
          f"levels {cv:.3f}")
    print("weights:", {k: round(float(v), 2) for k, v in weights.items()})
    print("recordings per level on the CEFR scale:",
          {graded.LEVELS[k]: [round(float(v), 2) for v in sorted(calibrate(np.array(by_level[k]), anchors))]
           for k in sorted(by_level)})
    labels = np.array([r["label"] if r["label"] is not None else -1 for r in rows])
    known = labels >= 0
    print("outside check, Dreaming Spanish's labels: rank correlation "
          f"{rank_correlation(scores[known], labels[known]):.3f}; median per label",
          {name: round(float(np.median(scores[labels == k])), 2) for name, k in LEVELS.items()})

if __name__ == "__main__":
    main()
