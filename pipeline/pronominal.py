"""Verbs that a card's example uses pronominally ("no te vuelvas a poner ..." is ponerse).

A pronominal verb often means something else than the plain one (poner, to put;
ponerse, to put on, to become, to set oneself), and its pronoun can stand apart from
it, before a verb it depends on. A language model reads each verb card's example
(PRONOMINAL.md) with the verb's pronominal senses from Wiktionary, so a fitting sense
comes from the dictionary rather than being made up; the card then shows the form and
its sense above the plain meaning, and the pronoun in bold in the example.

  batches [size]   write build/pronominal_batches/batch_NNN.json for the verb cards
                   whose example has no judgement yet
  merge            check build/pronominal_out/*.json and fold it into
                   build/pronominal.json

Wiktionary senses: the kaikki.org extract of the English Wiktionary's Spanish entries
(CC BY-SA 4.0), path in KAIKKI_ES (default: phonetix's cache); senses tagged
"reflexive" or "pronominal" are the pronominal ones.
"""

import glob
import gzip
import json
import os
import re
import sys

from config import BUILD
from translate import load

KAIKKI = os.environ.get("KAIKKI_ES", os.path.expanduser("~/projects/code/phonetix/.cache/kaikki/es.jsonl.gz"))
BATCHES = BUILD / "pronominal_batches"
OUT = BUILD / "pronominal_out"
RESULT = BUILD / "pronominal.json"
PRONOUNS = {"me", "te", "se", "nos", "os"}


def mark(example, pronoun):
    """The example with the pronoun that belongs to the bold verb in bold too: the
    nearest one before the verb, where a pronoun standing apart goes."""
    if not pronoun:
        return example
    verb = example.index("<b>")
    before = list(re.finditer(rf"(?<![\w>])({re.escape(pronoun)})(?!\w)", example[:verb], re.I))
    if not before:
        return example
    m = before[-1]
    return example[:m.start()] + f"<b>{m.group(1)}</b>" + example[m.end():]


def shown(entry):
    """The example as a card shows it with this judgement."""
    return mark(entry["example"], entry.get("pronoun")) if entry.get("pronominal") else entry["example"]


def senses(verbs):
    """Pronominal senses per verb, from Wiktionary."""
    found = {}
    with gzip.open(KAIKKI, "rt", encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            if entry.get("pos") != "verb" or entry.get("word") not in verbs:
                continue
            for sense in entry.get("senses", []):
                tags = set(sense.get("tags", []))
                gloss = (sense.get("glosses") or [""])[-1]
                if tags & {"reflexive", "pronominal"} and "form-of" not in tags and gloss:
                    found.setdefault(entry["word"], [])
                    if gloss not in found[entry["word"]]:
                        found[entry["word"]].append(gloss)
    return found


def cards():
    """Verb cards whose headword is not pronominal already, by key."""
    fields = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    return {k: n for k, n in fields.items()
            if k.endswith("|VERB") and not n["Word"].endswith("se") and "<b>" in n["Example"]}


def batches(size):
    done = load(RESULT, {})
    todo = {k: n for k, n in cards().items() if k not in done or shown(done[k]) != n["Example"]}
    found = senses({n["Word"] for n in todo.values()})
    items = [{"key": k, "verb": n["Word"], "example": n["Example"], "senses": found.get(n["Word"], [])}
             for k, n in todo.items()]
    os.makedirs(BATCHES, exist_ok=True)
    start = len(glob.glob(str(BATCHES / "batch_*.json")))
    for i in range(0, len(items), size):
        json.dump(items[i:i + size], open(BATCHES / f"batch_{start + i // size:03d}.json", "w"),
                  ensure_ascii=False, indent=1)
    print(f"{len(items)} verb cards in {(len(items) + size - 1) // size} batches")


def merge():
    done = load(RESULT, {})
    asked = {}
    for path in sorted(glob.glob(str(BATCHES / "batch_*.json"))):
        for item in json.load(open(path, encoding="utf-8")):
            asked[item["key"]] = item
    yes = no = bad = 0
    for path in sorted(glob.glob(str(OUT / "batch_*.json"))):
        for item in json.load(open(path, encoding="utf-8")):
            q = asked.get(item.get("key"))
            if q is None:
                bad += 1
                continue
            entry = {"example": q["example"], "pronominal": bool(item.get("pronominal"))}
            if entry["pronominal"]:
                form, gloss, pronoun = item.get("form") or "", item.get("gloss") or "", item.get("pronoun")
                outside = re.sub(r"<b>.*?</b>", " ", q["example"]).lower().split()
                # The form is the card's verb with a pronoun; a pronoun standing apart is in
                # the example outside the bold verb.
                if (not re.fullmatch(re.escape(q["verb"]) + r"(se|me|te|nos|os)", form) or not gloss
                        or (pronoun and (pronoun.lower() not in PRONOUNS
                                         or pronoun.lower() not in [re.sub(r"\W", "", w) for w in outside]))):
                    bad += 1
                    continue
                sense = item.get("sense")
                entry.update(form=re.sub(r"(me|te|nos|os)$", "se", form), gloss=gloss, pronoun=pronoun,
                             wiktionary=q["senses"][sense] if isinstance(sense, int) and 0 <= sense < len(q["senses"]) else None)
                yes += 1
            else:
                no += 1
            done[item["key"]] = entry
    json.dump(done, open(RESULT, "w"), ensure_ascii=False, indent=1)
    print(f"{yes} pronominal, {no} not, {bad} rejected; {len(done)} in {RESULT.name}")


if __name__ == "__main__":
    if sys.argv[1] == "batches":
        batches(int(sys.argv[2]) if len(sys.argv) > 2 else 200)
    else:
        merge()
