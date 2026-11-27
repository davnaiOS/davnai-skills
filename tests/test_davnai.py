"""Tests for davnai.py's own logic (run: python -m pytest tests). Rendering tests need ffmpeg."""
import base64
import http.server
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "davnai-video" / "scripts"))
import davnai  # noqa: E402

FFMPEG = shutil.which("ffmpeg") is not None


def fake_words(n=24, pause_at=12):
    words, t = [], 0.2
    for i in range(n):
        if i == pause_at:
            t += 2.0
        words.append([f"w{i}" + ("." if i % 6 == 5 else ""), round(t, 2), round(t + 0.3, 2)])
        t += 0.4
    return words


def test_lines_split_at_sentences_and_pauses():
    lines = davnai.split_lines(fake_words())
    assert [ln["id"] for ln in lines] == [1, 2, 3, 4]
    assert lines[0]["words"][-1][0] == "w5."


def test_keep_uses_line_numbers_not_times():
    lines = davnai.split_lines(fake_words())
    spans = davnai.keep_spans(lines, [[3, 4], {"from": [1, 2], "to": [1, 3]}], 20)
    assert spans[0][0] == pytest.approx(lines[2]["start"] - 0.08)
    assert spans[1][0] == pytest.approx(lines[0]["words"][1][1] - 0.08)
    with pytest.raises(davnai.Problem):
        davnai.keep_spans(lines, [[9, 10]], 20)
    with pytest.raises(davnai.Problem):
        davnai.keep_spans(lines, [{"from": [1, 99], "to": [2, 1]}], 20)


def test_tighten_shortens_long_pauses_only():
    words = fake_words()
    spans = davnai.tighten([(0.1, 11.0)], words)
    assert len(spans) == 2
    total = sum(e - s for s, e in spans)
    assert 10.9 - total == pytest.approx(2.1 - 0.3, abs=0.01)


def test_timeline_maps_words_with_speed_and_transitions():
    words = [[w[0], w[1], w[2], 1] for w in fake_words(12, pause_at=99)]
    pieces = [{"s": 0.0, "e": 2.4, "group": 0}, {"s": 2.4, "e": 4.8, "group": 1}]
    plain = davnai.Timeline([dict(p) for p in pieces], None, 1.0)
    assert plain.duration == pytest.approx(4.8)
    fast = davnai.Timeline([dict(p) for p in pieces], None, 2.0)
    assert fast.duration == pytest.approx(2.4)
    flash = davnai.Timeline([dict(p) for p in pieces], "flash", 1.0)
    assert flash.duration == pytest.approx(4.8 - 0.2)
    mapped = flash.words(words)
    assert mapped[0][1] == pytest.approx(0.2)
    assert all(a[1] <= b[1] for a, b in zip(mapped, mapped[1:]))


def test_zoom_pieces_follow_lines():
    lines = davnai.split_lines(fake_words())
    pieces = [{"s": 0.0, "e": 12.0, "group": 0}]
    zoomed = davnai.apply_zooms(pieces, {"zoom": [{"lines": [2, 2], "amount": 1.3}]}, lines)
    assert any(p.get("z") == 1.3 for p in zoomed)
    auto = davnai.apply_zooms([{"s": 0.0, "e": 12.0, "group": 0}], {"auto_zoom": True}, lines)
    assert {p.get("z") for p in auto} == {1.0, 1.12}


def test_ass_colours_are_bgr_with_alpha():
    assert davnai.ass_colour("#FF8800") == "&H000088FF"
    assert davnai.ass_colour("#fff", 0.5) == "&H80FFFFFF"
    assert davnai.ass_time(3661.5) == "1:01:01.50"


def test_ticket_round_trip():
    raw = json.dumps({"v": "vid", "p": "pass", "s": 8, "n": 2, "b": 10, "u": "https://davnai.com"})
    ticket = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
    assert davnai.read_ticket(ticket)["u"] == "https://davnai.com"
    with pytest.raises(davnai.Problem):
        davnai.read_ticket("not-a-ticket")


