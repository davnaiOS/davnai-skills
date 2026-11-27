#!/usr/bin/env python3
"""Davnai video editing on your own computer (https://davnai.com). MIT licence.

Commands (python davnai.py <command> --help for details):
  check                     what's installed and what's missing
  brand <brand_url>         save the Brand Kit from Davnai (get_brand_files) in ~/.davnai/brand
  transcribe <video>        numbered transcript lines (reused on the second run)
  frame <video> --line N    one still from the middle of line N (to check framing)
  storyboard <plan.json>    the scenes to approve before rendering (and a picture page)
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
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = "1.1.0"
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
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    out = subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
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
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
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
    hf = MOTION_DIR / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
    if node_major() >= 22 and hf.exists():
        lines.append("✓ motion graphics (HyperFrames)")
    else:
        lines.append("· optional: motion graphics need Node.js 22+ and HyperFrames: python davnai.py setup --motion")
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
    model = WhisperModel(args.model, device="auto", compute_type="int8")
    segments, details = model.transcribe(str(source), word_timestamps=True, vad_filter=True, language=args.language)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append([text, round(w.start, 3), round(w.end, 3)])
    if not words:
        raise Problem("No speech was found in this file.")
    lines = split_lines(words)
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


def line_window(words: list[list], first: int, last: int) -> tuple[float, float] | None:
    """Where lines first..last are in the edited video (from its words), or None if they were cut."""
    inside = [w for w in words if first <= w[3] <= last]
    return (min(w[1] for w in inside), max(w[2] for w in inside)) if inside else None


def split_pieces(pieces: list[dict], cuts: list[float]) -> list[dict]:
    out = []
    for p in pieces:
        points = sorted(c for c in cuts if p["s"] + 0.05 < c < p["e"] - 0.05)
        edges = [p["s"], *points, p["e"]]
        out += [{**p, "s": a, "e": b} for a, b in zip(edges, edges[1:])]
    return out


def apply_zooms(pieces: list[dict], cfg: dict, lines: list[dict]) -> list[dict]:
    zooms = []
    for z in cfg.get("zoom") or []:
        rng = z.get("lines") if isinstance(z, dict) else z
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            raise Problem("Each zoom needs \"lines\": [first, last].")
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


def write_ass(path: Path, width: int, height: int, cfg: dict, brand: dict, words: list[list], duration: float) -> bool:
    """Captions (Brand Kit style), the hook title and text callouts, all in one subtitle file."""
    caps = brand.get("captions") or {}
    look = {**DEFAULT_STYLE, **(caps.get("look") or {})}
    margins = caps.get("margins") or DEFAULT_MARGINS
    colours = [c.get("hex") for c in brand.get("colours") or [] if c.get("hex")]
    brand_colour = colours[0] if colours else look.get("accent") or "#FFD43B"
    tall = height > width
    short_side = min(width, height)
    size = max(16, round(float(look.get("size", 0.075)) * short_side))
    m = margins["tall" if tall else "wide"]
    place = cfg.get("caption_position") or caps.get("position") or look.get("place") or "bottom"
    align, margin_v = {"top": (8, round(m["top"] * height)), "middle": (5, 0)}.get(place, (2, round(m["bottom"] * height)))
    font_file = caps.get("font_file")
    family = caps.get("font_family") if font_file and (BRAND_DIR / font_file).exists() else "Arial"
    box = look.get("box")
    border, back = (3, ass_colour(box.get("color"), 1 - float(box.get("alpha", 0.6)))) if box else (1, ass_colour("#000000", 0.5))
    outline = round(float(look.get("outline", 0.07)) * size, 1) if not box else round(size * 0.18, 1)
    side = round(width * 0.08)
    styles = [
        f"Style: Davnai,{family},{size},{ass_colour(look.get('color'))},{ass_colour(look.get('accent'))},{ass_colour(look.get('outlineColor'))},{back},-1,0,0,0,100,100,0,0,{border},{outline},{2 if look.get('shadow') else 0},{align},{side},{side},{margin_v},1",
        f"Style: Hook,{family},{round(short_side * 0.085)},{ass_colour('#FFFFFF')},{ass_colour('#FFFFFF')},{ass_colour(brand_colour)},{ass_colour(brand_colour)},-1,0,0,0,100,100,0,0,3,{round(short_side * 0.02)},0,8,{side},{side},{round(height * (0.12 if tall else 0.08))},1",
        f"Style: Callout,{family},{round(short_side * 0.055)},{ass_colour('#111111')},{ass_colour('#111111')},{ass_colour('#FFFFFF')},{ass_colour('#FFFFFF')},-1,0,0,0,100,100,0,0,3,{round(short_side * 0.015)},0,8,{side},{side},{round(height * (0.22 if tall else 0.12))},1",
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
            intro = ANIM_TAGS.get(anim, "")
            if anim == "type":
                for k, w in enumerate(group):
                    w_end = group[k + 1][1] if k + 1 < len(group) else end
                    events.append(f"Dialogue: 0,{ass_time(w[1] if k else start)},{ass_time(w_end)},Davnai,,0,0,0,,{' '.join(word_text(x, j == k) for j, x in enumerate(group[: k + 1]))}")
            elif karaoke:
                for k, w in enumerate(group):
                    w_end = group[k + 1][1] if k + 1 < len(group) else end
                    events.append(f"Dialogue: 0,{ass_time(w[1] if k else start)},{ass_time(w_end)},Davnai,,0,0,0,,{intro if k == 0 else ''}{' '.join(word_text(x, j == k) for j, x in enumerate(group))}")
            else:
                events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Davnai,,0,0,0,,{intro}{' '.join(word_text(x, False) for x in group)}")
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
    family = caps.get("font_family") if caps.get("font_file") and (BRAND_DIR / caps["font_file"]).exists() else "Arial"
    size = round(min(width, height) * 0.08)
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

    aspect = cfg.get("aspect", "9:16")
    focus_x = min(1.0, max(0.0, float(cfg.get("focus_x", 0.5))))
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
        timeline = Timeline(pieces, transition, speed)
        w, h = target_size(aspect, info["width"], info["height"], final)
        fps = 30.0 if aspect != "source" else min(60.0, max(24.0, round(info["fps"])))
        si = add_input("-i", str(source))
        tempo = f",atempo={speed:g}" if abs(speed - 1) > 0.001 else ""
        for k, p in enumerate(pieces):
            # Each piece is shaped to the output first, so zooms work on the small frame (fast, little memory).
            graph.append(f"[{si}:v]trim=start={p['s']:.3f}:end={p['e']:.3f},setpts=PTS-STARTPTS[pv{k}]")
            graph += shape(f"pv{k}", f"ps{k}", info["width"], info["height"], w, h, focus_x, fps, fill)
            z = zoom_filter(p.get("z", 1.0), p.get("zs", "punch"), w, h, 0.5, fps)
            graph.append(f"[ps{k}]{z}setpts=(PTS-STARTPTS)/{speed:g},setsar=1[v{k}]")
            if info["audio"]:
                graph.append(f"[{si}:a]atrim=start={p['s']:.3f}:end={p['e']:.3f},asetpts=PTS-STARTPTS{tempo},{AUDIO_FMT}[a{k}]")
            else:
                graph.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={(p['e'] - p['s']) / speed:.3f},aformat=sample_fmts=fltp[a{k}]")
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
        if cfg.get("clean_audio"):
            audio_fx.append("highpass=f=80,afftdn=nf=-25")
        if cfg.get("loudness", True):
            audio_fx.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        graph.append(f"[acut]{','.join(audio_fx) or 'anull'},{AUDIO_FMT}[abase]")
        words = timeline.words(src_words)
        main_len = timeline.duration

    label = "vbase"
    if cfg.get("look"):
        if cfg["look"] not in LOOKS:
            raise Problem(f"Unknown look '{cfg['look']}'. Use: {', '.join(LOOKS)}.")
        graph.append(f"[{label}]{LOOKS[cfg['look']]}[vlook]")
        label = "vlook"
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
    ass = folder / f"{name}_v{version}.ass"
    if write_ass(ass, w, h, cfg, brand, words, main_len):
        fonts = folder / "fonts"
        fonts.mkdir(exist_ok=True)
        font_file = (brand.get("captions") or {}).get("font_file")
        if font_file and (BRAND_DIR / font_file).exists():
            shutil.copy2(BRAND_DIR / font_file, fonts / Path(font_file).name)
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
    if cfg.get("music"):
        mi = add_input("-stream_loop", "-1", "-i", str(resolve(cfg["music"])))
        graph.append(f"[{mi}:a]{AUDIO_FMT},volume={float(cfg.get('music_volume', 0.12)):g},atrim=duration={main_len:.3f}[mus]")
        mixes.append("[mus]")
    for k, item in enumerate(cfg.get("sfx") or []):
        line = item.get("line")
        window = line_window(words, int(line), int(line)) if line is not None else None
        if window is None:
            raise Problem(f"Sound effect {k + 1}: line {line} isn't in this video.")
        fi = add_input("-i", str(resolve(item.get("file") or "")))
        ms = max(0, round((window[0] - 0.1) * 1000))
        graph.append(f"[{fi}:a]{AUDIO_FMT},volume={float(item.get('volume', 0.6)):g},adelay={ms}|{ms}[fx{k}]")
        mixes.append(f"[fx{k}]")
    if mixes:
        graph.append(f"[{alabel}]{''.join(mixes)}amix=inputs={len(mixes) + 1}:duration=first:normalize=0[amix]")
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
    timing = {"offset": intro_len, "main": main_len, "lines": {str(k): [round(a + intro_len, 3), round(b + intro_len, 3)] for k, (a, b) in windows.items()}}
    (folder / f"{name}_v{version}.timing.json").write_text(json.dumps(timing), encoding="utf-8")
    if cfg.get("motion"):
        apply_motion(out, cfg, brand, timing, w, h, fps, final, folder, f"{name}_v{version}", plan_dir)
    return out


# ---------------------------------------------------------------- motion graphics (HyperFrames)

MOTION_DIR = BRAND_DIR.parent / "motion"
NO_TRACKING = {"HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}  # the person's renders stay private
MOTION_TYPES = ("title", "lower_third", "callout", "emoji", "counter", "list", "chart", "quote", "chapter", "end_screen", "custom")


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
    font_file = caps.get("font", {}).get("name") if isinstance(caps.get("font"), dict) else None
    return {
        "primary": colours[0] if colours else "#4F46E5",
        "secondary": colours[1] if len(colours) > 1 else "#111827",
        "accent": look.get("accent") or "#FACC15",
        "text": "#FFFFFF",
        "font": caps.get("font_family") or "Arial",
        "font_file": f"fonts/{font_file}" if font_file and (BRAND_DIR / "fonts" / font_file).exists() else None,
        "logo": (brand.get("logo") or {}).get("file"),
        "handle": brand.get("handle") or "",
    }


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
    if not isinstance(rng, (list, tuple)) or len(rng) != 2:
        raise Problem(f"Motion graphic '{item.get('type')}' needs \"lines\": [first, last] (or \"at\": \"start\" / \"end\").")
    found = [timing["lines"][str(n)] for n in range(int(rng[0]), int(rng[1]) + 1) if str(n) in timing["lines"]]
    if not found:
        raise Problem(f"Motion graphic '{item.get('type')}': lines {rng[0]}-{rng[1]} aren't in this video.")
    a, b = min(f[0] for f in found), max(f[1] for f in found)
    if item.get("type") == "chapter":
        b = min(b, a + float(item.get("seconds", 2.2)))
    return max(0.0, a - 0.1), min(total, b + float(item.get("hold", 0.3)))


def spot(position: str, w: int, h: int) -> str:
    tall = h > w
    top = {"top": 0.12 if tall else 0.08, "upper": 0.24, "middle": 0.42, "lower": 0.56 if tall else 0.66, "bottom": 0.62 if tall else 0.78}.get(position, 0.12)
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
        style = item.get("style", "pop")
        text = str(item.get("text", ""))
        inner = "".join(f'<span class="w">{esc(x)}</span> ' for x in text.split()) if style in ("words", "typewriter") else esc(text)
        if style == "typewriter":
            inner = "".join(f'<span class="c">{esc(c) if c != " " else "&nbsp;"}</span>' for c in text)
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
    if kind == "custom":
        src = Path(str(item.get("html", ""))).expanduser()
        src = src if src.is_absolute() else (plan_dir / src).resolve()
        if not src.exists():
            raise Problem(f"Custom motion graphic: can't find {src}.")
        html = f'<script>window.__davnaiCurrent="{mid}";</script><div {attrs} class="g custom">{src.read_text(encoding="utf-8")}</div>'
        return html, f'(window.__davnaiQueue["{mid}"]||[]).forEach(fn=>fn(tl,document.getElementById("{mid}"),{t0:.3f},{dur:.3f},window.BRAND));'
    raise Problem(f"Unknown motion graphic '{kind}'. Use: {', '.join(MOTION_TYPES)}.")


def motion_css(w: int, h: int, look: dict) -> str:
    u = min(w, h) / 100
    face = f'@font-face{{font-family:"DavnaiBrand";src:url("{look["font_file"]}");font-weight:100 900}}' if look["font_file"] else ""
    family = '"DavnaiBrand",' if look["font_file"] else ""
    p, s, a, t = look["primary"], look["secondary"], look["accent"], look["text"]
    return f"""{face}
