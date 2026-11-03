"""List the channels' videos and download their Spanish captions.

  list    add every video of the channels in data/channels.json to data/videos.json (id,
          title, duration, channel); videos already listed keep their entry. A channel's
          "latest" keeps only that many of its newest videos (news channels upload
          thousands of clips)
  fetch [k/n]  download the Spanish caption tracks of the immersion videos that have none
               yet; with k/n, only shard k of n

Captions come from yt-dlp: the human-made Spanish track where the channel uploaded one,
and YouTube's speech recognition of the video's own audio ("es-orig"), which exists only
when the video is spoken in Spanish. One yt-dlp run takes all videos with a pause between
requests: a separate process per video repeats YouTube's bot check every time and gets
the address blocked. The signed-in browser session (YTDLP_COOKIES, a yt-dlp
--cookies-from-browser spec such as chromium+kwallet6:<profile dir>, or FIREFOX_PROFILE)
keeps it trusted. Without that session YouTube shows no captions at all, and yt-dlp needs
a JavaScript runtime on PATH (deno) to solve YouTube's challenges.
"""

import json
import os
import subprocess
import sys
import tempfile

from config import CAPTIONS, DATA, FIREFOX_PROFILE, YTDLP_COOKIES

YT_DLP = ["yt-dlp", "--impersonate", "chrome"]


def list_videos():
    path = DATA / "videos.json"
    try:
        videos = json.load(open(path))
    except FileNotFoundError:
        videos = []
    known = {v["id"] for v in videos}
    for ch in json.load(open(DATA / "channels.json")):
        # A channel's /videos tab lists the newest first; "latest" keeps that many.
        cap = ["--playlist-end", str(ch["latest"])] if ch.get("latest") else []
        out = subprocess.run(YT_DLP + ["--flat-playlist", "-J"] + cap + [ch["url"]],
                             capture_output=True, text=True, check=True).stdout
        new = [e for e in json.loads(out)["entries"] if e["id"] not in known]
        videos += [{"id": e["id"], "title": e.get("title"), "duration": e.get("duration"),
                    "channel": ch["name"]} for e in new]
        known |= {e["id"] for e in new}
        print(f"{ch['name']}: {len(new)} new", flush=True)
        json.dump(videos, open(path, "w"), ensure_ascii=False, indent=1)


def fetch(shard="0/1"):
    """shard k/n takes every n-th missing video from the k-th, so n processes can share
    the work; SLEEP_REQUESTS and SLEEP_SUBTITLES set yt-dlp's pauses in seconds."""
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    videos = [v for v in json.load(open(DATA / "videos.json")) if kinds.get(v["id"]) == "immersion"]
    CAPTIONS.mkdir(parents=True, exist_ok=True)
    k, n = map(int, shard.split("/"))
    missing = [v["id"] for v in videos if not any(CAPTIONS.glob(f"{v['id']}.*.vtt"))][k::n]
    print(f"{len(missing)} videos without captions")
    if not missing:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("".join(f"https://www.youtube.com/watch?v={i}\n" for i in missing))
    browser = YTDLP_COOKIES or (f"firefox:{FIREFOX_PROFILE}::none" if FIREFOX_PROFILE else None)
    cookies = ["--cookies-from-browser", browser] if browser else []
    subprocess.run(YT_DLP + cookies + [
        "--skip-download", "--write-sub", "--write-auto-sub", "--sub-lang", "es-orig,es",
        "--sub-format", "vtt", "--sleep-requests", os.environ.get("SLEEP_REQUESTS", "1"),
        "--sleep-subtitles", os.environ.get("SLEEP_SUBTITLES", "3"),
        "--retries", "5", "--extractor-retries", "5", "--ignore-errors",
        "-o", str(CAPTIONS / "%(id)s.%(ext)s"), "-a", f.name])


if __name__ == "__main__":
    {"list": list_videos, "fetch": fetch}[sys.argv[1]](*sys.argv[2:])