class FakeDavnai(http.server.BaseHTTPRequestHandler):
    parts: dict = {}
    completed: list = []

    def log_message(self, *args):
        pass

    def do_PUT(self):
        assert self.headers["Authorization"] == "Bearer pass"
        n = int(self.path.rsplit("/", 1)[1])
        FakeDavnai.parts[n] = self.rfile.read(int(self.headers["Content-Length"]))
        self._reply({"etag": f"e{n}"})

    def do_POST(self):
        FakeDavnai.completed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self._reply({"ok": True})

    def _reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_upload_sends_every_part_then_finishes(tmp_path):
    data = bytes(range(256)) * 100  # 25,600 bytes
    f = tmp_path / "final.mp4"
    f.write_bytes(data)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeDavnai)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        raw = json.dumps({"v": "vid", "p": "pass", "s": 10000, "n": 3, "b": len(data), "u": f"http://127.0.0.1:{server.server_port}"})
        ticket = base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")
        assert davnai.main(["upload", str(f), ticket]) == 0
    finally:
        server.shutdown()
    assert b"".join(FakeDavnai.parts[n] for n in (1, 2, 3)) == data
    assert FakeDavnai.completed[-1] == {"parts": [{"part_number": 1, "etag": "e1"}, {"part_number": 2, "etag": "e2"}, {"part_number": 3, "etag": "e3"}]}


def test_upload_refuses_a_file_of_another_size(tmp_path, capsys):
    f = tmp_path / "final.mp4"
    f.write_bytes(b"12345")
    raw = json.dumps({"v": "vid", "p": "pass", "s": 10, "n": 1, "b": 6, "u": "http://127.0.0.1:9"})
    assert davnai.main(["upload", str(f), base64.urlsafe_b64encode(raw.encode()).decode()]) == 1
    assert "bytes" in capsys.readouterr().err


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_render_preview_versions_and_final(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    monkeypatch.setattr(davnai, "STYLE_FILE", tmp_path / "style.json")
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)], check=True)
    folder = davnai.workdir(video)
    st = video.stat()
    (folder / "transcript.json").write_text(json.dumps({"stamp": {"size": st.st_size, "mtime": int(st.st_mtime)}, "seconds": 12, "lines": davnai.split_lines(fake_words())}))
    plan = folder / "plan.json"
    plan.write_text(json.dumps({"source": "../talk.mp4", "outputs": [{"name": "s1", "aspect": "9:16", "keep": [[3, 4], [1, 2]], "tighten": True, "captions": True, "transition": "flash", "auto_zoom": True, "hook_text": "Hi", "progress_bar": True, "end_card": "Bye"}]}))
    assert davnai.main(["render", str(plan)]) == 0
    assert davnai.main(["render", str(plan)]) == 0  # nothing changed: kept, not made again
    assert not (folder / "s1_v2_preview.mp4").exists()
    assert davnai.main(["render", str(plan), "--force"]) == 0
    assert (folder / "s1_v1_preview.mp4").exists() and (folder / "s1_v2_preview.mp4").exists()
    assert davnai.main(["render", str(plan), "--final"]) == 0
    info = davnai.probe(folder / "s1_final.mp4")
    assert (info["width"], info["height"]) == (1080, 1920)
    assert video.stat().st_size == st.st_size  # the original is never changed


def test_motion_windows_come_from_lines_and_merge():
    timing = {"offset": 1.0, "main": 10.0, "lines": {"1": [1.2, 2.0], "2": [2.4, 3.9], "5": [7.0, 8.0]}}
    assert davnai.item_window({"type": "title", "lines": [1, 2]}, timing, 11) == pytest.approx((1.1, 4.2))
    assert davnai.item_window({"type": "end_screen", "at": "end", "seconds": 2}, timing, 11) == pytest.approx((9.0, 11.0))
    assert davnai.item_window({"type": "title", "at": "start"}, timing, 11) == pytest.approx((0.0, 3.0))
    with pytest.raises(davnai.Problem):
        davnai.item_window({"type": "title", "lines": [3, 4]}, timing, 11)  # cut lines
    assert davnai.merge_windows([(0, 2, 0), (1.5, 3, 1), (5, 6, 2)]) == [(0, 3, [0, 1]), (5, 6, [2])]


