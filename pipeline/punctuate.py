"""Punctuation and capitals for captions that speech recognition left without them.

Most videos only have YouTube's speech recognition captions: lowercase, no punctuation,
so an example cut from them (captions.snippet) cannot end at a sentence end. A
punctuation, truecasing and sentence boundary model (xlm-roberta, 1-800-BAD-CODE on
Hugging Face, through the punctuators package) restores them over each whole transcript.
It keeps the words one to one, so the punctuated words go back into the caption chunks
they came from and the chunks keep their timings.

Output: build/punctuated/<video id>.json, the video's caption chunks as [start, text];
captions.load_chunks(vid, punctuated=True) reads them. A video whose captions are
punctuated already, or whose words the model did not return one to one, gets no file.
"""

import json
import sys

from captions import SENTENCE_END, load_chunks
from config import BUILD
from sentences import norm

OUT = BUILD / "punctuated"
MODEL = "1-800-BAD-CODE/xlm-roberta_punctuation_fullstop_truecase"


def main(videos):
    from punctuators.models import PunctCapSegModelONNX
    model = PunctCapSegModelONNX.from_pretrained(MODEL)
    OUT.mkdir(parents=True, exist_ok=True)
    done = skipped = 0
    for n, vid in enumerate(videos, 1):
        path = OUT / f"{vid}.json"
        chunks = load_chunks(vid)
        if path.exists() or not chunks or any(SENTENCE_END.search(c) for _, c in chunks):
            continue
        words = [w for _, c in chunks for w in c.split()]
        out = [w for s in model.infer([" ".join(words)], apply_sbd=True)[0] for w in s.split()]
        if [norm(w) for w in out] != [norm(w) for w in words]:
            skipped += 1
            continue
        result, i = [], 0
        for start, c in chunks:
            k = len(c.split())
            result.append([start, " ".join(out[i:i + k])])
            i += k
        json.dump(result, open(path, "w"), ensure_ascii=False)
        done += 1
        print(f"\r{n}/{len(videos)} videos, {done} punctuated, {skipped} skipped", end="", flush=True)
    print()


if __name__ == "__main__":
    # All videos any card quotes, or the ones named on the command line.
    vocab = json.load(open(BUILD / "vocab.json", encoding="utf-8"))
    videos = sys.argv[1:] or sorted({e["video"] for e in vocab} | {m["video"] for e in vocab for m in e["more"]})
    main(videos)
