"""Reading the videos' Spanish captions: parsing, picking example sentences.

Captions are WebVTT files in CAPTIONS (config.py), named <video id>.<track>.vtt, where
the track is "es" (human-made when YouTube has one) or "es-orig" (YouTube's speech
recognition of the video's own audio). A video without captions may have a plain
<video id>.txt transcript instead.
"""

import re

from wordfreq import zipf_frequency

from config import CAPTIONS

EXAMPLE_WORDS = 16
MAX_EXAMPLE_WORDS = 40
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
                t = TAG.sub("", line).strip()
                if t:
                    chunks.append((start, t))
        elif start is not None:
            if line.strip():
                cue.append(TAG.sub("", line).strip())
            elif cue:
                chunks.append((start, " ".join(cue)))
                cue, start = [], None
    return chunks


def is_human(path):
    try:
        return "<c>" not in open(path, encoding="utf-8").read()
    except FileNotFoundError:
        return False


def load_chunks(vid):
    """Caption chunks of one video; a video without captions falls back to ytt's
    whisper transcript, cut into eight-word chunks that all link to the start."""
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


def snippet(occurrence, cache):
    """Speech around one occurrence with the word in bold, and the second to link to.

    A caption chunk is two to three seconds of speech, six to nine words. The example
    grows by neighbouring chunks, before and after in turn, until it holds about one
    sentence. Where the episode's captions are punctuated, it keeps growing to the
    sentence ends around the word (up to MAX_EXAMPLE_WORDS) and is cut there, so it reads
    as whole sentences. The link starts at its first chunk.
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
    # Bold the occurrence inside its own chunk, not an earlier repeat of the word.
    own = re.sub(rf"\b({re.escape(surface)})\b", r"<b>\1</b>", chunks[ci][1], count=1)
    if "<b>" not in own:
        own = re.sub(rf"({re.escape(surface)})", r"<b>\1</b>", chunks[ci][1], count=1, flags=re.I)

    def assemble(a, b):
        return " ".join(
            [chunks[i][1] for i in range(a, ci)] + [own]
            + [chunks[i][1] for i in range(ci + 1, b + 1)]
        ).split()

    # Without a bolded word there is nothing to anchor the sentence cut on.
    if punctuated and "<b>" in own:
        def bounds(tokens):
            bold = next(i for i, t in enumerate(tokens) if "<b>" in t)
            start = None
            for i in range(bold, -1, -1):
                if SENTENCE_START.match(tokens[i]):
                    start = i
                    break
                if i < bold and SENTENCE_END.search(tokens[i]):
                    start = i + 1
                    break
            end = next((i for i in range(bold, len(tokens)) if SENTENCE_END.search(tokens[i])), None)
            return start, end

        start, end = bounds(assemble(first, last))
        while (start is None or end is None) and words(first, last) < MAX_EXAMPLE_WORDS and grow():
            start, end = bounds(assemble(first, last))
        tokens = assemble(first, last)
        if start is not None and end is not None and end - start + 1 >= 4:
            # The link still starts at the first chunk; the sentence lies inside it.
            return " ".join(tokens[start:end + 1]), max(0, int(chunks[first][0]) - 1)
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
