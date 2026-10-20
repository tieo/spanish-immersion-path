"""Whole sentences for the examples that speech recognition left without punctuation.

A card's example comes from captions (captions.snippet). Where the captions are
punctuated it is cut at the sentence ends around the word; where they are YouTube's
speech recognition, lowercase and unpunctuated, it is a window of about sixteen words
that starts and ends anywhere, mid-sentence. Here a language model reads the window with
the speech around it and marks the sentence the word belongs to.

  batches [size]   write build/sentence_batches/batch_NNN.json for every example without
                   sentence bounds and no sentence yet
  merge            check build/sentence_out/*.json against the transcript and fold what
                   passes into build/sentences.json
  more             cut the further examples of every card ("heard again in ...") again
                   from the captions punctuate.py punctuated, into build/more.json

A sentence passes when its words, compared without case, accents and punctuation, are a
run of the transcript containing the bold word: the model punctuates and fixes accents
but quotes the speaker. The link then starts at the chunk the sentence starts in.
SENTENCES.md is the model's task.
"""

import glob
import json
import os
import re
import sys
import unicodedata

from captions import MAX_EXAMPLE_WORDS, load_chunks, snippet
from config import BUILD
from translate import load

SENTENCES = BUILD / "sentences.json"
BATCHES = BUILD / "sentence_batches"
OUT = BUILD / "sentence_out"
CONTEXT_CHUNKS = 4
BOUNDED = re.compile(r'^[¿¡"«A-ZÁÉÍÓÚÑ].*[.?!…»"]$')


def plain(html):
    return re.sub(r"<[^>]+>", "", html)


def norm(word):
    word = unicodedata.normalize("NFD", word.lower())
    return "".join(c for c in word if c.isalnum())


def tokens(text):
    return [t for t in (norm(w) for w in plain(text).split()) if t]


def bounded(example):
    return bool(BOUNDED.match(plain(example).strip()))


def context(entry, chunks):
    """The example with the speech around it, its bold word kept, as (word, chunk)
    pairs. The example's link names the chunk it starts in; the example itself may
    start inside that chunk, where captions.snippet cut it at a sentence start."""
    want = tokens(entry["example_es"])
    for first, (start, _) in enumerate(chunks):
        if max(0, int(start) - 1) != entry["start"]:
            continue
        words, last = [], first
        while last < len(chunks) and len(words) < len(want) + MAX_EXAMPLE_WORDS:
            words += [(w, last) for w in chunks[last][1].split()]
            last += 1
        normed = [norm(plain(w)) for w, _ in words]
        # Positions in words of the non-empty tokens, to map a token run back to words.
        kept = [i for i, t in enumerate(normed) if t]
        flat = [normed[i] for i in kept]
        at = next((k for k in range(len(flat) - len(want) + 1) if flat[k:k + len(want)] == want), None)
        if at is None:
            continue
        a, b = kept[at], kept[at + len(want) - 1]
        lo = max(0, first - CONTEXT_CHUNKS)
        hi = min(len(chunks) - 1, words[b][1] + CONTEXT_CHUNKS)
        before = [(w, i) for i in range(lo, first) for w in chunks[i][1].split()] + words[:a]
        after = words[b + 1:] + [(w, i) for i in range(last, hi + 1) for w in chunks[i][1].split()]
        # The example's own words carry the bold tag; each takes the chunk of the
        # caption word at its place.
        own_words = entry["example_es"].split()
        span = words[a:b + 1]
        own = [(w, span[min(k, len(span) - 1)][1]) for k, w in enumerate(own_words)]
        return before + own + after
    return None


