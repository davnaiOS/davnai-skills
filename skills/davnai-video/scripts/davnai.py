#!/usr/bin/env python3
"""Davnai video editing on your own computer (https://davnai.com). MIT licence.

Commands (python davnai.py <command> --help for details):
  check                     what's installed and what's missing
  brand <brand_url>         save the Brand Kit from Davnai (get_brand_files) in ~/.davnai/brand
  transcribe <video>        numbered transcript lines (reused on the second run)
  frame <video> --line N    one still from the middle of line N (to check framing)
  render <plan.json>        previews (v1, v2, ...); --final for full quality
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

VERSION = "1.0.0"
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
            lines.append(f"✗ {tool}: install ffmpeg (Windows: winget install ffmpeg; Mac: brew install ffmpeg; Linux: apt install ffmpeg).")
    if shutil.which("ffmpeg"):
        filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout
        lines.append("✓ captions (libass)" if re.search(r"\bass\b", filters) else "✗ this ffmpeg can't burn captions (no libass): install a full ffmpeg build.")
    try:
        import faster_whisper  # noqa: F401
        lines.append("✓ transcripts (faster-whisper)")
    except ImportError:
        ok = False
        lines.append("✗ transcripts: pip install faster-whisper")
    try:
        import fontTools  # noqa: F401
        lines.append("✓ brand fonts (fonttools)")
    except ImportError:
        lines.append("· optional: pip install fonttools brotli (uses the exact Brand Kit caption font)")
    lines.append("✓ Brand Kit saved" if (BRAND_DIR / "brand.json").exists() else "· Brand Kit not saved yet: call get_brand_files in Davnai, then run: davnai.py brand \"<brand_url>\"")
    lines.append("Ready." if ok else "Install what's marked ✗, then run check again.")
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
    for end in ("intro", "outro"):
        part = brand.get(end) or {}
        path = BRAND_DIR / ((part.get("file") or {}).get("path") or "-")
        if cfg.get(end) and path.exists():
            pinfo = probe(path)
            pi = add_input("-i", str(path))
            graph.append(fit(f"{pi}:v", f"{end}v", w, h, fps))
            graph.append(f"[{pi}:a]{AUDIO_FMT}[{end}a]" if pinfo["audio"] else f"anullsrc=r=48000:cl=stereo,atrim=duration={pinfo['seconds']:.3f},aformat=sample_fmts=fltp[{end}a]")
            pieces_seq.append(end)
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
    return out


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
