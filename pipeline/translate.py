"""Batches for the translators and merging what they return.

  batches [size]   write build/batches/batch_NNN.json for every word whose example has
                   no translation yet (new word, or its example sentence changed)
  merge            fold build/translated/*.json into build/translations.json, each record
                   remembering the Spanish example it was translated from

Translators follow TRANSLATE.md: one output file per batch, same name, in
build/translated/. data/overrides.json holds hand corrections; they change only the
fields they name and win over any translator output.
"""

import glob
import json
import os
import re
import sys

from config import BUILD, DATA

TRANSLATIONS = BUILD / "translations.json"
# Kept by the translators but not worth a card: an English loanword and the
# spelling variants of y/o before i-/o- sounds.
SKIP_HEADWORDS = {"cool", "e", "u"}


def headword(tr):
    """The translated word without its article, or None when it makes no card."""
    if not tr.get("keep", True):
        return None
    head = re.sub(r"^(el/la|los/las|el|la|los|las) ", "", tr.get("word") or "")
    return None if head in SKIP_HEADWORDS else head


def load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except FileNotFoundError:
        return default


def batches(size):
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    done = load(TRANSLATIONS, {})
    todo = [
        {"key": f"{v['lemma']}|{v['pos']}", "lemma": v["lemma"], "pos": v["pos"],
         "forms": v["forms"], "example_es": v["example_es"]}
        for v in vocab
        if done.get(f"{v['lemma']}|{v['pos']}", {}).get("example_es") != v["example_es"]
    ]
    os.makedirs(BUILD / "batches", exist_ok=True)
    start = len(glob.glob(str(BUILD / "batches" / "batch_*.json")))
    for i in range(0, len(todo), size):
        name = BUILD / "batches" / f"batch_{start + i // size:03d}.json"
        json.dump(todo[i:i + size], open(name, "w"), ensure_ascii=False, indent=1)
        print(name.name, len(todo[i:i + size]))
    print(f"{len(todo)} words to translate")


def merge():
    done = load(TRANSLATIONS, {})
    for out in sorted(glob.glob(str(BUILD / "translated" / "batch_*.json"))):
        source = {x["key"]: x for x in json.load(open(BUILD / "batches" / os.path.basename(out)))}
        for item in json.load(open(out, encoding="utf-8")):
            if item["key"] in source:
                item["example_es"] = source[item["key"]]["example_es"]
                done[item["key"]] = item
    for fix in load(DATA / "overrides.json", []):
        if fix["key"] in done:
            done[fix["key"]].update(fix)
    json.dump(done, open(TRANSLATIONS, "w"), ensure_ascii=False, indent=1)
    print(f"{len(done)} translations")


if __name__ == "__main__":
    if sys.argv[1] == "batches":
        batches(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    else:
        merge()
