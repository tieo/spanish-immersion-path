"""Data for the progress page and the curve in the README.

Writes site/playlist.json (the playlist id and, per video in watching order, its title,
channel, length, speed, score and number of cards) and site/curve.svg, the difficulty
score along the playlist, one dot per video coloured by channel.
"""

import json

from config import BUILD, DATA, ROOT

COLORS = {"Easy Spanish": "#e3a64d", "Dreaming Spanish": "#b07cff", "Spanish After Hours": "#4dc3e3"}


def curve(videos, path):
    w, h, ml, mr, mt, mb = 900, 300, 50, 12, 16, 34
    lo, hi = min(v["score"] for v in videos), max(v["score"] for v in videos)
    x = lambda i: ml + i / max(1, len(videos) - 1) * (w - ml - mr)
    y = lambda s: mt + (h - mt - mb) * (1 - (s - lo) / ((hi - lo) or 1))
    dots = "".join(
        f'<circle cx="{x(i):.1f}" cy="{y(v["score"]):.1f}" r="2.3" fill="{COLORS.get(v["channel"], "#7aa2ff")}"/>'
        for i, v in enumerate(videos))
    legend = "".join(
        f'<circle cx="{ml + 10 + 170 * k}" cy="{h - 10}" r="5" fill="{c}"/>'
        f'<text x="{ml + 20 + 170 * k}" y="{h - 6}">{name}</text>'
        for k, (name, c) in enumerate(COLORS.items()))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" '
           f'font-size="12" fill="#8a90a2"><rect width="{w}" height="{h}" rx="10" fill="#171a23"/>'
           f'<text x="8" y="{mt + 10}">harder</text><text x="8" y="{h - mb}">easier</text>'
           f'<text x="{ml}" y="{h - mb + 14}">#1</text>'
           f'<text x="{w - mr}" y="{h - mb + 14}" text-anchor="end">#{len(videos)}</text>'
           f'{dots}{legend}</svg>')
    open(path, "w").write(svg)


def main():
    order = json.load(open(DATA / "order.json"))
    cards = json.load(open(BUILD / "cards_per_video.json"))
    try:
        playlist = json.load(open(DATA / "playlist.json"))["id"]
    except FileNotFoundError:
        playlist = None
    videos = [{"position": v["position"], "id": v["id"], "title": v["title"],
               "channel": v["channel"], "duration": v.get("duration"),
               "wpm": round(v["wpm"], 1), "score": round(v["score"], 3),
               "cards": cards.get(v["id"], 0), "watched": v["watched"]} for v in order]
    json.dump({"playlist": playlist, "videos": videos},
              open(ROOT / "site" / "playlist.json", "w"), ensure_ascii=False)
    curve(videos, ROOT / "site" / "curve.svg")
    print(f"{len(videos)} videos, {sum(v['cards'] for v in videos)} cards")


if __name__ == "__main__":
    main()
