"""Vocabulary for the immersion playlist: 20 to 40 new words per video.

Input: data/order.json (videos in watching order, from levels.py) and their Spanish
captions. Words are counted as spaCy lemmas over all videos. The lemmas that make
up the first half of all spoken words are taken as known from the start (the learner's
"skip the most common half"); of the rest, lemmas heard in at least two videos are
candidates.

Each video, in watching order, gets the candidates it contains that no earlier video has
taken, most widespread across the playlist first (then most common in Spanish), up to
PER_VIDEO; if it has fewer than
MIN_PER_VIDEO such words it takes all it has. So every word easier than a video's cards
was carded by an earlier video, and the cards move from common to rarer words along the
playlist. A word taken by a video quotes its cleanest sentence from that video and links
the next LINKS videos in watching order where it comes back.

Output: build/vocab.json (the words with their examples, read by translate batching,
ipa.py, audio.py and deck.py) and build/stats.json.
"""

import collections
import json
import re

import spacy
from wordfreq import zipf_frequency

from captions import SKIP_POS, load_chunks, score, snippet
from config import BUILD, DATA
COVERAGE_CUT = 0.5
MIN_VIDEOS = 2
SINGLE_VIDEO_ZIPF = 2.5
PER_VIDEO = 30
MIN_PER_VIDEO = 20
LINKS = 30


def main():
    order = json.load(open(DATA / "order.json"))
    nlp = spacy.load("es_core_news_md", disable=["ner"])
    counts = collections.Counter()
    videos_of = collections.defaultdict(list)          # lemma -> video ids in order
    occ = collections.defaultdict(list)                # (lemma, vid) -> [(chunk, surface)]
    forms = collections.defaultdict(collections.Counter)
    pos_votes = collections.defaultdict(collections.Counter)
    lemmas_in = {}
    line_videos = collections.Counter()
    total = 0
    for v in order:
        vid = v["id"]
        chunks = load_chunks(vid)
        words = " ".join(c for _, c in chunks).lower().split()
        line_videos.update({" ".join(words[i:i + 5]) for i in range(len(words) - 4)})
        bounds, text = [], ""
        for i, (_, chunk) in enumerate(chunks):
            bounds.append((len(text), len(text) + len(chunk), i))
            text += chunk + " "
        seen = []
        b = 0
        for tok in nlp(text):
            while b < len(bounds) - 1 and tok.idx >= bounds[b][1]:
                b += 1
            if not tok.is_alpha:
                continue
            total += 1
            lemma = tok.lemma_.lower()
            counts[lemma] += 1
            pos_votes[lemma][tok.pos_] += 1
            if tok.pos_ in SKIP_POS:
                continue
            forms[lemma][tok.text.lower()] += 1
            if not videos_of[lemma] or videos_of[lemma][-1] != vid:
                videos_of[lemma].append(vid)
                seen.append(lemma)
            occ[(lemma, vid)].append((vid, bounds[b][2], tok.text))
        lemmas_in[vid] = seen
        print(f"\r{len(lemmas_in)}/{len(order)} videos read", end="", flush=True)
    print()

    ranked = counts.most_common()
    known, cum = set(), 0
    for lemma, n in ranked:
        if cum / total >= COVERAGE_CUT:
            break
        known.add(lemma)
        cum += n

    def candidate(lemma):
        # The tagger sometimes returns a verb with its clitic as two words ("arrepentir él").
        if lemma in known or not lemma.isalpha():
            return False
        if len(videos_of[lemma]) < MIN_VIDEOS and zipf_frequency(lemma, "es") < SINGLE_VIDEO_ZIPF:
            return False
        if pos_votes[lemma].most_common(1)[0][0] in SKIP_POS:
            return False
        # English fillers the speakers drop in read as Spanish to the tagger.
        return zipf_frequency(lemma, "en") <= zipf_frequency(lemma, "es") + 1.5

    stock = {g for g, n in line_videos.items() if n >= 4}

    def is_stock(html):
        w = re.sub(r"<[^>]+>", "", html).lower().split()
        return any(" ".join(w[i:i + 5]) in stock for i in range(len(w) - 4))

    position = {v["id"]: v["position"] for v in order}
    titles = {v["id"]: v["title"] for v in order}
    taken, vocab, cache = set(), [], {}
    per_video = {}
    for v in order:
        vid = v["id"]
        cands = [l for l in lemmas_in[vid] if l not in taken and candidate(l)]
        cands.sort(key=lambda l: (-len(videos_of[l]), -zipf_frequency(l, "es"), -counts[l]))
        chosen = cands[:PER_VIDEO] if len(cands) > PER_VIDEO else cands
        per_video[vid] = len(chosen)
        for lemma in chosen:
            taken.add(lemma)
            options = [snippet(o, cache) for o in occ[(lemma, vid)]]
            example, start = max(options, key=lambda c: score(c[0]) * (0.3 if is_stock(c[0]) else 1))
            later = [w for w in videos_of[lemma] if position[w] > position[vid]][:LINKS]
            more = []
            for w in later:
                text, at = snippet(occ[(lemma, w)][0], cache)
                more.append({"example_es": text, "video": w, "start": at,
                             "episode_title": titles[w], "episode_number": position[w],
                             "watch_position": position[w]})
            vocab.append({
                "lemma": lemma, "pos": pos_votes[lemma].most_common(1)[0][0],
                "count": counts[lemma], "episodes": len(videos_of[lemma]),
                "forms": [f for f, _ in forms[lemma].most_common(4)],
                "example_es": example, "video": vid, "start": start,
                "episode_title": titles[vid], "episode_number": position[vid],
                "watch_position": position[vid], "more": more,
                "all_positions": sorted(position[w] for w in videos_of[lemma]),
            })
        cache.clear()

    BUILD.mkdir(parents=True, exist_ok=True)
    json.dump(vocab, open(BUILD / "vocab.json", "w"), ensure_ascii=False)
    sizes = list(per_video.values())
    never = [l for l in videos_of if candidate(l) and l not in taken]
    stats = {"videos": len(order), "tokens": total, "lemmas": len(counts),
             "known_cut": len(known), "known_cut_words": [l for l, _ in ranked[:len(known)]],
             "cards": len(vocab), "videos_with_cards": sum(1 for s in sizes if s),
             "videos_under_20": sum(1 for s in sizes if 0 < s < MIN_PER_VIDEO),
             "never_taken": len(never)}
    json.dump(stats, open(BUILD / "stats.json", "w"), ensure_ascii=False, indent=1)
    print({k: v for k, v in stats.items() if k != "known_cut_words"})


if __name__ == "__main__":
    main()