def test_motion_graphics_are_brand_coloured_seekable_html(tmp_path):
    look = davnai.brand_look({"colours": [{"hex": "#123456"}], "captions": {"font_family": "Inter"}})
    assert look["primary"] == "#123456"
    for item in [{"type": "title", "text": "Hi there", "style": s} for s in ("pop", "slide", "bounce", "words", "typewriter", "glow")] + [
        {"type": "lower_third", "name": "A", "role": "B"}, {"type": "callout", "text": "Free"}, {"type": "emoji", "emoji": "🔥"},
        {"type": "counter", "from": 0, "to": 9}, {"type": "list", "items": ["a", "b"]}, {"type": "chart", "bars": [{"label": "x", "value": 3}]},
        {"type": "quote", "text": "q"}, {"type": "chapter", "number": 1, "text": "c"}, {"type": "end_screen"},
    ]:
        html, js = davnai.motion_item(0, item, 1.0, 2.0, 540, 960, look, tmp_path, tmp_path)
        assert 'data-start="1.000"' in html and "tl." in js, item
    assert "<script>" not in davnai.motion_item(0, {"type": "title", "text": "<script>x</script>"}, 0, 1, 540, 960, look, tmp_path, tmp_path)[0]
    with pytest.raises(davnai.Problem):
        davnai.motion_item(0, {"type": "nope"}, 0, 1, 540, 960, look, tmp_path, tmp_path)


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_storyboard_lists_scenes_and_writes_a_picture_page(tmp_path, capsys):
    video = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)], check=True)
    folder = davnai.workdir(video)
    st = video.stat()
    (folder / "transcript.json").write_text(json.dumps({"stamp": {"size": st.st_size, "mtime": int(st.st_mtime)}, "seconds": 12, "lines": davnai.split_lines(fake_words())}))
    plan = folder / "plan.json"
    plan.write_text(json.dumps({"source": "../talk.mp4", "outputs": [{"name": "s1", "keep": [[3, 4], [1, 1]], "hook_text": "Hook", "motion": [{"type": "lower_third", "name": "Ada", "lines": [3, 3]}]}]}))
    assert davnai.main(["storyboard", str(plan)]) == 0
    out = capsys.readouterr().out
    assert "1. lines 3-4" in out and "lower_third: Ada" in out and "Opens with: \"Hook\"" in out
    page = (folder / "plan_storyboard.html").read_text()
    assert page.count('class="card"') == 2 and "data:image/jpeg;base64," in page


def test_every_theme_is_complete():
    assert len(davnai.THEMES) == 12
    for name, theme in davnai.THEMES.items():
        assert theme["caption_font"] in davnai.FONT_SOURCES and theme["title_font"] in davnai.FONT_SOURCES, name
        assert theme["title_style"] in ("pop", "slide", "bounce", "words", "typewriter", "glow"), name
        assert set(theme["sounds"].values()) <= set(davnai.SOUND_RECIPES), name
        for key in ("look", "transition"):
            value = theme["defaults"].get(key)
            assert value is None or value in (davnai.LOOKS if key == "look" else davnai.TRANSITIONS), (name, value)
        if name in davnai.THEME_CSS:
            davnai.THEME_CSS[name].format(s=1, t=1, h=1, g=1, a="#fff", p="#000")


