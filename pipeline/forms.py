"""Four fixed forms of every verb, for the back of its card.

  uv run --with verbecc --with lemminflect python forms.py

Spanish verbs are irregular in clusters, and one form stands for each: the "I" form of
the present (quiero: the stem change through the present and the whole present
subjunctive), of the preterite (quise: the whole preterite and the past subjunctive), of
the future (querré: the future and the conditional) and the participle (querido). Every
verb card shows these four in the same order, so the regular pattern is always in the
same place; the letters where a form departs from the regular one are marked, spelling
changes (crucé) included. The few verbs whose "you" command is irregular (di, haz, ten)
show it as a fifth form, and the fully irregular ser, estar, ir and haber their "he/she"
present.

The forms come from verbecc's conjugation tables; a verb it has no table for (it would
only predict one) or fails on gets no forms. Each form's English gloss is the card's meaning
inflected by lemminflect. Output: build/forms.json, {note key: HTML}, which deck.py puts
after the part of speech.
"""

import difflib
import html
import json
import re

from lemminflect import getInflection
from verbecc import CompleteConjugator

from config import BUILD

FORMS = BUILD / "forms.json"
INFINITIVE = re.compile(r"^([a-zñáéíóú]+?(ar|er|ir|ír))(se)?$")
HE_PRESENT = {"ser": "is", "estar": "is", "ir": "goes", "haber": "has"}


def regular(infinitive):
    """The four forms the regular pattern gives."""
    base, ending = infinitive[:-2], infinitive[-2:]
    a = ending == "ar"
    return [base + "o", base + ("é" if a else "í"), infinitive.replace("ír", "ir") + "é",
            base + ("ado" if a else "ido")]


def marked(form, rule):
    """The form with the letters that differ from the rule's form in <i>."""
    differs = [False] * len(form)
    for op, _, _, j1, j2 in difflib.SequenceMatcher(None, rule, form).get_opcodes():
        # Letters left out ("querré" for "quereré") mark the letters on both sides.
        for j in (range(j1, j2) if j2 > j1 else range(max(j1 - 1, 0), min(j1 + 1, len(form)))) \
                if op != "equal" else ():
            differs[j] = True
    out, j = [], 0
    while j < len(form):
        k = j
        while k < len(form) and differs[k] == differs[j]:
            k += 1
        part = html.escape(form[j:k])
        out.append(f"<i>{part}</i>" if differs[j] else part)
        j = k
    return "".join(out)


def glosses(meaning):
    """English for the four forms and the command from the card's meaning ("to want"),
    or None when the meaning is no "to ..." verb."""
    # A verb its example uses pronominally has that sense first; the forms are the plain verb's.
    plain = re.search(r'class="plain">(.*?)</div>', meaning)
    text = re.sub(r"<[^>]+>", " ", plain.group(1) if plain else meaning).strip()
    m = re.match(r"to ([a-z]+)(.*)", re.split(r"[;,(]", text)[0].strip())
    if not m:
        return None
    verb, rest = m.group(1), m.group(2).rstrip()
    past = (getInflection(verb, "VBD") or [verb + "ed"])[0]
    participle = (getInflection(verb, "VBN") or [past])[0]
    return [f"I {verb}{rest}", f"I {past}{rest}", f"I will {verb}{rest}", f"{participle}{rest}", f"{verb}{rest}!"]


def first(moods, mood, tense, person=None):
    for row in moods[mood][tense]:
        if person is None or row.get("pr") == person:
            return row["c"][0].split()[-1]
    return None


def main():
    notes = json.load(open(BUILD / "note_fields.json", encoding="utf-8"))
    conjugator = CompleteConjugator(lang="es")
    out, skipped = {}, 0
    for key, fields in notes.items():
        if not key.endswith(("|VERB", "|AUX")):
            continue
        m = INFINITIVE.match(fields["Word"].strip().lower())
        if not m:
            continue
        infinitive = m.group(1)
        try:
            table = json.loads(conjugator.conjugate(infinitive).to_json())
        except Exception:  # verbecc fails on some rare verbs: no forms rather than wrong ones
            table = {"verb": {"predicted": True}}
        if table["verb"].get("predicted"):
            skipped += 1
            continue
        moods = table["moods"]
        forms = [first(moods, "indicativo", "presente", "yo"),
                 first(moods, "indicativo", "pretérito-perfecto-simple", "yo"),
                 first(moods, "indicativo", "futuro", "yo"),
                 first(moods, "participo", "participo")]
        cells = list(zip(forms, regular(infinitive)))
        english = glosses(fields["Meaning"]) or ["present", "past", "future", "participle", "command"]
        labels = english[:4]
        command, he = first(moods, "imperativo", "afirmativo", "tú"), first(moods, "indicativo", "presente", "él")
        if command and command != he:
            cells.append((command, he))
            labels.append(english[4])
        if infinitive in HE_PRESENT:
            cells.append((he, he))
            labels.append(f"he {HE_PRESENT[infinitive]}")
        out[key] = '<div class="forms">' + "".join(
            f"<div><span>{marked(form, rule)}</span><small>{html.escape(label)}</small></div>"
            for (form, rule), label in zip(cells, labels)) + "</div>"
    json.dump(out, open(FORMS, "w"), ensure_ascii=False)
    print(f"forms for {len(out)} verbs; {skipped} without a conjugation table")


if __name__ == "__main__":
    main()