html,body{{margin:0;background:#000}}
#stage{{position:relative;width:{w}px;height:{h}px;overflow:hidden;font-family:{family}"{look['font']}",Arial,sans-serif;font-weight:800;color:{t}}}
video.base{{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}}
.g{{position:absolute}}
.box{{display:inline-block;background:{p};color:{t};border-radius:{round(2.2 * u)}px;padding:{round(1.2 * u)}px {round(2.6 * u)}px;box-shadow:0 {round(u)}px {round(3 * u)}px rgba(0,0,0,.35)}}
.title{{font-size:{round(8 * u)}px;line-height:1.1;font-weight:900}}
.title .w,.title .c{{display:inline-block}}
.callout{{font-size:{round(5.5 * u)}px;background:{a};color:#111}}
.emoji{{font-size:{round(16 * u)}px}}
.lt-bar{{width:{round(48 * u)}px;height:{round(1.2 * u)}px;background:{a};margin-bottom:{round(1.2 * u)}px}}
.lt-name{{display:inline-block;background:{p};padding:{round(u)}px {round(2 * u)}px;font-size:{round(5.5 * u)}px}}
.lt-role{{display:block;width:max-content;background:{s};padding:{round(0.7 * u)}px {round(2 * u)}px;font-size:{round(3.6 * u)}px;font-weight:600}}
.num{{font-size:{round(14 * u)}px;font-weight:900;color:{t};text-shadow:0 {round(0.6 * u)}px {round(2 * u)}px rgba(0,0,0,.5)}}
.num .v{{color:{a}}}
.label{{font-size:{round(4.5 * u)}px;font-weight:700}}
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
"""


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
    items = cfg["motion"]
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
            if look["font_file"]:
                (project / "fonts").mkdir(exist_ok=True)
                shutil.copy2(BRAND_DIR / look["font_file"], project / look["font_file"])
            parts, anims = [], []
            for k in ks:
                ia, ib, _ = spans[k]
                html, js = motion_item(k, items[k], ia - a, ib - ia, w, h, look, plan_dir, project)
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
            seg = work / f"seg{g}.mp4"
            proc = subprocess.run([*cli, "render", str(project), "-o", str(seg), "-q", "looks" if final else "draft", "-f", f"{fps:g}", "--quiet"], env={**os.environ, **NO_TRACKING}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0 or not seg.exists():
                tail = "\n".join((proc.stderr or proc.stdout).strip().splitlines()[-8:])
                raise Problem(f"HyperFrames couldn't render the graphics at {a:.1f}s:\n{tail}\n(The page is in {project}; `hyperframes preview` there shows it.)")
            segments.append((a, seg))
        inputs = ["-i", str(base)]
        chain, label = [], "0:v"
        for g, (a, seg) in enumerate(segments):
            inputs += ["-itsoffset", f"{a:.3f}", "-i", str(seg)]
            chain.append(f"[{label}][{g + 1}:v]overlay=0:0:eof_action=pass[o{g}]")
            label = f"o{g}"
        quality = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if final else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28"]
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs, "-filter_complex", ";".join(chain), "-map", f"[{label}]", "-map", "0:a?", *quality, "-c:a", "copy", "-movflags", "+faststart", str(out)])
        base.unlink(missing_ok=True)
        if final:
            shutil.rmtree(work, ignore_errors=True)
    except BaseException:
        if not out.exists() and base.exists():
            base.replace(out)
        raise


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
        extras = [x for x in ("hook_text", "captions", "auto_zoom", "progress_bar", "end_card", "music", "intro", "outro", "logo") if cfg.get(x)]
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
    out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
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
    pip = [sys.executable, "-m", "pip", "install", "--user", "--quiet", "faster-whisper", "fonttools", "brotli"]
    say("Installing the Python parts (speech-to-text, brand fonts)...")
    proc = subprocess.run(pip, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 and "externally-managed" in (proc.stderr or ""):
        proc = subprocess.run([*pip, "--break-system-packages"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
            restart = restart or (ok and sys.platform == "win32")
            lines.append(f"✓ {label} installed" if ok else f"✗ {label} didn't install. Try: {' '.join(hint)}")
        elif not hint:
            lines.append(f"✗ {label}: install it from {'https://nodejs.org' if tool == 'node' else 'https://ffmpeg.org/download.html'} (Linux: sudo apt install {'nodejs' if tool == 'node' else 'ffmpeg'})")
        else:
            lines.append(f"· {label} skipped")
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
        version = next_version(folder, name) if not args.final else max(1, next_version(folder, name) - 1)
        if not args.final:
            (folder / f"{name}_v{version}.plan.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        start = time.time()
        out = render_output(plan_path.parent, cfg, plan, brand, args.final, version, folder)
        info = probe(out)
        made.append(f"{'Final' if args.final else f'Preview v{version}'} of {name}: {out} ({info['seconds']:.1f}s, {info['width']}x{info['height']}, made in {time.time() - start:.0f}s)")
    say(*made)
    if not args.final:
        say("Ask the person to watch it and say what to change. Make the final only when they say it's the one (--final).")


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


def main(argv: list[str] | None = None) -> int:
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
