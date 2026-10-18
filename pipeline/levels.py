"""Score every immersion video and write the watching order, easy to hard.

Three measures per video, from its Spanish captions, each turned into a z-score across
all videos and averaged into one difficulty score:
- speed: words per minute of caption time (first to last caption);
- vocabulary: share of spoken words outside the 2,000 most common Spanish words;
- grammar: share of verbs in a subjunctive, conditional, imperfect or preterite form,
  from spaCy's morphology tags.

Videos come from data/videos.json, kept when data/classes.json calls them immersion and
they have Spanish captions. Videos listed in data/watched.json (already seen by the
learner) lead the order as listed; the rest follow by score.

Output: data/order.json, one row per video in watching order.
"""

import json
import re
import statistics
import sys

import spacy
from wordfreq import top_n_list

from captions import load_chunks
from config import DATA

HARD_FORMS = ({"Mood": "Sub"}, {"Mood": "Cnd"}, {"Tense": "Imp"}, {"Tense": "Past"})


def measures(chunks, nlp, common):
    text = " ".join(c for _, c in chunks)
    words = re.findall(r"[a-záéíóúüñ]+", text.lower())
    minutes = (chunks[-1][0] - chunks[0][0]) / 60 if chunks[-1][0] > chunks[0][0] else None
    verbs = hard = 0
    for tok in nlp(text):
        if tok.pos_ in ("VERB", "AUX"):
            verbs += 1
            morph = tok.morph.to_dict()
            if any(all(morph.get(k) == v for k, v in form.items()) for form in HARD_FORMS):
                hard += 1
    return {
        "wpm": len(words) / minutes if minutes else None,
        "rare": sum(1 for w in words if w not in common) / len(words),
        "grammar": hard / verbs if verbs else 0.0,
    }


def main():
    videos = json.load(open(DATA / "videos.json"))
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    try:
        watched = json.load(open(DATA / "watched.json"))
    except FileNotFoundError:
        watched = []
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    common = set(top_n_list("es", 2000))
    rows, skipped = [], {"lesson": 0, "no captions": 0}
    for v in videos:
        if kinds.get(v["id"]) != "immersion" and v["id"] not in watched:
            skipped["lesson"] += 1
            continue
        chunks = load_chunks(v["id"])
        if len(chunks) < 10:
            skipped["no captions"] += 1
            continue
        row = {k: v.get(k) for k in ("id", "title", "channel", "duration")}
        row.update(measures(chunks, nlp, common))
        rows.append(row)
        print(f"\r{len(rows)} scored", end="", file=sys.stderr)
    print(file=sys.stderr)
    # Videos without timestamps (plain transcripts) get the median speed.
    median_wpm = statistics.median(r["wpm"] for r in rows if r["wpm"])
    for r in rows:
        r["wpm"] = r["wpm"] or median_wpm
    for key in ("wpm", "rare", "grammar"):
        mean = statistics.mean(r[key] for r in rows)
        sd = statistics.stdev(r[key] for r in rows)
        for r in rows:
            r[f"z_{key}"] = (r[key] - mean) / sd
    for r in rows:
        r["score"] = (r["z_wpm"] + r["z_rare"] + r["z_grammar"]) / 3
    seen = {vid: i for i, vid in enumerate(watched)}
    first = sorted((r for r in rows if r["id"] in seen), key=lambda r: seen[r["id"]])
    rest = sorted((r for r in rows if r["id"] not in seen), key=lambda r: r["score"])
    order = first + rest
    for i, r in enumerate(order, 1):
        r["position"] = i
        r["watched"] = r["id"] in seen
    json.dump(order, open(DATA / "order.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(order)} videos in order ({len(first)} watched); skipped {skipped}")


if __name__ == "__main__":
    main()
