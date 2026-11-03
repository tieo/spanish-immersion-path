"""List the channels' videos and download their Spanish captions.

  list    add every video of the channels to data/videos.json (id, title, duration,
          channel); videos already listed keep their entry
  fetch   download the Spanish caption tracks of the immersion videos that have none yet

Captions come from yt-dlp: the human-made Spanish track where the channel uploaded one,
and YouTube's speech recognition of the video's own audio ("es-orig"), which exists only
when the video is spoken in Spanish. One yt-dlp run takes all videos with a pause between
requests: a separate process per video repeats YouTube's bot check every time and gets
the address blocked. The signed-in browser session (FIREFOX_PROFILE) keeps it trusted.
"""

import json
import subprocess
import sys
import tempfile

from config import CAPTIONS, DATA, FIREFOX_PROFILE

CHANNELS = {
    "Easy Spanish": "https://www.youtube.com/@easyspanish/videos",
    "Dreaming Spanish": "https://www.youtube.com/@DreamingSpanish/videos",
    "Spanish After Hours": "https://www.youtube.com/channel/UCfG2VhlQgy5bHGmkpeKcjVA/videos",
    # For learners, mostly taught in Spanish: lessons among them are left out by
    # classification (CLASSIFY.md).
    "Español con Juan": "https://www.youtube.com/@espanolconjuan/videos",
    "Spanish Language Coach": "https://www.youtube.com/@spanishlanguagecoach/videos",
    "Use your Spanish": "https://www.youtube.com/@UseYourSpanish/videos",
    "Real Fast Spanish": "https://www.youtube.com/@RealFastSpanish/videos",
    "Hoy Hablamos": "https://www.youtube.com/@hoyhablamos/videos",
    "Spanish with Vicente": "https://www.youtube.com/@SpanishwithVicente/videos",
    "Linguriosa": "https://www.youtube.com/@Linguriosa/videos",
    "StoryLearning Spanish": "https://www.youtube.com/@storylearningspanish/videos",
    # Made for native speakers: explainers, science, travel, for the upper levels.
    "CuriosaMente": "https://www.youtube.com/@curiosamente/videos",
    "Academia Play": "https://www.youtube.com/@AcademiaPlay/videos",
    "Date un Vlog": "https://www.youtube.com/@dateunvlog/videos",
    "QuantumFracture": "https://www.youtube.com/@QuantumFracture/videos",
    "CdeCiencia": "https://www.youtube.com/@CdeCiencia/videos",
    "Ter": "https://www.youtube.com/@Ter/videos",
    "Luisito Comunica": "https://www.youtube.com/@luisitocomunica/videos",
}
YT_DLP = ["yt-dlp", "--impersonate", "chrome"]


def list_videos():
    path = DATA / "videos.json"
    try:
        videos = json.load(open(path))
    except FileNotFoundError:
        videos = []
    known = {v["id"] for v in videos}
    for channel, url in CHANNELS.items():
        out = subprocess.run(YT_DLP + ["--flat-playlist", "-J", url],
                             capture_output=True, text=True, check=True).stdout
        new = [e for e in json.loads(out)["entries"] if e["id"] not in known]
        videos += [{"id": e["id"], "title": e.get("title"), "duration": e.get("duration"),
                    "channel": channel} for e in new]
        print(f"{channel}: {len(new)} new")
    json.dump(videos, open(path, "w"), ensure_ascii=False, indent=1)


def fetch():
    kinds = {c["id"]: c["kind"] for c in json.load(open(DATA / "classes.json"))}
    videos = [v for v in json.load(open(DATA / "videos.json")) if kinds.get(v["id"]) == "immersion"]
    CAPTIONS.mkdir(parents=True, exist_ok=True)
    missing = [v["id"] for v in videos if not any(CAPTIONS.glob(f"{v['id']}.*.vtt"))]
    print(f"{len(missing)} videos without captions")
    if not missing:
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("".join(f"https://www.youtube.com/watch?v={i}\n" for i in missing))
    cookies = ["--cookies-from-browser", f"firefox:{FIREFOX_PROFILE}::none"] if FIREFOX_PROFILE else []
    subprocess.run(YT_DLP + cookies + [
        "--skip-download", "--write-sub", "--write-auto-sub", "--sub-lang", "es-orig,es",
        "--sub-format", "vtt", "--sleep-requests", "1", "--sleep-subtitles", "3",
        "--retries", "5", "--extractor-retries", "5", "--ignore-errors",
        "-o", str(CAPTIONS / "%(id)s.%(ext)s"), "-a", f.name])


if __name__ == "__main__":
    {"list": list_videos, "fetch": fetch}[sys.argv[1]]()
