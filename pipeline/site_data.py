"""Data for the progress page and the curve in the README.

Writes site/playlist.json (the playlist id and, per video in order, its title, channel,
length, speed, level score and number of cards) and site/curve.svg: every video as a bar
along the hours of the path, as wide as the video is long and as high as its level,
coloured by channel.
"""

import json

from config import BUILD, DATA, ROOT

COLORS = {"Easy Spanish": "#3987e5", "Dreaming Spanish": "#d95926", "Spanish After Hours": "#199e70"}
LEVEL_NAMES = ["superbeginner", "beginner", "intermediate", "advanced"]


def curve(videos, path):
    w, h, ml, mr, mt, mb = 900, 300, 96, 14, 14, 48
    iw, ih = w - ml - mr, h - mt - mb
    hours = sum(v["duration"] or 0 for v in videos) / 3600
    lo = min(-0.5, min(v["score"] for v in videos) - 0.2)
    hi = max(3.5, max(v["score"] for v in videos) + 0.2)
    x = lambda t: ml + t / hours * iw
    y = lambda s: mt + ih * (1 - (min(hi, max(lo, s)) - lo) / (hi - lo))
    grid = "".join(
        f'<line x1="{ml}" x2="{w - mr}" y1="{y(k):.1f}" y2="{y(k):.1f}" stroke="#2a2e3b"/>'
        f'<text x="{ml - 8}" y="{y(k) + 4:.1f}" text-anchor="end">{name}</text>'
        for k, name in enumerate(LEVEL_NAMES))
    bars, t = [], 0.0
    for v in videos:
        d = (v["duration"] or 0) / 3600
        bars.append(f'<rect x="{x(t):.2f}" y="{y(v["score"]) - 1.5:.1f}" width="{max(0.6, x(t + d) - x(t)):.2f}" '
                    f'height="3" fill="{COLORS.get(v["channel"], "#8a90a2")}"/>')
        t += d
    ticks = "".join(f'<text x="{x(k):.1f}" y="{h - mb + 16}" text-anchor="middle">{k} h</text>'
                    for k in range(0, int(hours) + 1, 50))
    legend = "".join(
        f'<rect x="{ml + 190 * k}" y="{h - 16}" width="12" height="4" rx="1" fill="{c}"/>'
        f'<text x="{ml + 18 + 190 * k}" y="{h - 10}">{name}</text>'
        for k, (name, c) in enumerate(COLORS.items()))
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" '
           f'font-size="12" fill="#a3a9ba"><rect width="{w}" height="{h}" rx="10" fill="#171a23"/>'
           f'{grid}{"".join(bars)}{ticks}{legend}</svg>')
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
               "wpm": round(v["wpm"], 1), "sps": round(v["sps"], 2), "score": round(v["score"], 3),
               "cards": cards.get(v["id"], 0)} for v in order]
    json.dump({"playlist": playlist, "videos": videos},
              open(ROOT / "site" / "playlist.json", "w"), ensure_ascii=False)
    curve(videos, ROOT / "site" / "curve.svg")
    print(f"{len(videos)} videos, {sum(v['cards'] for v in videos)} cards")


if __name__ == "__main__":
    main()
