"""Reading the videos' Spanish captions: parsing, picking example sentences.

Captions are WebVTT files in CAPTIONS (config.py), named <video id>.<track>.vtt, where
the track is "es" (human-made when YouTube has one) or "es-orig" (YouTube's speech
recognition of the video's own audio). A video without captions may have a plain
<video id>.txt transcript instead.
"""

import html
import json
import re

from wordfreq import zipf_frequency

from config import BUILD, CAPTIONS

EXAMPLE_WORDS = 16
SKIP_POS = {"PROPN", "NUM", "PUNCT", "SYM", "X", "SPACE", "INTJ"}

TIME = re.compile(r"(\d+):(\d+):(\d+)\.(\d+) -->")
TAG = re.compile(r"<[^>]+>")


def parse_vtt(path):
    """Return [(start_seconds, text)] for each new speech chunk.

    Speech-recognition tracks carry word timings (<c> tags) on the new line of each cue
    and repeat the previous line untimed, so only timed lines count. Human-made tracks
    have no timings; each cue is one chunk."""
    text = open(path, encoding="utf-8").read()
    timed = "<c>" in text
    chunks, start, cue = [], None, []
    for line in text.splitlines() + [""]:
        m = TIME.match(line)
        if m:
            h, mi, s, ms = map(int, m.groups())
            start = h * 3600 + mi * 60 + s + ms / 1000
            cue = []
        elif timed:
            if "<c>" in line and start is not None:
                t = html.unescape(TAG.sub("", line)).replace("\xa0", " ").strip()
                if t:
                    chunks.append((start, t))
        elif start is not None:
            if line.strip():
                cue.append(html.unescape(TAG.sub("", line)).replace("\xa0", " ").strip())
            elif cue:
                chunks.append((start, " ".join(cue)))
                cue, start = [], None
    return chunks


def is_human(path):
    try:
        return "<c>" not in open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return False


def load_chunks(vid, punctuated=False):
    """Caption chunks of one video; a video without captions falls back to ytt's
    whisper transcript, cut into eight-word chunks that all link to the start. With
    punctuated, speech recognition captions come with the punctuation punctuate.py
    restored, where it has run."""
    if punctuated:
        try:
            return [tuple(c) for c in json.load(open(BUILD / "punctuated" / f"{vid}.json", encoding="utf-8"))]
        except FileNotFoundError:
            pass
    # A human-made Spanish track beats speech recognition; yt-dlp writes it as "es".
    if is_human(CAPTIONS / f"{vid}.es.vtt"):
        return parse_vtt(CAPTIONS / f"{vid}.es.vtt")
    for track in ("es-orig", "es"):
        try:
            return parse_vtt(CAPTIONS / f"{vid}.{track}.vtt")
        except FileNotFoundError:
            pass
    try:
        words = open(CAPTIONS / f"{vid}.txt", encoding="utf-8").read().split()
    except FileNotFoundError:
        return []
    return [(0, " ".join(words[i:i + 8])) for i in range(0, len(words), 8)]


SENTENCE_END = re.compile(r"[.?!…]$")
SENTENCE_START = re.compile(r"^[¿¡]")
CLAUSE_END = re.compile(r"[.?!…,;:]$")
# A sentence shorter than this takes the next one along, so the example says something.
MIN_SENTENCE_WORDS = 5
# Longer sentences are cut to the clauses around the word, up to this many words.
MAX_SENTENCE_WORDS = 35
CLAUSE_WORDS = 22
SEARCH_WORDS = 70


def speech(tokens):
    """Tokens without the captions' bracketed sound tags ([música], [El supermercado]).
    A tag holding the bold word stays whole, so the example shows it is no speech."""
    out, tag = [], None
    for t in tokens:
        bare = re.sub(r"<[^>]+>", "", t)
        if tag is None and bare.startswith("["):
            tag = []
        if tag is None:
            out.append(t)
            continue
        tag.append(t)
        if bare.endswith("]"):
            if any("<b>" in w for w in tag):
                out += tag
            tag = None
    return out + (tag or [])


def sentences(tokens):
    """[first, last] token index pairs of the sentences in a token run; the first and
    the last may be cut off by the run's edges (None there)."""
    out, first = [], 0
    for i, t in enumerate(tokens):
        if i > first and SENTENCE_START.match(t) and not SENTENCE_END.search(tokens[i - 1]):
            out.append([first, i - 1])
            first = i
        if SENTENCE_END.search(re.sub(r"<[^>]+>", "", t)):
            out.append([first, i])
            first = i + 1
    if first < len(tokens):
        out.append([first, None])
    if out and out[0][0] == 0:
        out[0][0] = None
    return out


