"""Recordings with a known CEFR level: what the level scale is fitted to.

Two sources, both made for learners at a stated CEFR level:
- the listening tasks of the Instituto Cervantes' DELE sample exams, the official Spanish
  exams per level, A1 to C2 (examenes.cervantes.es, through the Internet Archive), named
  <level>-<exam file>;
- the "Explora audios" bank of profe-de-espanol.de: short talks by Spanish teachers on
  everyday topics, each tagged with the level it is meant for, named <level>-pde-<title>
  (a recording tagged "C1 y C2" counts as C1, "A2+" as A2).

  transcribe   build/graded/audio/<level>-<name>.mp3|mp4 to build/graded/<level>-<name>.json:
               every word with its start time, from Whisper, and the end of the last
               word; WHISPER_DEVICE=cuda with WHISPER_COMPUTE=float16 runs it on an NVIDIA
               GPU (about 25 times real time on an RTX A2000, against 4 to 5 on a CPU)

A DELE recording also holds the exam's spoken instructions and the silence left for
answers: the instructions are a small part of the speech, and the silence makes its pause
share meaningless, so the fit leaves pauses out.
"""

import json
import os
import shutil
import subprocess
import sys

import numpy as np

from config import BUILD

GRADED = BUILD / "graded"
LEVELS = ["a1", "a2", "b1", "b2", "c1", "c2"]
MODEL = "small"


def recordings():
    """{name: CEFR level index} of the transcribed recordings."""
    return {p.stem: LEVELS.index(p.stem.split("-")[0])
            for p in sorted(GRADED.glob("*.json")) if p.stem.split("-")[0] in LEVELS}


def load(name):
    data = json.load(open(GRADED / f"{name}.json", encoding="utf-8"))
    return [tuple(w) for w in data["words"]], data["end"]


def samples(path):
    """The recording as 16 kHz mono float samples, decoded by ffmpeg (FFMPEG, or the one
    on PATH)."""
    ffmpeg = os.environ.get("FFMPEG") or shutil.which("ffmpeg")
    raw = subprocess.run([ffmpeg, "-nostdin", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def transcribe():
    from faster_whisper import WhisperModel
    model = WhisperModel(MODEL, device=os.environ.get("WHISPER_DEVICE", "cpu"), compute_type=os.environ.get("WHISPER_COMPUTE", "int8"))
    for audio in sorted((GRADED / "audio").iterdir()):
        out = GRADED / f"{audio.name.split('.')[0]}.json"
        if out.exists():
            continue
        segments, _ = model.transcribe(samples(audio), language="es", word_timestamps=True,
                                       vad_filter=True)
        words, end = [], 0.0
        for seg in segments:
            for w in seg.words:
                if w.word.strip():
                    words.append([round(w.start, 2), w.word.strip()])
                    end = round(w.end, 2)
        json.dump({"words": words, "end": end}, open(out, "w"), ensure_ascii=False)
        print(f"{audio.name}: {len(words)} words", flush=True)


if __name__ == "__main__":
    {"transcribe": transcribe}[sys.argv[1]]()
