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
import unicodedata

from config import BUILD, DATA

TRANSLATIONS = BUILD / "translations.json"
# Kept by the translators but not worth a card: an English loanword and the
# spelling variants of y/o before i-/o- sounds.
SKIP_HEADWORDS = {"cool", "e", "u"}
LINKING_WORDS = {"a", "de", "en", "con", "que"}
LIGHT_VERBS = {"estar", "ser", "tener", "hacer", "dar", "darse", "quedar", "quedarse", "poner", "ponerse"}


def fold(text):
    """Lower case without accents or a leading article, as a list of words."""
    plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    return re.sub(r"^(el/la|los/las|el|la|los|las|un|una) ", "", plain).split()


def names_expression(found, word):
    """Whether a translator's headword is the expression pool.py found in the captions.

    The catalog counts the found words per video, so a card for something longer or
    different ("a tiempo" answered as "a tiempo completo") would be introduced for videos
    that never say it. The headword may add a light verb in front ("al loro" as "estar al
    loro"), the reflexive to a leading verb and one linking word at the end ("a medida" as
    "a medida que"). A headword of one word is a spelling of a lemma with its own card
    ("a penas" as "apenas").
    """
    if " " not in word.strip():
        return False
    found, word = fold(found), fold(word)
    if not found or not word:
        return False
    if word[0] in LIGHT_VERBS and word[0] not in (found[0], found[0] + "se"):
        word = word[1:]
    if word and word[0] == found[0] + "se":
        word[0] = found[0]
    return word[:len(found)] == found and len(word) - len(found) <= 1 and set(word[len(found):]) <= LINKING_WORDS


def headword(tr):
    """The word a card teaches, without a noun's article, or None when it makes no card.

    An expression keeps its article: "la verdad" as a filler is not the noun "verdad".
    """
    if not tr.get("keep", True):
        return None
    word = tr.get("word") or ""
    if tr.get("key", "").endswith("|EXPR"):
        return word if names_expression(tr["key"].split("|")[0], word) else None
    head = re.sub(r"^(el/la|los/las|el|la|los|las) ", "", word)
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
         "forms": v["forms"], "example_es": v["example_es"],
         **({"dictionary": v["gloss"]} if v.get("gloss") else {})}
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