def cut(tokens, open_edges=False):
    """The sentence holding the bold word, from tokens of punctuated speech: a short
    one with its neighbour, a long one cut to the clauses around the word and marked
    with "…" where it goes on. None when the run's edges leave the sentence open,
    unless open_edges: then the run's edges count as where it goes on."""
    bold = next(i for i, t in enumerate(tokens) if "<b>" in t)
    spans = sentences(tokens)
    k = next(j for j, (a, b) in enumerate(spans) if (a or 0) <= bold and (b is None or bold <= b))
    a, b = spans[k]
    if (a is None or b is None) and not open_edges:
        return None
    opened_a, opened_b = a is None, b is None
    a, b = a or 0, len(tokens) - 1 if b is None else b
    if b - a + 1 < MIN_SENTENCE_WORDS:
        if k + 1 < len(spans) and spans[k + 1][1] is not None:
            b = spans[k + 1][1]
        elif k > 0 and spans[k - 1][0] is not None:
            a = spans[k - 1][0]
    if b - a + 1 <= MAX_SENTENCE_WORDS and not (opened_a or opened_b):
        return finish(tokens[a:b + 1])
    # Clauses around the word, taken in turn on each side while they fit.
    lo = next((i + 1 for i in range(bold - 1, a - 1, -1) if CLAUSE_END.search(tokens[i])), a)
    hi = next((i for i in range(bold, b + 1) if CLAUSE_END.search(re.sub(r"<[^>]+>", "", tokens[i]))), b)
    grown = True
    while grown:
        grown = False
        before = next((i + 1 for i in range(lo - 2, a - 1, -1) if CLAUSE_END.search(tokens[i])), a)
        if lo > a and hi - before + 1 <= CLAUSE_WORDS:
            lo, grown = before, True
        after = next((i for i in range(hi + 1, b + 1) if CLAUSE_END.search(tokens[i])), b)
        if hi < b and after - lo + 1 <= CLAUSE_WORDS:
            hi, grown = after, True
    # Speech without commas: the words around the bold one.
    if hi - lo + 1 > MAX_SENTENCE_WORDS:
        lo = max(lo, bold - CLAUSE_WORDS // 2)
        hi = min(hi, lo + CLAUSE_WORDS - 1)
    out = tokens[lo:hi + 1]
    if lo > a or opened_a:
        out = ["…" + out[0]]  + out[1:]
    if hi < b or (opened_b and not SENTENCE_END.search(out[-1])):
        out[-1] = re.sub(r"[,;:]$", "", out[-1]) + "…"
    return finish(out)


def finish(out):
    """A sentence starts with a capital; one the speaker breaks off (a question
    follows) ends in "…"."""
    out = list(out)
    if not re.search(r"[.?!…»\"]$", re.sub(r"<[^>]+>", "", out[-1])):
        out[-1] = re.sub(r"[,;:]$", "", out[-1]) + "…"
    if not out[0].startswith("…"):
        out[0] = re.sub(r"^((?:<b>)?[¿¡\"«]?)(\w)", lambda m: m.group(1) + m.group(2).upper(), out[0], count=1)
    return out


def snippet(occurrence, cache):
    """Speech around one occurrence with the word in bold, and the second to link to.

    A caption chunk is two to three seconds of speech, six to nine words. The example
    grows by neighbouring chunks, before and after in turn, until it holds about one
    sentence. Where the episode's captions are punctuated, it keeps growing until the
    sentence around the word is whole (up to SEARCH_WORDS) and is cut to it (cut()).
    Sound tags are left out. The link starts at its first chunk.
    """
    vid, ci, surface = occurrence
    if vid not in cache:
        cache[vid] = load_chunks(vid)
    chunks = cache[vid]
    punctuated = any(SENTENCE_END.search(c) for _, c in chunks)
    first = last = ci

    def words(a, b):
        return sum(len(chunks[i][1].split()) for i in range(a, b + 1))

    def grow():
        nonlocal first, last
        if first > 0 and (ci - first <= last - ci or last == len(chunks) - 1):
            first -= 1
        elif last < len(chunks) - 1:
            last += 1
        else:
            return False
        return True

    while words(first, last) < EXAMPLE_WORDS and grow():
        pass
    # Bold the occurrence inside its own chunk, not an earlier repeat of the word; a
    # word at a chunk's edge may sit in the next one.
    for k in (ci, ci + 1, ci - 1):
        if not 0 <= k < len(chunks):
            continue
        own = re.sub(rf"\b({re.escape(surface)})\b", r"<b>\1</b>", chunks[k][1], count=1)
        if "<b>" not in own:
            own = re.sub(rf"({re.escape(surface)})", r"<b>\1</b>", chunks[k][1], count=1, flags=re.I)
        if "<b>" in own:
            ci = k
            break
    else:
        own = chunks[ci][1]
    first, last = min(first, ci), max(last, ci)

    def assemble(a, b):
        return speech(" ".join(
            [chunks[i][1] for i in range(a, ci)] + [own]
            + [chunks[i][1] for i in range(ci + 1, b + 1)]
        ).split())

    # Without a bolded word there is nothing to anchor the sentence cut on.
    if punctuated and "<b>" in own:
        sentence = cut(assemble(first, last))
        while sentence is None and words(first, last) < SEARCH_WORDS and grow():
            sentence = cut(assemble(first, last))
        if sentence is None:
            sentence = cut(assemble(first, last), open_edges=True)
        if sentence:
            # The link still starts at the first chunk; the sentence lies inside it.
            return " ".join(sentence), max(0, int(chunks[first][0]) - 1)
    return " ".join(assemble(first, last)), max(0, int(chunks[first][0]) - 1)


def score(html):
    """How well a snippet reads: share of real Spanish words, word variety, length."""
    words = re.sub(r"<[^>]+>", "", html).split()
    if not words:
        return 0.0
    real = sum(1 for w in words if zipf_frequency(w, "es") >= 3.0)
    # Repeated words (la caña la caña la caña) read as drills, not speech.
    variety = len(set(words)) / len(words)
    length = min(len(words), 8) / 8
    return (real / len(words)) * variety * length