def test_themes_apply_under_the_plan_and_take_the_brand_colours(monkeypatch, tmp_path):
    monkeypatch.setattr(davnai, "ensure_fonts", lambda names: {n: tmp_path / n for n in names})
    for n in davnai.FONT_SOURCES:
        (tmp_path / n).write_bytes(b"x")
    brand = {"colours": [{"hex": "#123456"}], "captions": {"look": {"accent": "#ABCDEF"}}}
    cfg, kit = davnai.themed({"transition": "cut"}, brand, davnai.theme_of({"theme": "bold"}, {}))
    assert cfg["transition"] == "cut" and cfg["look"] == "punchy" and cfg["auto_zoom"] is True  # the plan wins; the rest comes from the theme
    assert kit["captions"]["look"]["accent"] == "#ABCDEF" and kit["captions"]["font_family"] == "Anton"
    assert davnai.brand_look(kit)["primary"] == "#123456" and davnai.brand_look(kit)["theme"] == "bold"
    _, own = davnai.themed({"theme_colours": True}, brand, davnai.theme_of({}, {"theme": "neon"}))
    assert own["captions"]["look"]["accent"] == "#22D3EE" and own["colours"] == []
    custom = davnai.theme_of({"theme": {"base": "clean", "caption": {"words": 2}, "title_font": "BebasNeue-Regular.ttf"}}, {})
    assert custom["caption"]["words"] == 2 and custom["title_font"] == "BebasNeue-Regular.ttf" and custom["caption"]["size"] == davnai.THEMES["clean"]["caption"]["size"]
    with pytest.raises(davnai.Problem):
        davnai.theme_of({"theme": "nope"}, {})
    with pytest.raises(davnai.Problem):
        davnai.theme_of({"theme": {"base": "clean", "title_font": "Comic.ttf"}}, {})


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_built_in_sounds_are_made_on_the_computer(monkeypatch, tmp_path):
    monkeypatch.setattr(davnai, "SOUNDS_DIR", tmp_path)
    for name in davnai.SOUND_RECIPES:
        info = davnai.probe(davnai.sound_file(name))
        assert info["audio"] and 0.05 < info["seconds"] < 2, name
    assert davnai.sound_file("nope") is None


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_quality_checks_find_black_and_quiet_video(tmp_path):
    bad = tmp_path / "bad.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=3", "-f", "lavfi", "-i", "sine=frequency=300:d=3", "-filter:a", "volume=0.05", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(bad)], check=True)
    notes = davnai.quality_checks(bad, {}, {})
    assert any(n.startswith("⚠ black picture") for n in notes) and any("⚠ loudness" in n for n in notes)


def test_effect_windows_and_filters():
    words = [["a", 1.0, 1.4, 1], ["b", 1.5, 2.0, 1], ["c", 3.0, 3.5, 2]]
    assert davnai.fx_window({"type": "shake", "lines": [1, 1]}, words, 10) == pytest.approx((0.95, 2.05))
    assert davnai.fx_window({"type": "flash", "lines": 2}, words, 10) == pytest.approx((2.95, 3.2))
    assert davnai.fx_window({"type": "grain", "all": True}, words, 10) == (0.0, 10)
    with pytest.raises(davnai.Problem):
        davnai.fx_window({"type": "shake", "lines": [5, 6]}, words, 10)
    for kind in ("shake", "flash", "rgb", "glitch", "blur", "bw", "vhs", "grain"):
        assert davnai.fx_chain(kind, 540, 960, {})
    with pytest.raises(davnai.Problem):
        davnai.fx_chain("nope", 540, 960, {})
    graph, label = davnai.fx_graph("v", {"fx": [{"type": "rgb", "lines": [1, 1]}, {"type": "behind", "text": "x", "lines": [2, 2]}]}, words, 10, 540, 960, 30)
    assert label == "fx0" and any("enable='between(t,0.950,2.050)'" in g for g in graph)


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_beats_are_found_in_music(tmp_path):
    music = tmp_path / "beat.wav"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*60*t)*exp(-mod(t,0.5)*12)':d=6", str(music)], check=True)
    beats = davnai.beats_of(music)
    assert 9 <= len(beats) <= 13
    assert all(0.4 <= b - a <= 0.6 for a, b in zip(beats, beats[1:]))
    graph, label = davnai.beat_pulse("v", beats, 540, 960, 30)
    assert label == "bp" and "zoompan" in graph[0]


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_words_behind_put_the_person_back_on_top(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    out = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=180x320:d=3:r=30", "-f", "lavfi", "-i", "sine=d=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)], check=True)

    def fake_cutout(seg, person):  # a red "person" in the middle; see-through elsewhere
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(seg), "-vf", "format=rgba,geq=r=255:g=0:b=0:a='if(between(X,W*0.4,W*0.6),255,0)'", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(person)], check=True)

    monkeypatch.setattr(davnai, "cut_out_person", fake_cutout)
    davnai.apply_behind(out, [(0.5, 2.5, {"text": "MONEY"})], {}, 180, 320, True, tmp_path, "v", 0.0)
    frame = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "1.5", "-i", str(out), "-frames:v", "1", "-vf", "crop=4:4:88:150", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    assert frame[0] > 200 and frame[2] < 60  # the person (red) is in front of the words
    assert davnai.probe(out)["audio"]


