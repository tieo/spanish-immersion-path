"""Spoken headwords for the cards: one Spain and one Latin American recording per word.

Piper (offline neural TTS) with es_ES-sharvard-medium for Spain and es_MX-claude-high for
Latin America. Both were picked by synthesizing 40 random card words, joining them into
one recording and transcribing it back with Whisper: sharvard 36/40 and claude-high
33/40, against 28/40 for es_ES-davefx and fewer for es_MX-ald. Single short clips are
not a usable test, Whisper invents phrases for them. Piper's Spanish
phonemizer reads the Spain voice with distinción (θ) and the Mexican one with seseo.
Recordings are embedded in the deck so the cards play on any device without a
text-to-speech engine installed.

Words are spoken slightly slower than Piper's default, for a learner. Files are named by
a hash of the voice model and the text, so an unchanged word keeps its file across
rebuilds and a voice change produces new files.

Output: build/media/sip_<hash>_<es|la>.mp3 and build/audio.json mapping headword to
file names. Voice models are read from PIPER_VOICES.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import wave

from piper import PiperVoice, SynthesisConfig

from config import BUILD, PIPER_VOICES

VOICES = {
    "es": str(PIPER_VOICES / "es_ES-sharvard-medium.onnx"),
    "la": str(PIPER_VOICES / "es_MX-claude-high.onnx"),
}
SLOWER = SynthesisConfig(length_scale=1.15)


def spoken(word):
    """The text to say: a common-gender noun "el/la estudiante" is read with "el"."""
    return re.sub(r"^el/la ", "el ", word).replace("los/las ", "los ")


def main():
    translations = json.load(open(BUILD / "translations.json", encoding="utf-8"))
    words = {t["word"] for t in translations.values() if t.get("word") and t.get("keep", True)}
    media = BUILD / "media"
    os.makedirs(media, exist_ok=True)
    voices = {k: PiperVoice.load(v) for k, v in VOICES.items()}
    out, made = {}, 0
    for word in sorted(words):
        text = spoken(word)
        files = {}
        for key, voice in voices.items():
            model = os.path.basename(VOICES[key])
            digest = hashlib.sha1(f"{model}|{text}".encode()).hexdigest()[:12]
            name = f"sip_{digest}_{key}.mp3"
            files[key] = name
            path = os.path.join(media, name)
            if os.path.exists(path):
                continue
            wav = path[:-4] + ".wav"
            with wave.open(wav, "wb") as w:
                voice.synthesize_wav(text, w, syn_config=SLOWER)
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-i", wav, "-ac", "1",
                 "-codec:a", "libmp3lame", "-q:a", "6", path],
                check=True,
            )
            os.remove(wav)
            made += 1
        out[word] = files
    json.dump(out, open(BUILD / "audio.json", "w"), ensure_ascii=False, indent=1)
    size = sum(os.path.getsize(p) for p in glob.glob(str(media / "*.mp3")))
    print(f"{len(out)} words, {made} new recordings, media {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
