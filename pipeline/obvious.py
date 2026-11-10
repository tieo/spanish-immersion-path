"""Which cards a learner who speaks English and German understands on first hearing.

  batches [size]   write build/obvious_batches/batch_NNN.json for every note in
                   build/note_fields.json without a verdict yet
  merge            fold build/obvious_out/*.json into build/obvious.json, {key: bool}

A language model decides by OBVIOUS.md. units.py marks the obvious words in the catalog,
and the app counts them as known: it never introduces them, and they count toward how
much of a video the learner understands.
"""

import glob
import json
import os
import re
import sys

from config import BUILD
from translate import load

OBVIOUS = BUILD / "obvious.json"
BATCHES = BUILD / "obvious_batches"
OUT = BUILD / "obvious_out"


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<(?!/?b>)[^>]+>", " ", html)).strip()


def batches(size):
    notes = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    done = load(OBVIOUS, {})
    todo = [{"key": k, "word": f["Word"], "meaning": text(f["Meaning"]), "example": text(f["Example"])}
            for k, f in notes.items() if k not in done]
    os.makedirs(BATCHES, exist_ok=True)
    start = len(glob.glob(str(BATCHES / "batch_*.json")))
    for i in range(0, len(todo), size):
        json.dump(todo[i:i + size], open(BATCHES / f"batch_{start + i // size:03d}.json", "w"),
                  ensure_ascii=False, indent=1)
    print(f"{len(todo)} notes in {(len(todo) + size - 1) // size} batches")


def merge():
    done = load(OBVIOUS, {})
    for out in sorted(glob.glob(str(OUT / "batch_*.json"))):
        for item in json.load(open(out, encoding="utf-8")):
            if isinstance(item.get("obvious"), bool):
                done[item["key"]] = item["obvious"]
    json.dump(done, open(OBVIOUS, "w"), ensure_ascii=False, indent=0)
    print(f"{sum(done.values())} obvious of {len(done)}")


if __name__ == "__main__":
    if sys.argv[1] == "batches":
        batches(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    else:
        merge()