def test_style_sits_under_the_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(davnai, "STYLE_FILE", tmp_path / "style.json")
    assert davnai.main(["style", "--set", "caption_words=3", "look=warm", "--note", "likes warm"]) == 0
    assert davnai.with_style({"look": "cool"}) == {"caption_words": 3, "look": "cool"}
    assert davnai.load_style()["notes"][-1].endswith("likes warm")
    assert davnai.main(["style", "--unset", "look"]) == 0
    assert davnai.load_style()["preferences"] == {"caption_words": 3}


def test_unchanged_outputs_have_the_same_fingerprint(tmp_path):
    a = davnai.output_digest({"name": "s", "keep": [[1, 2]]}, {}, tmp_path, False)
    assert a == davnai.output_digest({"keep": [[1, 2]], "name": "s"}, {}, tmp_path, False)
    assert a != davnai.output_digest({"name": "s", "keep": [[1, 3]]}, {}, tmp_path, False)
    assert a != davnai.output_digest({"name": "s", "keep": [[1, 2]]}, {}, tmp_path, True)


def test_review_notes_come_back_as_lines():
    text = "\n".join(davnai.notes_text({"name": "s", "version": 2, "marks": [{"kind": "cut", "time": 65.2, "line": 14, "said": "so um", "note": ""}, {"kind": "change", "time": None, "note": "warmer"}]}))
    assert "[cut] 1:05 line 14 (\"so um\"): (no note)" in text and "[change] whole video: warmer" in text


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_many_cuts_never_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    monkeypatch.setattr(davnai, "STYLE_FILE", tmp_path / "style.json")
    video = tmp_path / "long.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=29.97", "-f", "lavfi", "-i", "sine=sample_rate=44100", "-t", "40", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)], check=True)
    words, t = [], 0.3
    while t < 39:
        words.append([f"w{len(words)}" + ("." if len(words) % 7 == 6 else ""), round(t, 3), round(t + 0.27, 3)])
        t += 0.33 + (0.85 if len(words) % 5 == 0 else 0)
    folder = davnai.workdir(video)
    st = video.stat()
    lines = davnai.split_lines(words)
    (folder / "transcript.json").write_text(json.dumps({"stamp": {"size": st.st_size, "mtime": int(st.st_mtime)}, "seconds": 40, "lines": lines}))
    plan = folder / "plan.json"
    plan.write_text(json.dumps({"source": "../long.mp4", "outputs": [{"name": "d", "aspect": "source", "keep": [[i, i + 1] for i in range(1, len(lines) - 2, 3)], "tighten": True, "speed": 1.1, "checks": False}]}))
    assert davnai.main(["render", str(plan)]) == 0
    timing = json.loads((folder / "d_v1.timing.json").read_text())
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=duration", "-of", "csv=p=0", str(folder / "d_v1_preview.mp4")], capture_output=True, text=True).stdout
    assert abs(float(out) - timing["main"]) < 0.02
