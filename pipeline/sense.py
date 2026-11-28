"""Which examples of an expression card use the expression in the card's sense.

  batches [size]   write build/sense_batches/batch_NNN.json for every expression note in
                   build/note_fields.json
  merge            fold build/sense_out/*.json into build/senses.json, {key: [bool, ...]}

pool.py finds an expression by its words, which often also occur together without forming
it: "en funciones" is the expression (acting, interim) in "la jefa de turno en funciones",
but only "in functions" in "almacenar HTML en funciones". A language model judges each
example by SENSE.md; the first value is the card's main example, the rest its further
examples in order. units.py counts an expression in a video by the share of examples that
fit, and leaves out a card none of whose examples fit.
"""

import glob
import json
import os
import re
import sys

from config import BUILD
from translate import load

SENSES = BUILD / "senses.json"
BATCHES = BUILD / "sense_batches"
OUT = BUILD / "sense_out"


def plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<(?!/?b>)[^>]+>", " ", html)).strip()


def batches(size):
    notes = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    done = load(SENSES, {})
    todo = [{"key": k, "expression": f["Word"], "meaning": plain(f["Meaning"]),
             "examples": [plain(f["Example"])] + [plain(m) for m in re.findall(r"<div>(.*?)<br>", f["MoreExamples"])]}
            for k, f in notes.items() if k.endswith("|EXPR") and k not in done]
    os.makedirs(BATCHES, exist_ok=True)
    for i in range(0, len(todo), size):
        json.dump(todo[i:i + size], open(BATCHES / f"batch_{i // size:03d}.json", "w"), ensure_ascii=False, indent=1)
    print(f"{len(todo)} expression notes in {(len(todo) + size - 1) // size} batches")


def merge():
    done = load(SENSES, {})
    for out in sorted(glob.glob(str(OUT / "batch_*.json"))):
        for item in json.load(open(out, encoding="utf-8")):
            if isinstance(item.get("fits"), list) and all(isinstance(x, bool) for x in item["fits"]):
                done[item["key"]] = item["fits"]
    json.dump(done, open(SENSES, "w"), ensure_ascii=False)
    print(f"{len(done)} judged; main example off sense {sum(1 for v in done.values() if v and not v[0])}, "
          f"none fit {sum(1 for v in done.values() if not any(v))}, under half fit "
          f"{sum(1 for v in done.values() if v and sum(v) < len(v) / 2)}")


if __name__ == "__main__":
    if sys.argv[1] == "batches":
        batches(int(sys.argv[2]) if len(sys.argv) > 2 else 100)
    else:
        merge()