def batches(size):
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    done = load(SENTENCES, {})
    todo, cache, lost = [], {}, 0
    for entry in vocab:
        key = f"{entry['lemma']}|{entry['pos']}"
        if bounded(entry["example_es"]) or done.get(key, {}).get("example_es") == entry["example_es"]:
            continue
        vid = entry["video"]
        if vid not in cache:
            cache = {vid: load_chunks(vid)}
        words = context(entry, cache[vid])
        if words is None:
            lost += 1
            continue
        todo.append({"key": key, "transcript": " ".join(w for w, _ in words)})
    os.makedirs(BATCHES, exist_ok=True)
    start = len(glob.glob(str(BATCHES / "batch_*.json")))
    for i in range(0, len(todo), size):
        name = BATCHES / f"batch_{start + i // size:03d}.json"
        json.dump(todo[i:i + size], open(name, "w"), ensure_ascii=False, indent=1)
    print(f"{len(todo)} examples in {(len(todo) + size - 1) // size} batches; {lost} not found in captions")


def merge():
    vocab = {f"{e['lemma']}|{e['pos']}": e for e in json.load(open(BUILD / "vocab.json", encoding="utf-8"))}
    done = load(SENTENCES, {})
    cache, passed, failed = {}, 0, []
    for out in sorted(glob.glob(str(OUT / "batch_*.json"))):
        for item in json.load(open(out, encoding="utf-8")):
            entry = vocab.get(item.get("key"))
            if entry is None or "<b>" not in item.get("sentence_es", ""):
                failed.append(item.get("key"))
                continue
            vid = entry["video"]
            if vid not in cache:
                cache = {vid: load_chunks(vid)}
            words = context(entry, cache[vid])
            if words is None:
                failed.append(item["key"])
                continue
            # Compare word by word, the bold one included, so the sentence is the run
            # holding the very occurrence the card is about.
            run = [(norm(plain(w)), "<b>" in w, i) for w, i in words if norm(plain(w))]
            said = [(norm(plain(w)), "<b>" in w) for w in item["sentence_es"].split() if norm(plain(w))]
            at = next((s for s in range(len(run) - len(said) + 1)
                       if [(t, b) for t, b, _ in run[s:s + len(said)]] == said), None)
            if at is None:
                failed.append(item["key"])
                continue
            chunk = run[at][2]
            done[item["key"]] = {
                "example_es": entry["example_es"],
                "sentence_es": item["sentence_es"],
                "sentence_en": item["sentence_en"],
                "start": max(0, int(cache[vid][chunk][0]) - 1),
            }
            passed += 1
    json.dump(done, open(SENTENCES, "w"), ensure_ascii=False, indent=1)
    print(f"{passed} sentences passed, {len(failed)} failed; {len(done)} in {SENTENCES.name}")
    if failed:
        print("failed:", ", ".join(map(str, failed[:20])))


def more():
    """The further examples are not translated, so they need no model: where the
    captions are punctuated now, captions.snippet cuts them at sentence ends."""
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    raw, punct, out = {}, {}, {}
    recut = kept = 0
    for entry in vocab:
        examples = []
        for m in entry["more"]:
            vid = m["video"]
            # Further examples jump between videos, so every video stays loaded.
            if vid not in raw:
                raw[vid], punct[vid] = load_chunks(vid), load_chunks(vid, punctuated=True)
            words = context(m, raw[vid])
            bold = next(((w, i) for w, i in words or [] if "<b>" in w), None)
            if bold is None or len(punct[vid]) != len(raw[vid]):
                examples.append({"example_es": m["example_es"], "start": m["start"]})
                kept += 1
                continue
            surface = re.sub(r"\W", "", plain(bold[0]))
            text, start = snippet((vid, bold[1], surface), punct)
            examples.append({"example_es": text, "start": start})
            recut += 1
        out[f"{entry['lemma']}|{entry['pos']}"] = examples
    json.dump(out, open(BUILD / "more.json", "w"), ensure_ascii=False)
    print(f"{recut} examples cut again, {kept} kept as they were")


if __name__ == "__main__":
    if sys.argv[1] == "batches":
        batches(int(sys.argv[2]) if len(sys.argv) > 2 else 250)
    elif sys.argv[1] == "more":
        more()
    else:
        merge()
