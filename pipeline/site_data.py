"""Data for the progress page and the curve in the README.

Writes site/playlist.json (the YouTube playlists, one per level, and, per video in order, its title, channel,
length, speaking rate in syllables per second, level score and number of cards) and site/curve.svg: every video as a bar
along the hours of the path, as wide as the video is long and as high as its level,
coloured by the kind of channel.
"""

import json

from config import BUILD, DATA, ORDER, ROOT

# Colour follows the kind of channel (its topic in data/channels.json, in six groups), the
# same on the progress page; the hues are validated for colour-blind separation on the
# page's dark surface.
GROUPS = {"engineering": "Engineering & repair", "repair": "Engineering & repair",
          "tech": "Tech & code", "dev": "Tech & code", "science": "Science",
          "history": "History & news", "news": "History & news",
          "comedy": "Comedy, travel & talk", "travel": "Comedy, travel & talk",
          "talk": "Comedy, travel & talk", "learner": "For learners"}
COLORS = {"Engineering & repair": "#3987e5", "Tech & code": "#d95926", "Science": "#199e70",
          "History & news": "#c98500", "Comedy, travel & talk": "#d55181", "For learners": "#9085e9"}
# CEFR levels: a score of 0 is the middle of A1, 1 of A2 and so on (levels.py).
LEVEL_NAMES = ["A1", "A2", "B1", "B2", "C1", "C2"]


def curve(videos, path):
    w, h, ml, mr, mt, mb = 900, 300, 96, 14, 14, 48
    iw, ih = w - ml - mr, h - mt - mb
    hours = sum(v["duration"] or 0 for v in videos) / 3600
    # Pre-A1 up to where 99 % of the videos sit: native videos for adults score beyond the
    # middle of C2, and drawn on its edge their order would be lost. The 1 % beyond sit on
    # the edges.
    scores = sorted(v["score"] for v in videos)
    lo, hi = -1.5, max(5.5, scores[int(len(scores) * 0.99)] + 0.25)
    x = lambda t: ml + t / hours * iw
    y = lambda s: mt + ih * (1 - (min(hi, max(lo, s)) - lo) / (hi - lo))
    grid = "".join(
        f'<line x1="{ml}" x2="{w - mr}" y1="{y(k):.1f}" y2="{y(k):.1f}" stroke="#2a2e3b"/>'
        f'<text x="{ml - 8}" y="{y(k) + 4:.1f}" text-anchor="end">{name}</text>'
        for k, name in enumerate(["Pre-A1"] + LEVEL_NAMES, -1))
    # Tens of thousands of videos share a few hundred pixels: a bar that would land on a
    # pixel and height already drawn in its colour is left out.
    bars, drawn, t = [], set(), 0.0
    for v in videos:
        d = (v["duration"] or 0) / 3600
        color = COLORS.get(v["group"], "#8a90a2")
        key = (round(x(t)), round(y(v["score"])), color)
        if key not in drawn:
            drawn.add(key)
            bars.append(f'<rect x="{x(t):.1f}" y="{y(v["score"]) - 1.5:.1f}" width="{max(0.6, x(t + d) - x(t)):.1f}" '
                        f'height="3" fill="{color}"/>')
        t += d
    step = next(s for s in (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000) if hours / s <= 10)
    ticks = "".join(f'<text x="{x(k):.1f}" y="{h - mb + 16}" text-anchor="middle">{k:,} h</text>'
                    for k in range(0, int(hours) + 1, step))
    legend, lx = [], ml
    for name, c in COLORS.items():
        legend.append(f'<rect x="{lx}" y="{h - 16}" width="12" height="4" rx="1" fill="{c}"/>'
                      f'<text x="{lx + 18}" y="{h - 10}">{name.replace("&", "&amp;")}</text>')
        lx += 18 + 6.6 * len(name) + 16
    legend = "".join(legend)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" '
           f'font-size="12" fill="#a3a9ba"><rect width="{w}" height="{h}" rx="10" fill="#171a23"/>'
           f'{grid}{"".join(bars)}{ticks}{legend}</svg>')
    open(path, "w").write(svg)


def main():
    order = json.load(open(ORDER))
    topics = {c["name"]: c.get("topic") for c in json.load(open(DATA / "channels.json"))}
    cards = json.load(open(BUILD / "cards_per_video.json"))
    try:
        playlists = [{"level": p["level"], "title": p["title"], "id": p["id"]}
                     for p in json.load(open(DATA / "playlist.json")).get("playlists", [])]
    except FileNotFoundError:
        playlists = []
    videos = [{"position": v["position"], "id": v["id"], "title": v["title"],
               "channel": v["channel"], "group": GROUPS.get(topics.get(v["channel"])),
               "duration": v.get("duration"),
               "sps": round(v["speaking_sps"], 2), "score": round(v["score"], 3),
               "cards": cards.get(v["id"], 0)} for v in order]
    json.dump({"playlists": playlists, "groups": COLORS, "videos": videos},
              open(ROOT / "site" / "playlist.json", "w"), ensure_ascii=False)
    curve(videos, ROOT / "site" / "curve.svg")
    print(f"{len(videos)} videos, {sum(v['cards'] for v in videos)} cards")


if __name__ == "__main__":
    main()
