"""Which cards a learner who speaks English and German understands on first hearing.

  batches [size]   write build/obvious_batches/batch_NNN.json for every note in
                   build/note_fields.json without a verdict yet
  merge            fold build/obvious_out/*.json into build/obvious.json, {key: bool}
  recheck [size]   write build/obvious_recheck_batches/ for every note judged obvious
  recheck-merge    keep a note obvious only where build/obvious_recheck_out/ agrees

A language model decides by OBVIOUS.md, and a second pass over the obvious ones keeps only
those it judges obvious again: a card counted as obvious is never taught, so a mistake there
costs more than one the other way. units.py marks the obvious words in the catalog,
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
RECHECK_BATCHES = BUILD / "obvious_recheck_batches"
RECHECK_OUT = BUILD / "obvious_recheck_out"


def text(html):
    return re.sub(r"\s+", " ", re.sub(r"<(?!/?b>)[^>]+>", " ", html)).strip()


def write_batches(keys, folder, size):
    notes = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    todo = [{"key": k, "word": notes[k]["Word"], "meaning": text(notes[k]["Meaning"]),
             "example": text(notes[k]["Example"])} for k in keys if k in notes]
    os.makedirs(folder, exist_ok=True)
    start = len(glob.glob(str(folder / "batch_*.json")))
    for i in range(0, len(todo), size):
        json.dump(todo[i:i + size], open(folder / f"batch_{start + i // size:03d}.json", "w"),
                  ensure_ascii=False, indent=1)
    print(f"{len(todo)} notes in {(len(todo) + size - 1) // size} batches")


def verdicts(folder):
    out = {}
    for path in sorted(glob.glob(str(folder / "batch_*.json"))):
        for item in json.load(open(path, encoding="utf-8")):
            if isinstance(item.get("obvious"), bool):
                out[item["key"]] = item["obvious"]
    return out


def merge(update):
    json.dump(update, open(OBVIOUS, "w"), ensure_ascii=False, indent=0)
    print(f"{sum(update.values())} obvious of {len(update)}")


if __name__ == "__main__":
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    done = load(OBVIOUS, {})
    if sys.argv[1] == "batches":
        notes = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
        write_batches([k for k in notes if k not in done], BATCHES, size)
    elif sys.argv[1] == "merge":
        merge({**done, **verdicts(OUT)})
    elif sys.argv[1] == "recheck":
        write_batches([k for k, v in done.items() if v], RECHECK_BATCHES, size)
    elif sys.argv[1] == "recheck-merge":
        again = verdicts(RECHECK_OUT)
        merge({k: v and again.get(k, False) for k, v in done.items()})
