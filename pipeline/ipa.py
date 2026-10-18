"""IPA for every card headword, Spain and Latin America.

Sounds come from the Wiktionary-derived Spanish dictionary that ships with phonetix
(assets/dictionaries/es.json.gz, path in PHONETIX_ES_DICT); espeak-ng fills in words it
lacks. That dictionary leaves most stress marks out, and Spanish stress follows from the
spelling: a written accent marks the stressed syllable, otherwise a word ending in a
vowel, n or s stresses the second-to-last syllable and any other the last. The mark goes
in front of the stressed syllable's onset (one consonant, or a stop or f followed by
l or r); one-syllable words carry none.

Latin America follows phonetix's es-419 rules: seseo (θ -> s) and yeísmo (ʎ -> ʝ).

Output: build/ipa.json mapping headword (without article) to {"es": ..., "la": ...}.
"""

import gzip
import json
import re
import subprocess

from config import BUILD, PHONETIX_ES_DICT
ARTICLE = re.compile(r"^(el/la|los/las|el|la|los|las) ")
STRONG, WEAK = set("aeo"), set("iu")
VOWELS = STRONG | WEAK
CLUSTER_FIRST = set("pbβtdðkɡɣgf")
CLUSTER_SECOND = set("lɾ")
ACCENTED = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u"}


def nuclei(sounds, hiatus_weak):
    """Start index of each syllable nucleus in a sequence of vowels and consonants.

    Two strong vowels are two syllables; a weak vowel next to another vowel shares its
    syllable unless the spelling accents it (hiatus_weak)."""
    starts, prev = [], None
    for i, ch in enumerate(sounds):
        if ch not in VOWELS:
            prev = None
            continue
        if prev is None:
            starts.append(i)
        else:
            split = (prev in STRONG and ch in STRONG) or (
                hiatus_weak and (prev in WEAK or ch in WEAK)
            )
            if split:
                starts.append(i)
        prev = ch
    return starts


def spelling_syllables(word):
    """Number of syllables and the stressed one counted from the end (1 = last)."""
    w = word.lower()
    w = re.sub(r"(?<=[qg])u(?=[eéií])", "", w)  # silent u in que, qui, gue, gui
    w = re.sub(r"y$", "i", w)  # final y is a vowel (hoy, muy)
    w = w.replace("ü", "u")
    accent_pos = None
    plain = []
    for ch in w:
        if ch in ACCENTED:
            accent_pos = len(plain)
            plain.append(ACCENTED[ch])
        else:
            plain.append(ch)
    hiatus = any(c in "íú" for c in w)
    starts = nuclei(plain, False)
    if hiatus:
        # An accented í/ú breaks its diphthong: count it as its own nucleus.
        starts = nuclei(plain, True)
    n = len(starts)
    if accent_pos is not None:
        idx = max(i for i, s in enumerate(starts) if s <= accent_pos)
        from_end = n - idx
    elif re.search(r"[aeiouns]$", word.lower()):
        from_end = 2
    else:
        from_end = 1
    return n, min(from_end, n), hiatus


def place_stress(ipa, word):
    """Put the stress mark into an unstressed Wiktionary transcription of one word."""
    n_spelled, from_end, hiatus = spelling_syllables(word)
    if n_spelled < 2:
        return ipa
    sounds = list(ipa)
    starts = nuclei(sounds, hiatus)
    if len(starts) != n_spelled:
        return None
    return mark(sounds, starts[len(starts) - from_end], "ˈ")


def mark(sounds, s, symbol):
    """Insert a stress symbol before the onset of the syllable whose nucleus is at s.

    The onset is a glide before the vowel (ˈbwe, ˈpje) plus the consonant in front of
    it, or two consonants when they are a stop or f followed by l or r (ˈtɾa, ˈβla)."""
    onset = s
    while onset > 0 and sounds[onset - 1] not in VOWELS:
        onset -= 1
    run = sounds[onset:s]
    glides = 1 if run and run[-1] in "jw" else 0
    cons = run[: len(run) - glides]
    if len(cons) >= 2 and cons[-2] in CLUSTER_FIRST and cons[-1] in CLUSTER_SECOND:
        take = 2
    else:
        take = 1 if cons else 0
    cut = s - glides - take
    return "".join(sounds[:cut]) + symbol + "".join(sounds[cut:])


def espeak(word):
    """Fallback transcription, stress moved to the syllable onset."""
    out = subprocess.run(
        ["espeak-ng", "-q", "--ipa", "-v", "es", word], capture_output=True, text=True
    ).stdout.strip().replace("ˌ", "")
    return out


def mente_adverb(word, entry):
    """-mente adverbs keep the adjective's stress as a secondary one: ˌklaɾaˈmente."""
    if not (word.endswith("mente") and entry.endswith("mente") and len(word) > 7):
        return None
    base = place_stress(entry[:-5], word[:-5])
    if base is None:
        return None
    return base.replace("ˈ", "ˌ") + "ˈmente"


def word_ipa(word, dictionary):
    entry = dictionary.get(word.lower())
    if entry and "ˈ" not in entry:
        adverb = mente_adverb(word.lower(), entry)
        if adverb:
            return adverb, "wiktionary"
    if entry and "ˈ" in entry:
        return entry, "wiktionary"
    if entry:
        stressed = place_stress(entry, word)
        if stressed is not None:
            return stressed, "wiktionary"
    return espeak(word), "espeak"


def latin_american(ipa):
    return ipa.replace("θ", "s").replace("ʎ", "ʝ")


def main():
    dictionary = json.load(gzip.open(PHONETIX_ES_DICT))
    translations = json.load(open(BUILD / "translations.json", encoding="utf-8"))
    heads = {ARTICLE.sub("", t["word"]) for t in translations.values()
             if t.get("word") and t.get("keep", True)}
    out, sources = {}, {"wiktionary": 0, "espeak": 0}
    for head in sorted(heads):
        parts = [word_ipa(w, dictionary) for w in head.split() if w.strip("-")]
        for _, src in parts:
            sources[src] += 1
        spain = " ".join(p for p, _ in parts)
        out[head] = {"es": spain, "la": latin_american(spain)}
    json.dump(out, open(BUILD / "ipa.json", "w"), ensure_ascii=False, indent=1)
    differ = sum(1 for v in out.values() if v["es"] != v["la"])
    print(f"{len(out)} headwords; words from {sources}; {differ} differ Spain/LatAm")


if __name__ == "__main__":
    main()
