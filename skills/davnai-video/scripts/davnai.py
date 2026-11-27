#!/usr/bin/env python3
"""Davnai video editing on your own computer (https://davnai.com). MIT licence.

Commands (python davnai.py <command> --help for details):
  check                     what's installed and what's missing
  brand <brand_url>         save the Brand Kit from Davnai (get_brand_files) in ~/.davnai/brand
  transcribe <video>        numbered transcript lines (reused on the second run)
  frame <video> --line N    one still from the middle of line N (to check framing)
  themes                    the built-in themes (12)
  storyboard <plan.json>    the scenes to approve before rendering (and a picture page)
  qc <video>                quality checks (also run after every render)
  review <plan.json>        a review page: the person marks moments and notes; you get them as line numbers
  style [--set k=v]         the person's lasting preferences (used for every video)
  match <reel.mp4>          read a reel they like (pace, colour, loudness) and suggest settings
  catalog [words]           search HyperFrames' 448 ready-made pieces; catalog-get <name> to adapt one
  render <plan.json>        previews (v1, v2, ...); --final for full quality; motion graphics via HyperFrames
  setup [--motion]          install what's missing (asks first; --yes when the person already agreed)
  voice "<text>"            a free voice-over made on this computer (faceless videos)
  probe <file>              name, size, length, width, height (for upload_from_computer)
  upload <file> <ticket>    send the final to Davnai (ticket from upload_from_computer)

Needs Python 3.9+ and ffmpeg. Transcripts need `pip install faster-whisper`; brand fonts work best with
`pip install fonttools brotli`. Originals are never changed: everything is written to "<video>.davnai".
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "2.1.0"
UA = f"davnai-skill/{VERSION}"
BRAND_DIR = Path(os.environ.get("DAVNAI_HOME", Path.home() / ".davnai")) / "brand"
PAUSE = 0.6  # pauses longer than this are shortened by "tighten"
KEEP_GAP = 0.15  # what's left either side of a shortened pause
SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
DEFAULT_STYLE = {  # Davnai's default caption look when no Brand Kit has been saved
    "size": 0.075, "upper": False, "color": "#FFFFFF", "accent": "#FFD43B", "outline": 0.08, "outlineColor": "#000000",
    "shadow": True, "box": None, "karaoke": "word", "words": 4, "place": "bottom",
}
DEFAULT_MARGINS = {"tall": {"top": 0.14, "bottom": 0.34}, "wide": {"top": 0.08, "bottom": 0.08}}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class Problem(Exception):
    """A plain-language problem to show the person (no stack trace)."""


# ---------------------------------------------------------------- helpers


def say(*lines: str) -> None:
    print("\n".join(lines), flush=True)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        raise Problem(f"{tool} isn't installed. Install ffmpeg (https://ffmpeg.org/download.html; Windows: winget install ffmpeg; Mac: brew install ffmpeg).")
    return path


def run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise Problem(f"ffmpeg stopped with an error:\n{tail}")


def probe(path: Path) -> dict:
    need("ffprobe")
    if not path.exists():
        raise Problem(f"Can't find {path}.")
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise Problem(f"{path.name} doesn't look like a video or audio file ffmpeg can read.")
    data = json.loads(out.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fps = 30.0
    if video and video.get("avg_frame_rate", "0/0") != "0/0":
        num, den = video["avg_frame_rate"].split("/")
        fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    width, height = (int(video.get("width", 0)), int(video.get("height", 0))) if video else (0, 0)
    rotate = 0
    for side in (video or {}).get("side_data_list", []) or []:
        rotate = int(side.get("rotation", 0) or 0)
    if abs(rotate) in (90, 270):
        width, height = height, width
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "seconds": round(float(data.get("format", {}).get("duration", 0) or 0), 2),
        "width": width,
        "height": height,
        "fps": round(fps, 3),
        "audio": audio is not None,
        "video": video is not None,
    }


def workdir(source: Path) -> Path:
    folder = source.with_name(source.name + ".davnai")
    folder.mkdir(exist_ok=True)
    return folder


def http(url: str, method: str = "GET", data: bytes | None = None, headers: dict | None = None, timeout: int = 120) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), err.read()


def json_error(body: bytes) -> str:
    try:
        return str(json.loads(body.decode("utf-8")).get("error") or "")
    except Exception:  # noqa: BLE001
        return ""


def ass_colour(hex_colour: str | None, alpha: float = 0.0) -> str:
    h = (hex_colour or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    h = (h + "FFFFFF")[:6]
    a = max(0, min(255, round(alpha * 255)))
    return f"&H{a:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ffmpeg_major() -> int:
    out = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").stdout
    m = re.search(r"ffmpeg version n?(\d+)", out)
    return int(m.group(1)) if m else 6


def even(n: float) -> int:
    return max(2, int(round(n / 2)) * 2)


# ---------------------------------------------------------------- check


def cmd_check(_args) -> None:
    lines = [f"Davnai script {VERSION}, Python {sys.version.split()[0]}"]
    ok = True
    if sys.version_info < (3, 9):
        ok = False
        lines.append("✗ Python 3.9 or newer is needed.")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            lines.append(f"✓ {tool}")
        else:
            ok = False
            lines.append(f"✗ {tool}: run python davnai.py setup (or install ffmpeg: Windows winget install Gyan.FFmpeg; Mac brew install ffmpeg; Linux apt install ffmpeg).")
    if shutil.which("ffmpeg"):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").stdout
        lines.append("✓ captions (libass)" if re.search(r"\bass\b", filters) else "✗ this ffmpeg can't burn captions (no libass): install a full ffmpeg build.")
    try:
        import faster_whisper  # noqa: F401
        lines.append("✓ transcripts (faster-whisper)")
    except ImportError:
        ok = False
        lines.append("✗ transcripts: run python davnai.py setup (or pip install faster-whisper)")
    try:
        import fontTools  # noqa: F401
        lines.append("✓ brand fonts (fonttools)")
    except ImportError:
        lines.append("· optional: pip install fonttools brotli (uses the exact Brand Kit caption font)")
    have = sum((FONTS_DIR / n).exists() for n in FONT_SOURCES)
    lines.append(f"✓ theme fonts ({have}/{len(FONT_SOURCES)})" if have == len(FONT_SOURCES) else f"· theme fonts {have}/{len(FONT_SOURCES)} (downloaded on first use, or by setup)")
    hf = MOTION_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if node_major() >= 22 and hf.exists():
        lines.append("✓ motion graphics (HyperFrames)")
    else:
        lines.append("· optional: motion graphics need Node.js 22+ and HyperFrames: python davnai.py setup --motion")
    studio = studio_problem()
    lines.append(f"✓ studio effects ({len(studio_effects())}) and cut-out" if studio is None else f"· optional: {studio}")
    lines.append("✓ Brand Kit saved" if (BRAND_DIR / "brand.json").exists() else "· Brand Kit not saved yet: call get_brand_files in Davnai, then run: davnai.py brand \"<brand_url>\"")
    lines.append("Ready." if ok else "Ask the person, then run: python davnai.py setup --yes (add --motion for motion graphics). Then check again.")
    say(*lines)


# ---------------------------------------------------------------- brand


def font_to_ttf(path: Path) -> Path | None:
    if path.suffix.lower() == ".ttf":
        return path
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(str(path))
        font.flavor = None
        out = path.with_suffix(".ttf")
        font.save(str(out))
        return out
    except Exception:  # noqa: BLE001
        return None


def cmd_brand(args) -> None:
    status, _, body = http(args.url)
    if status != 200:
        raise Problem(json_error(body) or f"Davnai answered {status}. Ask the AI to call get_brand_files again for a fresh link.")
    pack = json.loads(body.decode("utf-8"))
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    (BRAND_DIR / "fonts").mkdir(exist_ok=True)
    saved = []

    def fetch(item: dict | None, folder: Path) -> str | None:
        if not item or not item.get("url"):
            return None
        code, _, data = http(item["url"], timeout=600)
        if code != 200:
            return None
        name = re.sub(r"[^\w.\-]", "_", item.get("name") or "file")
        (folder / name).write_bytes(data)
        return name

    caps = pack.get("captions") or {}
    font_name = fetch(caps.get("font"), BRAND_DIR / "fonts")
    if font_name:
        ttf = font_to_ttf(BRAND_DIR / "fonts" / font_name)
        caps["font_file"] = f"fonts/{ttf.name}" if ttf else None
        saved.append("caption font" + ("" if ttf else " (can't convert it: pip install fonttools brotli; a standard bold font is used)"))
    logo = pack.get("logo")
    if logo and fetch(logo, BRAND_DIR):
        logo["file"] = re.sub(r"[^\w.\-]", "_", logo["name"])
        saved.append("logo")
    for end in ("intro", "outro"):
        part = pack.get(end) or {}
        if part.get("file") and fetch(part["file"], BRAND_DIR):
            part["file"]["path"] = re.sub(r"[^\w.\-]", "_", part["file"]["name"])
            saved.append(f"their own {end}")
    for item in [caps.get("font"), logo, (pack.get("intro") or {}).get("file"), (pack.get("outro") or {}).get("file")]:
        if isinstance(item, dict):
            item.pop("url", None)  # links expire; the files are kept instead
    pack["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (BRAND_DIR / "brand.json").write_text(json.dumps(pack, indent=1), encoding="utf-8")
    colours = ", ".join(c.get("hex", "") for c in pack.get("colours", [])[:5]) or "none"
    missing = [label for label, ok in (("colours", pack.get("colours")), ("logo", pack.get("logo")), ("handle", pack.get("handle")), ("voice", pack.get("voice"))) if not ok]
    if missing:
        say(f"Their Brand Kit has no {', '.join(missing)} yet. Tell the person, and offer to set the basics now with Davnai's update_brand_kit "
            "(colours, handle, and a voice written from two posts they like); a logo is added on Davnai's Brand Kit page. "
            "Or carry on: the theme's own colours are used, and nothing is left broken.")
    say(
        f"Brand Kit saved for {pack.get('name') or 'this person'} in {BRAND_DIR}.",
        f"Captions: {caps.get('style_name', 'default')} ({caps.get('font_family', '')}), {caps.get('position', 'bottom')}. Colours: {colours}.",
        f"Files: {', '.join(saved) or 'none'}.",
        *(f"{end.capitalize()}: {pack[end]['note']}" for end in ("intro", "outro") if (pack.get(end) or {}).get("note")),
    )


def load_brand() -> dict:
    path = BRAND_DIR / "brand.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# ---------------------------------------------------------------- transcript


def join_pieces(words: list[list]) -> list[list]:
    """Whisper sometimes splits a word into pieces ("$7" ",000", "8" "%", "non" "-registered", "it" "'s"): put them back
    together so captions read "$7,000", "8%" and "non-registered" (pure)."""
    out: list[list] = []
    for w in words:
        text = str(w[0])
        piece = re.match(r"^(,\d|%|-[A-Za-z]|'(s|t|re|ll|ve|m|d)\b)", text, re.I) is not None
        if out and (piece or out[-1][0] == "$"):
            out[-1] = [out[-1][0] + text, out[-1][1], w[2], *w[3:]]
        else:
            out.append(list(w))
    return out


def split_lines(words: list[list]) -> list[dict]:
    """Words [[text, start, end], ...] into short numbered lines (a sentence, a pause, or at most 16 words)."""
    lines, current = [], []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sentence = re.search(r"[.!?…]$", w[0]) is not None
        long_pause = nxt is not None and nxt[1] - w[2] > 0.8
        if nxt is None or end_sentence or long_pause or len(current) >= 16 or (len(current) >= 10 and re.search(r"[,;:]$", w[0])):
            lines.append({"id": len(lines) + 1, "start": current[0][1], "end": current[-1][2], "words": current})
            current = []
    return lines


def transcript_path(source: Path) -> Path:
    return workdir(source) / "transcript.json"


def speech_audio(source: Path):
    """The sound as 16 kHz mono samples, read by ffmpeg, so the speech model never depends on PyAV's version
    (some PyAV releases don't fit some faster-whisper releases). Falls back to the file path without numpy."""
    try:
        import numpy as np
    except ImportError:
        return str(source)
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0 or not proc.stdout:
        raise Problem(f"Couldn't read the sound in {source.name}: " + proc.stderr.decode("utf-8", "replace").strip()[-300:])
    return np.frombuffer(proc.stdout, dtype=np.float32).copy()


def load_transcript(source: Path) -> dict:
    path = transcript_path(source)
    if not path.exists():
        raise Problem(f"No transcript for {source.name} yet. Run: davnai.py transcribe \"{source}\"")
    return json.loads(path.read_text(encoding="utf-8"))


def print_lines(lines: list[dict], pick: str | None = None) -> None:
    first, last = 1, len(lines)
    if pick:
        m = re.fullmatch(r"(\d+)-(\d+)", pick.strip())
        if not m:
            raise Problem("Use --lines like 1-200.")
        first, last = int(m.group(1)), int(m.group(2))
    if not pick and len(lines) > 400:
        say(f"(Long transcript: {len(lines)} lines. Showing 1-400; see the rest with --lines 401-800 and so on.)")
        last = 400
    for line in lines[first - 1:last]:
        text = " ".join(w[0] for w in line["words"])
        print(f"#{line['id']} ({line['end'] - line['start']:.1f}s) {text}")


def cmd_transcribe(args) -> None:
    source = Path(args.video).expanduser().resolve()
    info = probe(source)
    if not info["audio"]:
        raise Problem(f"{source.name} has no sound to transcribe.")
    path = transcript_path(source)
    stamp = {"size": info["bytes"], "mtime": int(source.stat().st_mtime)}
    if path.exists() and not args.again:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("stamp") == stamp:
            say(f"Transcript of {source.name} ({len(data['lines'])} lines, reused):")
            print_lines(data["lines"], args.lines)
            return
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise Problem("Transcripts need faster-whisper: pip install faster-whisper") from exc
    say(f"Transcribing {source.name} ({info['seconds'] / 60:.1f} min) with the '{args.model}' model on this computer...")
    try:
        model = WhisperModel(args.model, device="auto", compute_type="int8")
    except Exception as exc:  # the first run downloads the model from Hugging Face
        raise Problem(f"Couldn't get the '{args.model}' speech model. The first transcript downloads it from huggingface.co "
                      f"(about 150 to 500 MB), so this computer needs internet access to that site once. ({type(exc).__name__}: {str(exc)[:160]})") from exc
    segments, details = model.transcribe(speech_audio(source), word_timestamps=True, vad_filter=True, language=args.language)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append([text, round(w.start, 3), round(w.end, 3)])
    if not words:
        raise Problem("No speech was found in this file.")
    lines = split_lines(join_pieces(words))
    path.write_text(json.dumps({"source": source.name, "stamp": stamp, "seconds": info["seconds"], "language": details.language, "lines": lines}), encoding="utf-8")
    say(f"Transcript of {source.name} ({len(lines)} lines):")
    print_lines(lines, args.lines)


# ---------------------------------------------------------------- choosing what to keep


def line_by_id(lines: list[dict], n) -> dict:
    try:
        n = int(n)
    except (TypeError, ValueError) as exc:
        raise Problem(f"'{n}' isn't a line number.") from exc
    if n < 1 or n > len(lines):
        raise Problem(f"Line {n} doesn't exist (the transcript has lines 1 to {len(lines)}).")
    return lines[n - 1]


def word_at(lines: list[dict], pair, edge: str) -> float:
    if not isinstance(pair, (list, tuple)) or len(pair) != 2:
        raise Problem("Use [line, word], for example [14, 3].")
    line = line_by_id(lines, pair[0])
    k = int(pair[1])
    if k < 1 or k > len(line["words"]):
        raise Problem(f"Line {pair[0]} has words 1 to {len(line['words'])}.")
    w = line["words"][k - 1]
    return w[1] if edge == "start" else w[2]


def keep_spans(lines: list[dict], keep: list, duration: float) -> list[tuple[float, float]]:
    """The plan's lines (IDs, never times) as [start, end] in seconds, in the order listed."""
    if not keep:
        raise Problem("This output has nothing in 'keep'.")
    spans = []
    for item in keep:
        if isinstance(item, dict):
            start, end = word_at(lines, item.get("from"), "start"), word_at(lines, item.get("to"), "end")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            a, b = line_by_id(lines, item[0]), line_by_id(lines, item[1])
            start, end = a["start"], b["end"]
        elif isinstance(item, (int, float)):
            line = line_by_id(lines, item)
            start, end = line["start"], line["end"]
        else:
            raise Problem(f"Can't read {json.dumps(item)} in 'keep'. Use [first, last] or {{\"from\": [line, word], \"to\": [line, word]}}.")
        if end <= start:
            raise Problem(f"{json.dumps(item)} ends before it starts.")
        spans.append((max(0.0, start - 0.08), min(duration, end + 0.15)))
    return spans


def all_words(lines: list[dict]) -> list[list]:
    return [w for line in lines for w in line["words"]]


def tighten(spans: list[tuple[float, float]], words: list[list]) -> list[tuple[float, float]]:
    out = []
    for s, e in spans:
        inside = [w for w in words if s <= (w[1] + w[2]) / 2 <= e]
        start = s
        for a, b in zip(inside, inside[1:]):
            if b[1] - a[2] > PAUSE:
                out.append((start, a[2] + KEEP_GAP))
                start = b[1] - KEEP_GAP
        out.append((start, e))
    return [(s, e) for s, e in out if e - s > 0.05]


# ---------------------------------------------------------------- themes, built-in sounds and quality checks

FONTS_DIR = BRAND_DIR.parent / "fonts"
SOUNDS_DIR = BRAND_DIR.parent / "sounds"
FONT_SOURCES = {  # free Google Fonts (Open Font License), downloaded by setup or on first use
    "Poppins-Medium.ttf": ("Poppins Medium", "ofl/poppins/Poppins-Medium.ttf"),
    "Poppins-Bold.ttf": ("Poppins", "ofl/poppins/Poppins-Bold.ttf"),
    "Poppins-ExtraBold.ttf": ("Poppins ExtraBold", "ofl/poppins/Poppins-ExtraBold.ttf"),
    "Anton-Regular.ttf": ("Anton", "ofl/anton/Anton-Regular.ttf"),
    "BebasNeue-Regular.ttf": ("Bebas Neue", "ofl/bebasneue/BebasNeue-Regular.ttf"),
    "DMSerifDisplay-Regular.ttf": ("DM Serif Display", "ofl/dmserifdisplay/DMSerifDisplay-Regular.ttf"),
    "DMSerifDisplay-Italic.ttf": ("DM Serif Display", "ofl/dmserifdisplay/DMSerifDisplay-Italic.ttf"),
    "Audiowide-Regular.ttf": ("Audiowide", "ofl/audiowide/Audiowide-Regular.ttf"),
    "Bungee-Regular.ttf": ("Bungee", "ofl/bungee/Bungee-Regular.ttf"),
    "SpaceMono-Bold.ttf": ("Space Mono", "ofl/spacemono/SpaceMono-Bold.ttf"),
    "ArchivoBlack-Regular.ttf": ("Archivo Black", "ofl/archivoblack/ArchivoBlack-Regular.ttf"),
    "PermanentMarker-Regular.ttf": ("Permanent Marker", "apache/permanentmarker/PermanentMarker-Regular.ttf"),
    "AbrilFatface-Regular.ttf": ("Abril Fatface", "ofl/abrilfatface/AbrilFatface-Regular.ttf"),
    "Righteous-Regular.ttf": ("Righteous", "ofl/righteous/Righteous-Regular.ttf"),
    # used by the studio effects engine
    "InstrumentSerif-Italic.ttf": ("Instrument Serif", "ofl/instrumentserif/InstrumentSerif-Italic.ttf"),
    "Inter.ttf": ("Inter", "ofl/inter/Inter%5Bopsz,wght%5D.ttf"),
    "Montserrat.ttf": ("Montserrat", "ofl/montserrat/Montserrat%5Bwght%5D.ttf"),
    "PlayfairDisplay.ttf": ("Playfair Display", "ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf"),
    "PlayfairDisplay-Italic.ttf": ("Playfair Display", "ofl/playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf"),
}
ENGINE = Path(__file__).resolve().parent.parent / "engine" / "fx.py"  # the studio effects (not in the one-file download)
MODELS_DIR = BRAND_DIR.parent / "models"
MODEL_FILES = {  # downloaded by setup from their makers, checked by fingerprint
    "yunet.onnx": ("https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                   "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "selfie_segmenter.tflite": ("https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite",
                                "191ac9529ae506ee0beefa6b2c945a172dab9d07d1e802a290a4e4038226658b"),
}
THEMES = {
    "clean": {
        "colours": ["#4338CA", "#0F172A"],  # used when the person has no brand colours
        "about": "Friendly and modern: rounded brand-colour boxes, soft shadows, gentle pops.",
        "caption_font": "Poppins-Bold.ttf", "title_font": "Poppins-ExtraBold.ttf",
        "caption": {"size": 0.072, "upper": False, "color": "#FFFFFF", "accent": "#FACC15", "outline": 0.05, "outlineColor": "#000000", "shadow": True, "box": None, "karaoke": "word", "words": 4, "anim": "pop", "place": "bottom"},
        "defaults": {"transition": "dissolve", "look": "soft"},
        "title_style": "pop", "sounds": {"transition": "swoosh", "motion": "pop"},
        "frame": "none", "grain": 0, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["dissolve", "slide", "zoom"], "title_styles": ["pop", "slide", "words"],
        "catalog": ["caption-highlight", "caption-pill-karaoke", "badge-pop", "card-resize", "count-up", "cta-close"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "bold": {
        "colours": ["#111111", "#FFE14D"],  # used when the person has no brand colours
        "about": "Loud and punchy: big uppercase words, hard shadows, flashes and zooms. For hooks and fast talkers.",
        "caption_font": "Anton-Regular.ttf", "title_font": "Anton-Regular.ttf",
        "caption": {"size": 0.095, "upper": True, "color": "#FFFFFF", "accent": "#FFE14D", "outline": 0.12, "outlineColor": "#000000", "shadow": False, "box": None, "karaoke": "word", "words": 2, "anim": "bounce", "keyScale": 1.15, "place": "middle"},
        "defaults": {"transition": "flash", "look": "punchy", "auto_zoom": True, "progress_bar": True},
        "title_style": "words", "sounds": {"transition": "whoosh", "motion": "impact"},
        "frame": "none", "grain": 0, "emphasis_fx": "shake",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["flash", "whip", "zoom", "glitch"], "title_styles": ["words", "bounce", "pop"],
        "catalog": ["caption-kinetic-slam", "char-slam-explode", "camera-shake", "kinetic-center-build", "shutter-slam", "beat-accent"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "editorial": {
        "colours": ["#1C1917", "#F5D0A9"],  # used when the person has no brand colours
        "about": "Calm and premium: serif titles, one quiet line of captions at the top, film-like colour.",
        "caption_font": "Poppins-Medium.ttf", "title_font": "DMSerifDisplay-Regular.ttf",
        "caption": {"size": 0.056, "upper": False, "color": "#FFFFFF", "accent": "#F5D0A9", "outline": 0.0, "outlineColor": "#000000", "shadow": True, "box": None, "karaoke": "word", "words": 6, "anim": "type", "place": "top"},
        "defaults": {"transition": "fade", "look": "cinematic"},
        "title_style": "glow", "sounds": {"transition": "swoosh", "motion": "click"},
        "frame": "letterbox", "grain": 0.5, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["fade", "dissolve", "blur"], "title_styles": ["glow", "typewriter", "slide"],
        "catalog": ["caption-editorial-emphasis", "caption-weight-shift", "grain-overlay", "curtain-reveal", "focus-blur-resolve", "morph-text"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "neon": {
        "colours": ["#0B0B1A", "#22D3EE"],  # used when the person has no brand colours
        "about": "Night-time and techy: glowing outlines, dark panels, glitch cuts.",
        "caption_font": "Audiowide-Regular.ttf", "title_font": "Audiowide-Regular.ttf",
        "caption": {"size": 0.068, "upper": True, "color": "#FFFFFF", "accent": "#22D3EE", "outline": 0.05, "outlineColor": "#22D3EE", "shadow": False, "box": None, "karaoke": "word", "words": 3, "anim": "fade", "glow": True, "place": "bottom"},
        "defaults": {"transition": "glitch", "look": "cool"},
        "title_style": "glow", "sounds": {"transition": "glitch", "motion": "ding"},
        "frame": "scanlines", "grain": 0, "emphasis_fx": "rgb",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["glitch", "flash", "blur"], "title_styles": ["glow", "typewriter", "words"],
        "catalog": ["caption-neon-glow", "caption-neon-accent", "rgb-glitch-text", "chromatic-aberration-wipe", "aurora-drift"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "minimal": {
        "colours": ["#18181B", "#3F3F46"],  # used when the person has no brand colours
        "about": "Quiet and simple: small captions at the top, plain cuts, no boxes.",
        "caption_font": "Poppins-Medium.ttf", "title_font": "Poppins-Bold.ttf",
        "caption": {"size": 0.05, "upper": False, "color": "#FFFFFF", "accent": "#FFFFFF", "outline": 0.03, "outlineColor": "#000000", "shadow": True, "box": None, "karaoke": "none", "words": 7, "anim": "fade", "place": "top"},
        "defaults": {},
        "title_style": "slide", "sounds": {},
        "frame": "none", "grain": 0, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["fade", "dissolve"], "title_styles": ["slide", "glow"],
        "catalog": ["caption-clip-wipe", "fade-through", "drift-hold", "blur-in"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "playful": {
        "colours": ["#FF5DA2", "#1B1B3A"],  # used when the person has no brand colours
        "about": "Bright and bouncy: rounded tilted stickers, big friendly letters, pops. For lifestyle, kids' and food content.",
        "caption_font": "Righteous-Regular.ttf", "title_font": "Bungee-Regular.ttf",
        "caption": {"size": 0.075, "upper": False, "color": "#FFFFFF", "accent": "#FF5DA2", "outline": 0.1, "outlineColor": "#1B1B3A", "shadow": True, "box": None, "karaoke": "word", "words": 3, "anim": "bounce", "keyScale": 1.2, "place": "bottom"},
        "defaults": {"transition": "slide_up", "look": "vivid"},
        "title_style": "bounce", "sounds": {"transition": "swoosh", "motion": "pop"},
        "frame": "none", "grain": 0, "emphasis_fx": "flash",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["slide_up", "circle", "zoom", "whip"], "title_styles": ["bounce", "pop", "words"],
        "catalog": ["caption-emoji-pop", "confetti", "badge-pop", "gesture-tap", "paper-collage-reveal"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "news": {
        "colours": ["#B91C1C", "#111111"],  # used when the person has no brand colours
        "about": "Newsroom: solid bars, uppercase headlines, straight wipes. For updates, explainers and commentary.",
        "caption_font": "ArchivoBlack-Regular.ttf", "title_font": "BebasNeue-Regular.ttf",
        "caption": {"size": 0.06, "upper": False, "color": "#FFFFFF", "accent": "#FFFFFF", "outline": 0.0, "outlineColor": "#000000", "shadow": False, "box": {"color": "#111111", "alpha": 0.85}, "karaoke": "none", "words": 5, "anim": "fade", "place": "bottom"},
        "defaults": {"transition": "wipe"},
        "title_style": "slide", "sounds": {"transition": "swoosh", "motion": "click"},
        "frame": "none", "grain": 0, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["wipe", "slide", "flash"], "title_styles": ["slide", "words"],
        "catalog": ["ticker-takeover", "caption-clip-wipe", "directional-wipe", "count-up", "chart-story"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "tech": {
        "colours": ["#0B0F14", "#34D399"],  # used when the person has no brand colours
        "about": "Developer and product: monospace type, typed-in captions, dark panels with a code feel.",
        "caption_font": "SpaceMono-Bold.ttf", "title_font": "SpaceMono-Bold.ttf",
        "caption": {"size": 0.055, "upper": False, "color": "#E5E7EB", "accent": "#34D399", "outline": 0.0, "outlineColor": "#000000", "shadow": False, "box": {"color": "#0B0F14", "alpha": 0.8}, "karaoke": "word", "words": 5, "anim": "type", "place": "bottom"},
        "defaults": {"transition": "glitch", "look": "cool"},
        "title_style": "typewriter", "sounds": {"transition": "glitch", "motion": "click"},
        "frame": "none", "grain": 0.3, "emphasis_fx": "glitch",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["glitch", "wipe", "slide"], "title_styles": ["typewriter", "words", "glow"],
        "catalog": ["code-terminal-run", "terminal-simulator", "caption-matrix-decode", "agent-cursor", "cursor-annotate", "ascii-trail-reveal"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "retro": {
        "colours": ["#C2410C", "#3B1F0E"],  # used when the person has no brand colours
        "about": "Retro: chunky letters, offset shadows, warm faded colour and film grain.",
        "caption_font": "Bungee-Regular.ttf", "title_font": "Bungee-Regular.ttf",
        "caption": {"size": 0.068, "upper": True, "color": "#FFF4D6", "accent": "#FF8A3D", "outline": 0.08, "outlineColor": "#3B1F0E", "shadow": True, "box": None, "karaoke": "word", "words": 3, "anim": "pop", "place": "bottom"},
        "defaults": {"transition": "dissolve", "look": "retro"},
        "title_style": "bounce", "sounds": {"transition": "whoosh", "motion": "pop"},
        "frame": "scanlines", "grain": 1.0, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["dissolve", "circle", "wipe"], "title_styles": ["bounce", "pop", "typewriter"],
        "catalog": ["grain-overlay", "stop-motion-cadence", "torn-paper-rip", "colorama-wipe", "caption-texture"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "luxury": {
        "colours": ["#0C0A08", "#E6C67A"],  # used when the person has no brand colours
        "about": "Luxury: elegant display serif, thin gold lines, slow dissolves. For fashion, property and beauty.",
        "caption_font": "Poppins-Medium.ttf", "title_font": "AbrilFatface-Regular.ttf",
        "caption": {"size": 0.058, "upper": False, "color": "#FFFFFF", "accent": "#E6C67A", "outline": 0.0, "outlineColor": "#000000", "shadow": True, "box": None, "karaoke": "word", "words": 5, "anim": "fade", "place": "bottom"},
        "defaults": {"transition": "dissolve", "look": "soft"},
        "title_style": "glow", "sounds": {"transition": "swoosh", "motion": "ding"},
        "frame": "border", "grain": 0.3, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["dissolve", "fade", "blur"], "title_styles": ["glow", "slide"],
        "catalog": ["caption-weight-shift", "gloss-sweep", "curtain-reveal", "focus-rack", "logo-brand-close"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "handwritten": {
        "colours": ["#FDE047", "#111111"],  # used when the person has no brand colours
        "about": "Creator notebook: marker handwriting, tilted notes, casual pops.",
        "caption_font": "PermanentMarker-Regular.ttf", "title_font": "PermanentMarker-Regular.ttf",
        "caption": {"size": 0.07, "upper": False, "color": "#FFFFFF", "accent": "#FDE047", "outline": 0.08, "outlineColor": "#111111", "shadow": True, "box": None, "karaoke": "word", "words": 3, "anim": "pop", "place": "bottom"},
        "defaults": {"transition": "whip"},
        "title_style": "words", "sounds": {"transition": "swoosh", "motion": "pop"},
        "frame": "none", "grain": 0.4, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["whip", "slide", "dissolve"], "title_styles": ["words", "bounce", "pop"],
        "catalog": ["hw-underline", "hw-arrow", "hw-callout-circle", "hw-box-label", "marker-checklist-card", "ink-bleed-reveal"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
    "podcast": {
        "colours": ["#1E3A8A", "#0F172A"],  # used when the person has no brand colours
        "about": "Podcast clips: the whole wide shot on a blurred background, big centred captions, key words stand out.",
        "caption_font": "Poppins-ExtraBold.ttf", "title_font": "Poppins-ExtraBold.ttf",
        "caption": {"size": 0.075, "upper": False, "color": "#FFFFFF", "accent": "#60A5FA", "outline": 0.08, "outlineColor": "#000000", "shadow": True, "box": None, "karaoke": "word", "words": 3, "anim": "pop", "keyScale": 1.15, "place": "middle"},
        "defaults": {"fill": "blur", "clean_audio": True},
        "title_style": "pop", "sounds": {"transition": "swoosh", "motion": "pop"},
        "frame": "none", "grain": 0, "emphasis_fx": "none",  # the theme kit: applied unless "theme_extras": false
        "other_transitions": ["dissolve", "flash"], "title_styles": ["pop", "words"],
        "catalog": ["caption-pill-karaoke", "caption-highlight", "count-up", "conic-progress-ring", "chat-message"],  # HyperFrames pieces that suit it (davnai.py catalog-get <name>)
    },
}

# Graphic shapes per theme (motion graphics), on top of the shared style.
THEME_CSS = {
    "bold": ".box{{border-radius:0;box-shadow:{s}px {s}px 0 #000;text-transform:uppercase}}.title{{font-size:{t}px}}.lt-name,.lt-role{{text-transform:uppercase}}",
    "editorial": ".box{{background:transparent;box-shadow:none;padding:0 0 {s}px;border-radius:0;border-bottom:{h}px solid {a};font-weight:400}}.panel{{background:rgba(10,10,10,.6);border-left:none;border-top:{h}px solid {a}}}.full{{background:#0d0d0d}}",
    "neon": ".box{{background:rgba(5,5,20,.55);border:{h}px solid {a};box-shadow:0 0 {g}px {a},inset 0 0 {s}px {a};text-shadow:0 0 {s}px {a}}}.panel{{border:{h}px solid {a};box-shadow:0 0 {g}px {a};background:rgba(5,5,20,.7)}}.full{{background:#05050f}}",
    "minimal": ".box{{background:transparent;box-shadow:none;padding:0;text-shadow:0 2px 12px rgba(0,0,0,.6)}}.title{{font-weight:500}}.panel{{background:rgba(0,0,0,.35);border-left:none}}",
    "playful": ".box{{border-radius:{g}px;transform:rotate(-2deg);box-shadow:0 {s}px 0 rgba(0,0,0,.25)}}.panel{{border-radius:{g}px;border-left:none;transform:rotate(1deg)}}",
    "news": ".box{{border-radius:0;box-shadow:none;border-left:{s}px solid {a};text-transform:uppercase}}.panel{{border-radius:0;border-left:{s}px solid {p}}}.lt-name{{text-transform:uppercase}}",
    "tech": ".box{{border-radius:{h}px;background:#0B0F14;border:{h}px solid {a};color:{a};box-shadow:none}}.panel{{background:#0B0F14;border-left:{h}px solid {a}}}",
    "retro": ".box{{border-radius:{h}px;border:{h}px solid #3B1F0E;box-shadow:{s}px {s}px 0 {a}}}.panel{{border:{h}px solid #3B1F0E;box-shadow:{s}px {s}px 0 {a}}}",
    "luxury": ".box{{background:transparent;box-shadow:none;padding:0 0 {s}px;border-radius:0;border-bottom:1px solid {a};color:#fff;font-weight:400;letter-spacing:.04em}}.panel{{background:rgba(0,0,0,.45);border-left:1px solid {a}}}.full{{background:#0c0a08}}",
    "handwritten": ".box{{background:#FFF8C5;color:#111;border-radius:{h}px;transform:rotate(-3deg);box-shadow:0 {s}px {g}px rgba(0,0,0,.3);font-weight:400}}.panel{{background:#FFF8C5;color:#111;transform:rotate(1.5deg);border-left:none}}",
}
def load_theme_files() -> list[str]:
    """Themes are also files: the skill's themes/ folder (one JSON file each) and the person's own in ~/.davnai/themes.
    A file replaces the built-in theme of the same name or adds a new one. Returns problems found (bad files are skipped)."""
    problems = []
    for folder in (Path(__file__).resolve().parent.parent / "themes", BRAND_DIR.parent / "themes"):
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = str(data.pop("name", path.stem))
                css = data.pop("css", None)
                base = json.loads(json.dumps(THEMES.get(data.get("base", name), THEMES["clean"])))
                base.update({k: v for k, v in data.items() if k not in ("caption", "defaults", "sounds", "base")})
                for key in ("caption", "defaults", "sounds"):
                    base[key] = {**base.get(key, {}), **(data.get(key) or {})}
                for key in ("caption_font", "title_font"):
                    if base[key] not in FONT_SOURCES:
                        raise ValueError(f"{key} {base[key]} isn't one of the theme fonts")
                THEMES[name] = base
                if css:
                    THEME_CSS[name] = css
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                problems.append(f"{path.name}: {exc}")
    return problems


SOUND_RECIPES = {  # made by ffmpeg on the person's computer: no sound files to licence
    "whoosh": "anoisesrc=color=pink:d=0.55:a=0.7:seed=7,highpass=f=300,lowpass=f=4500,afade=t=in:d=0.3,afade=t=out:st=0.3:d=0.25",
    "swoosh": "anoisesrc=color=pink:d=0.4:a=0.4:seed=11,highpass=f=900,lowpass=f=6000,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.2",
    "pop": "aevalsrc='0.8*sin(2*PI*(380+900*exp(-t*28))*t)*exp(-t*16)':d=0.28",
    "click": "aevalsrc='0.7*sin(2*PI*2400*t)*exp(-t*90)':d=0.08",
    "ding": "aevalsrc='0.5*(sin(2*PI*1320*t)+0.4*sin(2*PI*2640*t))*exp(-t*4)':d=1.2",
    "impact": "aevalsrc='0.9*sin(2*PI*(45+120*exp(-t*12))*t)*exp(-t*5)':d=0.9",
    "riser": "aevalsrc='0.35*sin(2*PI*(200*t+300*t*t))*min(t/1.2,1)':d=1.4",
    "glitch": "aevalsrc='0.45*sgn(sin(2*PI*180*t))*gt(mod(floor(t*40),3),0)*exp(-t*3)':d=0.35",
}


BUILT_IN_THEMES = json.loads(json.dumps(THEMES))  # before any theme files: the one-file download's own copy
BUILT_IN_CSS = dict(THEME_CSS)
THEME_FILE_PROBLEMS = load_theme_files()


def ensure_fonts(names) -> dict[str, Path]:
    """The theme fonts on this computer (downloads missing ones from Google Fonts once)."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    found = {}
    for name in names:
        path = FONTS_DIR / name
        if not path.exists() and name in FONT_SOURCES:
            code, _, data = http(f"https://raw.githubusercontent.com/google/fonts/main/{FONT_SOURCES[name][1]}", timeout=60)
            if code == 200 and data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                path.write_bytes(data)
        if path.exists():
            found[name] = path
    return found


def sound_file(name: str) -> Path | None:
    """A built-in sound, made once with ffmpeg."""
    if name not in SOUND_RECIPES:
        return None
    path = SOUNDS_DIR / f"{name}.wav"
    if not path.exists():
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", SOUND_RECIPES[name], "-ar", "48000", "-ac", "2", str(path)])
    return path


def theme_of(cfg: dict, plan: dict) -> dict | None:
    """A built-in theme by name, or your own: {"base": "bold", "caption": {...}, "defaults": {...}, ...}."""
    pick = cfg.get("theme") or plan.get("theme")
    if not pick:
        return None
    own = pick if isinstance(pick, dict) else {}
    name = own.get("base", "clean") if own else pick
    if name not in THEMES:
        raise Problem(f"Unknown theme '{name}'. Use: {', '.join(THEMES)}, or your own with \"base\".")
    theme = json.loads(json.dumps(THEMES[name]))
    for key in ("caption", "defaults", "sounds"):
        theme[key].update(own.get(key) or {})
    for key in ("caption_font", "title_font", "title_style"):
        if own.get(key):
            if key.endswith("_font") and own[key] not in FONT_SOURCES:
                raise Problem(f"Theme font '{own[key]}': use one of {', '.join(FONT_SOURCES)}.")
            theme[key] = own[key]
    return {"name": name, **theme}


def themed(cfg: dict, brand: dict, theme: dict | None) -> tuple[dict, dict]:
    """The output and Brand Kit with the theme applied (pure apart from fetching its fonts). The plan's own settings
    win over the theme; the Brand Kit's colours (and caption accent) recolour it unless "theme_colours" is true."""
    if not theme:
        return cfg, brand
    cfg = {**theme["defaults"], **cfg}
    brand = json.loads(json.dumps(brand or {}))
    fonts = ensure_fonts([theme["caption_font"], theme["title_font"]])
    look = dict(theme["caption"])
    own = (brand.get("captions") or {}).get("look") or {}
    if own.get("accent") and not cfg.get("theme_colours") and theme["name"] != "minimal":
        look["accent"] = own["accent"]
        if theme["name"] == "neon":
            look["outlineColor"] = own["accent"]
    caps = brand.setdefault("captions", {})
    caps["look"] = look
    caps["position"] = cfg.get("caption_position") or look["place"]
    cap_font = fonts.get(theme["caption_font"])
    caps["font_family"] = FONT_SOURCES[theme["caption_font"]][0] if cap_font else "Arial"
    caps["font_path"] = str(cap_font) if cap_font else None
    title_font = fonts.get(theme["title_font"])
    brand["theme"] = {"name": theme["name"], "title_style": theme["title_style"], "sounds": theme["sounds"],
                      "frame": theme.get("frame", "none"), "grain": theme.get("grain", 0), "emphasis_fx": theme.get("emphasis_fx", "none"),
                      "title_family": FONT_SOURCES[theme["title_font"]][0] if title_font else None, "title_path": str(title_font) if title_font else None}
    if cfg.get("theme_colours") or not [c for c in brand.get("colours") or [] if c.get("hex")]:
        brand["colours"] = [{"name": "theme", "hex": hx} for hx in theme.get("colours", [])]  # no brand colours: the theme's own
    return cfg, brand


def caption_font_path(caps: dict) -> Path | None:
    if caps.get("font_path") and Path(caps["font_path"]).exists():
        return Path(caps["font_path"])
    if caps.get("font_file") and (BRAND_DIR / caps["font_file"]).exists():
        return BRAND_DIR / caps["font_file"]
    return None


def measure(path: Path, filters: str) -> str:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf" if not filters.startswith("a:") else "-af", filters.removeprefix("a:"), "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    return proc.stderr


def quality_checks(path: Path, cfg: dict, brand: dict) -> list[str]:
    """Checks every render before the person sees it: black or frozen picture, loudness, length for the platform,
    and (when OpenCV is installed) captions covering a face."""
    info = probe(path)
    notes = []
    video_log = measure(path, "blackdetect=d=0.4:pix_th=0.10,freezedetect=n=0.002:d=2")
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", video_log)
    notes.append("⚠ black picture at " + ", ".join(f"{float(a):.1f}s" for a, _ in black[:4]) if black else "✓ no black frames")
    frozen = re.findall(r"freeze_start: ([\d.]+)", video_log)
    allowed = bool(cfg.get("scenes")) or any(m.get("type") in ("quote", "chapter", "end_screen") for m in cfg.get("motion") or []) or cfg.get("end_card")
    if frozen and not allowed:
        notes.append("⚠ the picture doesn't move for 2s+ at " + ", ".join(f"{float(a):.1f}s" for a in frozen[:4]))
    else:
        notes.append("✓ no frozen picture")
    if info["audio"]:
        audio_log = measure(path, "a:ebur128=peak=true,silencedetect=n=-45dB:d=2.5")
        loud = re.findall(r"I:\s+(-?[\d.]+) LUFS", audio_log.split("Summary:")[-1])
        if loud:
            lufs = float(loud[-1])
            notes.append(f"{'✓' if -17 <= lufs <= -11 else '⚠'} loudness {lufs:.1f} LUFS (social apps like about -14)")
        silent = re.findall(r"silence_start: ([\d.]+)", audio_log)
        if silent and not cfg.get("scenes"):
            notes.append("⚠ 2.5s+ of silence at " + ", ".join(f"{float(a):.1f}s" for a in silent[:4]))
    else:
        notes.append("⚠ no sound")
    if info["height"] > info["width"] and info["seconds"] > 180:
        notes.append(f"⚠ {info['seconds']:.0f}s is long for Shorts (YouTube Shorts allow 3 minutes; Reels and TikTok work best under 90s)")
    if cfg.get("captions"):
        notes.append(face_check(path, cfg, brand, info))
    return [n for n in notes if n]


def face_check(path: Path, cfg: dict, brand: dict, info: dict) -> str:
    try:
        import cv2  # optional: pip install opencv-python-headless
    except ImportError:
        return "· captions vs faces not checked (pip install opencv-python-headless to check)"
    caps = brand.get("captions") or {}
    look = {**DEFAULT_STYLE, **(caps.get("look") or {})}
    margins = caps.get("margins") or DEFAULT_MARGINS
    w, h = info["width"], info["height"]
    tall = h > w
    place = cfg.get("caption_position") or caps.get("position") or look.get("place") or "bottom"
    size = float(cfg.get("caption_size") or look.get("size", 0.075)) * min(w, h)
    m = margins["tall" if tall else "wide"]
    if cfg.get("caption_y"):  # the plan put the captions' bottom edge at this height
        band = (float(cfg["caption_y"]) * h - size * 2.6, float(cfg["caption_y"]) * h)
    elif place == "top":
        band = (m["top"] * h, m["top"] * h + size * 2.6)
    elif place == "middle":
        band = (h / 2 - size * 1.3, h / 2 + size * 1.3)
    else:
        band = (h - m["bottom"] * h - size * 2.6, h - m["bottom"] * h)
    finder = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    video = cv2.VideoCapture(str(path))
    hits, looked = [], 0
    for k in range(8):
        t = info["seconds"] * (k + 0.5) / 8
        video.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = video.read()
        if not ok:
            continue
        looked += 1
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for (_x, y, _fw, fh) in finder.detectMultiScale(grey, 1.15, 6, minSize=(int(min(w, h) * 0.12),) * 2):
            if y < band[1] and y + fh > band[0]:
                hits.append(t)
                break
    video.release()
    if looked and len(hits) >= max(2, looked // 3):
        better = "top" if place != "top" else "bottom"
        return f"⚠ captions cover a face at {', '.join(f'{t:.0f}s' for t in hits[:4])}: try \"caption_position\": \"{better}\" (or a different focus_x)"
    return "✓ captions clear of faces"


def cmd_themes(_args) -> None:
    say("Themes (\"theme\": \"<name>\" in the plan, or your own: {\"base\": \"bold\", \"caption\": {...}}):",
        *(f"  {n}: {t['about']} Fonts: {FONT_SOURCES[t['caption_font']][0]} / {FONT_SOURCES[t['title_font']][0]}. "
          f"Defaults: {', '.join(f'{k} {v}' for k, v in t['defaults'].items()) or 'none'}." for n, t in THEMES.items()),
        "The Brand Kit's colours and caption accent recolour every theme (\"theme_colours\": true keeps the theme's own).",
        f"Your own themes: JSON files in {BRAND_DIR.parent / 'themes'} (copy one from the skill's themes/ folder and change it).",
        *(f"⚠ skipped theme file {p}" for p in THEME_FILE_PROBLEMS))


def cmd_qc(args) -> None:
    need("ffmpeg")
    path = Path(args.file).expanduser().resolve()
    say(f"Checks for {path.name}:", *("  " + n for n in quality_checks(path, {"captions": args.captions}, load_brand())))


# ---------------------------------------------------------------- timeline (source times → the edited video's times)

TRANSITIONS = {  # name → ffmpeg xfade type and length (seconds)
    "fade": ("fadeblack", 0.35), "flash": ("fadewhite", 0.2), "dissolve": ("dissolve", 0.4), "whip": ("smoothleft", 0.25),
    "slide": ("slideleft", 0.3), "slide_up": ("slideup", 0.3), "zoom": ("zoomin", 0.3), "wipe": ("wipeleft", 0.3),
    "circle": ("circleopen", 0.35), "glitch": ("pixelize", 0.25), "blur": ("hblur", 0.3),
}
LOOKS = {
    "warm": "colorbalance=rs=0.06:bs=-0.06:rm=0.03:bm=-0.03,eq=saturation=1.08",
    "cool": "colorbalance=rs=-0.05:bs=0.06:bm=0.03,eq=saturation=1.02",
    "vivid": "eq=saturation=1.35:contrast=1.06",
    "punchy": "eq=contrast=1.14:saturation=1.2,unsharp=5:5:0.5",
    "bw": "hue=s=0,eq=contrast=1.12",
    "cinematic": "eq=contrast=1.1:saturation=0.9,colorbalance=rs=-0.04:bs=0.05:rh=0.06:bh=-0.05,vignette=PI/5",
    "soft": "eq=contrast=0.94:brightness=0.02:saturation=0.95",
    "vintage": "curves=preset=vintage,vignette=PI/4",
    "retro": "curves=preset=vintage,eq=saturation=0.85,noise=alls=12:allf=t,vignette=PI/4",
}


class Timeline:
    """Kept pieces of the source, grouped by the plan's keep items (transitions go between groups)."""

    def __init__(self, pieces: list[dict], transition: str | None, speed: float):
        self.pieces = pieces
        self.speed = speed
        self.kind, self.fade = TRANSITIONS.get(transition or "", (None, 0.0))
        groups: dict[int, list[dict]] = {}
        for p in pieces:
            groups.setdefault(p["group"], []).append(p)
        self.groups = [groups[k] for k in sorted(groups)]
        lengths = [sum((p["e"] - p["s"]) / speed for p in g) for g in self.groups]
        if self.kind and min(lengths, default=0) < self.fade * 2.5:
            self.kind, self.fade = None, 0.0  # a piece too short to blend: plain cuts
        self.lengths = lengths
        start = 0.0
        for k, g in enumerate(self.groups):
            t = start
            for p in g:
                p["out"] = t
                t += (p["e"] - p["s"]) / speed
            start += lengths[k] - self.fade
        self.duration = sum(lengths) - self.fade * max(0, len(self.groups) - 1)

    def words(self, words: list[list]) -> list[list]:
        out = []
        for p in self.pieces:
            for w in words:
                if p["s"] <= (w[1] + w[2]) / 2 <= p["e"]:
                    out.append([w[0], p["out"] + max(0.0, w[1] - p["s"]) / self.speed, p["out"] + (min(p["e"], w[2]) - p["s"]) / self.speed, w[3]])
        return sorted(out, key=lambda w: w[1])


def word_span(words: list[list], frm, to=None) -> tuple[float, float] | None:
    """Where "from": [line, word] .. "to": [line, word] is in the edited video (word numbers start at 1; "to" defaults
    to the end of the from line), or None if those words were cut (pure)."""
    def at(spec, last):
        line, n = int(spec[0]), int(spec[1])
        in_line = [w for w in words if w[3] == line]
        if not in_line:
            return None
        k = min(max(1, n), len(in_line)) - 1
        return in_line[k][2] if last else in_line[k][1]
    start = at(frm, False)
    end = at(to, True) if to else (max((w[2] for w in words if w[3] == int(frm[0])), default=None))
    return (start, end) if start is not None and end is not None and end > start else None


def line_window(words: list[list], first: int, last: int) -> tuple[float, float] | None:
    """Where lines first..last are in the edited video (from its words), or None if they were cut."""
    inside = [w for w in words if first <= w[3] <= last]
    return (min(w[1] for w in inside), max(w[2] for w in inside)) if inside else None


def split_pieces(pieces: list[dict], cuts: list[float]) -> list[dict]:
    out = []
    for p in pieces:
        points = sorted(c for c in cuts if p["s"] + 0.25 < c < p["e"] - 0.25)  # never a sliver: a 3-frame zoom change reads as a glitch
        points = [c for i, c in enumerate(points) if i == 0 or c - points[i - 1] > 0.25]
        edges = [p["s"], *points, p["e"]]
        out += [{**p, "s": a, "e": b} for a, b in zip(edges, edges[1:])]
    return out


def apply_zooms(pieces: list[dict], cfg: dict, lines: list[dict]) -> list[dict]:
    zooms = []
    for z in cfg.get("zoom") or []:
        rng = z.get("lines") if isinstance(z, dict) else z
        if isinstance(z, dict) and isinstance(z.get("from"), (list, tuple)):  # from a word to a word
            fl = line_by_id(lines, z["from"][0])
            tl_ = line_by_id(lines, (z.get("to") or [z["from"][0], len(fl["words"])])[0])
            fw = fl["words"][min(max(1, int(z["from"][1])), len(fl["words"])) - 1]
            tw = tl_["words"][min(max(1, int((z.get("to") or [0, len(tl_["words"])])[1])), len(tl_["words"])) - 1]
            zooms.append((fw[1] - 0.05, tw[2] + 0.1, float(z.get("amount") or 1.18), z.get("style") or "punch"))
            continue
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            raise Problem("Each zoom needs \"lines\": [first, last] (or \"from\": [line, word]).")
        a, b = line_by_id(lines, rng[0]), line_by_id(lines, rng[1])
        zooms.append((a["start"] - 0.05, b["end"] + 0.1, float((z.get("amount") if isinstance(z, dict) else None) or 1.18), (z.get("style") if isinstance(z, dict) else None) or "punch"))
    if cfg.get("auto_zoom"):
        pieces = split_pieces(pieces, [ln["start"] - 0.05 for ln in lines])
        for k, p in enumerate(pieces):
            p.setdefault("z", 1.12 if k % 2 else 1.0)
            p.setdefault("zs", "punch")
    if zooms:
        pieces = split_pieces(pieces, [t for z in zooms for t in z[:2]])
        for p in pieces:
            mid = (p["s"] + p["e"]) / 2
            for s, e, amount, style in zooms:
                if s <= mid <= e:
                    p["z"], p["zs"] = amount, style
    return pieces


# ---------------------------------------------------------------- captions and on-screen text


def caption_groups(words: list[list], per_line: int) -> list[list[list]]:
    groups, current = [], []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or len(current) >= per_line or nxt[1] - w[2] > 0.5 or re.search(r"[.!?…]$", w[0]):
            groups.append(current)
            current = []
    return groups


ANIM_TAGS = {
    "pop": "{\\fscx70\\fscy70\\t(0,110,\\fscx100\\fscy100)}",
    "bounce": "{\\fscx100\\fscy60\\t(0,90,\\fscy118)\\t(90,170,\\fscy100)}",
    "fade": "{\\fad(140,0)}",
    "slide": "{\\fad(80,0)\\frx40\\t(0,140,\\frx0)}",
}


def ass_text(t: str) -> str:
    return t.replace("{", "(").replace("}", ")").replace("\\", "/").replace("\n", "\\N")


def write_ass(path: Path, width: int, height: int, cfg: dict, brand: dict, words: list[list], duration: float, quiet: list[tuple[float, float]] = (), hide: list[tuple[float, float]] = ()) -> bool:
    """Captions (Brand Kit style), the hook title and text callouts, all in one subtitle file."""
    caps = brand.get("captions") or {}
    look = {**DEFAULT_STYLE, **(caps.get("look") or {})}
    margins = caps.get("margins") or DEFAULT_MARGINS
    colours = [c.get("hex") for c in brand.get("colours") or [] if c.get("hex")]
    brand_colour = colours[0] if colours else look.get("accent") or "#FFD43B"
    tall = height > width
    short_side = min(width, height)
    size = max(16, round(float(cfg.get("caption_size") or look.get("size", 0.075)) * short_side))
    m = margins["tall" if tall else "wide"]
    place = cfg.get("caption_position") or caps.get("position") or look.get("place") or "bottom"
    align, margin_v = {"top": (8, round(m["top"] * height)), "middle": (5, 0)}.get(place, (2, round(m["bottom"] * height)))
    if cfg.get("caption_y"):  # the plan puts the captions' bottom edge at this height (0 top, 1 bottom), e.g. over the chest
        align, margin_v = 2, round((1 - min(0.95, max(0.1, float(cfg["caption_y"])))) * height)
    family = caps.get("font_family") if caption_font_path(caps) else "Arial"
    theme = brand.get("theme") or {}
    title_family = theme.get("title_family") or family
    box = look.get("box")
    border, back = (3, ass_colour(box.get("color"), 1 - float(box.get("alpha", 0.6)))) if box else (1, ass_colour("#000000", 0.5))
    outline = round(float(look.get("outline", 0.07)) * size, 1) if not box else round(size * 0.18, 1)
    side = round(width * 0.08)
    styles = [
        f"Style: Davnai,{family},{size},{ass_colour(look.get('color'))},{ass_colour(look.get('accent'))},{ass_colour(look.get('outlineColor'))},{back},-1,0,0,0,100,100,0,0,{border},{outline},{2 if look.get('shadow') else 0},{align},{side},{side},{margin_v},1",
        f"Style: Hook,{title_family},{round(short_side * 0.085)},{ass_colour('#FFFFFF')},{ass_colour('#FFFFFF')},{ass_colour(brand_colour)},{ass_colour(brand_colour)},-1,0,0,0,100,100,0,0,3,{round(short_side * 0.02)},0,8,{side},{side},{round(height * (0.12 if tall else 0.08))},1",
        f"Style: Callout,{title_family},{round(short_side * 0.055)},{ass_colour('#111111')},{ass_colour('#111111')},{ass_colour('#FFFFFF')},{ass_colour('#FFFFFF')},-1,0,0,0,100,100,0,0,3,{round(short_side * 0.015)},0,8,{side},{side},{round(height * (0.22 if tall else 0.12))},1",
    ]
    events = []
    if cfg.get("captions") and words:
        fixes = {k.lower(): v for k, v in (cfg.get("fix") or {}).items()}
        emphasis = {e.lower() for e in cfg.get("emphasis") or []}
        per_line = int(cfg.get("caption_words") or look.get("words") or 4)
        upper = bool(look.get("upper"))
        accent = ass_colour(look.get("accent"))
        anim = cfg.get("caption_animation") or look.get("anim") or "pop"
        karaoke = look.get("karaoke", "word") != "none" and (look.get("accent") or "").upper() != (look.get("color") or "").upper()
        glow = "{\\blur4}" if look.get("glow") else ""
        big = max(1.0, float(look.get("keyScale", 1.0)), 1.15 if emphasis else 1.0)

        def word_text(w: list, active: bool) -> str:
            key = re.sub(r"[^\w']", "", w[0]).lower()
            t = ass_text(fixes.get(key, w[0]))
            t = t.upper() if upper else t
            if key in emphasis:
                return f"{{\\c{accent}\\fscx{round(big * 100)}\\fscy{round(big * 100)}}}{t}{{\\r}}"
            return f"{{\\c{accent}}}{t}{{\\r}}" if active and karaoke else t

        for group in caption_groups(words, per_line):
            start, end = group[0][1], max(group[-1][2], group[0][1] + 0.3)
            # While an effect fills the frame (words behind, a poster, a studio effect) the captions keep going but move
            # up out of its way, so the viewer never loses the words.
            # While a scene shrinks the speaker into a card or window, the captions drop to the bottom of the frame
            # (over the lower part of the video) so they never sit on the scene's headline.
            low = any(a - 0.05 <= start <= b - 0.1 for a, b in hide)
            busy = not low and any(a - 0.05 <= start <= b for a, b in quiet)
            mv = round(m["top"] * height) if busy else round(height * 0.055) if low else 0
            top_tag = "{\\an8}" if busy else "{\\an2}" if low else ""
            intro = top_tag + glow + ANIM_TAGS.get(anim, "")
            if anim == "type":
                for k, w in enumerate(group):
                    w_end = group[k + 1][1] if k + 1 < len(group) else end
                    events.append(f"Dialogue: 0,{ass_time(w[1] if k else start)},{ass_time(w_end)},Davnai,,0,0,{mv},,{top_tag}{glow}{' '.join(word_text(x, j == k) for j, x in enumerate(group[: k + 1]))}")
            elif karaoke:
                for k, w in enumerate(group):
                    w_end = group[k + 1][1] if k + 1 < len(group) else end
                    events.append(f"Dialogue: 0,{ass_time(w[1] if k else start)},{ass_time(w_end)},Davnai,,0,0,{mv},,{intro if k == 0 else top_tag + glow}{' '.join(word_text(x, j == k) for j, x in enumerate(group))}")
            else:
                events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Davnai,,0,0,{mv},,{intro}{' '.join(word_text(x, False) for x in group)}")
    if cfg.get("hook_text"):
        seconds = float(cfg.get("hook_seconds", 3))
        events.append(f"Dialogue: 1,{ass_time(0)},{ass_time(min(seconds, duration))},Hook,,0,0,0,,{ANIM_TAGS['pop']}{ass_text(str(cfg['hook_text']))}")
    for item in cfg.get("texts") or []:
        rng = item.get("lines")
        window = line_window(words, int(rng[0]), int(rng[1])) if isinstance(rng, (list, tuple)) and len(rng) == 2 else None
        if window is None:
            raise Problem(f"Text \"{item.get('text', '')}\": its lines {rng} aren't in this video.")
        pos = {"top": "", "middle": "{\\an5}", "bottom": "{\\an2}"}.get(item.get("position", "top"), "")
        events.append(f"Dialogue: 2,{ass_time(window[0])},{ass_time(window[1] + 0.2)},Callout,,0,0,0,,{pos}{ANIM_TAGS['pop']}{ass_text(str(item.get('text', '')))}")
    for a, b, text, x, y in cfg.get("_labels") or []:
        events.append(f"Dialogue: 3,{ass_time(a)},{ass_time(b)},Callout,,0,0,0,,{{\\an8\\pos({x},{y})}}{ANIM_TAGS['pop']}{ass_text(text)}")
    if not events:
        return False
    header = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    path.write_text(header + "\n" + "\n".join(events) + "\n", encoding="utf-8")
    return True


def end_card_ass(path: Path, width: int, height: int, text: str, brand: dict) -> None:
    caps = brand.get("captions") or {}
    family = (brand.get("theme") or {}).get("title_family") or (caps.get("font_family") if caption_font_path(caps) else "Arial")
    size = round(min(width, height) * 0.115)
    text = text.upper() if len(text) <= 40 else text
    path.write_text("\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: End,{family},{size},{ass_colour('#FFFFFF')},{ass_colour('#FFFFFF')},{ass_colour('#000000', 0.6)},{ass_colour('#000000', 1)},-1,0,0,0,100,100,0,0,1,{round(size * 0.04)},0,5,{round(width * 0.1)},{round(width * 0.1)},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,{ass_time(0.1)},{ass_time(60)},End,,0,0,0,,{ANIM_TAGS['pop']}{ass_text(text)}",
    ]) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- render


def target_size(aspect: str, src_w: int, src_h: int, final: bool) -> tuple[int, int]:
    if aspect in SIZES:
        w, h = SIZES[aspect]
    else:
        w, h = src_w or 1920, src_h or 1080
        scale = min(1.0, 1920 / max(w, h))
        w, h = w * scale, h * scale
    if not final:
        w, h = w / 2, h / 2
    return even(w), even(h)


def shape(label_in: str, label_out: str, src_w: int, src_h: int, w: int, h: int, focus_x: float, fps: float, fill: str = "crop") -> list[str]:
    """Fit a picture to the output's shape: crop (keeping focus_x across), or the whole picture on a blurred copy."""
    tail = f"setsar=1,fps={fps:g},format=yuv420p"
    if fill == "blur" and src_w and src_h and abs(src_w / src_h - w / h) > 0.02:
        return [
            f"[{label_in}]split[{label_out}_bgs][{label_out}_fgs]",
            f"[{label_out}_bgs]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:2,eq=brightness=-0.06[{label_out}_bg]",
            f"[{label_out}_fgs]scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos[{label_out}_fg]",
            f"[{label_out}_bg][{label_out}_fg]overlay=(W-w)/2:(H-h)/2,{tail}[{label_out}]",
        ]
    crop = ""
    if src_w and src_h:
        src_ar, ar = src_w / src_h, w / h
        if src_ar > ar + 0.01:
            cw = even(src_h * ar)
            crop = f"crop={cw}:{even(src_h)}:{max(0, round((src_w - cw) * focus_x))}:0,"
        elif src_ar < ar - 0.01:
            ch = even(src_w / ar)
            crop = f"crop={even(src_w)}:{ch}:0:{max(0, round((src_h - ch) / 2))},"
    return [f"[{label_in}]{crop}scale={w}:{h}:flags=lanczos,{tail}[{label_out}]"]


def fit(label_in: str, label_out: str, w: int, h: int, fps: float) -> str:
    """Fit inside the output's shape with bars (intros, outros and pictures of another shape)."""
    return f"[{label_in}]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps:g},format=yuv420p[{label_out}]"


AUDIO_FMT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
CUT_FADE = 0.012  # seconds of fade at each cut: removes the click without being heard
VOICE_CLEAN = "highpass=f=75,afftdn=nf=-32:tn=1,dynaudnorm=f=200:g=15:p=0.9:m=6,equalizer=f=250:t=q:w=1.2:g=-2,equalizer=f=4500:t=q:w=1.5:g=2,acompressor=threshold=-21dB:ratio=3:attack=6:release=140:makeup=2"
VOICE_CLEAN_STRONG = "highpass=f=90,afftdn=nf=-26:tn=1,dynaudnorm=f=200:g=15:p=0.9:m=6,equalizer=f=250:t=q:w=1.2:g=-3,equalizer=f=4500:t=q:w=1.5:g=2.5,acompressor=threshold=-22dB:ratio=3.5:attack=5:release=120:makeup=2"
LIMITER = "alimiter=limit=0.89:attack=4:release=60:level=disabled"  # never louder than -1 dB: no distortion
DUCK = "sidechaincompress=threshold=0.02:ratio=10:attack=15:release=420:makeup=1"  # music dips under speech


def zoom_filter(z: float, style: str, src_w: int, src_h: int, focus_x: float, fps: float) -> str:
    if z <= 1.001:
        return ""
    if style == "smooth":
        return f"zoompan=z='min(1+{z - 1:.3f}*on/{round(fps * 0.6)},{z:.3f})':x='(iw-iw/zoom)*{focus_x:.3f}':y='(ih-ih/zoom)/2':d=1:s={even(src_w)}x{even(src_h)}:fps={fps:g},"
    cw, ch = even(src_w / z), even(src_h / z)
    return f"crop={cw}:{ch}:{round((src_w - cw) * focus_x)}:{round((src_h - ch) / 2)},scale={even(src_w)}:{even(src_h)},"


def next_version(folder: Path, name: str) -> int:
    found = [int(m.group(1)) for p in folder.glob(f"{name}_v*.plan.json") if (m := re.search(r"_v(\d+)\.plan\.json$", p.name))]
    return max(found, default=0) + 1


def render_output(plan_dir: Path, cfg: dict, plan: dict, brand: dict, final: bool, version: int, folder: Path) -> Path:
    name = re.sub(r"[^\w\-]", "_", cfg.get("name") or "video")
    inputs: list[list[str]] = []
    graph: list[str] = []

    def add_input(*arg: str) -> int:
        inputs.append(list(arg))
        return len(inputs) - 1

    def resolve(p: str) -> Path:
        q = Path(str(p)).expanduser()
        return q if q.is_absolute() else (plan_dir / q).resolve()

    def sound(p: str) -> Path:
        """A sound file of theirs, or a built-in one by name (whoosh, swoosh, pop, click, ding, impact, riser, glitch)."""
        q = resolve(p)
        return q if q.exists() else (sound_file(str(p)) or q)

    cfg, brand = themed(cfg, brand, theme_of(cfg, plan))
    fonts_dir = folder / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    theme = brand.get("theme") or {}
    for fp in (caption_font_path(brand.get("captions") or {}), Path(theme["title_path"]) if theme.get("title_path") else None):
        if fp and fp.exists():
            shutil.copy2(fp, fonts_dir / fp.name)
    auto_sounds: list[tuple[float, str]] = []
    joins_sound = theme.get("sounds", {}).get("transition") if cfg.get("sounds", True) and cfg.get("transition") not in (None, "cut") else None

    aspect = cfg.get("aspect", "9:16")
    focus_x = min(1.0, max(0.0, float(cfg.get("focus_x", 0.5))))
    face_out = None
    fill = cfg.get("fill", "crop")
    speed = min(2.0, max(0.5, float(cfg.get("speed", 1.0))))
    transition = cfg.get("transition")
    if transition and transition not in TRANSITIONS and transition != "cut":
        raise Problem(f"Unknown transition '{transition}'. Use: cut, {', '.join(TRANSITIONS)}.")

    if cfg.get("scenes"):  # faceless: clips and pictures over a voice-over
        voice = resolve(cfg.get("voice") or "")
        vinfo = probe(voice)
        lines = load_transcript(voice)["lines"]
        w, h = target_size(aspect if aspect != "source" else "9:16", 0, 0, final)
        fps = 30.0
        scenes = cfg["scenes"]
        kind, fade = TRANSITIONS.get(transition or "", (None, 0.0))
        starts = []
        for k, sc in enumerate(scenes):
            rng = sc.get("lines")
            if not isinstance(rng, (list, tuple)) or len(rng) != 2:
                raise Problem(f"Scene {k + 1} needs \"lines\": [first, last].")
            starts.append(0.0 if k == 0 else line_by_id(lines, rng[0])["start"])
        if cfg.get("beat_cuts") and cfg.get("music"):
            beats = beats_of(resolve(cfg["music"]), vinfo["seconds"])
            for k in range(1, len(starts)):  # scene changes land on the nearest beat (within 0.3 s)
                near = min(beats, key=lambda bt: abs(bt - starts[k]), default=None)
                if near is not None and abs(near - starts[k]) <= 0.3 and near > starts[k - 1] + 0.5:
                    starts[k] = near
        ends = starts[1:] + [vinfo["seconds"]]
        if kind and min(e - s for s, e in zip(starts, ends)) < fade * 2.5:
            kind, fade = None, 0.0
        for k, sc in enumerate(scenes):
            dur = max(0.2, ends[k] - starts[k]) + (fade if k < len(scenes) - 1 else 0.0)  # blends overlap: keep in time with the voice
            clip = resolve(sc.get("clip") or "")
            if not clip.exists():
                raise Problem(f"Scene {k + 1}: can't find {clip}.")
            if clip.suffix.lower() in IMAGE_EXT:
                idx = add_input("-loop", "1", "-framerate", f"{fps:g}", "-t", f"{dur:.3f}", "-i", str(clip))
                frames = max(1, round(dur * fps))
                graph.append(f"[{idx}:v]scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},zoompan=z='min(zoom+0.0008,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps:g},setsar=1,format=yuv420p,trim=duration={dur:.3f},setpts=PTS-STARTPTS[s{k}]")
            else:
                cinfo = probe(clip)
                idx = add_input("-stream_loop", "-1", "-ss", f"{float(sc.get('start', 0)):.3f}", "-t", f"{dur:.3f}", "-i", str(clip))
                graph += shape(f"{idx}:v", f"c{k}", cinfo["width"], cinfo["height"], w, h, float(sc.get("focus_x", 0.5)), fps, sc.get("fill", fill))
                graph.append(f"[c{k}]trim=duration={dur:.3f},setpts=PTS-STARTPTS[s{k}]")
        if kind and len(scenes) > 1:
            prev, offset = "s0", 0.0
            for k in range(1, len(scenes)):
                offset += (ends[k - 1] - starts[k - 1])
                graph.append(f"[{prev}][s{k}]xfade=transition={kind}:duration={fade:.3f}:offset={offset:.3f}[x{k}]")
                prev = f"x{k}"
            graph.append(f"[{prev}]null[vbase]")
        else:
            graph.append("".join(f"[s{k}]" for k in range(len(scenes))) + f"concat=n={len(scenes)}:v=1:a=0[vbase]")
        if joins_sound:
            auto_sounds += [(t, joins_sound) for t in starts[1:]]
        vi = add_input("-i", str(voice))
        graph.append(f"[{vi}:a]{AUDIO_FMT}[abase]")
        words = [[w_[0], w_[1], w_[2], ln["id"]] for ln in lines for w_ in ln["words"]]
        main_len = vinfo["seconds"]
    else:  # cut a recording by its transcript lines
        source = resolve(cfg.get("source") or plan.get("source") or "")
        info = probe(source)
        lines = load_transcript(source)["lines"]
        src_words = [[w_[0], w_[1], w_[2], ln["id"]] for ln in lines for w_ in ln["words"]]
        pieces = []
        for g, item in enumerate(cfg.get("keep") or []):
            spans = keep_spans(lines, [item], info["seconds"])
            if cfg.get("tighten"):
                spans = tighten(spans, src_words)
            pieces += [{"s": s, "e": e, "group": g} for s, e in spans]
        if not pieces:
            raise Problem("This output has nothing in 'keep'.")
        pieces = apply_zooms(pieces, cfg, lines)
        w, h = target_size(aspect, info["width"], info["height"], final)
        fps = 30.0 if aspect != "source" else min(60.0, max(24.0, round(info["fps"])))
        # Every piece is a whole number of frames (and its sound exactly as long), so captions and graphics never
        # drift, however many cuts there are.
        for p in pieces:
            p["frames"] = max(1, round((p["e"] - p["s"]) / speed * fps))
            p["e"] = p["s"] + p["frames"] / fps * speed
        timeline = Timeline(pieces, transition, speed)
        if cfg.get("face_aware", True):  # find the speaker: keep them in a tall crop, and keep text off their face
            faces = detect_faces(source, [(p["s"] + p["e"]) / 2 for p in pieces[:: max(1, len(pieces) // 10)]])
            better = auto_focus(cfg, faces, info["width"], info["height"], w, h)
            if better is not None:
                focus_x = better
            box = median_box(faces)
            face_out = face_to_output(box, info["width"], info["height"], w, h, focus_x, fill) if box else None
        tempo = f",atempo={speed:g}" if abs(speed - 1) > 0.001 else ""
        for k, p in enumerate(pieces):
            # Each piece reads only its own seconds of the file (one input per piece), so many cuts in a long video
            # never pile up frames in memory; and it's shaped to the output first, so zooms work on the small frame.
            si = add_input("-ss", f"{p['s']:.4f}", "-t", f"{p['e'] - p['s'] + 2 / fps:.4f}", "-i", str(source))
            graph.append(f"[{si}:v]setpts=PTS-STARTPTS[pv{k}]")
            graph += shape(f"pv{k}", f"ps{k}", info["width"], info["height"], w, h, focus_x, fps, fill)
            z = zoom_filter(p.get("z", 1.0), p.get("zs", "punch"), w, h, 0.5, fps)
            graph.append(f"[ps{k}]{z}setpts=(PTS-STARTPTS)/{speed:g},fps={fps:g},tpad=stop_mode=clone:stop=3,trim=end_frame={p['frames']},setpts=PTS-STARTPTS,setsar=1[v{k}]")
            if info["audio"]:
                piece_len = (p["e"] - p["s"]) / speed
                fades = f",afade=t=in:d={CUT_FADE},afade=t=out:st={max(0.0, piece_len - CUT_FADE):.4f}:d={CUT_FADE}" if piece_len > CUT_FADE * 4 else ""  # no pop at the cut
                graph.append(f"[{si}:a]atrim=end={p['e'] - p['s']:.4f},asetpts=PTS-STARTPTS{tempo},{AUDIO_FMT}{fades},apad,atrim=end_sample={round(p['frames'] / fps * 48000)}[a{k}]")
            else:
                graph.append(f"anullsrc=r=48000:cl=stereo,atrim=end_sample={round(p['frames'] / fps * 48000)},aformat=sample_fmts=fltp[a{k}]")
        index = {id(p): k for k, p in enumerate(pieces)}
        for gi, group in enumerate(timeline.groups):
            ks = [index[id(p)] for p in group]
            graph.append("".join(f"[v{k}][a{k}]" for k in ks) + f"concat=n={len(ks)}:v=1:a=1[gv{gi}][ga{gi}]")
        if timeline.kind and len(timeline.groups) > 1:
            pv, pa, offset = "gv0", "ga0", 0.0
            for gi in range(1, len(timeline.groups)):
                offset += timeline.lengths[gi - 1] - timeline.fade
                graph.append(f"[{pv}][gv{gi}]xfade=transition={timeline.kind}:duration={timeline.fade:.3f}:offset={offset:.3f}[xv{gi}]")
                graph.append(f"[{pa}][ga{gi}]acrossfade=d={timeline.fade:.3f}[xa{gi}]")
                pv, pa = f"xv{gi}", f"xa{gi}"
            graph.append(f"[{pv}]null[vcut]")
            graph.append(f"[{pa}]anull[acut]")
        else:
            n = len(timeline.groups)
            graph.append("".join(f"[gv{gi}][ga{gi}]" for gi in range(n)) + f"concat=n={n}:v=1:a=1[vcut][acut]")
        graph.append("[vcut]null[vbase]")
        audio_fx = []
        if cfg.get("voice", "clean") != "raw":  # rumble out, hiss down, even level, a touch of air: speech that sounds produced
            audio_fx.append(VOICE_CLEAN_STRONG if cfg.get("clean_audio") or cfg.get("voice") == "strong" else VOICE_CLEAN)
        if cfg.get("loudness", True):
            audio_fx.append("loudnorm=I=-14:TP=-1.5:LRA=9")
        graph.append(f"[acut]{','.join(audio_fx + [LIMITER])},{AUDIO_FMT}[abase]")
        words = timeline.words(src_words)
        main_len = timeline.duration
        if joins_sound:
            auto_sounds += [(g[0]["out"], joins_sound) for g in timeline.groups[1:]]

    label = "vbase"
    raw_label = None
    if any(it.get("type") == "compare" for it in cfg.get("fx") or []):
        graph.append("[vbase]split[vbase0][vraw]")
        label, raw_label = "vbase0", "vraw"
    if cfg.get("split"):
        part, label = split_graph(label, cfg, w, h, fps, main_len, add_input, resolve)
        graph += part
        cfg.setdefault("caption_position", "middle")
    if cfg.get("look"):
        if cfg["look"] not in LOOKS:
            raise Problem(f"Unknown look '{cfg['look']}'. Use: {', '.join(LOOKS)}.")
        graph.append(f"[{label}]{LOOKS[cfg['look']]}[vlook]")
        label = "vlook"
    extras = theme if cfg.get("theme_extras", True) else {}
    if extras:  # the theme kit: grain over the whole video, an effect on each emphasised word
        fx = list(cfg.get("fx") or [])
        if extras.get("grain") and not any(f.get("type") == "grain" for f in fx):
            fx.append({"type": "grain", "all": True, "strength": float(extras["grain"])})
        if extras.get("emphasis_fx") not in (None, "none") and cfg.get("emphasis"):
            wanted = {e.lower() for e in cfg["emphasis"]}
            hit = sorted({int(wd[3]) for wd in words if re.sub(r"[^\w']", "", wd[0]).lower() in wanted})[:8]
            fx += [{"type": extras["emphasis_fx"], "lines": [n, n], "seconds": 0.35, "strength": 0.8} for n in hit]
        cfg = {**cfg, "fx": fx}
    part, label = fx_graph(label, cfg, words, main_len, w, h, fps)
    graph += part
    if cfg.get("beat_pulse") and cfg.get("music"):
        part, label = beat_pulse(label, beats_of(resolve(cfg["music"]), main_len), w, h, fps, float(cfg.get("beat_amount", 0.04)))
        graph += part
    behind = behind_windows(cfg, words, main_len)
    if any(it.get("slice") or it.get("type") == "cycle" for _, _, it in behind):  # sliced words and picture changes land on the beat
        song = beats_of(resolve(cfg["music"]), main_len) if cfg.get("music") else []
        behind = [(a, b, {**it, "_beats": song}) if it.get("slice") or it.get("type") == "cycle" else (a, b, it) for a, b, it in behind]
        behind = [(a, b, {**it, "_images": cycle_images(it, resolve)}) if it.get("type") == "cycle" else (a, b, it) for a, b, it in behind]
    for k, it in enumerate(cfg.get("fx") or []):
        if it.get("type") == "cycle" and not it.get("behind", True):  # pictures over the whole frame: no cut-out needed
            a, b = fx_window(it, words, main_len)
            song = beats_of(resolve(cfg["music"]), main_len) if cfg.get("music") else []
            reel = folder / f"{name}_v{version}_cycle{k}.mp4"
            cycle_reel(reel, cycle_images(it, resolve), cycle_times(a, b, song, float(it.get("every", 0.4))), b, w, h)
            ci = add_input("-itsoffset", f"{a:.3f}", "-i", str(reel))
            alpha = min(1.0, float(it.get("opacity", 1.0)))
            graph.append(f"[{ci}:v]format=rgba,colorchannelmixer=aa={alpha:.2f}[cy{k}]")
            graph.append(f"[{label}][cy{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[vcy{k}]")
            label = f"vcy{k}"
    studio = [(*fx_window(it, words, main_len), it) for it in cfg.get("fx") or [] if it.get("type") == "studio"]
    if studio and studio_problem():
        raise Problem(studio_problem())
    compares = [(*fx_window(it, words, main_len), it) for it in cfg.get("fx") or [] if it.get("type") == "compare"]
    if compares:  # before / after: the cut picture, before looks and effects, on the left half
        part, label = compare_graph(label, raw_label, compares, w, h)
        graph += part
        cfg = {**cfg, "_labels": [lab for a, b, it in compares for lab in compare_labels(a, b, it, w, h)]}
    for k, item in enumerate(cfg.get("broll") or []):  # cutaways, picture-in-picture and stickers over the main video
        rng = item.get("lines")
        window = line_window(words, int(rng[0]), int(rng[1])) if isinstance(rng, (list, tuple)) and len(rng) == 2 else None
        if window is None:
            raise Problem(f"B-roll {k + 1}: its lines {rng} aren't in this video.")
        a, b = window[0], window[1] + 0.15
        clip = resolve(item.get("clip") or "")
        if not clip.exists():
            raise Problem(f"B-roll {k + 1}: can't find {clip}.")
        mode = item.get("mode", "full")
        dur = b - a
        if clip.suffix.lower() in IMAGE_EXT:
            bi = add_input("-loop", "1", "-framerate", f"{fps:g}", "-t", f"{dur:.3f}", "-i", str(clip))
            cw_, ch_ = 0, 0
        else:
            cinfo = probe(clip)
            bi = add_input("-stream_loop", "-1", "-ss", f"{float(item.get('start', 0)):.3f}", "-t", f"{dur:.3f}", "-i", str(clip))
            cw_, ch_ = cinfo["width"], cinfo["height"]
        if mode == "full":
            if cw_:
                graph += shape(f"{bi}:v", f"bs{k}", cw_, ch_, w, h, float(item.get("focus_x", 0.5)), fps)
            else:
                graph.append(f"[{bi}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps={fps:g},format=yuv420p[bs{k}]")
            graph.append(f"[bs{k}]setpts=PTS-STARTPTS+{a:.3f}/TB[b{k}]")
            graph.append(f"[{label}][b{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[vb{k}]")
        else:
            share = 0.42 if mode == "pip" else 0.24
            bw = even(w * share)
            frame = f",pad=iw+{even(bw * 0.03)}:ih+{even(bw * 0.03)}:(ow-iw)/2:(oh-ih)/2:white" if mode == "pip" else ""
            graph.append(f"[{bi}:v]scale={bw}:-2,format=rgba{frame},setpts=PTS-STARTPTS+{a:.3f}/TB[b{k}]")
            spot = {"top-left": f"{round(w * 0.05)}:{round(h * 0.1)}", "top-right": f"W-w-{round(w * 0.05)}:{round(h * 0.1)}", "middle": "(W-w)/2:(H-h)/2", "bottom-left": f"{round(w * 0.05)}:H-h-{round(h * 0.38 if h > w else h * 0.1)}"}.get(item.get("position", "top-right"), f"W-w-{round(w * 0.05)}:{round(h * 0.1)}")
            graph.append(f"[{label}][b{k}]overlay={spot}:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[vb{k}]")
        label = f"vb{k}"
    frame = (extras or {}).get("frame", "none")
    if frame != "none":  # the theme's frame, under the captions
        edge = max(2, round(min(w, h) * 0.004))
        accent = "0x" + ((brand.get("captions") or {}).get("look", {}).get("accent") or "#FFFFFF").lstrip("#")
        frame_filter = {
            "letterbox": f"drawbox=x=0:y=0:w=iw:h=ih*0.07:color=black:t=fill,drawbox=x=0:y=ih*0.93:w=iw:h=ih*0.07:color=black:t=fill",
            "border": f"drawbox=x=iw*0.035:y=ih*0.025:w=iw*0.93:h=ih*0.95:color={accent}@0.85:t={edge}",
            "scanlines": f"drawgrid=w=0:h={max(3, edge * 2)}:t=1:c=black@0.16",
        }.get(frame)
        if frame_filter:
            graph.append(f"[{label}]{frame_filter}[vframe]")
            label = "vframe"
    if face_out and not cfg.get("caption_position") and not cfg.get("caption_y"):  # captions move off the face (the plan can still choose)
        caps_ = brand.get("captions") or {}
        look_ = {**DEFAULT_STYLE, **(caps_.get("look") or {})}
        preferred = caps_.get("position") or look_.get("place") or "bottom"
        place = clear_place(face_out, w, h, look_, caps_.get("margins") or DEFAULT_MARGINS, preferred)
        if place != preferred:
            cfg = {**cfg, "caption_position": place}
    ass = folder / f"{name}_v{version}.ass"
    scenes = [(*fx_window(it, words, main_len), it) for it in cfg.get("motion") or [] if it.get("type") == "scene"]
    hide = [(a, b) for a, b, it in scenes if it.get("title") or it.get("items") or it.get("number")]
    # With later passes (cut-out effects, studio effects, graphics, scenes) the captions are burned in last, so they stay
    # full size and sharp on top of everything, even when a scene shrinks the video into a card.
    late_captions = bool(behind or studio or cfg.get("motion"))
    has_captions = write_ass(ass, w, h, cfg, brand, words, main_len, [(a, b) for a, b, it in behind if it.get("type") in ("behind", "poster")] + [(a, b) for a, b, _ in studio], hide)
    if has_captions:
        fonts = folder / "fonts"
        fonts.mkdir(exist_ok=True)
        if not late_captions:
            graph.append(f"[{label}]ass={ass.name}:fontsdir=fonts[vcap]")
            label = "vcap"
    colours = [c.get("hex") for c in brand.get("colours") or [] if c.get("hex")]
    bar_colour = "0x" + (colours[0] if colours else "#FFD43B").lstrip("#")
    if cfg.get("progress_bar"):
        bar_h = max(4, even(h * 0.008))
        y = "0" if cfg.get("progress_bar") == "top" else f"ih-{bar_h}"
        graph.append(f"[{label}]drawbox=x=0:y={y}:w='iw*t/{max(main_len, 0.1):.3f}':h={bar_h}:color={bar_colour}@1:t=fill[vbar]")
        label = "vbar"
    logo = brand.get("logo") or {}
    if cfg.get("logo") and logo.get("file") and (BRAND_DIR / logo["file"]).exists():
        li = add_input("-i", str(BRAND_DIR / logo["file"]))
        lw = even(min(w, h) * 0.14)
        graph.append(f"[{li}:v]scale={lw}:-1,format=rgba,colorchannelmixer=aa=0.9[lg]")
        graph.append(f"[{label}][lg]overlay=W-w-{round(w * 0.04)}:{round(h * (0.12 if h > w else 0.05))}[vlogo]")
        label = "vlogo"

    alabel = "abase"
    mixes = []
    if cfg.get("music"):  # under the voice: it dips while you speak and comes back in the pauses, fades in and out
        mi = add_input("-stream_loop", "-1", "-i", str(resolve(cfg["music"])))
        fade_out = max(0.0, main_len - 1.5)
        graph.append(f"[{mi}:a]{AUDIO_FMT},volume={float(cfg.get('music_volume', 0.2)):g},atrim=duration={main_len:.3f},afade=t=in:d=0.6,afade=t=out:st={fade_out:.3f}:d=1.5[mus]")
        if cfg.get("duck", True):
            graph.append(f"[{alabel}]asplit=2[vox][key]")
            graph.append(f"[mus][key]{DUCK}[musd]")
            alabel = "vox"
            mixes.append("[musd]")
        else:
            mixes.append("[mus]")
    if cfg.get("sounds", True):  # sound follows the picture: a whoosh on each zoom and effect, a hit on the big ones
        auto_sounds += picture_sounds(cfg, words, main_len, [t for t, _ in auto_sounds])
    for k, item in enumerate(cfg.get("sfx") or []):
        line = item.get("line")
        window = line_window(words, int(line), int(line)) if line is not None else None
        if window is None:
            raise Problem(f"Sound effect {k + 1}: line {line} isn't in this video.")
        fi = add_input("-i", str(sound(item.get("file") or "")))
        ms = max(0, round((window[0] - 0.1) * 1000))
        graph.append(f"[{fi}:a]{AUDIO_FMT},volume={float(item.get('volume', 0.6)):g},adelay={ms}|{ms}[fx{k}]")
        mixes.append(f"[fx{k}]")
    for k, (at, name_) in enumerate(auto_sounds):  # the theme's sound on each transition
        fi = add_input("-i", str(sound_file(name_)))
        ms = max(0, round((at - 0.18) * 1000))
        graph.append(f"[{fi}:a]{AUDIO_FMT},volume=0.45,adelay={ms}|{ms}[ax{k}]")
        mixes.append(f"[ax{k}]")
    if mixes:
        graph.append(f"[{alabel}]{''.join(mixes)}amix=inputs={len(mixes) + 1}:duration=first:normalize=0,{LIMITER}[amix]")
        alabel = "amix"

    tail_pieces = []
    if cfg.get("end_card"):
        card = cfg["end_card"] if isinstance(cfg["end_card"], dict) else {"text": str(cfg["end_card"])}
        seconds = float(card.get("seconds", 2.5))
        ci = add_input("-f", "lavfi", "-i", f"color=c={bar_colour}:s={w}x{h}:r={fps:g}:d={seconds:.2f}")
        card_ass = folder / f"{name}_v{version}_end.ass"
        end_card_ass(card_ass, w, h, card.get("text") or (brand.get("handle") or "Follow for more"), brand)
        graph.append(f"[{ci}:v]ass={card_ass.name}:fontsdir=fonts,setsar=1,format=yuv420p[endv]")
        graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={seconds:.2f},aformat=sample_fmts=fltp[enda]")
        tail_pieces.append(("endv", "enda"))
    pieces_seq = []
    intro_len = 0.0
    for end in ("intro", "outro"):
        part = brand.get(end) or {}
        path = BRAND_DIR / ((part.get("file") or {}).get("path") or "-")
        if cfg.get(end) and path.exists():
            pinfo = probe(path)
            pi = add_input("-i", str(path))
            graph.append(fit(f"{pi}:v", f"{end}v", w, h, fps))
            graph.append(f"[{pi}:a]{AUDIO_FMT}[{end}a]" if pinfo["audio"] else f"anullsrc=r=48000:cl=stereo,atrim=duration={pinfo['seconds']:.3f},aformat=sample_fmts=fltp[{end}a]")
            pieces_seq.append(end)
            if end == "intro":
                intro_len = pinfo["seconds"]
    seq = ([("introv", "introa")] if "intro" in pieces_seq else []) + [(label, alabel)] + tail_pieces + ([("outrov", "outroa")] if "outro" in pieces_seq else [])
    if len(seq) > 1:
        graph.append(f"[{label}]setsar=1[vmain]")
        seq = [("vmain", a_) if v == label else (v, a_) for v, a_ in seq]
        graph.append("".join(f"[{v}][{a_}]" for v, a_ in seq) + f"concat=n={len(seq)}:v=1:a=1[vout][aout]")
        label, alabel = "vout", "aout"

    script = folder / f"{name}_v{version}.filter.txt"
    script.write_text(";\n".join(graph), encoding="utf-8")
    title = re.sub(r"[^\w\-]", "_", cfg.get("title", "") or "")[:40]
    out = folder / (f"{name}{'_' + title if title else ''}_final.mp4" if final else f"{name}_v{version}_preview.mp4")
    if final and out.exists():
        out = out.with_name(out.stem + f"_v{version}.mp4")
    quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "96k"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for arg in inputs:
        cmd += arg
    # ffmpeg 7 reads a filter script with "-/filter_complex"; older versions with -filter_complex_script.
    cmd += ["-/filter_complex" if ffmpeg_major() >= 7 else "-filter_complex_script", script.name, "-map", f"[{label}]", "-map", f"[{alabel}]", *quality, "-movflags", "+faststart", out.name]
    run(cmd, cwd=folder)
    # Where each transcript line is in this video (code works out times; the AI only names lines).
    windows: dict[int, list[float]] = {}
    for wd in words:
        win = windows.setdefault(int(wd[3]), [wd[1], wd[2]])
        win[0], win[1] = min(win[0], wd[1]), max(win[1], wd[2])
    caps_band = None
    if cfg.get("captions"):
        caps_ = brand.get("captions") or {}
        look_ = {**DEFAULT_STYLE, **(caps_.get("look") or {})}
        caps_band = [round(v, 1) for v in caption_band(cfg.get("caption_position") or caps_.get("position") or look_.get("place") or "bottom", w, h, look_, caps_.get("margins") or DEFAULT_MARGINS)]
        if cfg.get("caption_y"):
            bottom = float(cfg["caption_y"]) * h
            caps_band = [round(bottom - float(cfg.get("caption_size") or look_.get("size", 0.075)) * min(w, h) * 2.6, 1), round(bottom, 1)]
    word_times: dict[str, list[list[float]]] = {}
    for wd in words:
        word_times.setdefault(str(int(wd[3])), []).append([round(wd[1] + intro_len, 3), round(wd[2] + intro_len, 3)])
    timing = {"words": word_times, "offset": intro_len, "main": main_len, "face": [round(v, 1) for v in face_out] if face_out else None, "captions": caps_band, "lines": {str(k): [round(a + intro_len, 3), round(b + intro_len, 3)] for k, (a, b) in windows.items()}}
    (folder / f"{name}_v{version}.timing.json").write_text(json.dumps(timing), encoding="utf-8")
    if behind:
        apply_behind(out, behind, brand, w, h, final, folder, f"{name}_v{version}", intro_len, face_out)
    if studio:
        apply_studio(out, studio, brand, w, h, final, folder, f"{name}_v{version}", intro_len, resolve)
    if cfg.get("motion"):
        apply_motion(out, cfg, brand, timing, w, h, fps, final, folder, f"{name}_v{version}", plan_dir)
    if has_captions and late_captions:
        burn_captions(out, ass, intro_len, final, folder)
    checks = quality_checks(out, cfg, brand) if (final or main_len <= 180) and cfg.get("checks", True) else []
    return out, checks


def shift_ass(text: str, seconds: float) -> str:
    """Moves every caption later by `seconds` (for an intro before the main part) (pure)."""
    if abs(seconds) < 0.001:
        return text

    def move(m):
        def t(v):
            h_, m_, s_ = v.split(":")
            total = max(0.0, int(h_) * 3600 + int(m_) * 60 + float(s_) + seconds)
            return ass_time(total)
        return f"Dialogue: {m.group(1)},{t(m.group(2))},{t(m.group(3))},"
    return re.sub(r"Dialogue: (\d+),([\d:.]+),([\d:.]+),", move, text)


def burn_captions(out: Path, ass: Path, offset: float, final: bool, folder: Path) -> None:
    """The captions, burned in as the last step so effects and scenes never shrink or blur them."""
    late = ass.with_name(ass.stem + "_late.ass")
    late.write_text(shift_ass(ass.read_text(encoding="utf-8"), offset), encoding="utf-8")
    base = out.with_name(out.stem + "_nocaps" + out.suffix)
    out.replace(base)
    quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "18"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "27"]
    try:
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", base.name, "-vf", f"ass={late.name}:fontsdir=fonts", "-map", "0:v", "-map", "0:a?", "-c:a", "copy", *quality, "-movflags", "+faststart", out.name], cwd=folder)
        base.unlink(missing_ok=True)
    except BaseException:
        if not out.exists() and base.exists():
            base.replace(out)
        raise


# ---------------------------------------------------------------- motion graphics (HyperFrames)

MOTION_DIR = BRAND_DIR.parent / "motion"
NO_TRACKING = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}  # the person's renders stay private
MOTION_TYPES = ("title", "lower_third", "callout", "emoji", "counter", "list", "chart", "quote", "chapter", "end_screen", "feed", "flythrough", "glass", "carousel", "scene", "block", "custom")


def hyperframes_cmd() -> list[str]:
    node = shutil.which("node")
    cli = MOTION_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if not node or not cli.exists():
        raise Problem("Motion graphics need Node.js 22+ and HyperFrames. Ask the person, then run: python davnai.py setup --motion")
    return [node, str(cli)]


def esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def brand_look(brand: dict) -> dict:
    caps = brand.get("captions") or {}
    look = {**DEFAULT_STYLE, **(caps.get("look") or {})}
    colours = [c.get("hex") for c in brand.get("colours") or [] if c.get("hex")]
    theme = brand.get("theme") or {}
    font_path = Path(theme["title_path"]) if theme.get("title_path") else caption_font_path(caps)
    if not font_path:
        kit_font = caps.get("font", {}).get("name") if isinstance(caps.get("font"), dict) else None
        font_path = BRAND_DIR / "fonts" / kit_font if kit_font and (BRAND_DIR / "fonts" / kit_font).exists() else None
    return {
        "primary": colours[0] if colours else "#1F2937",  # neutral when there's no Brand Kit or theme colour
        "secondary": colours[1] if len(colours) > 1 else "#111827",
        "accent": look.get("accent") or "#FACC15",
        "text": "#FFFFFF",
        "font": theme.get("title_family") or caps.get("font_family") or "Arial",
        "font_path": str(font_path) if font_path and font_path.exists() else None,
        "logo": (brand.get("logo") or {}).get("file"),
        "handle": brand.get("handle") or "",
        "theme": theme.get("name"),
        "title_style": theme.get("title_style") or "pop",
        "sound": (theme.get("sounds") or {}).get("motion"),
    }


SPOT_TOPS = {"top": (0.12, 0.08), "upper": (0.24, 0.24), "middle": (0.42, 0.42), "lower": (0.56, 0.66), "bottom": (0.62, 0.78), "foot": (0.72, 0.8)}
DEFAULT_SPOT = {"title": "top", "counter": "upper", "list": "upper", "chart": "upper", "glass": "upper", "carousel": "top"}


def keep_off_face(item: dict, face, w: int, h: int, captions=None) -> dict:
    """A graphic without a chosen position moves to the nearest place that covers neither the face nor the captions,
    or at least not the face (pure)."""
    kind = item.get("type")
    if (not face and not captions) or item.get("position") or kind not in (*DEFAULT_SPOT, "lower_third"):
        return item
    tall = h > w
    default = DEFAULT_SPOT.get(kind) or ("upper" if tall else "lower")
    height = {"title": 0.16, "lower_third": 0.12, "carousel": 0.25 if tall else 0.3}.get(kind, 0.3) * h
    zones = ([(face[1] - face[3] * 0.15, face[1] + face[3] * 1.15)] if face else []) + ([tuple(captions)] if captions else [])
    order = [default] + [p for p in ("top", "upper", "lower", "bottom", "middle", "foot") if p != default]

    def clear(place: str, blocked: list) -> bool:
        a = SPOT_TOPS[place][0 if tall else 1] * h
        return all(a + height < top or a > bottom for top, bottom in blocked)
    for blocked in (zones, zones[:1] if face else []):
        for place in order:
            if blocked and clear(place, blocked):
                return item if place == default else {**item, "position": place}
    return item


def item_window(item: dict, timing: dict, total: float) -> tuple[float, float]:
    """Where a graphic goes, from its transcript lines (or the start or end of the video): code, never the AI."""
    if item.get("at") == "start":
        return 0.0, min(total, float(item.get("seconds", 3)))
    if item.get("at") == "end":
        end = timing["offset"] + timing["main"]
        return max(0.0, end - float(item.get("seconds", 3))), end
    rng = item.get("lines")
    if isinstance(rng, int):
        rng = [rng, rng]
    if isinstance(item.get("from"), (list, tuple)) and timing.get("words"):
        flat = [[0, s_, e_, int(ln)] for ln, spans in timing["words"].items() for s_, e_ in spans]
        win = word_span(sorted(flat, key=lambda x: x[1]), item["from"], item.get("to"))
        if win is None:
            raise Problem(f"Motion graphic '{item.get('type')}': words {item['from']}..{item.get('to')} aren't in this video.")
        return max(0.0, win[0] - 0.1), min(total, win[1] + float(item.get("hold", 0.3)))
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        raise Problem(f"Motion graphic '{item.get('type')}' needs \"lines\": [first, last] (or \"from\": [line, word], \"at\": \"start\" / \"end\").")
    found = [timing["lines"][str(n)] for n in range(int(rng[0]), int(rng[1]) + 1) if str(n) in timing["lines"]]
    if not found:
        raise Problem(f"Motion graphic '{item.get('type')}': lines {rng[0]}-{rng[1]} aren't in this video.")
    a, b = min(f[0] for f in found), max(f[1] for f in found)
    if item.get("type") == "chapter":
        b = min(b, a + float(item.get("seconds", 2.2)))
    return max(0.0, a - 0.1), min(total, b + float(item.get("hold", 0.3)))


def spot(position: str, w: int, h: int) -> str:
    tall = h > w
    top = {p: v[0 if tall else 1] for p, v in SPOT_TOPS.items()}.get(position, 0.12 if tall else 0.08)
    return f"top:{round(h * top)}px;"


def motion_item(k: int, item: dict, t0: float, dur: float, w: int, h: int, look: dict, plan_dir: Path, project: Path) -> tuple[str, str]:
    """One graphic as HTML plus its GSAP animation (positions are seconds inside the segment)."""
    u = min(w, h) / 100  # 1% of the shorter side
    kind = item.get("type")
    mid = f"m{k}"
    t1 = t0 + dur
    out_at = max(t0 + 0.4, t1 - 0.35)
    attrs = f'id="{mid}" data-start="{t0:.3f}" data-duration="{dur:.3f}"'
    pos = item.get("position", "")
    if kind == "title":
        style = item.get("style") or look.get("title_style") or "pop"
        text = str(item.get("text", ""))
        inner = "".join(f'<span class="w">{esc(x)}</span> ' for x in text.split()) if style in ("words", "typewriter") else esc(text)
        if style == "typewriter":  # letters appear one by one, but words never break across lines
            inner = " ".join('<span class="word">' + "".join(f'<span class="c">{esc(c)}</span>' for c in word) + "</span>" for word in text.split())
        html = f'<div {attrs} class="g" style="{spot(pos or "top", w, h)}left:{round(6 * u)}px;right:{round(6 * u)}px;text-align:center"><div class="box title">{inner}</div></div>'
        anim = {
            "pop": f'tl.from("#{mid} .box",{{scale:0.3,autoAlpha:0,duration:0.45,ease:"back.out(2.2)"}},{t0:.3f});',
            "slide": f'tl.from("#{mid} .box",{{x:-{w},duration:0.5,ease:"power3.out"}},{t0:.3f});',
            "bounce": f'tl.from("#{mid} .box",{{y:-{round(h * 0.4)},duration:0.8,ease:"bounce.out"}},{t0:.3f});',
            "words": f'tl.from("#{mid} .w",{{y:{round(6 * u)},autoAlpha:0,duration:0.35,stagger:0.09,ease:"back.out(2)"}},{t0:.3f});',
            "typewriter": f'tl.from("#{mid} .c",{{autoAlpha:0,duration:0.01,stagger:{min(0.06, dur * 0.5 / max(1, len(text))):.3f}}},{t0:.3f});',
            "glow": f'tl.from("#{mid} .box",{{autoAlpha:0,filter:"blur(20px)",scale:1.3,duration:0.6,ease:"power2.out"}},{t0:.3f});',
        }.get(style)
        if anim is None:
            raise Problem(f"Title style '{style}': use pop, slide, bounce, words, typewriter or glow.")
        return html, anim + f'tl.to("#{mid} .box",{{autoAlpha:0,y:-{round(3 * u)},duration:0.3}},{out_at:.3f});'
    if kind == "lower_third":
        # Tall videos: above the face area and clear of the captions; wide videos: the classic lower third.
        html = (f'<div {attrs} class="g" style="{spot(pos or ("upper" if h > w else "lower"), w, h)}left:{round(5 * u)}px">'
                f'<div class="lt-bar"></div><div class="lt-name">{esc(item.get("name", ""))}</div><div class="lt-role">{esc(item.get("role", ""))}</div></div>')
        js = (f'tl.from("#{mid} .lt-bar",{{scaleX:0,transformOrigin:"left",duration:0.4,ease:"power3.out"}},{t0:.3f})'
              f'.from("#{mid} .lt-name",{{y:{round(4 * u)},autoAlpha:0,duration:0.35}},{t0 + 0.2:.3f})'
              f'.from("#{mid} .lt-role",{{autoAlpha:0,duration:0.35}},{t0 + 0.4:.3f})'
              f'.to("#{mid}",{{x:-{w},duration:0.4,ease:"power3.in"}},{out_at - 0.1:.3f});')
        return html, js
    if kind in ("callout", "emoji"):
        corner = {"top-left": f"left:{round(6 * u)}px;top:{round(h * 0.14)}px", "top-right": f"right:{round(6 * u)}px;top:{round(h * 0.14)}px",
                  "middle": f"left:0;right:0;top:{round(h * 0.4)}px;text-align:center", "bottom-left": f"left:{round(6 * u)}px;top:{round(h * 0.55)}px",
                  "bottom-right": f"right:{round(6 * u)}px;top:{round(h * 0.55)}px"}.get(pos or "top-right", f"right:{round(6 * u)}px;top:{round(h * 0.14)}px")
        body = f'<div class="emoji">{esc(item.get("emoji", ""))}</div>' if kind == "emoji" else f'<div class="box callout">{esc(item.get("emoji", ""))} {esc(item.get("text", ""))}</div>'
        html = f'<div {attrs} class="g" style="{corner}">{body}</div>'
        sel = f"#{mid} > div"
        js = (f'tl.from("{sel}",{{scale:0,rotation:-25,duration:0.4,ease:"back.out(3)"}},{t0:.3f})'
              f'.to("{sel}",{{rotation:6,yoyo:true,repeat:{max(1, int(dur / 0.5))},duration:0.25,ease:"sine.inOut"}},{t0 + 0.4:.3f})'
              f'.to("{sel}",{{scale:0,autoAlpha:0,duration:0.25}},{out_at:.3f});')
        return html, js
    if kind == "counter":
        start_v, end_v = float(item.get("from", 0)), float(item.get("to", 100))
        decimals = int(item.get("decimals", 0))
        html = (f'<div {attrs} class="g" style="{spot(pos or "upper", w, h)}left:0;right:0;text-align:center">'
                f'<div class="num">{esc(item.get("prefix", ""))}<span class="v">{start_v:,.{decimals}f}</span>{esc(item.get("suffix", ""))}</div>'
                f'<div class="label">{esc(item.get("label", ""))}</div></div>')
        js = (f'(function(){{const o={{v:{start_v}}};const el=document.querySelector("#{mid} .v");'
              f'tl.from("#{mid}",{{scale:0.5,autoAlpha:0,duration:0.35,ease:"back.out(2)"}},{t0:.3f});'
              f'tl.to(o,{{v:{end_v},duration:{max(0.6, min(dur - 0.8, 2.5)):.2f},ease:"power2.out",onUpdate:()=>{{el.textContent=o.v.toLocaleString("en-US",{{minimumFractionDigits:{decimals},maximumFractionDigits:{decimals}}});}}}},{t0 + 0.2:.3f});'
              f'tl.to("#{mid}",{{autoAlpha:0,duration:0.3}},{out_at:.3f});}})();')
        return html, js
    if kind == "list":
        items = [str(x) for x in item.get("items") or []]
        if not items:
            raise Problem("A list needs \"items\".")
        title = f'<div class="list-title">{esc(item["title"])}</div>' if item.get("title") else ""
        rows = "".join(f'<div class="row"><span class="tick">✓</span>{esc(x)}</div>' for x in items)
        html = f'<div {attrs} class="g panel" style="{spot(pos or "upper", w, h)}left:{round(6 * u)}px;right:{round(6 * u)}px">{title}{rows}</div>'
        gap = min(0.8, max(0.2, (dur * 0.6) / len(items)))
        js = f'tl.from("#{mid}",{{autoAlpha:0,y:{round(3 * u)},duration:0.3}},{t0:.3f});'
        js += f'tl.from("#{mid} .row",{{x:-{round(20 * u)},autoAlpha:0,duration:0.3,stagger:{gap:.2f},ease:"power3.out"}},{t0 + 0.3:.3f});'
        return html, js + f'tl.to("#{mid}",{{autoAlpha:0,duration:0.3}},{out_at:.3f});'
    if kind == "chart":
        bars = item.get("bars") or []
        if not bars:
            raise Problem("A chart needs \"bars\": [{\"label\": \"Jan\", \"value\": 10}, ...].")
        top = max(float(b.get("value", 0)) for b in bars) or 1
        cols = "".join(f'<div class="col"><div class="val">{esc(b.get("display", b.get("value", "")))}</div><div class="bar" style="height:{round(float(b.get("value", 0)) / top * 30 * u)}px"></div><div class="lab">{esc(b.get("label", ""))}</div></div>' for b in bars)
        title = f'<div class="list-title">{esc(item["title"])}</div>' if item.get("title") else ""
        html = f'<div {attrs} class="g panel" style="{spot(pos or "upper", w, h)}left:{round(6 * u)}px;right:{round(6 * u)}px">{title}<div class="chart">{cols}</div></div>'
        js = (f'tl.from("#{mid}",{{autoAlpha:0,duration:0.3}},{t0:.3f})'
              f'.from("#{mid} .bar",{{scaleY:0,transformOrigin:"bottom",duration:0.6,stagger:0.12,ease:"power3.out"}},{t0 + 0.2:.3f})'
              f'.from("#{mid} .val",{{autoAlpha:0,duration:0.2,stagger:0.12}},{t0 + 0.6:.3f})'
              f'.to("#{mid}",{{autoAlpha:0,duration:0.3}},{out_at:.3f});')
        return html, js
    if kind in ("quote", "chapter"):
        if kind == "quote":
            body = f'<div class="quote">“{esc(item.get("text", ""))}”</div>' + (f'<div class="author">— {esc(item["author"])}</div>' if item.get("author") else "")
        else:
            body = (f'<div class="chap-num">{esc(item.get("number", ""))}</div>' if item.get("number") is not None else "") + f'<div class="chap-title">{esc(item.get("text", ""))}</div>'
        html = f'<div {attrs} class="g full"><div class="full-in">{body}</div></div>'
        js = (f'tl.from("#{mid}",{{clipPath:"inset(0 100% 0 0)",duration:0.45,ease:"power3.inOut"}},{t0:.3f})'
              f'.from("#{mid} .full-in > div",{{y:{round(5 * u)},autoAlpha:0,duration:0.4,stagger:0.12}},{t0 + 0.3:.3f})'
              f'.to("#{mid}",{{clipPath:"inset(0 0 0 100%)",duration:0.4,ease:"power3.inOut"}},{max(t0 + 0.8, t1 - 0.4):.3f});')
        return html, js
    if kind == "end_screen":
        logo = ""
        if look["logo"] and (BRAND_DIR / look["logo"]).exists():
            shutil.copy2(BRAND_DIR / look["logo"], project / look["logo"])
            logo = f'<img class="logo" src="{esc(look["logo"])}">'
        html = (f'<div {attrs} class="g full"><div class="full-in">{logo}<div class="chap-title">{esc(item.get("text", "Follow for more"))}</div>'
                f'<div class="handle">{esc(item.get("handle") or look["handle"])}</div><div class="btn">{esc(item.get("button", "Follow"))}</div></div></div>')
        js = (f'tl.from("#{mid}",{{autoAlpha:0,duration:0.4}},{t0:.3f})'
              f'.from("#{mid} .full-in > *",{{y:{round(6 * u)},autoAlpha:0,duration:0.4,stagger:0.12,ease:"back.out(1.8)"}},{t0 + 0.2:.3f})'
              f'.to("#{mid} .btn",{{scale:1.08,yoyo:true,repeat:{max(1, int(dur / 0.6))},duration:0.3}},{t0 + 1.0:.3f});')
        return html, js
    if kind == "feed":
        return motion_feed(mid, attrs, item, t0, dur, w, h, look)
    if kind == "flythrough":
        return motion_flythrough(mid, attrs, item, t0, dur, w, h)
    if kind == "glass":
        return motion_glass(mid, attrs, item, t0, dur, w, h, pos)
    if kind == "scene":
        return motion_scene(mid, attrs, item, t0, dur, w, h, look, plan_dir, project)
    if kind == "carousel":
        return motion_carousel(mid, attrs, item, t0, dur, w, h, pos, plan_dir, project)
    if kind == "block":
        return motion_block(mid, item, t0, dur, w, h, plan_dir, project)
    if kind == "custom":
        src = Path(str(item.get("html", ""))).expanduser()
        src = src if src.is_absolute() else (plan_dir / src).resolve()
        if not src.exists():
            raise Problem(f"Custom motion graphic: can't find {src}.")
        html = f'<script>window.__davnaiCurrent="{mid}";</script><div {attrs} class="g custom">{src.read_text(encoding="utf-8")}</div>'
        return html, f'(window.__davnaiQueue["{mid}"]||[]).forEach(fn=>fn(tl,document.getElementById("{mid}"),{t0:.3f},{dur:.3f},window.BRAND));'
    raise Problem(f"Unknown motion graphic '{kind}'. Use: {', '.join(MOTION_TYPES)}.")


def motion_feed(mid: str, attrs: str, item: dict, t0: float, dur: float, w: int, h: int, look: dict) -> tuple[str, str]:
    """The video plays inside a social post that scrolls up a phone feed into place, then the edit takes over again."""
    u = min(w, h) / 100
    src, media_at = item["_base"]
    handle = str(item.get("handle") or look.get("handle") or "@you")
    scale = 0.68 if h > w else 0.5
    vw, vh = round(w * scale), round(h * scale)
    filler = f'<div class="ph"><div class="ph-a"></div><div class="ph-b" style="height:{round(vh * 0.35)}px"></div></div>'
    post = (f'<div class="post" style="width:{vw}px"><div class="post-top"><div class="ava">{esc(handle.lstrip("@")[:1].upper())}</div>'
            f'<div class="who">{esc(handle)}</div><div class="follow">Follow</div></div>'
            f'<div class="pv" style="width:{vw}px;height:{vh}px"><video data-start="{t0:.3f}" data-duration="{dur:.3f}" data-media-start="{media_at + t0:.3f}" src="{esc(src)}" muted playsinline></video></div>'
            f'<div class="acts"><span class="heart">♥</span><span>💬</span><span>↗</span><span class="likes">{esc(item.get("likes", "12.4K"))}</span></div>'
            f'<div class="cap"><b>{esc(handle)}</b> {esc(item.get("caption", ""))}</div></div>')
    html = f'<div {attrs} class="g feed"><div class="feed-col">{filler}{post}{filler}</div></div>'
    post_h = vh + 26 * u  # header, actions and caption around the video
    land = round((h - post_h) / 2 - (9.5 * u + vh * 0.35))  # the post ends up centred, the posts around it peeking in
    out_at = max(t0 + 1.4, t0 + dur - 0.45)
    js = (f'tl.from("#{mid}",{{autoAlpha:0,duration:0.25}},{t0:.3f})'
          f'.fromTo("#{mid} .feed-col",{{y:{round(h * 0.9)}}},{{y:{land},duration:0.9,ease:"power3.out"}},{t0:.3f})'
          f'.fromTo("#{mid} .heart",{{scale:1}},{{scale:1.6,color:"#FF3B5C",yoyo:true,repeat:1,duration:0.18}},{t0 + 1.1:.3f})'
          f'.to("#{mid} .feed-col",{{scale:{1 / scale:.3f},y:0,duration:0.45,ease:"power2.in"}},{out_at:.3f})'
          f'.to("#{mid}",{{autoAlpha:0,duration:0.15}},{out_at + 0.32:.3f});')
    return html, js


SCENE_LAYOUTS = {  # how the speaker's video sits in a scene: scale, vertical shift (share of height), corner radius (share of width)
    "card": (0.7, 0.12, 0.05),
    "window": (0.44, 0.25, 0.06),
    "split": (0.58, 0.21, 0.04),
    "full": (1.0, 0.0, 0.0),
}
SCENE_BACKGROUNDS = ("grid", "gradient", "dark", "light", "dots")


def scene_background(kind: str, look: dict, project: Path, plan_dir: Path) -> tuple[str, bool]:
    """CSS for a scene's background and whether text on it should be dark (pure but for copying a picture)."""
    p, a = look["primary"], look["accent"]
    if kind == "light":
        return "background:#F3EFE6;background-image:radial-gradient(rgba(0,0,0,.07) 1.5px,transparent 1.5px);background-size:28px 28px", True
    if kind == "dark":
        return "background:radial-gradient(circle at 50% 30%,#23232B,#09090C)", False
    if kind == "gradient":
        return f"background:radial-gradient(circle at 30% 20%,{a}55,transparent 45%),radial-gradient(circle at 70% 80%,{p},#07070A 75%)", False
    if kind == "dots":
        return f"background:{p};background-image:radial-gradient(rgba(255,255,255,.16) 2px,transparent 2px);background-size:34px 34px", False
    if kind.startswith("#") or kind.startswith("rgb"):
        return f"background:{kind}", False
    pic = Path(kind).expanduser()
    pic = pic if pic.is_absolute() else (plan_dir / pic).resolve()
    if kind not in SCENE_BACKGROUNDS and pic.exists():
        shutil.copy2(pic, project / f"bg_{pic.name}")
        return f"background:#000 url('bg_{esc(pic.name)}') center/cover", False
    return (f"background:{p};background-image:linear-gradient(rgba(255,255,255,.09) 2px,transparent 2px),"
            f"linear-gradient(90deg,rgba(255,255,255,.09) 2px,transparent 2px);background-size:72px 72px"), False


def readable_accent(accent: str, on_light: bool) -> str:
    """The accent colour, darkened when it would vanish on a light background (yellow on paper) (pure)."""
    c = accent.lstrip("#")
    if not on_light or len(c) != 6:
        return accent
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    if 0.299 * r + 0.587 * g + 0.114 * b < 140:
        return accent
    return "#1F1F1F"  # a light accent (yellow) can't be read as text on paper: dark ink instead (big words get a highlighter)


def fit_title(text: str, width: float, height: float, biggest: float) -> int:
    """A headline size that fits its box: uppercase bold, about 0.6 of the size per letter, 1.05 line height (pure)."""
    size = biggest
    while size > 14:
        per_line = max(1, int(width / (size * 0.6)))
        lines, cur = 1, 0
        for word in text.split():
            if cur and cur + 1 + len(word) > per_line:
                lines, cur = lines + 1, len(word)
            else:
                cur += (1 if cur else 0) + len(word)
        if lines * size * 1.05 <= height:
            break
        size *= 0.92
    return round(size)


def motion_scene(mid: str, attrs: str, item: dict, t0: float, dur: float, w: int, h: int, look: dict, plan_dir: Path, project: Path) -> tuple[str, str]:
    """A designed scene: the speaker's video moves into a card, a small window or the lower half over a background,
    with a headline, a list or a big number; then it goes back to full screen. Contrast between neighbouring beats."""
    layout = item.get("layout", "card")
    if layout not in SCENE_LAYOUTS:
        raise Problem(f"Scene layout '{layout}': use {', '.join(SCENE_LAYOUTS)}.")
    scale, dy, radius = SCENE_LAYOUTS[layout]
    bg_css, dark_text = scene_background(str(item.get("background", "grid")), look, project, plan_dir)
    u = min(w, h) / 100
    ink = "#141414" if dark_text else "#FFFFFF"
    accent = look["accent"]
    text_accent = readable_accent(accent, dark_text)  # small text in the accent: darker on paper
    top_room = h * (0.5 - scale / 2 + dy)  # free space above the video
    room = max(top_room - h * 0.06 - 4 * u, h * 0.12)
    rows = len(item.get("items") or []) * 9.5 * u + (6.5 * u if item.get("kicker") else 0) + (7 * u if item.get("sub") else 0) + (24 * u if item.get("number") is not None else 0)
    title_fs = fit_title(str(item.get("title") or ""), w - 14 * u, max(room - rows, room * 0.35), 11 * u)
    parts = []
    if item.get("kicker"):
        parts.append(f'<div class="sc-kick" style="color:{text_accent}">{esc(item["kicker"])}</div>')
    if item.get("title"):
        hl = {x.lower() for x in item.get("highlight") or []}
        tint = (f' style="background:{accent};color:{ink};padding:0 .1em;border-radius:.08em"' if dark_text  # a highlighter on paper
                else f' style="color:{accent}"')
        words = "".join(f'<span class="sc-w"{tint if x.lower().strip(".,!?") in hl else ""}>{esc(x)}</span> ' for x in str(item["title"]).split())
        parts.append(f'<div class="sc-title" style="color:{ink};font-size:{title_fs}px">{words}</div>')
    if item.get("number") is not None:
        n = item["number"] if isinstance(item["number"], dict) else {"to": item["number"]}
        parts.append(f'<div class="sc-num" style="color:{text_accent}">{esc(n.get("prefix", ""))}<span class="sc-v">{float(n.get("from", 0)):,.0f}</span>{esc(n.get("suffix", ""))}</div>'
                     + (f'<div class="sc-sub" style="color:{ink}">{esc(n["label"])}</div>' if n.get("label") else ""))
    for x in item.get("items") or []:
        parts.append(f'<div class="sc-row" style="color:{ink}"><span class="sc-dot" style="background:{text_accent}"></span>{esc(x)}</div>')
    if item.get("sub"):
        parts.append(f'<div class="sc-sub" style="color:{ink}">{esc(item["sub"])}</div>')
    text_h = max(top_room - 6 * u, h * 0.12)
    content = f'<div class="sc-text" style="top:{round(h * 0.06)}px;height:{round(text_h)}px">{"".join(parts)}</div>' if parts else ""
    text_attrs = attrs.replace(f'id="{mid}"', f'id="{mid}t"')
    html = f'<div {attrs} class="sc-bg" style="{bg_css}"></div><div {text_attrs} class="g sc-layer">{content}</div>'
    t_in, t_out = t0, max(t0 + 0.6, t0 + dur - 0.38)
    js = (f'tl.fromTo("video.base",{{scale:1,y:0,borderRadius:0}},{{scale:{scale},y:{round(h * dy)},borderRadius:{round(w * radius / scale)},boxShadow:"0 {round(2 * u)}px {round(6 * u)}px rgba(0,0,0,.45)",duration:0.45,ease:"power3.inOut"}},{t_in:.3f})'
          f'.to("video.base",{{scale:1,y:0,borderRadius:0,boxShadow:"0 0 0 rgba(0,0,0,0)",duration:0.38,ease:"power3.inOut"}},{t_out:.3f});')
    if parts:
        js += (f'tl.from("#{mid}t .sc-kick, #{mid}t .sc-sub",{{y:{round(3 * u)},autoAlpha:0,duration:0.3}},{t_in + 0.3:.3f});'
               f'tl.from("#{mid}t .sc-w",{{y:{round(6 * u)},autoAlpha:0,duration:0.32,stagger:0.07,ease:"back.out(2)"}},{t_in + 0.25:.3f});'
               f'tl.from("#{mid}t .sc-row",{{x:-{round(12 * u)},autoAlpha:0,duration:0.3,stagger:{min(0.6, max(0.18, dur * 0.5 / max(1, len(item.get("items") or [1])))):.2f},ease:"power3.out"}},{t_in + 0.45:.3f});'
               f'tl.to("#{mid}t .sc-text",{{autoAlpha:0,duration:0.25}},{t_out - 0.05:.3f});')
        if item.get("number") is not None:
            n = item["number"] if isinstance(item["number"], dict) else {"to": item["number"]}
            js += (f'(function(){{const o={{v:{float(n.get("from", 0))}}};const el=document.querySelector("#{mid}t .sc-v");'
                   f'tl.from("#{mid}t .sc-num",{{scale:0.6,autoAlpha:0,duration:0.35,ease:"back.out(2)"}},{t_in + 0.3:.3f});'
                   f'tl.to(o,{{v:{float(n.get("to", 0))},duration:{max(0.6, min(dur - 1.2, 2.2)):.2f},ease:"power2.out",onUpdate:()=>{{el.textContent=Math.round(o.v).toLocaleString("en-US");}}}},{t_in + 0.4:.3f});}})();')
    return html, js


def motion_glass(mid: str, attrs: str, item: dict, t0: float, dur: float, w: int, h: int, pos: str) -> tuple[str, str]:
    """A frosted-glass panel over the video (the picture shows through, blurred): a title, a line or a list, an icon."""
    u = min(w, h) / 100
    rows = "".join(f'<div class="gl-row"><span class="gl-dot"></span>{esc(x)}</div>' for x in item.get("items") or [])
    body = (f'<div class="gl-icon">{esc(item["icon"])}</div>' if item.get("icon") else "") + \
           (f'<div class="gl-title">{esc(item["title"])}</div>' if item.get("title") else "") + \
           (f'<div class="gl-text">{esc(item["text"])}</div>' if item.get("text") else "") + rows
    if not body:
        raise Problem("A glass panel needs a \"title\", \"text\" or \"items\".")
    html = (f'<div {attrs} class="g" style="{spot(pos or ("upper" if h > w else "middle"), w, h)}left:{round(8 * u)}px;right:{round(8 * u)}px">'
            f'<div class="glass">{body}<div class="gl-sheen"></div></div></div>')
    out_at = max(t0 + 0.6, t0 + dur - 0.35)
    js = (f'tl.from("#{mid} .glass",{{y:{round(6 * u)},scale:0.92,autoAlpha:0,duration:0.5,ease:"power3.out"}},{t0:.3f})'
          f'.fromTo("#{mid} .gl-sheen",{{x:"-120%"}},{{x:"220%",duration:1.1,ease:"power2.inOut"}},{t0 + 0.3:.3f})'
          f'.from("#{mid} .gl-row",{{x:-{round(6 * u)},autoAlpha:0,duration:0.3,stagger:0.15}},{t0 + 0.35:.3f})'
          f'.to("#{mid} .glass",{{autoAlpha:0,y:-{round(3 * u)},duration:0.3}},{out_at:.3f});')
    return html, js


def motion_carousel(mid: str, attrs: str, item: dict, t0: float, dur: float, w: int, h: int, pos: str, plan_dir: Path, project: Path) -> tuple[str, str]:
    """Pictures on a slowly turning 3D ring over the video (products, screenshots, places, faces of guests)."""
    pics = []
    for i, x in enumerate(item.get("images") or []):
        src = Path(str(x)).expanduser()
        src = src if src.is_absolute() else (plan_dir / src).resolve()
        if not src.exists():
            raise Problem(f"Carousel: can't find {src}.")
        name = f"{mid}_{i}{src.suffix.lower()}"
        shutil.copy2(src, project / name)
        pics.append(name)
    if len(pics) < 3:
        raise Problem("A carousel needs at least 3 \"images\".")
    u = min(w, h) / 100
    cw = round(w * (0.3 if h > w else 0.18))
    radius = round(cw / (2 * math.tan(math.pi / len(pics))) * 1.15)
    cards = "".join(f'<div class="car-card" style="width:{cw}px;height:{round(cw * 1.25)}px;margin-left:-{cw // 2}px;'
                    f'transform:rotateY({360 / len(pics) * i:.2f}deg) translateZ({radius}px);background-image:url({esc(n)})"></div>' for i, n in enumerate(pics))
    html = (f'<div {attrs} class="g car" style="{spot(pos or "top", w, h)}left:0;right:0;height:{round(cw * 1.4)}px">'
            f'<div class="car-ring" style="transform:translateZ(-{radius}px)">{cards}</div></div>')
    turns = float(item.get("turns", 0.5))
    js = (f'tl.from("#{mid}",{{autoAlpha:0,scale:0.7,duration:0.45,ease:"back.out(1.6)"}},{t0:.3f})'
          f'.fromTo("#{mid} .car-ring",{{rotationY:0}},{{rotationY:{-360 * turns:.1f},duration:{dur:.3f},ease:"none"}},{t0:.3f})'
          f'.to("#{mid}",{{autoAlpha:0,duration:0.3}},{max(t0 + 0.5, t0 + dur - 0.3):.3f});')
    return html, js


def motion_flythrough(mid: str, attrs: str, item: dict, t0: float, dur: float, w: int, h: int) -> tuple[str, str]:
    """A 'coming up' opener: a card per chapter (a still from that moment and its title) flies past in 3D."""
    stills = item.get("_stills") or []
    chapters = item.get("chapters") or []
    u = min(w, h) / 100
    cw = round(w * (0.74 if h > w else 0.46))
    ch = round(cw * 9 / 16) if w > h else round(cw * 1.15)
    cards = "".join(f'<div class="fly-card" style="width:{cw}px;margin-left:-{cw // 2}px;margin-top:-{(ch + round(16 * u)) // 2}px">'
                    f'<div class="fly-pic" style="height:{ch}px;background-image:url({esc(still)})"></div>'
                    f'<div class="fly-t"><span class="fly-n">{i + 1:02d}</span> {esc(c.get("text", ""))}</div></div>'
                    for i, (c, still) in enumerate(zip(chapters, stills)))
    head = f'<div class="fly-head">{esc(item.get("title", "Coming up"))}</div>'
    html = f'<div {attrs} class="g full fly">{head}<div class="fly-stage">{cards}</div></div>'
    n = max(1, len(stills))
    step = max(0.45, (dur - 0.5) / n)
    js = f'tl.from("#{mid}",{{autoAlpha:0,duration:0.2}},{t0:.3f}).from("#{mid} .fly-head",{{y:-{round(6 * u)},autoAlpha:0,duration:0.3}},{t0:.3f});'
    for i in range(n):
        at = t0 + 0.25 + i * step
        side = -1 if i % 2 else 1
        js += (f'tl.fromTo("#{mid} .fly-card:nth-child({i + 1})",{{z:-1400,rotationY:{35 * side},x:{round(w * 0.25) * side},autoAlpha:0}},'
               f'{{z:0,rotationY:0,x:0,autoAlpha:1,duration:{step * 0.55:.2f},ease:"power3.out"}},{at:.3f})')
        js += f'.to("#{mid} .fly-card:nth-child({i + 1})",{{z:700,rotationY:{-20 * side},autoAlpha:0,duration:{step * 0.4:.2f},ease:"power2.in"}},{at + step * 0.6:.3f});'
    return html, js + f'tl.to("#{mid}",{{autoAlpha:0,duration:0.2}},{t0 + dur - 0.2:.3f});'


def motion_block(mid: str, item: dict, t0: float, dur: float, w: int, h: int, plan_dir: Path, project: Path) -> tuple[str, str]:
    """A whole HyperFrames catalog scene, by name (as it comes) or from your edited copy ("html"), fitted to the video."""
    comps = project / "compositions"
    comps.mkdir(exist_ok=True)
    if item.get("html"):
        src = Path(str(item["html"])).expanduser()
        src = src if src.is_absolute() else (plan_dir / src).resolve()
        if not src.exists():
            raise Problem(f"Block: can't find {src}.")
        target = comps / src.name
        shutil.copy2(src, target)
        assets = src.parent / "assets"
        if assets.is_dir():
            shutil.copytree(assets, project / "assets", dirs_exist_ok=True)
    elif item.get("name"):
        proc = subprocess.run([*hyperframes_cmd(), "add", str(item["name"]), "--dir", str(project), "--json", "--no-clipboard"], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        try:
            written = [Path(p) for p in json.loads(proc.stdout).get("written", []) if str(p).endswith(".html")]
        except json.JSONDecodeError:
            written = []
        if not written:
            raise Problem(f"Couldn't get the catalog block '{item['name']}' (davnai.py catalog lists them).")
        target = written[0]
    else:
        raise Problem("A block needs \"name\" (from davnai.py catalog) or \"html\" (your edited copy).")
    page = target.read_text(encoding="utf-8")
    cid = (re.search(r'data-composition-id="([^"]+)"', page) or [None, mid])[1]
    bw = int((re.search(r'data-width="(\d+)"', page) or [None, 1080])[1])
    bh = int((re.search(r'data-height="(\d+)"', page) or [None, 1920])[1])
    scale = (max if item.get("fit") == "cover" else min)(w / bw, h / bh)
    left, top = round((w - bw * scale) / 2), round((h - bh * scale) / 2)
    values = f" data-variable-values='{esc(json.dumps(item['vars']))}'" if item.get("vars") else ""
    rel = os.path.relpath(target, project).replace("\\", "/")
    html = (f'<div id="{mid}" data-composition-id="{esc(cid)}" data-composition-src="{esc(rel)}" data-start="{t0:.3f}" data-duration="{dur:.3f}" data-width="{bw}" data-height="{bh}"{values} '
            f'style="position:absolute;left:{left}px;top:{top}px;width:{bw}px;height:{bh}px;transform:scale({scale:.4f});transform-origin:0 0"></div>')
    return html, ""


def motion_css(w: int, h: int, look: dict) -> str:
    u = min(w, h) / 100
    face = f'@font-face{{font-family:"DavnaiBrand";src:url("fonts/{Path(look["font_path"]).name}");font-weight:100 900}}' if look.get("font_path") else ""
    family = '"DavnaiBrand",' if look.get("font_path") else ""
    p, s, a, t = look["primary"], look["secondary"], look["accent"], look["text"]
    return f"""{face}
html,body{{margin:0;background:#000}}
#stage{{position:relative;width:{w}px;height:{h}px;overflow:hidden;font-family:{family}"{look['font']}",Arial,sans-serif;font-weight:800;color:{t}}}
video.base{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.g{{position:absolute}}
.box{{display:inline-block;background:{p};color:{t};border-radius:{round(2.2 * u)}px;padding:{round(1.2 * u)}px {round(2.6 * u)}px;box-shadow:0 {round(u)}px {round(3 * u)}px rgba(0,0,0,.35)}}
.title{{font-size:{round(8 * u)}px;line-height:1.1;font-weight:900}}
.title .w,.title .c{{display:inline-block}}
.title .word{{display:inline-block;white-space:nowrap}}
.callout{{font-size:{round(5.5 * u)}px;background:{a};color:#111}}
.emoji{{font-size:{round(16 * u)}px}}
.lt-bar{{width:{round(48 * u)}px;height:{round(1.2 * u)}px;background:{a};margin-bottom:{round(1.2 * u)}px}}
.lt-name{{display:inline-block;background:{p};padding:{round(u)}px {round(2 * u)}px;font-size:{round(5.5 * u)}px}}
.lt-role{{display:block;width:max-content;background:{s};padding:{round(0.7 * u)}px {round(2 * u)}px;font-size:{round(3.6 * u)}px;font-weight:600}}
.num{{display:inline-block;font-size:{round(14 * u)}px;font-weight:900;color:{t};background:rgba(10,10,14,.72);border-radius:{round(3 * u)}px;padding:{round(1 * u)}px {round(4 * u)}px;text-shadow:0 {round(0.6 * u)}px {round(2 * u)}px rgba(0,0,0,.5)}}
.num .v{{color:{a}}}
.label{{display:inline-block;margin-top:{round(1.2 * u)}px;font-size:{round(4.5 * u)}px;font-weight:700;background:rgba(10,10,14,.6);border-radius:{round(2 * u)}px;padding:{round(0.5 * u)}px {round(2.5 * u)}px}}
.panel{{background:rgba(17,17,17,.82);border-radius:{round(3 * u)}px;padding:{round(3 * u)}px;border-left:{round(u)}px solid {p}}}
.list-title{{font-size:{round(5.5 * u)}px;margin-bottom:{round(1.5 * u)}px;color:{a}}}
.row{{font-size:{round(4.6 * u)}px;margin:{round(1.2 * u)}px 0;font-weight:700}}
.tick{{display:inline-block;width:{round(6 * u)}px;color:{p}}}
.chart{{display:flex;align-items:flex-end;gap:{round(2.5 * u)}px;height:{round(40 * u)}px}}
.col{{flex:1;text-align:center}}
.bar{{background:{p};border-radius:{round(u)}px {round(u)}px 0 0}}
.val{{font-size:{round(3.6 * u)}px;margin-bottom:{round(0.6 * u)}px}}
.lab{{font-size:{round(3.2 * u)}px;margin-top:{round(0.6 * u)}px;font-weight:600}}
.full{{inset:0;background:{p};display:flex;align-items:center;justify-content:center;text-align:center}}
.full-in{{padding:0 {round(8 * u)}px}}
.quote{{font-size:{round(7 * u)}px;line-height:1.2}}
.author{{font-size:{round(4 * u)}px;margin-top:{round(3 * u)}px;color:{a}}}
.chap-num{{font-size:{round(22 * u)}px;color:{a};line-height:1}}
.chap-title{{font-size:{round(8 * u)}px}}
.handle{{font-size:{round(5 * u)}px;margin-top:{round(2 * u)}px;color:{a}}}
.btn{{display:inline-block;margin-top:{round(4 * u)}px;background:{t};color:{p};border-radius:{round(5 * u)}px;padding:{round(1.6 * u)}px {round(6 * u)}px;font-size:{round(5 * u)}px}}
.logo{{max-width:{round(30 * u)}px;max-height:{round(16 * u)}px;margin-bottom:{round(3 * u)}px}}
.feed{{inset:0;background:#0E0E10;overflow:hidden}}
.feed-col{{position:absolute;left:0;right:0;top:0;display:flex;flex-direction:column;align-items:center;gap:{round(4 * u)}px;transform-origin:50% 50%}}
.ph{{width:{round(w * 0.68)}px;opacity:.35;filter:blur(2px)}}
.ph-a{{height:{round(4 * u)}px;width:40%;background:#3A3A40;border-radius:{round(2 * u)}px;margin-bottom:{round(1.5 * u)}px}}
.ph-b{{background:#2A2A30;border-radius:{round(2 * u)}px}}
.post{{background:#17171A;border-radius:{round(2.5 * u)}px;overflow:hidden;font-family:Inter,Arial,sans-serif;font-weight:600;color:#fff}}
.post-top{{display:flex;align-items:center;gap:{round(2 * u)}px;padding:{round(2 * u)}px}}
.ava{{width:{round(7 * u)}px;height:{round(7 * u)}px;border-radius:50%;background:{p};display:flex;align-items:center;justify-content:center;font-size:{round(3.8 * u)}px}}
.who{{font-size:{round(3.6 * u)}px;flex:1}}
.follow{{font-size:{round(3.2 * u)}px;color:{a}}}
.pv{{position:relative;overflow:hidden;background:#000}}
.pv video{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.acts{{display:flex;gap:{round(4 * u)}px;align-items:center;padding:{round(2 * u)}px;font-size:{round(5 * u)}px}}
.heart{{display:inline-block}}
.likes{{font-size:{round(3.4 * u)}px;margin-left:auto}}
.cap{{padding:0 {round(2 * u)}px {round(2.5 * u)}px;font-size:{round(3.3 * u)}px;font-weight:400}}
.fly{{perspective:{round(max(w, h) * 1.1)}px;background:radial-gradient(circle at 50% 40%,{p},#05050A)}}
.fly-head{{position:absolute;top:{round(h * 0.08)}px;left:0;right:0;text-align:center;font-size:{round(6 * u)}px;color:{a};letter-spacing:.08em;text-transform:uppercase}}
.fly-stage{{position:absolute;inset:0;transform-style:preserve-3d}}
.fly-card{{position:absolute;left:50%;top:52%;transform-style:preserve-3d;opacity:0}}
.fly-pic{{background-size:cover;background-position:center;border-radius:{round(2.5 * u)}px;box-shadow:0 {round(2 * u)}px {round(6 * u)}px rgba(0,0,0,.6);border:{max(2, round(0.5 * u))}px solid {t}}}
.fly-t{{margin-top:{round(2.5 * u)}px;font-size:{round(5.5 * u)}px;text-align:center}}
.fly-n{{color:{a}}}
.glass{{position:relative;overflow:hidden;padding:{round(4 * u)}px {round(5 * u)}px;border-radius:{round(4 * u)}px;background:rgba(255,255,255,.14);
  -webkit-backdrop-filter:blur({round(2.4 * u)}px) saturate(1.5);backdrop-filter:blur({round(2.4 * u)}px) saturate(1.5);
  border:1px solid rgba(255,255,255,.35);box-shadow:0 {round(2 * u)}px {round(6 * u)}px rgba(0,0,0,.25),inset 0 1px 0 rgba(255,255,255,.5);color:#fff}}
.gl-sheen{{position:absolute;top:0;bottom:0;left:0;width:40%;background:linear-gradient(105deg,transparent,rgba(255,255,255,.35),transparent);pointer-events:none}}
.gl-icon{{font-size:{round(9 * u)}px;line-height:1;margin-bottom:{round(1.5 * u)}px}}
.gl-title{{font-size:{round(6.5 * u)}px;font-weight:900;line-height:1.1}}
.gl-text{{font-size:{round(4.4 * u)}px;font-weight:600;margin-top:{round(1.2 * u)}px;opacity:.92}}
.gl-row{{font-size:{round(4.4 * u)}px;font-weight:700;margin-top:{round(1.4 * u)}px;display:flex;align-items:center;gap:{round(2 * u)}px}}
.gl-dot{{width:{round(2 * u)}px;height:{round(2 * u)}px;border-radius:50%;background:{a};flex:none}}
video.base{{z-index:1;transform-origin:50% 50%}}
.sc-bg{{position:absolute;inset:0;z-index:0}}
.g{{z-index:2}}
.sc-layer{{inset:0}}
.sc-text{{position:absolute;left:{round(7 * u)}px;right:{round(7 * u)}px;display:flex;flex-direction:column;justify-content:center;gap:{round(1.6 * u)}px}}
.sc-kick{{font-size:{round(4 * u)}px;letter-spacing:.14em;text-transform:uppercase;font-weight:800}}
.sc-title{{font-size:{round(11 * u)}px;line-height:1.02;font-weight:900;text-transform:uppercase}}
.sc-w{{display:inline-block}}
.sc-num{{font-size:{round(17 * u)}px;line-height:1;font-weight:900}}
.sc-sub{{font-size:{round(5.2 * u)}px;font-weight:700;opacity:.9}}
.sc-row{{font-size:{round(7.2 * u)}px;line-height:1.1;font-weight:900;display:flex;align-items:center;gap:{round(2.6 * u)}px}}
.sc-dot{{width:{round(3.2 * u)}px;height:{round(3.2 * u)}px;border-radius:50%;flex:none}}
.car{{perspective:{round(w * 2.2)}px}}
.car-ring{{position:absolute;left:50%;top:0;width:0;height:100%;transform-style:preserve-3d}}
.car-card{{position:absolute;top:0;background-size:cover;background-position:center;border-radius:{round(2 * u)}px;border:{max(2, round(0.5 * u))}px solid #fff;box-shadow:0 {round(u)}px {round(4 * u)}px rgba(0,0,0,.45);backface-visibility:visible}}
""" + THEME_CSS.get(look.get("theme") or "", "").format(s=round(1.2 * u), t=round(9.5 * u), h=max(2, round(0.4 * u)), g=round(2.5 * u), a=a, p=p)


def chapter_stills(video: Path, item: dict, timing: dict, project: Path, k: int) -> list[str]:
    """A still from the start of each chapter (by its transcript line), for the flythrough cards."""
    chapters = item.get("chapters") or []
    if not chapters:
        raise Problem("A flythrough needs \"chapters\": [{\"text\": \"Setup\", \"line\": 4}, ...].")
    names = []
    for i, c in enumerate(chapters):
        at = (timing["lines"].get(str(c.get("line"))) or [None])[0]
        if at is None:
            raise Problem(f"Flythrough chapter \"{c.get('text', '')}\": line {c.get('line')} isn't in this video.")
        name = f"fly{k}_{i}.jpg"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at + 0.4:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(project / name)])
        names.append(name)
    return names


def merge_windows(spans: list[tuple[float, float, int]]) -> list[tuple[float, float, list[int]]]:
    """Graphics whose times overlap are rendered together (pure)."""
    groups: list[tuple[float, float, list[int]]] = []
    for a, b, k in sorted(spans):
        if groups and a <= groups[-1][1] + 0.05:
            ga, gb, ks = groups[-1]
            groups[-1] = (ga, max(gb, b), ks + [k])
        else:
            groups.append((a, b, [k]))
    return groups


def apply_motion(out: Path, cfg: dict, brand: dict, timing: dict, w: int, h: int, fps: float, final: bool, folder: Path, stem: str, plan_dir: Path) -> None:
    """Adds the plan's motion graphics. Only the moments with graphics go through HyperFrames (headless Chrome), as
    short full-frame segments of this very video, which ffmpeg then lays back in place: long videos stay fast."""
    cli = hyperframes_cmd()
    gsap = MOTION_DIR / "node_modules" / "gsap" / "dist" / "gsap.min.js"
    if not gsap.exists():
        raise Problem("GSAP is missing. Run: python davnai.py setup --motion")
    total = probe(out)["seconds"]
    look = brand_look(brand)
    items = [keep_off_face(item, timing.get("face"), w, h, timing.get("captions")) for item in cfg["motion"]]
    for k, item in enumerate(items):  # a flythrough takes as long as its chapters need, unless told
        if item.get("type") == "flythrough" and "seconds" not in item and not item.get("lines"):
            items[k] = {**item, "seconds": round(0.95 * len(item.get("chapters") or []) + 0.7, 2)}
    spans = [(*item_window(item, timing, total), k) for k, item in enumerate(items)]
    base = out.with_name(out.stem + "_base" + out.suffix)
    out.replace(base)
    work = folder / f"{stem}_motion"
    shutil.rmtree(work, ignore_errors=True)
    segments = []
    try:
        for g, (a, b, ks) in enumerate(merge_windows(spans)):
            project = work / f"seg{g}"
            project.mkdir(parents=True)
            shutil.copy2(gsap, project / "gsap.min.js")
            if look.get("font_path"):
                (project / "fonts").mkdir(exist_ok=True)
                shutil.copy2(look["font_path"], project / "fonts" / Path(look["font_path"]).name)
            parts, anims = [], []
            base_rel = os.path.relpath(base, project).replace("\\", "/")
            for k in ks:
                ia, ib, _ = spans[k]
                item = items[k]
                if item.get("type") == "feed":
                    item = {**item, "_base": (base_rel, a)}
                if item.get("type") == "flythrough":
                    item = {**item, "_stills": chapter_stills(base, item, timing, project, k)}
                html, js = motion_item(k, item, ia - a, ib - ia, w, h, look, plan_dir, project)
                parts.append(html)
                anims.append(js)
            base_rel = os.path.relpath(base, project).replace("\\", "/")
            page = f"""<!doctype html><html><head><meta charset="utf-8"><style>{motion_css(w, h, look)}</style>
<script>window.BRAND={json.dumps({**look, "width": w, "height": h})};window.__davnaiQueue={{}};window.registerDavnai=function(fn){{(window.__davnaiQueue[window.__davnaiCurrent]=window.__davnaiQueue[window.__davnaiCurrent]||[]).push(fn);}};</script>
</head><body>
<div id="stage" data-composition-id="main" data-start="0" data-width="{w}" data-height="{h}" data-fps="{fps:g}">
<video class="base" data-start="0" data-duration="{b - a:.3f}" data-media-start="{a:.3f}" src="{esc(base_rel)}" muted playsinline></video>
{''.join(parts)}
<script src="gsap.min.js"></script>
<script>const tl=gsap.timeline({{paused:true}});{''.join(anims)}window.__timelines={{main:tl}};</script>
</div></body></html>"""
            (project / "index.html").write_text(page, encoding="utf-8")
            segments.append((a, project, work / f"seg{g}.mp4"))

        def draw(job):  # each moment is its own HyperFrames render; a few run at once
            a, project, seg = job
            proc = subprocess.run([*cli, "render", str(project), "-o", str(seg), "-q", "looks" if final else "draft", "-f", f"{fps:g}", "--quiet"], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0 or not seg.exists():
                tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
                raise Problem(f"HyperFrames couldn't render the graphics at {a:.1f}s:\n{tail}\n(The page is in {project}; `hyperframes preview` there shows it.)")
            return a, seg
        segments = side_by_side(draw, segments, heavy=True)
        inputs = ["-i", str(base)]
        chain, label = [], "0:v"
        for g, (a, seg) in enumerate(segments):
            inputs += ["-itsoffset", f"{a:.3f}", "-i", str(seg)]
            chain.append(f"[{label}][{g + 1}:v]overlay=0:0:eof_action=pass[o{g}]")
            label = f"o{g}"
        quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
        # The theme's sound as each graphic appears (unless "sounds": false), mixed under the voice.
        pops = [(spans[k][0], items[k].get("sound") or ("whoosh" if items[k].get("type") == "scene" else look.get("sound"))) for k in range(len(items)) if cfg.get("sounds", True) and items[k].get("sound", True) is not False]
        pops = [(t, sound_file(str(n))) for t, n in pops if n and sound_file(str(n))]
        audio = ["-map", "0:a?", "-c:a", "copy"]
        if pops and probe(base)["audio"]:
            mix = []
            for j, (t, path) in enumerate(pops):
                inputs += ["-i", str(path)]
                idx = len(segments) + 1 + j
                ms = max(0, round(t * 1000))
                chain.append(f"[{idx}:a]{AUDIO_FMT},volume=0.4,adelay={ms}|{ms}[p{j}]")
                mix.append(f"[p{j}]")
            chain.append(f"[0:a]{''.join(mix)}amix=inputs={len(mix) + 1}:duration=first:normalize=0,{LIMITER}[amx]")
            audio = ["-map", "[amx]", "-c:a", "aac", "-b:a", "160k" if final else "96k"]
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[{label}]", *audio, *quality, "-movflags", "+faststart", str(out)])
        base.unlink(missing_ok=True)
        if final:
            shutil.rmtree(work, ignore_errors=True)
    except BaseException:
        if not out.exists() and base.exists():
            base.replace(out)
        raise


# ---------------------------------------------------------------- faces: framing and keeping text off them

LIGHTS = ("spotlight", "low_key", "silhouette", "neon", "rim", "under_light", "golden_hour")


def detect_faces(path: Path, times: list[float]) -> list[tuple[float, float, float, float]]:
    """Faces (x, y, w, h in the source's pixels) found at these times; [] when OpenCV isn't installed."""
    try:
        import cv2
    except ImportError:
        return []
    finder = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    video = cv2.VideoCapture(str(path))
    found = []
    for t in times[:12]:
        video.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
        ok, frame = video.read()
        if not ok:
            continue
        grey = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        side = min(grey.shape[:2])
        faces = finder.detectMultiScale(grey, 1.15, 6, minSize=(int(side * 0.08),) * 2)
        if len(faces):
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])  # the biggest face: the speaker
            found.append((float(x), float(y), float(fw), float(fh)))
    video.release()
    return found


def median_box(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float] | None:
    if not boxes:
        return None
    mid = lambda i: sorted(b[i] for b in boxes)[len(boxes) // 2]  # noqa: E731
    return (mid(0), mid(1), mid(2), mid(3))


def face_to_output(box, src_w: int, src_h: int, w: int, h: int, focus_x: float, fill: str):
    """Where a source face lands in the output frame (the same crop or fit as shape())."""
    x, y, fw, fh = box
    if fill == "blur" and abs(src_w / src_h - w / h) > 0.02:
        s = min(w / src_w, h / src_h)
        ox, oy = (w - src_w * s) / 2, (h - src_h * s) / 2
        return (ox + x * s, oy + y * s, fw * s, fh * s)
    src_ar, ar = src_w / src_h, w / h
    x0 = y0 = 0.0
    cw, ch = src_w, src_h
    if src_ar > ar + 0.01:
        cw = src_h * ar
        x0 = (src_w - cw) * focus_x
    elif src_ar < ar - 0.01:
        ch = src_w / ar
        y0 = (src_h - ch) / 2
    s = w / cw
    return ((x - x0) * s, (y - y0) * s, fw * s, fh * s)


def caption_band(place: str, w: int, h: int, look: dict, margins: dict) -> tuple[float, float]:
    size = float(look.get("size", 0.075)) * min(w, h)
    m = margins["tall" if h > w else "wide"]
    if place == "top":
        return (m["top"] * h, m["top"] * h + size * 2.6)
    if place == "middle":
        return (h / 2 - size * 1.3, h / 2 + size * 1.3)
    return (h - m["bottom"] * h - size * 2.6, h - m["bottom"] * h)


def clear_place(face, w: int, h: int, look: dict, margins: dict, preferred: str) -> str:
    """The caption position nearest the preferred one that doesn't cover the face (pure)."""
    if not face:
        return preferred
    top, bottom = face[1] - face[3] * 0.15, face[1] + face[3] * 1.15  # a little hair and chin
    for place in [preferred] + [p for p in ("bottom", "top", "middle") if p != preferred]:
        a, b = caption_band(place, w, h, look, margins)
        if b < top or a > bottom:
            return place
    return preferred


def auto_focus(cfg: dict, faces: list, src_w: int, src_h: int, w: int, h: int) -> float | None:
    """When a wide video becomes tall and the plan didn't set focus_x, keep the speaker's face in the frame."""
    face = median_box(faces)
    if face is None or "focus_x" in cfg or src_w / src_h <= w / h + 0.01 or cfg.get("fill") == "blur":
        return None
    cw = src_h * (w / h)
    centre = face[0] + face[2] / 2
    return min(1.0, max(0.0, (centre - cw / 2) / max(1.0, src_w - cw)))


# ---------------------------------------------------------------- relighting the person (needs the cut-out)


def relight_layers(k: int, item: dict, label: str, person: str, a: float, b: float, w: int, h: int, face, accent: str) -> tuple[list[str], str]:
    """Filters that relight one window: the background changes, light or a glow is added, the person goes back on top."""
    light = item.get("light", "spotlight")
    if light not in LIGHTS:
        raise Problem(f"Unknown light '{light}'. Use: {', '.join(LIGHTS)}.")
    u = max(2, round(min(w, h) / 160))
    fx_, fy_ = (face[0] + face[2] / 2, face[1] + face[3] / 2) if face else (w / 2, h * 0.38)
    en = f"enable='between(t,{a:.3f},{b:.3f})'"
    bg = {
        "spotlight": f"eq=brightness=-0.28:saturation=0.75,vignette=angle=PI/3.2:x0={fx_:.0f}:y0={fy_:.0f}",
        "low_key": "eq=brightness=-0.5:saturation=0.6",
        "silhouette": "eq=brightness=0.14:contrast=1.15:saturation=1.2",
        "neon": "eq=brightness=-0.42:saturation=0.8",
        "rim": "eq=brightness=-0.22:saturation=0.9",
        "under_light": "eq=brightness=-0.35:saturation=0.85",
    }[light]
    body = {
        "spotlight": "eq=brightness=0.05:contrast=1.08",
        "low_key": "eq=contrast=1.22:brightness=-0.02",
        "silhouette": "lutrgb=r=12:g=12:b=16",
        "neon": "eq=brightness=-0.06:saturation=1.2",
        "rim": "null",
        "under_light": "eq=brightness=-0.05",
    }[light]
    colour = "0x" + (item.get("color") or {"neon": accent if accent.upper() not in ("#FFFFFF", "#FFF") else "#FF2BD6", "rim": "#FFF4E0", "under_light": "#FF7A1A"}.get(light, "#FFFFFF")).lstrip("#")
    g = [f"[{label}]split[r{k}a][r{k}b]", f"[r{k}b]{bg}[r{k}bg]", f"[r{k}a][r{k}bg]overlay=0:0:{en}[r{k}l]", f"[{person}]format=rgba,split[r{k}p][r{k}m]"]
    out = f"r{k}l"
    if light in ("neon", "rim"):  # a halo behind the person
        blur = {"neon": 7 * u, "rim": 3 * u}[light]
        shape = f",boxblur={blur}:2"
        strength = float(item.get("strength", 1.0)) * {"neon": 1.0, "rim": 0.85}[light]
        g += [f"[r{k}m]alphaextract{shape}[r{k}mask]",
              f"color=c={colour}:s={w}x{h}:d={b - a:.3f}:r=30,format=rgba,setpts=PTS-STARTPTS+{a:.3f}/TB[r{k}c]",
              f"[r{k}c][r{k}mask]alphamerge,colorchannelmixer=aa={min(1.0, strength):.2f}[r{k}glow]",
              f"[{out}][r{k}glow]overlay=0:0:{en}:eof_action=pass[r{k}g]"]
        out = f"r{k}g"
    elif light == "under_light":  # warm light from below, on the person only
        g += [f"[r{k}m]alphaextract,geq=lum='lum(X,Y)*pow(Y/H\\,1.6)'[r{k}mask]",
              f"color=c={colour}:s={w}x{h}:d={b - a:.3f}:r=30,format=rgba,setpts=PTS-STARTPTS+{a:.3f}/TB[r{k}c]",
              f"[r{k}c][r{k}mask]alphamerge,colorchannelmixer=aa={min(1.0, 0.7 * float(item.get('strength', 1.0))):.2f}[r{k}glow]"]
    else:
        g.append(f"[r{k}m]nullsink")
    g += [f"[r{k}p]{body}[r{k}body]", f"[{out}][r{k}body]overlay=0:0:{en}:eof_action=pass[r{k}o]"]
    if light == "under_light":
        g.append(f"[r{k}o][r{k}glow]overlay=0:0:{en}:eof_action=pass[r{k}u]")
        return g, f"r{k}u"
    return g, f"r{k}o"


# ---------------------------------------------------------------- studio effects (the engine in ../engine)


def workers(jobs: int, heavy: bool = False) -> int:
    """How many slow steps run at once: about one per two processor cores (fewer for browser renders)."""
    cores = os.cpu_count() or 2
    return max(1, min(jobs, cores // (4 if heavy else 2) or 1, 3 if heavy else 8))


def THREADS_EACH(jobs: int) -> dict[str, str]:  # noqa: N802
    """Thread limits for each of several engine runs at once, so they share the cores instead of fighting over them."""
    n = str(max(1, (os.cpu_count() or 2) // max(1, workers(jobs))))
    return {"OMP_NUM_THREADS": n, "OPENBLAS_NUM_THREADS": n, "OPENCV_FOR_THREADS_NUM": n}


def side_by_side(fn, jobs: list, heavy: bool = False) -> list:
    """Runs fn on each job, several at once, keeping their order; the first problem stops the rest."""
    if workers(len(jobs), heavy) <= 1:
        return [fn(j) for j in jobs]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers(len(jobs), heavy)) as pool:
        return list(pool.map(fn, jobs))


def studio_effects() -> dict[str, str]:
    """The studio effects and what each does, read from the engine (no imports needed)."""
    if not ENGINE.exists():
        return {}
    text = ENGINE.read_text(encoding="utf-8")
    return dict(re.findall(r"@effect\('([a-z0-9-]+)', '([^']*)'\)", text))


def studio_problem() -> str | None:
    """Why the studio effects can't run here, or None when they can."""
    if not ENGINE.exists():
        return "The studio effects need the Davnai skill installed (github.com/davnaiOS/davnai-skills), not just davnai.py."
    missing = [m for m in ("numpy", "cv2", "PIL", "mediapipe") if importlib.util.find_spec(m) is None]
    if missing:
        return f"The studio effects need {', '.join(missing)}: run python davnai.py setup --yes."
    if not all((MODELS_DIR / n).exists() for n in MODEL_FILES):
        return "The studio effects need the face and cut-out models: run python davnai.py setup --yes."
    return None


def ensure_models() -> list[str]:
    """Downloads the face finder and cut-out models once; returns the ones that are ready."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    ready = []
    for name, (url, digest) in MODEL_FILES.items():
        path = MODELS_DIR / name
        if not path.exists():
            code, _, data = http(url, timeout=120)
            if code == 200 and hashlib.sha256(data).hexdigest() == digest:
                path.write_bytes(data)
        if path.exists():
            ready.append(name)
    return ready


def studio_plan(items: list[tuple[float, float, dict]], s0: float, offset: float, resolve, work: Path) -> list[dict]:
    """The engine's plan for one stretch of video: times from the transcript lines, options as given (pure but for pictures)."""
    known = studio_effects()
    plan = []
    for k, (a, b, item) in enumerate(items):
        name = {"apple-toggles": "settings-toggles"}.get(str(item.get("effect") or "").lower(), str(item.get("effect") or "").lower())
        if known and name not in known:
            raise Problem(f"Unknown studio effect '{name}'. See reference/studio.md (or library/studio.md) for the {len(known)} effects.")
        step = {key: val for key, val in item.items() if key not in ("type", "effect", "lines", "at", "seconds", "all") and not key.startswith("_")}
        if isinstance(step.get("images"), list):  # the engine takes a folder of pictures or clips
            folder = work / f"pics{k}"
            folder.mkdir(parents=True, exist_ok=True)
            for i, pic in enumerate(step["images"]):
                src = resolve(str(pic))
                if not src.exists():
                    raise Problem(f"Studio effect '{name}': can't find {src}.")
                shutil.copy2(src, folder / f"{i:03d}{src.suffix.lower()}")
            step["images"] = str(folder)
        elif step.get("images"):
            step["images"] = str(resolve(str(step["images"])))
        for key in ("text", "lines_text", "right", "others"):
            if isinstance(step.get(key), list):
                step[key] = "|".join(str(x) for x in step[key])
        if "lines_text" in step:  # the engine's own "lines" option (cover lines); ours are transcript lines
            step["lines"] = step.pop("lines_text")
        start = round(a + offset - s0, 3)
        if "at_seconds" in step:  # seconds into the effect; tap wants the time in the clip
            step["at"] = round(start + float(step.pop("at_seconds")), 3) if name == "tap" else step.pop("at_seconds")
        if "ticks_seconds" in step:
            ticks = step.pop("ticks_seconds")
            ticks = ticks if isinstance(ticks, list) else str(ticks).split("|")
            step["ticks"] = "|".join(f"{(start if name == 'todo' else 0) + float(t):.2f}" for t in ticks)  # todo wants clip times
        plan.append({"fx": name, "start": start, "end": round(b + offset - s0, 3), **step})
    return plan


def apply_studio(out: Path, items: list[tuple[float, float, dict]], brand: dict, w: int, h: int, final: bool, folder: Path, stem: str, offset: float, resolve) -> None:
    """Studio effects run only on the stretches that have them (the engine draws every frame, so it's kept short)."""
    problem = studio_problem()
    if problem:
        raise Problem(problem)
    work = folder / f"{stem}_studio"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    base = out.with_name(out.stem + "_prestudio" + out.suffix)
    out.replace(base)
    total = probe(base)["seconds"]
    look = brand_look(brand)
    env = {**os.environ, "DAVNAI_HOME": str(BRAND_DIR.parent), "DAVNAI_FONTS": str(FONTS_DIR), "DAVNAI_MODELS": str(MODELS_DIR),
           "DAVNAI_BRAND": json.dumps({"name": brand.get("name") or "", "handle": look.get("handle") or "", "primary": look["primary"], "accent": look["accent"]})}
    try:
        ensure_fonts(FONT_SOURCES)
        jobs = []
        for g, (a, b, ks) in enumerate(merge_windows([(a + offset, b + offset, k) for k, (a, b, _) in enumerate(items)])):
            s0, s1 = max(0.0, a - 0.6), min(total, b + 0.6)
            seg, done = work / f"seg{g}.mp4", work / f"seg{g}_fx.mp4"
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{s0:.3f}", "-t", f"{s1 - s0:.3f}", "-i", str(base), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", str(seg)])
            plan = studio_plan([items[k] for k in ks], s0, offset, resolve, work)
            (work / f"seg{g}.json").write_text(json.dumps({"effects": plan}, indent=1), encoding="utf-8")
            jobs.append((a, s0, s1, seg, done, work / f"seg{g}.json"))
        say(f"Studio effects: {len(jobs)} moment{'s' * (len(jobs) != 1)}, {workers(len(jobs))} at a time...")

        def one(job):
            a, s0, s1, seg, done, plan_file = job
            proc = subprocess.run([sys.executable, str(ENGINE), "--plan", str(plan_file), str(seg), str(done), "--width", str(min(w, h))],
                                  env={**env, **THREADS_EACH(len(jobs))}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0 or not done.exists():
                raise Problem(f"The studio effect at {a:.1f}s didn't render:\n" + "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-6:]))
            return s0, s1, done
        segments = side_by_side(one, jobs)
        inputs, chain, label = ["-i", str(base)], [], "0:v"
        for g, (s0, s1, done) in enumerate(segments):
            inputs += ["-itsoffset", f"{s0:.3f}", "-i", str(done)]
            chain.append(f"[{g + 1}:v]scale={w}:{h},setsar=1[sf{g}]")
            chain.append(f"[{label}][sf{g}]overlay=0:0:enable='between(t,{s0:.3f},{s1 - 0.04:.3f})':eof_action=pass[so{g}]")
            label = f"so{g}"
        quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[{label}]", "-map", "0:a?", "-c:a", "copy", *quality, "-movflags", "+faststart", str(out)])
        base.unlink(missing_ok=True)
        if final:
            shutil.rmtree(work, ignore_errors=True)
    except BaseException:
        if not out.exists() and base.exists():
            base.replace(out)
        raise


# ---------------------------------------------------------------- signature effects (timed by transcript lines)

FX_TYPES = ("shake", "flash", "rgb", "glitch", "blur", "bw", "vhs", "grain", "light_leak", "behind", "relight", "poster", "compare", "cycle", "custom", "studio")
BLOCKED_FILTERS = ("movie", "amovie", "sendcmd", "asendcmd", "zmq", "azmq")  # custom effects may not read files or take commands


def check_custom_filter(chain: str, w: int, h: int) -> str:
    """A custom effect is one ffmpeg filter chain (no extra inputs or outputs); it's tried on a blank frame first."""
    chain = str(chain or "").strip()
    if not chain:
        raise Problem("A custom effect needs \"filter\": an ffmpeg filter chain, e.g. \"hue=h=90*t,eq=contrast=1.3\".")
    if any(c in chain for c in "[];"):
        raise Problem(f"Custom effect \"{chain}\": use one chain of filters joined by commas (no [labels] or ;).")
    names = {re.split(r"[=@]", part.strip(), maxsplit=1)[0] for part in re.split(r"(?<!\\),", chain)}
    if names & set(BLOCKED_FILTERS):
        raise Problem(f"Custom effect: {', '.join(sorted(names & set(BLOCKED_FILTERS)))} can't be used (it reads files or takes commands).")
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d=0.2:r=10", "-vf", f"{chain},scale={w}:{h},format=yuv420p", "-f", "null", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise Problem(f"Custom effect \"{chain}\" doesn't work in ffmpeg:\n" + "\n".join(proc.stderr.strip().splitlines()[-4:]))
    return chain


def compare_graph(label: str, raw: str, items: list[tuple[float, float, dict]], w: int, h: int) -> tuple[list[str], str]:
    """Before / after: the left half shows the picture before looks and effects, with a divider line."""
    graph = [f"[{raw}]split={len(items)}" + "".join(f"[cr{k}]" for k in range(len(items)))] if len(items) > 1 else [f"[{raw}]null[cr0]"]
    bar = max(2, round(min(w, h) * 0.008))
    for k, (a, b, _item) in enumerate(items):
        graph.append(f"[cr{k}]crop={w // 2}:{h}:0:0[ch{k}]")
        graph.append(f"[{label}][ch{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[cm{k}]")
        graph.append(f"[cm{k}]drawbox=x={w // 2 - bar // 2}:y=0:w={bar}:h=ih:color=white:t=fill:enable='between(t,{a:.3f},{b:.3f})'[cp{k}]")
        label = f"cp{k}"
    return graph, label


def compare_labels(a: float, b: float, item: dict, w: int, h: int) -> list[tuple[float, float, str, int, int]]:
    """The two labels over a before / after (pure)."""
    left, right = item.get("labels") or ["RAW", "EDIT"]
    y = round(h * (0.08 if h > w else 0.06))
    return [(a, b, str(left), w // 4, y), (a, b, str(right), w * 3 // 4, y)]


def picture_sounds(cfg: dict, words: list[list], total: float, taken: list[float]) -> list[tuple[float, str]]:
    """Automatic sound effects for what changes on screen: punch zooms, effects and cut-out moments (thinned, so they
    never crowd: at least 0.7 s apart, and never on top of a transition's sound). A plan entry's own "sound" wins (pure)."""
    events = []
    for z in cfg.get("zoom") or []:
        rng = z.get("lines") if isinstance(z, dict) else z
        win = line_window(words, int(rng[0]), int(rng[1])) if isinstance(rng, (list, tuple)) and len(rng) == 2 else None
        if isinstance(z, dict) and isinstance(z.get("from"), (list, tuple)):
            win = word_span(words, z["from"], z.get("to"))
        if win and (z.get("style", "punch") if isinstance(z, dict) else "punch") == "punch":
            events.append((win[0], (z.get("sound") if isinstance(z, dict) else None) or "swoosh"))
    for item in cfg.get("fx") or []:
        if item.get("sound") is False or item.get("type") in ("grain", "custom") or item.get("all"):
            continue
        try:
            a, _b = fx_window(item, words, total)
        except Problem:
            continue
        events.append((a, item.get("sound") or ("impact" if item.get("type") in ("behind", "poster") else "whoosh")))
    out, used = [], sorted(taken)
    for t, name in sorted(events):
        if all(abs(t - u) >= 0.7 for u in used) and sound_file(name):
            out.append((t, name))
            used.append(t)
    return out


def fx_window(item: dict, words: list[list], total: float) -> tuple[float, float]:
    """Where an effect plays in the edited video (main part), from its lines: code, never the AI."""
    if item.get("all"):
        return 0.0, total
    if item.get("at") == "start":
        return 0.0, min(total, float(item.get("seconds", 1.5)))
    if item.get("at") == "end":
        return max(0.0, total - float(item.get("seconds", 1.5))), total
    rng = item.get("lines")
    if isinstance(rng, int):
        rng = [rng, rng]
    if isinstance(item.get("from"), (list, tuple)):
        win = word_span(words, item["from"], item.get("to"))
        if win is None:
            raise Problem(f"Effect '{item.get('type')}': words {item['from']}..{item.get('to')} aren't in this video.")
        a, b = win
        if item.get("type") == "flash":
            b = a + float(item.get("seconds", 0.15))
        return max(0.0, a - 0.05), min(total, b + 0.05)
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        raise Problem(f"Effect '{item.get('type')}' needs \"lines\": [first, last] (or \"from\": [line, word], \"all\": true, \"at\": \"start\"/\"end\").")
    win = line_window(words, int(rng[0]), int(rng[1]))
    if win is None:
        raise Problem(f"Effect '{item.get('type')}': lines {rng[0]}-{rng[1]} aren't in this video.")
    a, b = win
    if item.get("type") == "flash":
        b = a + float(item.get("seconds", 0.15))
    elif item.get("seconds"):
        b = min(b, a + float(item["seconds"]))
    return max(0.0, a - 0.05), min(total, b + 0.05)


def fx_chain(kind: str, w: int, h: int, item: dict) -> str:
    """The ffmpeg filters for one effect (applied only inside its window)."""
    u = max(2, round(min(w, h) / 160))
    strength = float(item.get("strength", 1.0))
    if kind == "shake":
        amp = 0.04 * strength
        return f"crop=iw*{1 - amp * 2:.3f}:ih*{1 - amp * 2:.3f}:x='(iw-ow)/2+(iw-ow)/2*sin(t*41)*0.9':y='(ih-oh)/2+(ih-oh)/2*cos(t*33)*0.9',scale={w}:{h}"
    if kind == "flash":
        return f"eq=brightness={0.45 * strength:.2f}:contrast=0.75"
    if kind == "rgb":
        return f"rgbashift=rh=-{round(3 * u * strength)}:bh={round(3 * u * strength)}"
    if kind == "glitch":
        return f"rgbashift=rh=-{round(5 * u * strength)}:bv={round(3 * u * strength)},noise=alls={round(35 * strength)}:allf=t,crop=iw:ih*0.985:0:'ih*0.015*mod(floor(t*24),2)',scale={w}:{h}"
    if kind == "blur":
        return f"boxblur={round(6 * u * strength)}:2"
    if kind == "bw":
        return "hue=s=0,eq=contrast=1.12"
    if kind == "vhs":
        return f"curves=preset=vintage,eq=saturation=1.25:contrast=1.08,rgbashift=rh=-{u}:bh={u},noise=alls={round(16 * strength)}:allf=t,drawgrid=w=0:h={max(3, u * 2)}:t=1:c=black@0.22"
    if kind == "grain":
        return f"noise=alls={round(12 * strength)}:allf=t"
    if kind == "custom":  # the AI's own filters, kept to the frame size
        return f"{check_custom_filter(item.get('filter'), w, h)},scale={w}:{h}"
    if kind == "relight":  # golden hour: no cut-out needed
        return f"colorbalance=rs={0.12 * strength:.2f}:gs={0.03 * strength:.2f}:bs=-{0.12 * strength:.2f}:rm={0.08 * strength:.2f}:bm=-{0.08 * strength:.2f},eq=brightness=0.03:saturation=1.12,vignette=PI/5"
    raise Problem(f"Unknown effect '{kind}'. Use: {', '.join(FX_TYPES)}.")


def fx_graph(label: str, cfg: dict, words: list[list], total: float, w: int, h: int, fps: float) -> tuple[list[str], str]:
    """Each effect runs on a copy of the picture, shown only inside its window (overlay with enable)."""
    graph = []
    for k, item in enumerate(cfg.get("fx") or []):
        kind = item.get("type")
        if needs_cutout(item) or kind in ("compare", "cycle", "studio"):
            continue  # cut-out effects come after the main render; before/after is laid on later
        a, b = fx_window(item, words, total)
        if kind == "light_leak":
            colours = item.get("colours") or ["0xFF8A00", "0xFF2D55"]
            graph.append(f"gradients=s={w}x{h}:c0={colours[0]}:c1={colours[1]}:x0=0:y0=0:x1={w}:y1={h}:speed=0.03:d={total:.3f}:r={fps:g},format=rgba,colorchannelmixer=aa={0.38 * float(item.get('strength', 1.0)):.2f}[lk{k}]")
            graph.append(f"[{label}][lk{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':shortest=1[fx{k}]")
        else:
            graph.append(f"[{label}]split[fxa{k}][fxb{k}]")
            graph.append(f"[fxb{k}]{fx_chain(kind, w, h, item)},setsar=1,format=yuv420p[fxc{k}]")
            graph.append(f"[fxa{k}][fxc{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'[fx{k}]")
        label = f"fx{k}"
    return graph, label


def beats_of(path: Path, limit: float | None = None) -> list[float]:
    """Beat times in a music file: loud onsets at least 0.25 s apart (ffmpeg decodes; plain Python finds the peaks)."""
    import array

    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), *(["-t", f"{limit:.2f}"] if limit else []), "-ac", "1", "-ar", "11025", "-f", "s16le", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    samples = array.array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    hop = 256
    energy = [sum(abs(x) for x in samples[i:i + hop]) / hop for i in range(0, len(samples) - hop, hop)]
    beats, last = [], -1.0
    for i in range(8, len(energy)):
        local = sum(energy[i - 8:i]) / 8 + 1
        t = i * hop / 11025
        if energy[i] > local * 1.6 and energy[i] > 400 and t - last >= 0.25:
            beats.append(round(t, 3))
            last = t
    return beats


def beat_pulse(label: str, beats: list[float], w: int, h: int, fps: float, amount: float = 0.04) -> tuple[list[str], str]:
    """A small zoom bump on every beat (zoompan on the finished frame size)."""
    if not beats:
        return [], label
    beats = beats[:150]
    bump = "+".join(f"gte(it,{b:.3f})*exp(-(it-{b:.3f})*14)" for b in beats)
    return [f"[{label}]zoompan=z='1+{amount:.3f}*min(1,{bump})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={w}x{h}:fps={fps:g},setsar=1[bp]"], "bp"


def split_graph(label: str, cfg: dict, w: int, h: int, fps: float, total: float, add_input, resolve) -> tuple[list[str], str]:
    """Split screen: the edit on one part, another clip (gameplay, a demo, B-roll) on the other."""
    sp = cfg["split"] if isinstance(cfg["split"], dict) else {"clip": cfg["split"]}
    clip = resolve(sp.get("clip") or "")
    if not clip.exists():
        raise Problem(f"Split screen: can't find {clip}.")
    share = min(0.6, max(0.25, float(sp.get("share", 0.45))))
    h_clip = even(h * share)
    h_main = h - h_clip
    info = probe(clip)
    if clip.suffix.lower() in IMAGE_EXT:
        ci = add_input("-loop", "1", "-framerate", f"{fps:g}", "-t", f"{total:.3f}", "-i", str(clip))
    else:
        ci = add_input("-stream_loop", "-1", "-ss", f"{float(sp.get('start', 0)):.3f}", "-t", f"{total:.3f}", "-i", str(clip))
    graph = shape(label, "spm", w, h, w, h_main, 0.5, fps)
    graph += shape(f"{ci}:v", "spc", info["width"], info["height"], w, h_clip, float(sp.get("focus_x", 0.5)), fps)
    order = "[spc][spm]" if sp.get("position") == "top" else "[spm][spc]"
    graph.append(f"{order}vstack=inputs=2,setsar=1[spv]")
    return graph, "spv"


def needs_cutout(item: dict) -> bool:
    """Effects done after the main render, with the person cut out: words behind, poster, relighting (not golden hour)."""
    kind = item.get("type")
    return kind in ("behind", "poster") or (kind == "cycle" and item.get("behind", True)) or (kind == "relight" and item.get("light", "spotlight") != "golden_hour")


def behind_windows(cfg: dict, words: list[list], total: float) -> list[tuple[float, float, dict]]:
    """Effects that need the person cut out, with their windows."""
    return [(*fx_window(item, words, total), item) for item in cfg.get("fx") or [] if needs_cutout(item)]


def cycle_times(a: float, b: float, beats: list[float], every: float = 0.4) -> list[float]:
    """When the picture changes: on each beat in the window, else every `every` seconds (pure)."""
    near = [t for t in beats if a < t < b - 0.1]
    if len(near) >= 2:
        return [a] + near
    every = max(0.12, every)
    return [a + i * every for i in range(max(1, int((b - a) / every + 0.999)))]


def cycle_images(item: dict, resolve) -> list[Path]:
    pics = [resolve(str(x)) for x in item.get("images") or []]
    if len(pics) < 2:
        raise Problem("A picture cycle needs at least 2 \"images\" (the person's own, stock, or pictures you made).")
    missing = [str(p) for p in pics if not p.exists()]
    if missing:
        raise Problem(f"Picture cycle: can't find {', '.join(missing)}.")
    return pics


def cycle_reel(out: Path, pics: list[Path], times: list[float], end: float, w: int, h: int) -> None:
    """A short clip of the pictures, each held until the next change (the pictures repeat if there are more changes)."""
    args, parts = [], []
    for i, t in enumerate(times):
        d = (times[i + 1] if i + 1 < len(times) else end) - t
        args += ["-loop", "1", "-framerate", "30", "-t", f"{max(d, 0.04):.3f}", "-i", str(pics[i % len(pics)])]
        parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,format=yuv420p[c{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[c{i}]" for i in range(len(times))) + f"concat=n={len(times)}:v=1:a=0[v]"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args, "-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


def slice_times(a: float, b: float, n: int, beats: list[float]) -> list[float]:
    """When each word of a sliced title lands: on the music's beats when there are enough, else evenly (pure)."""
    if n <= 0:
        return []
    near = [t for t in beats if a <= t < b - 0.15]
    if near and near[0] - a > 0.12:
        near = [a] + near
    if len(near) >= n:
        return near[:n]
    step = (b - a) * 0.6 / max(1, n)
    return [a + i * step for i in range(n)]


def poster_size(words_: list[str], w: int, h: int, top: float, face=None) -> tuple[int, bool]:
    """Font size for a poster title, and whether it goes on one line; it fits above the face (only the hair overlaps)."""
    room = max(h * 0.16, face[1] + face[3] * 0.25 - top) if face else h * 0.3
    one = min(round(min(w, h) * 0.42), round(w * 0.9 / max(1, len(" ".join(words_)) * 0.66)), round(room))
    longest = max((len(x) for x in words_), default=1)
    stacked = min(round(min(w, h) * 0.42), round(w * 0.9 / max(1, longest * 0.66)), round(room / max(1, len(words_))))
    return (one, True) if one >= stacked * 0.75 else (stacked, False)


def behind_ass(path: Path, w: int, h: int, items: list[tuple[float, float, dict]], brand: dict, offset: float, face=None) -> None:
    look = brand_look(brand)
    family = look["font"] if look.get("font_path") else "Arial"
    size = round(min(w, h) * 0.3)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Behind,{family},{size},{ass_colour(look['primary'])},{ass_colour(look['primary'])},{ass_colour('#000000', 0.7)},{ass_colour('#000000', 1)},-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for a, b, item in items:
        kind = item.get("type", "behind")
        if kind not in ("behind", "poster"):
            continue
        colour = ass_colour(item.get("color") or (look["text"] if kind == "poster" else look["primary"]))
        y = round(h * float(item.get("y", 0.05 if kind == "poster" else 0.38)))
        words_ = str(item.get("text", "")).upper().split()
        if kind == "behind" and item.get("slice") and len(words_) > 1:
            # Each word slams in on its own beat, from alternating sides, stacked like a cut-up poster.
            fs = min(size, round(h * 0.55 / len(words_)))
            gap = round(fs * 0.92)
            for i, (word, t) in enumerate(zip(words_, slice_times(a, b, len(words_), item.get("_beats") or []))):
                wfs = min(fs, round(w * 0.92 / max(1, len(word) * 0.62)))
                wy = y - gap * (len(words_) - 1) // 2 + i * gap
                x0 = w // 2 + (1 if i % 2 == 0 else -1) * round(w * 0.7)
                tilt = (-4, 3, -2, 4)[i % 4]
                tint = colour if i % 2 == 0 else ass_colour(item.get("color2") or look["accent"])  # every other word in the accent
                lines.append(f"Dialogue: 0,{ass_time(t + offset)},{ass_time(b + offset)},Behind,,0,0,0,,{{\\move({x0},{wy},{w // 2},{wy},0,140)\\fs{wfs}\\frz{tilt}\\c{tint}}}{ass_text(word)}")
            continue
        text = ass_text(" ".join(words_))
        if kind == "poster":  # as big as fits above the face: one line, or a word per line
            pfs, single = poster_size(words_, w, h, y, None if "y" in item else face)
            stacked = text if single else "\\N".join(ass_text(x) for x in words_)
            lines.append(f"Dialogue: 0,{ass_time(a + offset)},{ass_time(b + offset)},Behind,,0,0,0,,{{\\an8\\pos({w // 2},{y})\\fs{pfs}\\fsp{-round(pfs * 0.03)}\\c{colour}\\fscx130\\fscy130\\t(0,180,\\fscx100\\fscy100)}}{stacked}")
            if item.get("sub"):
                lines.append(f"Dialogue: 1,{ass_time(a + offset + 0.2)},{ass_time(b + offset)},Behind,,0,0,0,,{{\\pos({w // 2},{round(h * 0.88)})\\fs{round(min(w, h) * 0.06)}\\c{colour}}}{ass_text(str(item['sub']).upper())}")
            continue
        lines.append(f"Dialogue: 0,{ass_time(a + offset)},{ass_time(b + offset)},Behind,,0,0,0,,{{\\pos({w // 2},{y})\\c{colour}\\fscx60\\fscy60\\t(0,220,\\fscx100\\fscy100)}}{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def inputs_of(args: list[str]) -> list[str]:
    """The input files in an ffmpeg argument list (each follows an -i)."""
    return [args[i + 1] for i, a in enumerate(args[:-1]) if a == "-i"]


def poster_background(path: Path, w: int, h: int, colour: str) -> None:
    """A flat brand-colour background with halftone dots that grow towards the bottom."""
    c = colour.lstrip("#")
    cell = max(8, round(min(w, h) / 36))
    dot = f"lt(hypot(mod(X,{cell})-{cell / 2},mod(Y,{cell})-{cell / 2}),{cell * 0.12}+{cell * 0.3}*Y/H)"
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)] if len(c) == 6 else [0, 0, 0]
    dark = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] < 110
    shade = "{v}+(255-{v})*0.2" if dark else "{v}*0.8"  # lighter dots on dark colours, darker dots on light ones
    ch = {n: f"if({dot},{shade.format(v=f'{n}(X,Y)')},{n}(X,Y))" for n in "rgb"}
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x{c}:s={w}x{h}:d=1", "-vf",
         f"format=rgb24,geq=r='{ch['r']}':g='{ch['g']}':b='{ch['b']}'", "-frames:v", "1", str(path)])


def cut_out_person(segment: Path, out: Path) -> None:
    """The person in a short clip, with a see-through background: the studio engine's cut-out (MediaPipe) when it's set up,
    else HyperFrames' model."""
    if studio_problem() is None:
        env = {**os.environ, "DAVNAI_HOME": str(BRAND_DIR.parent), "DAVNAI_MODELS": str(MODELS_DIR)}
        proc = subprocess.run([sys.executable, str(ENGINE), "--cutout", str(segment), str(out)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0 and out.exists():
            return
    proc = subprocess.run([*hyperframes_cmd(), "remove-background", str(segment), "-o", str(out), "--quality", "balanced"], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out.exists():
        raise Problem("Couldn't cut the person out for the words-behind effect:\n" + "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-5:]))


def apply_behind(out: Path, items: list[tuple[float, float, dict]], brand: dict, w: int, h: int, final: bool, folder: Path, stem: str, offset: float, face=None) -> None:
    """Big words behind the person: the words are drawn on the video, then the cut-out person goes back on top."""
    work = folder / f"{stem}_behind"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    base = out.with_name(out.stem + "_prebehind" + out.suffix)
    out.replace(base)
    try:
        people = []
        for k, (a, b, item) in enumerate(items):
            seg = work / f"seg{k}.mp4"
            if item.get("type") == "poster":  # the moment freezes: one frame, held
                still = work / f"still{k}.png"
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a + offset + 0.05:.3f}", "-i", str(base), "-frames:v", "1", str(still)])
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-framerate", "30", "-t", f"{b - a:.3f}", "-i", str(still), "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(seg)])
            else:
                run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{a + offset:.3f}", "-t", f"{b - a:.3f}", "-i", str(base), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(seg)])
            people.append((a + offset, b + offset, work / f"person{k}.webm", seg))
        side_by_side(lambda job: cut_out_person(job[3], job[2]), people)
        people = [(a, b, person) for a, b, person, _seg in people]
        ass = work / "behind.ass"
        behind_ass(ass, w, h, items, brand, offset, face)
        look = brand_look(brand)
        fonts = work / "fonts"
        fonts.mkdir()
        if look.get("font_path"):
            shutil.copy2(look["font_path"], fonts / Path(look["font_path"]).name)
        inputs, chain, label = ["-i", str(base)], [], "0:v"
        accent = (brand.get("captions") or {}).get("look", {}).get("accent") or "#FF2BD6"
        for k, (a, b, person) in enumerate(people):  # relighting first, so words and people go on top of the new light
            inputs += ["-c:v", "libvpx-vp9", "-itsoffset", f"{a:.3f}", "-i", str(person)]
            item = items[k][2]
            if item.get("type") == "relight":
                part, label = relight_layers(k, item, label, f"{k + 1}:v", a, b, w, h, face, accent)
                chain += part
        for k, (a, b, person) in enumerate(people):  # posters: a flat halftone background in the brand colour
            if items[k][2].get("type") == "poster":
                bg = work / f"poster{k}.png"
                poster_background(bg, w, h, items[k][2].get("background") or look["primary"])
                inputs += ["-loop", "1", "-framerate", "30", "-t", f"{b - a:.3f}", "-i", str(bg)]
                bi = len(inputs_of(inputs)) - 1
                chain.append(f"[{bi}:v]format=yuv420p,fade=t=in:st=0:d=0.12:c=white,setpts=PTS-STARTPTS+{a:.3f}/TB[pb{k}]")
                chain.append(f"[{label}][pb{k}]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[pg{k}]")
                label = f"pg{k}"
        for k, (a, b, person) in enumerate(people):  # picture cycles: the pictures replace the room, the person stays in front
            item = items[k][2]
            if item.get("type") == "cycle":
                reel = work / f"cycle{k}.mp4"
                cycle_reel(reel, item["_images"], [t + offset for t in cycle_times(items[k][0], items[k][1], item.get("_beats") or [], float(item.get("every", 0.4)))], b, w, h)
                inputs += ["-itsoffset", f"{a:.3f}", "-i", str(reel)]
                ci = len(inputs_of(inputs)) - 1
                chain.append(f"[{label}][{ci}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[cg{k}]")
                label = f"cg{k}"
        for k, (a, b, person) in enumerate(people):
            if items[k][2].get("type") == "cycle":
                chain.append(f"[{label}][{k + 1}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[cp{k}]")
                label = f"cp{k}"
        if any(item.get("type", "behind") in ("behind", "poster") for _, _, item in items):
            chain.append(f"[{label}]ass={ass.name}:fontsdir=fonts[bt]")
            label = "bt"
            for k, (a, b, person) in enumerate(people):
                if items[k][2].get("type", "behind") in ("behind", "poster"):
                    chain.append(f"[{label}][{k + 1}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})':eof_action=pass[bh{k}]")
                    label = f"bh{k}"
                if items[k][2].get("type") == "poster":  # a paper border, like a printed poster
                    edge = max(4, round(min(w, h) * 0.025))
                    chain.append(f"[{label}]drawbox=x=0:y=0:w=iw:h=ih:color=white:t={edge}:enable='between(t,{a:.3f},{b:.3f})'[pf{k}]")
                    label = f"pf{k}"
        quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[{label}]", "-map", "0:a?", "-c:a", "copy", *quality, "-movflags", "+faststart", str(out)], cwd=work)
        base.unlink(missing_ok=True)
        if final:
            shutil.rmtree(work, ignore_errors=True)
    except BaseException:
        if not out.exists() and base.exists():
            base.replace(out)
        raise


def catalog_items(query: str | None = None) -> list[dict]:
    args = [*hyperframes_cmd(), "catalog", "--json"] + ([query] if query else [])
    proc = subprocess.run(args, env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace")
    try:
        return json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise Problem("HyperFrames' catalog didn't answer. Check the internet connection and try again.") from exc


def cmd_catalog(args) -> None:
    items = catalog_items(" ".join(args.words) if args.words else None)
    if args.type:
        items = [x for x in items if x.get("type") == args.type]
    shown = items[: args.limit]
    say(f"HyperFrames catalog: {len(items)} match{'es' if len(items) != 1 else ''}" + (f", first {len(shown)}" if len(items) > len(shown) else "") + ":")
    for x in shown:
        dims = x.get("dimensions") or {}
        size = f" {dims.get('width')}x{dims.get('height')}" if dims else ""
        say(f"  {x['name']} [{x['type']}{size}{', ' + str(round(x['duration'], 1)) + 's' if x.get('duration') else ''}] {x.get('description', '')[:110]}")
    say("Blocks go in a plan as {\"type\": \"block\", \"name\": \"<name>\", \"lines\": [a, b]}; components: `davnai.py catalog-get <name>`, then adapt it into a custom graphic (reference/motion.md).")


def cmd_catalog_get(args) -> None:
    target = MOTION_DIR / "catalog"
    target.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([*hyperframes_cmd(), "add", args.name, "--dir", str(target), "--json", "--no-clipboard", *(["--force"] if args.force else [])], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise Problem(f"Couldn't get '{args.name}' from the catalog:\n{(proc.stderr or proc.stdout).strip()[-400:]}") from exc
    if not info.get("ok"):
        raise Problem(f"Couldn't get '{args.name}': {info}")
    say(f"Got {args.name} ({info.get('type', '').replace('hyperframes:', '')}):", *(f"  {p}" for p in info.get("written", [])),
        "Copy it next to the plan, replace the sample names, logos and colours with the person's (never show another company's branding), "
        "then use it as {\"type\": \"block\", \"html\": \"<your copy>\", \"lines\": [a, b]} (a block) or adapt it into a custom graphic (a component).")


# ---------------------------------------------------------------- review page, style profile, matching a reel

STYLE_FILE = BRAND_DIR.parent / "style.json"
MARKS = ("change", "cut", "keep", "question")


def load_style() -> dict:
    try:
        return json.loads(STYLE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"preferences": {}, "notes": []}


def save_style(style: dict) -> None:
    STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STYLE_FILE.write_text(json.dumps(style, indent=1, ensure_ascii=False), encoding="utf-8")


def with_style(cfg: dict) -> dict:
    """The person's saved preferences sit under the plan (the plan always wins) and over the theme."""
    prefs = load_style().get("preferences") or {}
    return {**prefs, **cfg} if prefs else cfg


def cmd_style(args) -> None:
    style = load_style()
    changed = False
    for pair in args.set or []:
        if "=" not in pair:
            raise Problem("Use --set key=value, e.g. --set caption_words=3 or --set theme=bold.")
        key, raw = pair.split("=", 1)
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        style["preferences"][key.strip()] = value
        changed = True
    for key in args.unset or []:
        changed = style["preferences"].pop(key, None) is not None or changed
    if args.note:
        style["notes"] = (style.get("notes") or [])[-49:] + [f"{time.strftime('%Y-%m-%d')}: {args.note}"]
        changed = True
    if changed:
        save_style(style)
    prefs = style.get("preferences") or {}
    say("Their style (used for every video unless the plan says otherwise):",
        *(f"  {k}: {json.dumps(v)}" for k, v in prefs.items()) or ["  (nothing saved yet)"],
        *(["What they've said before:"] + [f"  - {n}" for n in (style.get("notes") or [])[-12:]] if style.get("notes") else []))


def output_digest(cfg: dict, plan: dict, plan_dir: Path, final: bool) -> str:
    """A fingerprint of everything that makes an output: its settings, the Brand Kit, its files and this script."""
    import hashlib

    parts = [VERSION, json.dumps(cfg, sort_keys=True), json.dumps(plan.get("theme"), sort_keys=True), str(final)]
    brand = BRAND_DIR / "brand.json"
    parts.append(str(brand.stat().st_mtime) if brand.exists() else "-")
    parts.append(json.dumps(load_style().get("preferences") or {}, sort_keys=True))
    for value in json.dumps(cfg).split('"'):
        if re.search(r"\.(mp4|mov|mkv|webm|mp3|wav|m4a|png|jpe?g|webp|html)$", value, re.I):
            p = Path(value).expanduser()
            p = p if p.is_absolute() else (plan_dir / p)
            parts.append(f"{value}:{p.stat().st_mtime if p.exists() else '-'}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def review_data(folder: Path, name: str, version: int, video: Path) -> dict:
    """What the review page shows: the transcript lines where they are in this version, and its scenes and graphics."""
    timing = json.loads((folder / f"{name}_v{version}.timing.json").read_text(encoding="utf-8"))
    cfg = json.loads((folder / f"{name}_v{version}.plan.json").read_text(encoding="utf-8"))
    texts = {}
    transcript = folder / "transcript.json"  # the .davnai folder belongs to the recording (or voice-over) being edited
    if transcript.exists():
        texts = {str(ln["id"]): " ".join(w[0] for w in ln["words"]) for ln in json.loads(transcript.read_text(encoding="utf-8"))["lines"]}
    lines = sorted(({"id": int(k), "start": v[0], "end": v[1], "text": texts.get(k, "")} for k, v in timing["lines"].items()), key=lambda x: x["start"])
    windows = timing["lines"]

    def span(rng):
        rng = [rng, rng] if isinstance(rng, int) else rng
        found = [windows[str(n)] for n in range(int(rng[0]), int(rng[1]) + 1) if str(n) in windows] if isinstance(rng, (list, tuple)) and len(rng) == 2 else []
        return (min(f[0] for f in found), max(f[1] for f in found)) if found else None

    scenes = []
    for k, item in enumerate(cfg.get("keep") or cfg.get("scenes") or []):
        if isinstance(item, dict) and "lines" in item:
            rng = item["lines"]
        elif isinstance(item, dict):
            rng = [(item.get("from") or [0])[0], (item.get("to") or [0])[0]]
        else:
            rng = item if isinstance(item, (list, tuple)) else [item, item]
        s = span(rng)
        if s:
            scenes.append({"label": f"Scene {k + 1}", "start": s[0], "end": s[1]})
    graphics = []
    for item in (cfg.get("motion") or []) + (cfg.get("fx") or []):
        s = span(item.get("lines")) if item.get("lines") is not None else None
        if item.get("at") == "start":
            s = (0, float(item.get("seconds", 3)))
        if s:
            graphics.append({"label": f"{item.get('type')}{': ' + str(item.get('text') or item.get('name') or '') if item.get('text') or item.get('name') else ''}", "start": s[0], "end": s[1]})
    return {"name": name, "version": version, "video": video.name, "duration": probe(video)["seconds"], "lines": lines, "scenes": scenes, "graphics": graphics}


REVIEW_PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Review __TITLE__</title><style>
body{font-family:system-ui,Arial,sans-serif;margin:0;background:#f4f4f7;color:#111}header{padding:14px 20px;background:#fff;border-bottom:1px solid #e5e5ea}
main{display:grid;grid-template-columns:minmax(260px,420px) 1fr;gap:18px;padding:18px 20px}@media(max-width:900px){main{grid-template-columns:1fr}}
video{width:100%;max-height:70vh;background:#000;border-radius:10px}.card{background:#fff;border-radius:12px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.06);margin-bottom:14px}
.lane{position:relative;height:26px;background:#eee;border-radius:6px;margin:6px 0 2px;cursor:pointer}.lane span{position:absolute;top:2px;bottom:2px;border-radius:4px;font-size:11px;color:#fff;overflow:hidden;white-space:nowrap;padding:3px 4px;box-sizing:border-box}
.scenes span{background:#5b4bdb}.gfx span{background:#e0662f}.marksl span{background:#111;width:3px!important;padding:0}.lab{font-size:12px;color:#666}#head{position:absolute;top:-2px;bottom:-2px;width:2px;background:#e11}
.lines{max-height:46vh;overflow:auto}.ln{padding:5px 6px;border-radius:6px;cursor:pointer;font-size:14px}.ln:hover{background:#f0f0f5}.ln.on{background:#ece9ff}.ln b{color:#888;font-weight:500;margin-right:6px}
.btns button{margin:4px 6px 4px 0;padding:8px 12px;border-radius:8px;border:1px solid #ccc;background:#fff;cursor:pointer;font-weight:600}.btns button.sel{background:#111;color:#fff;border-color:#111}
textarea{width:100%;box-sizing:border-box;border-radius:8px;border:1px solid #ccc;padding:8px;font:inherit}.primary{background:#5b4bdb!important;color:#fff!important;border-color:#5b4bdb!important}
.mark{display:flex;gap:8px;align-items:flex-start;font-size:14px;padding:6px 0;border-bottom:1px solid #eee}.mark .t{font-weight:700;min-width:84px}.mark button{margin-left:auto;border:none;background:none;color:#999;cursor:pointer}
#msg{font-size:13px;color:#2a7}</style></head><body>
<header><b>Review: __TITLE__</b> <span class="lab">Pause where something should change, pick a mark, write a note, press Add. Press Done when you've finished.</span></header>
<main><div><video id="v" controls playsinline src="__VIDEO__"></video>
<div class="card"><div class="lab">Scenes</div><div class="lane scenes" id="ls"></div><div class="lab">Graphics and effects</div><div class="lane gfx" id="lg"></div><div class="lab">Your marks</div><div class="lane marksl" id="lm"><div id="head"></div></div></div></div>
<div><div class="card"><div class="btns" id="kinds"></div><textarea id="note" rows="2" placeholder="What should change here? (e.g. cut this, bigger captions, use a different clip)"></textarea>
<div class="btns"><button class="primary" id="add">Add mark at <span id="now">0:00</span></button><button id="general">Add a note for the whole video</button></div></div>
<div class="card"><b>Marks</b><div id="marks"></div><div class="btns"><button class="primary" id="done">Done: send to the AI</button><button id="copy">Copy notes</button><button id="dl">Download notes</button></div><div id="msg"></div></div>
<div class="card"><b>What's said</b> <span class="lab">(click a line to jump)</span><div class="lines" id="lines"></div></div></div></main>
<script>
const D=__DATA__;const v=document.getElementById('v');let kind='change';let marks=[];
const fmt=t=>Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0');
const lineAt=t=>{let best=null;for(const l of D.lines){if(t>=l.start-0.2&&t<=l.end+0.3)return l;if(!best||Math.abs(l.start-t)<Math.abs(best.start-t))best=l;}return best;};
function lane(id,items){const el=document.getElementById(id);items.forEach(it=>{const s=document.createElement('span');s.style.left=(it.start/D.duration*100)+'%';s.style.width=Math.max(.6,(it.end-it.start)/D.duration*100)+'%';s.textContent=it.label||'';s.title=it.label||'';s.onclick=e=>{e.stopPropagation();v.currentTime=it.start;};el.appendChild(s);});el.onclick=e=>{const r=el.getBoundingClientRect();v.currentTime=(e.clientX-r.left)/r.width*D.duration;};}
lane('ls',D.scenes);lane('lg',D.graphics);
const kinds={change:'Change',cut:'Cut',keep:'Keep',question:'Question'};const kb=document.getElementById('kinds');
Object.entries(kinds).forEach(([k,l])=>{const b=document.createElement('button');b.textContent=l;b.onclick=()=>{kind=k;[...kb.children].forEach(c=>c.classList.toggle('sel',c===b));};if(k===kind)b.classList.add('sel');kb.appendChild(b);});
const L=document.getElementById('lines');D.lines.forEach(l=>{const d=document.createElement('div');d.className='ln';d.dataset.id=l.id;d.innerHTML='<b>'+fmt(l.start)+' · #'+l.id+'</b>';d.appendChild(document.createTextNode(l.text));d.onclick=()=>{v.currentTime=l.start;v.play();};L.appendChild(d);});
v.ontimeupdate=()=>{document.getElementById('now').textContent=fmt(v.currentTime);document.getElementById('head').style.left=(v.currentTime/D.duration*100)+'%';const l=lineAt(v.currentTime);document.querySelectorAll('.ln').forEach(x=>x.classList.toggle('on',l&&x.dataset.id==l.id));};
function draw(){const m=document.getElementById('marks');m.innerHTML='';const lm=document.getElementById('lm');lm.querySelectorAll('span').forEach(s=>s.remove());
marks.forEach((k,i)=>{const r=document.createElement('div');r.className='mark';r.innerHTML='<span class="t">'+(k.time==null?'Whole video':fmt(k.time)+' #'+k.line)+'</span>';const t=document.createElement('span');t.textContent='['+kinds[k.kind]+'] '+k.note;r.appendChild(t);const x=document.createElement('button');x.textContent='✕';x.onclick=()=>{marks.splice(i,1);draw();save();};r.appendChild(x);m.appendChild(r);
if(k.time!=null){const s=document.createElement('span');s.style.left=(k.time/D.duration*100)+'%';s.title=k.note;lm.appendChild(s);}});}
function add(whole){const note=document.getElementById('note').value.trim();if(!note&&kind!=='cut'&&kind!=='keep'){document.getElementById('note').focus();return;}const t=v.currentTime;const l=whole?null:lineAt(t);
marks.push({kind,time:whole?null:Math.round(t*10)/10,line:l?l.id:null,said:l?l.text:null,note});document.getElementById('note').value='';draw();save();}
document.getElementById('add').onclick=()=>add(false);document.getElementById('general').onclick=()=>add(true);
const text=()=>'Review notes for '+D.name+' v'+D.version+':\n'+marks.map(k=>'- ['+k.kind+'] '+(k.time==null?'whole video':fmt(k.time)+' line '+k.line+(k.said?' ("'+k.said.slice(0,60)+'")':''))+': '+(k.note||'(no note)')).join('\n');
const payload=()=>JSON.stringify({name:D.name,version:D.version,marks});
async function save(done){try{const r=await fetch(done?'/done':'/notes',{method:'POST',body:payload()});document.getElementById('msg').textContent=r.ok?(done?'Sent. You can close this page and go back to the chat.':'Saved'):'';}catch(e){document.getElementById('msg').textContent=done?'Not connected: press Copy notes and paste them into the chat.':'';}}
document.getElementById('done').onclick=()=>save(true);
document.getElementById('copy').onclick=async()=>{try{await navigator.clipboard.writeText(text());document.getElementById('msg').textContent='Copied: paste them into the chat.';}catch(e){prompt('Copy these notes:',text());}};
document.getElementById('dl').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([payload()],{type:'application/json'}));a.download=D.name+'_v'+D.version+'_notes.json';a.click();};
fetch('/notes').then(r=>r.ok?r.json():null).then(j=>{if(j&&j.marks){marks=j.marks;draw();}}).catch(()=>{});
</script></body></html>"""


def notes_text(notes: dict) -> list[str]:
    out = [f"Review notes for {notes.get('name')} v{notes.get('version')} ({len(notes.get('marks') or [])} marks):"]
    for m in notes.get("marks") or []:
        where = "whole video" if m.get("time") is None else f"{int(m['time'] // 60)}:{int(m['time'] % 60):02d} line {m.get('line')}" + (f" (\"{(m.get('said') or '')[:60]}\")" if m.get("said") else "")
        out.append(f"  - [{m.get('kind')}] {where}: {m.get('note') or '(no note)'}")
    out.append("Change the plan by line numbers, render a new version, and save any lasting preference with `davnai.py style`.")
    return out


def cmd_review(args) -> None:
    import http.server
    import threading
    import webbrowser

    plan_path = Path(args.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    outputs = [o for o in plan.get("outputs", []) if not args.only or o.get("name") in args.only]
    if not outputs:
        raise Problem("No output to review.")
    cfg = outputs[0]
    name = re.sub(r"[^\w\-]", "_", cfg.get("name") or "video")
    anchor = Path(cfg.get("voice") or cfg.get("source") or plan.get("source") or plan_path.name)
    anchor = anchor if anchor.is_absolute() else (plan_path.parent / anchor)
    folder = plan_path.parent if plan_path.parent.name.endswith(".davnai") else workdir(anchor.resolve())
    version = args.version or max(1, next_version(folder, name) - 1)
    video = folder / f"{name}_v{version}_preview.mp4"
    if not video.exists():
        raise Problem(f"There's no preview v{version} of {name} yet. Render it first.")
    data = review_data(folder, name, version, video)
    page = folder / f"{name}_v{version}_review.html"
    page.write_text(REVIEW_PAGE.replace("__TITLE__", esc(f"{name} v{version}")).replace("__VIDEO__", esc(video.name)).replace("__DATA__", json.dumps(data).replace("</", "<\\/")), encoding="utf-8")
    notes_file = folder / f"{name}_v{version}_notes.json"
    finished = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", kind="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", f"/{page.name}"):
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if path == "/notes":
                return self._send(200, notes_file.read_bytes()) if notes_file.exists() else self._send(404)
            if path == f"/{video.name}":  # with Range support so the player can jump around
                size = video.stat().st_size
                rng = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
                start, end = (int(rng.group(1) or 0), int(rng.group(2) or size - 1)) if rng else (0, size - 1)
                end = min(end, size - 1)
                with video.open("rb") as f:
                    f.seek(start)
                    body = f.read(end - start + 1)
                return self._send(206 if rng else 200, body, "video/mp4", {"Accept-Ranges": "bytes", **({"Content-Range": f"bytes {start}-{end}/{size}"} if rng else {})})
            return self._send(404)

        do_HEAD = do_GET

        def do_POST(self):
            body = self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 1_000_000))
            try:
                notes = json.loads(body)
                assert isinstance(notes.get("marks"), list)
            except Exception:  # noqa: BLE001
                return self._send(400)
            notes_file.write_text(json.dumps(notes, indent=1, ensure_ascii=False), encoding="utf-8")
            self._send(200, b"{}")
            if self.path == "/done":
                finished.set()

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    say(f"Review page: {url} (also saved as {page})", "Opening it for the person. Waiting until they press Done (up to {} minutes)...".format(args.wait))
    if not args.no_browser:
        webbrowser.open(url)
    finished.wait(timeout=args.wait * 60)
    server.shutdown()
    if notes_file.exists():
        say(*notes_text(json.loads(notes_file.read_text(encoding="utf-8"))))
    else:
        say("No notes yet. If the person copied them, they'll paste them into the chat; `davnai.py notes` shows saved ones later.")


def cmd_notes(args) -> None:
    folder = Path(args.folder).expanduser().resolve()
    files = sorted(folder.glob("*_notes.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise Problem(f"No review notes in {folder}.")
    say(*notes_text(json.loads(files[-1].read_text(encoding="utf-8"))))


def cmd_match(args) -> None:
    """Reads a reel the person likes (pace, colour, loudness, shape) and suggests settings to match it."""
    need("ffmpeg")
    ref = Path(args.video).expanduser().resolve()
    info = probe(ref)
    log = measure(ref, "select='gt(scene,0.32)',showinfo")
    cuts = len(re.findall(r"pts_time:", log))
    per_min = cuts / max(info["seconds"] / 60, 0.01)
    stats = measure(ref, "fps=2,signalstats,metadata=print")
    mean = lambda key: (lambda xs: sum(xs) / len(xs) if xs else 0)([float(x) for x in re.findall(rf"lavfi\.signalstats\.{key}=([\d.]+)", stats)])  # noqa: E731
    bright, sat, hue_u, hue_v = mean("YAVG"), mean("SATAVG"), mean("UAVG"), mean("VAVG")
    loud = re.findall(r"I:\s+(-?[\d.]+) LUFS", measure(ref, "a:ebur128").split("Summary:")[-1]) if info["audio"] else []
    warm = hue_v - hue_u
    look = "bw" if sat < 6 else "vivid" if sat > 55 else "warm" if warm > 8 else "cool" if warm < -8 else "cinematic" if bright < 85 else "soft"
    theme = "bold" if per_min > 28 else "minimal" if per_min < 6 else "editorial" if bright < 90 and sat < 40 else "clean"
    suggestions = {"theme": theme, "look": look, "transition": "cut" if per_min > 20 else "dissolve", "tighten": per_min > 10, "auto_zoom": per_min > 18, "aspect": "9:16" if info["height"] > info["width"] else "16:9" if info["width"] > info["height"] else "1:1"}
    sheet = ref.with_name(ref.stem + "_match.jpg")
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(ref), "-vf", f"fps={6 / max(info['seconds'], 1):.4f},scale=240:-2,tile=6x1", "-frames:v", "1", str(sheet)])
    say(f"{ref.name}: {info['seconds']:.0f}s, {info['width']}x{info['height']}, about {per_min:.0f} cuts a minute (a shot every {60 / max(per_min, 0.1):.1f}s)"
        + (f", loudness {float(loud[-1]):.1f} LUFS" if loud else "") + f", brightness {bright:.0f}/255, colour {sat:.0f} ({'warm' if warm > 8 else 'cool' if warm < -8 else 'neutral'}).",
        f"Suggested settings: {json.dumps(suggestions)}",
        f"Six stills: {sheet} — look at them for the caption font, size, colours and position, then set the theme's \"caption\" to match (reference/themes.md).",
        "Save it for every video with: davnai.py style --set theme=... --set look=... --note \"matches <reel>\"")


# ---------------------------------------------------------------- storyboard


def scene_list(cfg: dict, plan: dict, plan_dir: Path) -> tuple[list[dict], float]:
    """The output's scenes (keep parts, or faceless scenes) with what's said and what happens on screen."""
    def resolve(p: str) -> Path:
        q = Path(str(p)).expanduser()
        return q if q.is_absolute() else (plan_dir / q).resolve()

    def happens(first: int, last: int) -> list[str]:
        notes = []
        inside = lambda rng: isinstance(rng, (list, tuple)) and len(rng) == 2 and int(rng[0]) <= last and int(rng[1]) >= first  # noqa: E731
        for z in cfg.get("zoom") or []:
            if inside(z.get("lines")):
                notes.append(f"zoom {z.get('style', 'punch')}")
        for b in cfg.get("broll") or []:
            if inside(b.get("lines")):
                notes.append(f"{b.get('mode', 'B-roll')}: {Path(str(b.get('clip', ''))).name}")
        for t in cfg.get("texts") or []:
            if inside(t.get("lines")):
                notes.append(f"text \"{t.get('text', '')}\"")
        for m in cfg.get("motion") or []:
            rng = m.get("lines")
            rng = [rng, rng] if isinstance(rng, int) else rng
            if inside(rng):
                notes.append(f"{m.get('type')}: {m.get('text') or m.get('name') or m.get('title') or ''}".rstrip(": "))
        for fx in cfg.get("fx") or []:
            rng = fx.get("lines")
            rng = [rng, rng] if isinstance(rng, int) else rng
            if inside(rng):
                notes.append(f"{fx.get('type')}" + (f" \"{fx['text']}\"" if fx.get("text") else ""))
        for s in cfg.get("sfx") or []:
            if s.get("line") is not None and first <= int(s["line"]) <= last:
                notes.append(f"sound: {Path(str(s.get('file', ''))).name}")
        return notes

    scenes = []
    if cfg.get("scenes"):
        voice = resolve(cfg.get("voice") or "")
        lines = load_transcript(voice)["lines"]
        for k, sc in enumerate(cfg["scenes"]):
            a, b = int(sc["lines"][0]), int(sc["lines"][1])
            said = " ".join(w[0] for n in range(a, b + 1) for w in line_by_id(lines, n)["words"])
            clip = resolve(sc.get("clip") or "")
            scenes.append({"n": k + 1, "lines": f"{a}-{b}", "seconds": line_by_id(lines, b)["end"] - line_by_id(lines, a)["start"], "said": said, "picture": clip, "at": float(sc.get("start", 0)), "notes": [f"clip: {clip.name}", *happens(a, b)]})
        return scenes, probe(voice)["seconds"]
    source = resolve(cfg.get("source") or plan.get("source") or "")
    info = probe(source)
    lines = load_transcript(source)["lines"]
    src_words = [[w[0], w[1], w[2], ln["id"]] for ln in lines for w in ln["words"]]
    pieces = []
    for g, item in enumerate(cfg.get("keep") or []):
        spans = keep_spans(lines, [item], info["seconds"])
        if cfg.get("tighten"):
            spans = tighten(spans, src_words)
        pieces += [{"s": s, "e": e, "group": g} for s, e in spans]
    timeline = Timeline(pieces, cfg.get("transition"), min(2.0, max(0.5, float(cfg.get("speed", 1.0)))))
    for k, group in enumerate(timeline.groups):
        ids = sorted({w[3] for w in src_words if any(p["s"] <= (w[1] + w[2]) / 2 <= p["e"] for p in group)})
        if not ids:
            continue
        said = " ".join(w[0] for w in src_words if any(p["s"] <= (w[1] + w[2]) / 2 <= p["e"] for p in group))
        first = line_by_id(lines, ids[0])
        scenes.append({"n": k + 1, "lines": f"{ids[0]}-{ids[-1]}", "seconds": timeline.lengths[k], "said": said, "picture": source, "at": (first["start"] + first["end"]) / 2, "notes": happens(ids[0], ids[-1])})
    return scenes, timeline.duration


def still_b64(path: Path, at: float) -> str:
    if path.suffix.lower() in IMAGE_EXT:
        args = ["-i", str(path)]
    else:
        args = ["-ss", f"{max(0.0, at):.3f}", "-i", str(path)]
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5", "-f", "image2", "-c:v", "mjpeg", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return base64.b64encode(proc.stdout).decode() if proc.returncode == 0 and proc.stdout else ""


def cmd_storyboard(args) -> None:
    need("ffmpeg")
    plan_path = Path(args.plan).expanduser().resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    outputs = [o for o in plan.get("outputs", []) if not args.only or o.get("name") in args.only]
    if not outputs:
        raise Problem("The plan has no outputs to storyboard.")
    cards_html, text = [], []
    for cfg in outputs:
        name = cfg.get("name") or "video"
        scenes, total = scene_list(cfg, plan, plan_path.parent)
        theme = cfg.get("theme") or plan.get("theme")
        extras = ([f"theme {theme if isinstance(theme, str) else theme.get('base', 'custom') + ' (custom)'}"] if theme else []) + [x for x in ("hook_text", "captions", "auto_zoom", "progress_bar", "end_card", "music", "intro", "outro", "logo") if cfg.get(x)]
        text.append(f"Storyboard: {name} ({cfg.get('aspect', '9:16')}, about {total:.0f}s){' · ' + ', '.join(extras) if extras else ''}")
        if cfg.get("hook_text"):
            text.append(f"  Opens with: \"{cfg['hook_text']}\"")
        if cfg.get("transition"):
            text.append(f"  Between scenes: {cfg['transition']}")
        cards = []
        for sc in scenes:
            said = sc["said"] if len(sc["said"]) <= 140 else sc["said"][:137] + "..."
            notes = "; ".join(sc["notes"])
            text.append(f"  {sc['n']}. lines {sc['lines']} ({sc['seconds']:.1f}s): \"{said}\"" + (f" [{notes}]" if notes else ""))
            img = still_b64(sc["picture"], sc["at"]) if sc["picture"].exists() else ""
            img_html = '<img src="data:image/jpeg;base64,' + img + '">' if img else ""
            notes_html = '<div class="notes">' + esc(notes) + "</div>" if notes else ""
            cards.append(f'<div class="card">{img_html}<div class="meta"><b>{sc["n"]}</b> · lines {esc(sc["lines"])} · {sc["seconds"]:.1f}s</div>'
                         f'<div class="said">“{esc(said)}”</div>{notes_html}</div>')
        cards_html.append(f'<h2>{esc(name)} <span>{esc(cfg.get("aspect", "9:16"))} · about {total:.0f}s{(" · " + esc(", ".join(extras))) if extras else ""}</span></h2>'
                          + (f'<p class="hook">Opens with: “{esc(cfg["hook_text"])}”</p>' if cfg.get("hook_text") else "") + f'<div class="grid">{"".join(cards)}</div>')
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Storyboard</title><style>
body{{font-family:system-ui,Arial,sans-serif;margin:24px;background:#f6f6f8;color:#111}}h1{{margin:0 0 8px}}h2{{margin:28px 0 8px}}h2 span{{font-weight:400;color:#666;font-size:14px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}}.card{{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.card img{{width:100%;display:block;background:#000;aspect-ratio:16/9;object-fit:cover}}.meta{{padding:8px 10px 0;font-size:13px;color:#444}}.said{{padding:4px 10px;font-size:14px}}
.notes{{padding:0 10px 10px;font-size:12px;color:#5b4bdb}}.hook{{color:#5b4bdb}}</style></head><body><h1>Storyboard</h1><p>Check the order and what happens in each scene before the preview is made.</p>{''.join(cards_html)}</body></html>"""
    out = plan_path.with_name(plan_path.stem + "_storyboard.html")
    out.write_text(page, encoding="utf-8")
    say(*text, f"Picture storyboard: {out}", "Show the person this list (and the page), and change the plan until they approve it. Then render.")


# ---------------------------------------------------------------- setup and voice


def node_major() -> int:
    node = shutil.which("node")
    if not node:
        return 0
    out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace").stdout
    m = re.match(r"v(\d+)", out.strip())
    return int(m.group(1)) if m else 0


def install_hint(tool: str) -> list[str] | None:
    """The command that installs a tool on this computer (Windows winget, Mac Homebrew), or None to install by hand."""
    if sys.platform == "win32" and shutil.which("winget"):
        ids = {"ffmpeg": "Gyan.FFmpeg", "node": "OpenJS.NodeJS.LTS"}
        return ["winget", "install", "-e", "--id", ids[tool], "--accept-source-agreements", "--accept-package-agreements"]
    if sys.platform == "darwin" and shutil.which("brew"):
        return ["brew", "install", {"ffmpeg": "ffmpeg", "node": "node"}[tool]]
    return None


def ask(question: str, yes: bool) -> bool:
    if yes:
        return True
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def cmd_setup(args) -> None:
    lines, restart = [], False
    pip = [sys.executable, "-m", "pip", "install", "--user", "--quiet", "faster-whisper", "fonttools", "brotli", "opencv-python-headless", "numpy", "pillow", "mediapipe"]
    say("Installing the Python parts (speech-to-text, brand fonts, face tracking and cut-out)...")
    proc = subprocess.run(pip, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 and "externally-managed" in (proc.stderr or ""):
        proc = subprocess.run([*pip, "--break-system-packages"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    lines.append("✓ Python parts" if proc.returncode == 0 else f"✗ Python parts: {(proc.stderr or '').strip().splitlines()[-1:]}")
    needed = ["ffmpeg"] + (["node"] if args.motion and node_major() < 22 else [])
    for tool in needed:
        if tool == "ffmpeg" and shutil.which("ffmpeg") and shutil.which("ffprobe"):
            lines.append("✓ ffmpeg")
            continue
        hint = install_hint(tool)
        label = "Node.js 22 or newer" if tool == "node" else "ffmpeg"
        if hint and ask(f"Install {label} with: {' '.join(hint)}?", args.yes):
            ok = subprocess.run(hint).returncode == 0
            find_new_installs()
            restart = restart or (ok and sys.platform == "win32" and not shutil.which("ffmpeg" if tool == "ffmpeg" else "node"))
            lines.append(f"✓ {label} installed" if ok else f"✗ {label} didn't install. Try: {' '.join(hint)}")
        elif not hint:
            lines.append(f"✗ {label}: install it from {'https://nodejs.org' if tool == 'node' else 'https://ffmpeg.org/download.html'} (Linux: sudo apt install {'nodejs' if tool == 'node' else 'ffmpeg'})")
        else:
            lines.append(f"· {label} skipped")
    if shutil.which("ffmpeg"):
        fonts = ensure_fonts(FONT_SOURCES)
        made = [n for n in SOUND_RECIPES if sound_file(n)]
        lines.append(f"✓ theme fonts ({len(fonts)}/{len(FONT_SOURCES)}) and built-in sounds ({len(made)})")
    models = ensure_models()
    lines.append(f"✓ face and cut-out models ({len(models)}/{len(MODEL_FILES)})" if len(models) == len(MODEL_FILES) else "✗ face and cut-out models didn't download; run setup again")
    if importlib.util.find_spec("mediapipe") is None:
        lines.append("· studio effects: MediaPipe didn't install for this Python (it supports Python 3.9 to 3.13). Install Python 3.12 and run setup with it.")
    if args.motion:
        npm = shutil.which("npm")
        if node_major() >= 22 and npm:
            MOTION_DIR.mkdir(parents=True, exist_ok=True)
            say("Installing HyperFrames and GSAP for motion graphics...")
            ok = subprocess.run([npm, "install", "--prefix", str(MOTION_DIR), "hyperframes@~0.9", "gsap@^3", "--no-audit", "--no-fund", "--silent"], env={**os.environ, **NO_TRACKING}).returncode == 0
            if ok:
                say("Getting the browser HyperFrames renders with (once)...")
                ok = subprocess.run([*hyperframes_cmd(), "browser", "ensure"], env={**os.environ, **NO_TRACKING}, stdout=subprocess.DEVNULL).returncode == 0
            lines.append("✓ motion graphics (HyperFrames)" if ok else "✗ motion graphics: HyperFrames didn't install; run setup --motion again")
        elif restart:
            lines.append("· Node.js was just installed: open a new terminal and run setup --motion again to finish")
        else:
            lines.append("✗ motion graphics need Node.js 22 or newer first")
    say(*lines)
    if restart:
        say("Windows only finds newly installed programs in a new terminal: close this one and run `python davnai.py check` in a new one.")


def cmd_voice(args) -> None:
    """A voice-over made on this computer with HyperFrames' free Kokoro voices (for faceless videos)."""
    out = Path(args.output).expanduser().resolve()
    text_arg = ["--text-file", str(Path(args.text).expanduser().resolve())] if Path(args.text).expanduser().exists() else [args.text]
    proc = subprocess.run([*hyperframes_cmd(), "tts", *text_arg, "-o", str(out), "-v", args.voice, "-s", str(args.speed)], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not out.exists():
        raise Problem("The voice wasn't made:\n" + "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-6:]))
    say(f"Voice-over saved: {out} ({probe(out)['seconds']:.1f}s). Next: davnai.py transcribe \"{out}\"")


def cmd_render(args) -> None:
    need("ffmpeg")
    plan_path = Path(args.plan).expanduser().resolve()
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Problem(f"Can't find {plan_path}.") from exc
    except json.JSONDecodeError as exc:
        raise Problem(f"{plan_path.name} isn't valid JSON: {exc}") from exc
    outputs = [o for o in plan.get("outputs", []) if not args.only or o.get("name") in args.only]
    if not outputs:
        raise Problem("The plan has no outputs" + (f" named {', '.join(args.only)}." if args.only else "."))
    brand = load_brand()
    made = []
    for cfg in outputs:
        anchor = Path(cfg.get("voice") or cfg.get("source") or plan.get("source") or plan_path.name)
        anchor = anchor if anchor.is_absolute() else (plan_path.parent / anchor)
        folder = plan_path.parent if plan_path.parent.name.endswith(".davnai") else workdir(anchor.resolve())
        name = re.sub(r"[^\w\-]", "_", cfg.get("name") or "video")
        if args.from_version:
            snap = folder / f"{name}_v{args.from_version}.plan.json"
            if not snap.exists():
                raise Problem(f"There's no version {args.from_version} of {name}.")
            cfg = json.loads(snap.read_text(encoding="utf-8"))
        cfg = with_style(cfg)
        digest = output_digest(cfg, plan, plan_path.parent, args.final)
        last = max(1, next_version(folder, name) - 1)
        last_digest = folder / f"{name}_v{last}{'_final' if args.final else ''}.digest"
        if not args.force and last_digest.exists() and last_digest.read_text().strip() == digest:
            made.append(f"{name}: unchanged since v{last}, kept (use --force to make it again)")
            continue
        version = next_version(folder, name) if not args.final else last
        if not args.final:
            (folder / f"{name}_v{version}.plan.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        start = time.time()
        out, checks = render_output(plan_path.parent, cfg, plan, brand, args.final, version, folder)
        (folder / f"{name}_v{version}{'_final' if args.final else ''}.digest").write_text(digest)
        info = probe(out)
        made.append(f"{'Final' if args.final else f'Preview v{version}'} of {name}: {out} ({info['seconds']:.1f}s, {info['width']}x{info['height']}, made in {time.time() - start:.0f}s)")
        made += [f"  {c}" for c in checks]
    say(*made)
    if not args.final:
        say("Fix anything marked ⚠ first (or tell the person why it's fine). Then ask them to watch it and say what to change. Make the final only when they say it's the one (--final).")


# ---------------------------------------------------------------- frame


def cmd_frame(args) -> None:
    need("ffmpeg")
    source = Path(args.video).expanduser().resolve()
    lines = load_transcript(source)["lines"]
    line = line_by_id(lines, args.line)
    at = (line["start"] + line["end"]) / 2
    out = workdir(source) / f"frame-line-{line['id']}.jpg"
    run(["ffmpeg", "-hide_banner", "-y", "-ss", f"{at:.3f}", "-i", str(source), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(out)])
    say(str(out))


# ---------------------------------------------------------------- probe and upload


def cmd_probe(args) -> None:
    info = probe(Path(args.file).expanduser().resolve())
    say(json.dumps({"filename": info["file"], "size": info["bytes"], "duration_seconds": info["seconds"], "width": info["width"], "height": info["height"]}))


MUSIC_DIR = BRAND_DIR.parent / "music"


def cmd_music(args) -> None:
    """Downloads a music track (from Davnai's get_music_file link) to ~/.davnai/music and prints the file to use."""
    url = str(args.url)
    if not url.startswith("https://"):
        raise Problem("Give the music_url from Davnai's get_music_file (it starts with https://).")
    code, _headers, data = http(url, timeout=120)
    if code != 200 or len(data) < 1000:
        raise Problem("Couldn't download that track (the link lasts an hour: ask Davnai's get_music_file again).")
    ext = next((e for e in (".mp3", ".m4a", ".wav", ".aac", ".ogg") if e in url.split("?")[0].lower()), ".mp3")
    name = re.sub(r"[^\w-]+", "-", args.name or "track").strip("-").lower() or "track"
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    path = MUSIC_DIR / f"{name}{ext}"
    path.write_bytes(data)
    seconds = probe(path)["seconds"]
    say(f"Saved {path} ({seconds:.0f}s). In the plan: \"music\": \"{path.as_posix()}\" (it dips under the voice by itself; it loops if the video is longer).")


def pace_numbers(changes: list[float], seconds: float, words: list[list]) -> dict:
    """How busy a video is: visual changes per second, the longest stretch with nothing changing, words per second
    and when the first word lands (pure)."""
    marks = [0.0] + sorted(t for t in changes if 0 < t < seconds) + [seconds]
    still = max((b - a for a, b in zip(marks, marks[1:])), default=seconds)
    talk = [w for w in words if w[2] > w[1]]
    span = (talk[-1][2] - talk[0][1]) if talk else 0.0
    return {"seconds": round(seconds, 1), "visual_changes": len(marks) - 2, "changes_per_second": round((len(marks) - 2) / max(seconds, 0.1), 2),
            "longest_still_seconds": round(still, 1), "words_per_second": round(len(talk) / span, 2) if span > 0 else None,
            "first_word_seconds": round(talk[0][1], 2) if talk else None}


def cmd_pace(args) -> None:
    """Measures the pace of a video (yours or a reference): changes on screen and talking speed."""
    path = Path(args.file).expanduser().resolve()
    info = probe(path)
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vf", f"scale=180:-2,select='gt(scene,{args.threshold})',showinfo", "-an", "-f", "null", "-"],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    changes = [float(x) for x in re.findall(r"pts_time:([\d.]+)", proc.stderr)]
    words = []
    if transcript_path(path).exists():
        words = [wd for ln in load_transcript(path)["lines"] for wd in ln["words"]]
    nums = pace_numbers(changes, info["seconds"], words)
    say(json.dumps(nums),
        f"{nums['visual_changes']} visual changes in {nums['seconds']}s ({nums['changes_per_second']} a second); longest stretch with nothing changing: {nums['longest_still_seconds']}s."
        + (f" Talking speed {nums['words_per_second']} words a second; first word at {nums['first_word_seconds']}s." if nums["words_per_second"] else " (Transcribe it to also get the talking speed.)"),
        "Short-form that holds attention usually changes something every 1 to 2 seconds and never sits still much over 3 seconds. "
        "Graphics that move inside the picture (titles, counters) count less than cuts and scene changes; for those, step through frames.")


def read_ticket(ticket: str) -> dict:
    try:
        raw = ticket.strip()
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        assert all(k in data for k in ("v", "p", "s", "n", "b", "u"))
        return data
    except Exception as exc:  # noqa: BLE001
        raise Problem("That ticket isn't right. Copy it exactly from upload_from_computer.") from exc


def cmd_upload(args) -> None:
    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise Problem(f"Can't find {path}.")
    t = read_ticket(args.ticket)
    size = path.stat().st_size
    if size != int(t["b"]):
        raise Problem(f"This file is {size:,} bytes but the ticket is for {int(t['b']):,}. Run probe on the final again and call upload_from_computer with its size.")
    base = f"{t['u'].rstrip('/')}/api/uploads/chat/{t['v']}"
    auth = {"Authorization": f"Bearer {t['p']}"}
    part_size, count = int(t["s"]), int(t["n"])
    done = [0]

    def send(n: int) -> dict:
        with path.open("rb") as f:
            f.seek((n - 1) * part_size)
            body = f.read(part_size)
        for attempt in range(5):
            try:
                status, headers, data = http(f"{base}/parts/{n}", "PUT", body, {**auth, "Content-Type": "application/octet-stream"}, timeout=300)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                status, data = 0, b""
            if status == 200:
                done[0] += 1
                if count > 4 and done[0] % max(1, count // 4) == 0:
                    print(f"  {done[0]}/{count} parts sent", flush=True)
                return {"part_number": n, "etag": json.loads(data.decode("utf-8"))["etag"]}
            if status in (400, 401, 404, 409):
                raise Problem(json_error(data) or f"Davnai refused part {n} ({status}).")
            time.sleep(2 ** attempt)
        raise Problem(f"Part {n} didn't go through after 5 tries. Check the internet connection and run upload again with a new ticket.")

    say(f"Uploading {path.name} ({size / 1048576:.1f} MB) to Davnai...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        parts = sorted(pool.map(send, range(1, count + 1)), key=lambda p: p["part_number"])
    status, _, data = http(f"{base}/complete", "POST", json.dumps({"parts": parts}).encode("utf-8"), {**auth, "Content-Type": "application/json"})
    if status != 200:
        raise Problem(json_error(data) or f"Davnai couldn't finish the upload ({status}).")
    say(f"Uploaded. Video id: {t['v']}", "Davnai is reading it now. Post it with create_posts and this video id.")


# ---------------------------------------------------------------- main


def find_new_installs() -> None:
    """Windows: programs installed a moment ago (winget, Node.js) aren't on this terminal's PATH until it's reopened,
    so look in the usual places and add what's there."""
    if sys.platform != "win32":
        return
    local, prog = os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", r"C:\Program Files")
    places = [Path(local) / "Microsoft" / "WinGet" / "Links", Path(prog) / "nodejs"]
    places += sorted((Path(local) / "Microsoft" / "WinGet" / "Packages").glob("Gyan.FFmpeg*/*/bin")) if local else []
    have = os.environ.get("PATH", "").split(os.pathsep)
    extra = [str(p) for p in places if p.is_dir() and str(p) not in have]
    if extra:
        os.environ["PATH"] = os.pathsep.join(have + extra)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows terminals: ✓ and ⚠ must never crash the script
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    find_new_installs()
    parser = argparse.ArgumentParser(prog="davnai.py", description="Davnai video editing on your own computer.")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="what's installed").set_defaults(fn=cmd_check)
    p = sub.add_parser("brand", help="save the Brand Kit from Davnai")
    p.add_argument("url")
    p.set_defaults(fn=cmd_brand)
    p = sub.add_parser("transcribe", help="numbered transcript lines")
    p.add_argument("video")
    p.add_argument("--model", default="base", help="base (quick) or small (more accurate)")
    p.add_argument("--language", default=None, help="e.g. en; leave out to detect")
    p.add_argument("--again", action="store_true", help="transcribe again even if a transcript exists")
    p.add_argument("--lines", help="show only these lines, e.g. 1-200 (long videos)")
    p.set_defaults(fn=cmd_transcribe)
    p = sub.add_parser("frame", help="one still from a transcript line")
    p.add_argument("video")
    p.add_argument("--line", required=True, type=int)
    p.set_defaults(fn=cmd_frame)
    p = sub.add_parser("render", help="make previews, or the final with --final")
    p.add_argument("plan")
    p.add_argument("--final", action="store_true")
    p.add_argument("--only", nargs="*", help="only these output names")
    p.add_argument("--from-version", type=int, help="render an earlier version's plan again")
    p.add_argument("--force", action="store_true", help="make outputs again even if nothing changed")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("storyboard", help="the scene list and a picture page to approve before rendering")
    p.add_argument("plan")
    p.add_argument("--only", nargs="*", help="only these output names")
    p.set_defaults(fn=cmd_storyboard)
    p = sub.add_parser("setup", help="install what's missing (asks first unless --yes)")
    p.add_argument("--motion", action="store_true", help="also Node.js, HyperFrames and GSAP for motion graphics")
    p.add_argument("--yes", action="store_true", help="don't ask (the person already said yes)")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("voice", help="a free voice-over made on this computer (needs setup --motion)")
    p.add_argument("text", help="the words, or a .txt file")
    p.add_argument("-o", "--output", default="voiceover.wav")
    p.add_argument("--voice", default="af_heart", help="e.g. af_heart, am_michael, bf_emma, bm_george")
    p.add_argument("--speed", type=float, default=1.0)
    p.set_defaults(fn=cmd_voice)
    sub.add_parser("themes", help="the built-in themes").set_defaults(fn=cmd_themes)
    p = sub.add_parser("review", help="open the review page for the latest preview and wait for the person's notes")
    p.add_argument("plan")
    p.add_argument("--only", nargs="*")
    p.add_argument("--version", type=int)
    p.add_argument("--wait", type=int, default=30, help="minutes to wait for Done (default 30)")
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_review)
    p = sub.add_parser("notes", help="the latest saved review notes in a .davnai folder")
    p.add_argument("folder")
    p.set_defaults(fn=cmd_notes)
    p = sub.add_parser("style", help="the person's saved style; --set key=value, --unset key, --note text")
    p.add_argument("--set", nargs="*")
    p.add_argument("--unset", nargs="*")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_style)
    p = sub.add_parser("match", help="read a reel the person likes and suggest settings to match it")
    p.add_argument("video")
    p.set_defaults(fn=cmd_match)
    p = sub.add_parser("catalog", help="search HyperFrames' catalog of ready-made pieces (needs setup --motion)")
    p.add_argument("words", nargs="*")
    p.add_argument("--type", choices=["block", "component"])
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_catalog)
    p = sub.add_parser("catalog-get", help="download one catalog piece to adapt")
    p.add_argument("name")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_catalog_get)
    p = sub.add_parser("qc", help="quality checks on a video (black or frozen picture, loudness, captions over faces)")
    p.add_argument("file")
    p.add_argument("--captions", action="store_true", help="also check captions against faces")
    p.set_defaults(fn=cmd_qc)
    p = sub.add_parser("music", help="download a music track from Davnai's get_music_file link")
    p.add_argument("url")
    p.add_argument("--name", help="a name for the file (the track's title)")
    p.set_defaults(fn=cmd_music)
    p = sub.add_parser("pace", help="how busy a video is: visual changes a second, longest still stretch, talking speed")
    p.add_argument("file")
    p.add_argument("--threshold", type=float, default=0.18, help="how big a change counts (0 to 1, default 0.18)")
    p.set_defaults(fn=cmd_pace)
    p = sub.add_parser("probe", help="size and length for upload_from_computer")
    p.add_argument("file")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("upload", help="send the final to Davnai")
    p.add_argument("file")
    p.add_argument("ticket")
    p.set_defaults(fn=cmd_upload)
    args = parser.parse_args(argv)
    try:
        args.fn(args)
    except Problem as problem:
        print(f"Problem: {problem}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
