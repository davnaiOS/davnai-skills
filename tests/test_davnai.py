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
    assert own["captions"]["look"]["accent"] == "#22D3EE" and [c["hex"] for c in own["colours"]] == davnai.THEMES["neon"]["colours"]
    _, bare = davnai.themed({}, {}, davnai.theme_of({"theme": "luxury"}, {}))  # no Brand Kit: the theme's own colours, not Davnai's
    assert davnai.brand_look(bare)["primary"] == davnai.THEMES["luxury"]["colours"][0]
    assert davnai.brand_look({})["primary"] == "#1F2937"
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


def test_an_empty_brand_kit_is_named_and_offered(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    pack = {"version": 1, "name": None, "handle": None, "voice": None, "colours": [], "captions": {"style": "highlight", "style_name": "Highlight", "look": {}}, "logo": None, "intro": {"choice": "animated", "file": None, "note": "x"}, "outro": {"choice": "animated", "file": None, "note": "x"}}
    monkeypatch.setattr(davnai, "http", lambda url, **k: (200, {}, json.dumps(pack).encode()))
    assert davnai.main(["brand", "https://davnai.com/api/brand/pack?k=x"]) == 0
    out = capsys.readouterr().out
    assert "no colours, logo, handle, voice yet" in out and "update_brand_kit" in out
    assert json.loads((tmp_path / "brand" / "brand.json").read_text())["colours"] == []


LOOK = {"size": 0.075}
MARGINS = {"tall": {"top": 0.12, "bottom": 0.34}, "wide": {"top": 0.08, "bottom": 0.1}}


def test_captions_and_titles_move_off_the_face():
    low_face = (200, 650, 130, 130)  # near the bottom of a 540x960 frame
    assert davnai.clear_place(None, 540, 960, LOOK, MARGINS, "bottom") == "bottom"
    assert davnai.clear_place(low_face, 540, 960, LOOK, {"tall": {"top": 0.12, "bottom": 0.2}, "wide": MARGINS["wide"]}, "bottom") == "top"
    high_face = (200, 120, 130, 130)
    assert davnai.keep_off_face({"type": "title", "text": "Hi"}, high_face, 540, 960).get("position") not in (None, "top")
    assert davnai.keep_off_face({"type": "title", "position": "top"}, high_face, 540, 960)["position"] == "top"  # the plan's choice wins
    assert "position" not in davnai.keep_off_face({"type": "title"}, None, 540, 960)


def test_face_lands_where_the_crop_puts_it():
    box = (1200, 300, 200, 200)  # in a 1920x1080 source
    x, y, fw, fh = davnai.face_to_output(box, 1920, 1080, 540, 960, 1.0, "crop")
    cw = 1080 * 540 / 960
    assert x == pytest.approx((1200 - (1920 - cw)) * 960 / 1080)
    assert fw == pytest.approx(200 * 960 / 1080)
    focus = davnai.auto_focus({}, [box], 1920, 1080, 540, 960)
    centre = davnai.face_to_output(box, 1920, 1080, 540, 960, focus, "crop")
    assert centre[0] + centre[2] / 2 == pytest.approx(270, abs=1)  # the speaker ends up in the middle
    assert davnai.auto_focus({"focus_x": 0.2}, [box], 1920, 1080, 540, 960) is None
    assert davnai.auto_focus({}, [], 1920, 1080, 540, 960) is None


def test_relight_lights_build_and_golden_hour_needs_no_cut_out():
    for light in davnai.LIGHTS[:-1]:
        graph, label = davnai.relight_layers(0, {"light": light}, "v", "p", 1.0, 2.0, 540, 960, (200, 200, 130, 130), "#FFFFFF")
        assert label.startswith("r0") and any("between(t,1.000,2.000)" in g for g in graph)
    with pytest.raises(davnai.Problem):
        davnai.relight_layers(0, {"light": "disco"}, "v", "p", 1, 2, 540, 960, None, "#FFFFFF")
    assert "colorbalance" in davnai.fx_chain("relight", 540, 960, {"light": "golden_hour"})


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_spotlight_darkens_the_background_not_the_person(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    out = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=gray:s=180x320:d=3:r=30", "-f", "lavfi", "-i", "sine=d=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)], check=True)

    def fake_cutout(seg, person):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(seg), "-vf", "format=rgba,geq=r=200:g=200:b=200:a='if(between(X,W*0.4,W*0.6),255,0)'", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(person)], check=True)

    monkeypatch.setattr(davnai, "cut_out_person", fake_cutout)
    davnai.apply_behind(out, [(0.5, 2.5, {"type": "relight", "light": "low_key"})], {}, 180, 320, True, tmp_path, "v", 0.0)

    def pixel(x):
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "1.5", "-i", str(out), "-frames:v", "1", "-vf", f"crop=2:2:{x}:150", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout[0]
    assert pixel(88) > 150 and pixel(10) < 70  # the person stays lit, the room goes dark


def test_sliced_words_land_on_the_beats():
    assert davnai.slice_times(1.0, 3.0, 3, [1.5, 2.0, 2.5, 2.9]) == [1.0, 1.5, 2.0]
    assert davnai.slice_times(1.0, 3.0, 3, [1.05, 1.5, 2.0]) == [1.05, 1.5, 2.0]
    even = davnai.slice_times(0.0, 3.0, 3, [])
    assert even == pytest.approx([0.0, 0.6, 1.2])


def test_sliced_and_poster_titles_are_written(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    ass = tmp_path / "b.ass"
    davnai.behind_ass(ass, 540, 960, [(0.0, 2.0, {"type": "behind", "text": "stop doing this", "slice": True, "_beats": [0.5, 1.0]}),
                                     (3.0, 5.0, {"type": "poster", "text": "level up", "sub": "Episode 4"}),
                                     (6.0, 7.0, {"type": "relight", "light": "neon"})], {}, 0.0)
    events = [ln for ln in ass.read_text().splitlines() if ln.startswith("Dialogue")]
    assert [e.split("}")[-1] for e in events] == ["STOP", "DOING", "THIS", "LEVEL\\NUP", "EPISODE 4"]
    assert "\\move(" in events[0] and "0:00:00.50" in events[1]


def test_poster_and_compare_build():
    assert davnai.needs_cutout({"type": "poster"}) and not davnai.needs_cutout({"type": "compare"})
    assert not davnai.needs_cutout({"type": "relight", "light": "golden_hour"})
    graph, label = davnai.compare_graph("v", "raw", [(1.0, 2.0, {}), (4.0, 5.0, {})], 540, 960)
    assert label == "cp1" and graph[0].startswith("[raw]split=2")
    labels = davnai.compare_labels(1.0, 2.0, {"labels": ["Before", "After"]}, 540, 960)
    assert [x[2] for x in labels] == ["Before", "After"] and labels[0][3] < labels[1][3]


def test_feed_and_flythrough_graphics():
    look = davnai.brand_look({})
    html, js = davnai.motion_item(0, {"type": "feed", "caption": "hi", "_base": ("../base.mp4", 4.0)}, 0.5, 4.0, 540, 960, look, Path("."), Path("."))
    assert 'data-media-start="4.500"' in html and "feed-col" in js
    html, js = davnai.motion_item(1, {"type": "flythrough", "chapters": [{"text": "A", "line": 1}, {"text": "B", "line": 2}], "_stills": ["a.jpg", "b.jpg"]}, 0.0, 2.6, 540, 960, look, Path("."), Path("."))
    assert html.count("fly-card") == 2 and "nth-child(2)" in js
    with pytest.raises(davnai.Problem):
        davnai.chapter_stills(Path("x.mp4"), {"chapters": [{"text": "A", "line": 9}]}, {"lines": {"1": [0, 1]}}, Path("."), 0)


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_poster_freezes_and_compare_shows_both_halves(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    out = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=180x320:d=3:r=30", "-f", "lavfi", "-i", "sine=d=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(out)], check=True)

    def fake_cutout(seg, person):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(seg), "-vf", "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(between(X,W*0.4,W*0.6),255,0)'", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(person)], check=True)

    monkeypatch.setattr(davnai, "cut_out_person", fake_cutout)
    davnai.apply_behind(out, [(0.5, 2.5, {"type": "poster", "text": "WOW"})], {}, 180, 320, True, tmp_path, "v", 0.0)

    def crop(t, x):
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(out), "-frames:v", "1", "-vf", f"crop=4:4:{x}:200", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    assert abs(crop(1.0, 88)[0] - crop(2.0, 88)[0]) < 12  # the person is frozen
    assert max(crop(1.5, 20)[:3]) < 90  # the background is the flat (dark) brand colour


def test_poster_title_fits_above_the_face():
    size, single = davnai.poster_size(["LEVEL", "UP"], 540, 960, 48, (200, 300, 140, 140))
    lines = 1 if single else 2
    assert 48 + size * lines <= 300 + 140 * 0.25 + 1
    assert davnai.poster_size(["GO"], 540, 960, 48)[1]


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_custom_effects_are_checked():
    assert davnai.fx_chain("custom", 180, 320, {"filter": "hue=h=90*t,eq=contrast=1.3"}).endswith("scale=180:320")
    for bad in ("", "[0:v]hue=h=9[x]", "movie=secret.mp4", "notafilter=1"):
        with pytest.raises(davnai.Problem):
            davnai.check_custom_filter(bad, 180, 320)


def test_picture_cycles_change_on_the_beat():
    assert davnai.cycle_times(1.0, 3.0, [1.5, 2.0, 2.5]) == [1.0, 1.5, 2.0, 2.5]
    assert davnai.cycle_times(0.0, 1.0, [], 0.4) == pytest.approx([0.0, 0.4, 0.8])
    assert davnai.needs_cutout({"type": "cycle"}) and not davnai.needs_cutout({"type": "cycle", "behind": False})
    with pytest.raises(davnai.Problem):
        davnai.cycle_images({"images": ["one.jpg"]}, Path)


def test_graphics_avoid_the_face_and_the_captions():
    face, captions = (202, 228, 136, 136), (528, 634)
    moved = davnai.keep_off_face({"type": "carousel"}, face, 540, 960, captions)
    top = davnai.SPOT_TOPS[moved["position"]][0] * 960
    assert top > 634 or top + 0.25 * 960 < 528
    html, js = davnai.motion_item(0, {"type": "glass", "title": "Hi", "items": ["a", "b"]}, 0.0, 2.0, 540, 960, davnai.brand_look({}), Path("."), Path("."))
    assert html.count("gl-row") == 2 and "gl-sheen" in js


def test_carousel_copies_its_pictures(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.jpg").write_bytes(b"x")
    project = tmp_path / "p"
    project.mkdir()
    html, _ = davnai.motion_item(2, {"type": "carousel", "images": ["0.jpg", "1.jpg", "2.jpg"]}, 0.0, 3.0, 540, 960, davnai.brand_look({}), tmp_path, project)
    assert html.count("car-card") == 3 and (project / "m2_0.jpg").exists()


def test_studio_effects_are_listed_and_branded():
    effects = davnai.studio_effects()
    assert len(effects) >= 51 and "orbit" in effects and "settings-toggles" in effects
    text = davnai.ENGINE.read_text(encoding="utf-8").lower()
    assert "vibha" not in text and "claude" not in text.replace("claude-video-effects", "")


def test_studio_plan_uses_lines_not_times(tmp_path):
    for i in range(2):
        (tmp_path / f"{i}.png").write_bytes(b"x")
    resolve = lambda p: (tmp_path / p)  # noqa: E731
    items = [(2.0, 4.0, {"type": "studio", "effect": "orbit", "images": ["0.png", "1.png"], "lines": [3, 4]}),
             (5.0, 7.0, {"type": "studio", "effect": "cover-star", "text": "UP", "lines_text": ["a", "b"], "lines": [5, 5]}),
             (5.5, 7.0, {"type": "studio", "effect": "tap", "at_seconds": 1.0, "lines": [5, 5]}),
             (6.0, 7.0, {"type": "studio", "effect": "todo", "ticks_seconds": [0.5, 1], "lines": [6, 6]})]
    plan = davnai.studio_plan(items, 1.5, 0.0, resolve, tmp_path)
    assert plan[0]["fx"] == "orbit" and plan[0]["start"] == 0.5 and plan[0]["end"] == 2.5 and len(list(Path(plan[0]["images"]).iterdir())) == 2
    assert plan[1]["lines"] == "a|b" and "lines_text" not in plan[1]
    assert plan[2]["at"] == 5.0 and plan[3]["ticks"] == "5.00|5.50"
    with pytest.raises(davnai.Problem):
        davnai.studio_plan([(0, 1, {"type": "studio", "effect": "nope"})], 0, 0, resolve, tmp_path)


def test_studio_needs_its_parts(monkeypatch, tmp_path):
    monkeypatch.setattr(davnai, "MODELS_DIR", tmp_path / "none")
    assert davnai.studio_problem()
    monkeypatch.setattr(davnai, "ENGINE", tmp_path / "missing.py")
    assert "skill installed" in davnai.studio_problem() and davnai.studio_effects() == {}


@pytest.mark.skipif(not FFMPEG or davnai.studio_problem() is not None, reason="needs ffmpeg and the studio parts")
def test_studio_effect_renders(tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=180x320:d=2:r=30", "-c:v", "libx264", str(clip)], check=True)
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps({"effects": [{"fx": "backdrop-word", "start": 0.2, "end": 1.8, "text": "HI"}]}))
    out = tmp_path / "o.mp4"
    env = {**__import__("os").environ, "DAVNAI_MODELS": str(davnai.MODELS_DIR), "DAVNAI_FONTS": str(davnai.FONTS_DIR)}
    proc = subprocess.run([sys.executable, str(davnai.ENGINE), "--plan", str(plan), str(clip), str(out), "--width", "180"], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert davnai.probe(out)["width"] == 180


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_speech_audio_is_read_by_ffmpeg(tmp_path):
    pytest.importorskip("numpy")
    clip = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=1.5", "-f", "lavfi", "-i", "color=s=64x64:d=1.5", "-shortest", str(clip)], check=True)
    audio = davnai.speech_audio(clip)
    assert str(audio.dtype) == "float32" and abs(len(audio) / 16000 - 1.5) < 0.1


def test_new_windows_installs_are_found(tmp_path, monkeypatch):
    links = tmp_path / "Microsoft" / "WinGet" / "Links"
    links.mkdir(parents=True)
    monkeypatch.setattr(davnai.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PATH", "C:/x")
    davnai.find_new_installs()
    assert str(links) in __import__("os").environ["PATH"]


def test_split_words_are_joined_back():
    words = [["$7", 0, 1], [",000", 1, 2], ["at", 2, 3], ["8", 3, 4], ["%", 4, 5], ["non", 5, 6], ["-registered", 6, 7], ["it", 7, 8], ["'s", 8, 9], ["-", 9, 10], ["ok", 10, 11]]
    assert [w[0] for w in davnai.join_pieces(words)] == ["$7,000", "at", "8%", "non-registered", "it's", "-", "ok"]
    assert davnai.join_pieces(words)[0][1:] == [0, 2]


def test_zoom_splits_never_leave_slivers():
    pieces = davnai.split_pieces([{"s": 0.0, "e": 3.0}], [0.1, 1.0, 1.1, 2.95])
    assert [(p["s"], p["e"]) for p in pieces] == [(0.0, 1.0), (1.0, 3.0)]
    assert min(p["e"] - p["s"] for p in pieces) >= 0.25


def test_cuts_fade_and_the_sound_is_limited():
    assert davnai.CUT_FADE < 0.03 and "alimiter" in davnai.LIMITER and "acompressor" in davnai.VOICE_CLEAN


def test_scenes_move_the_video_and_fit_their_words():
    look = davnai.brand_look({})
    html, js = davnai.motion_item(0, {"type": "scene", "layout": "window", "background": "grid", "kicker": "The setup", "title": "Tax-sheltered compounding", "highlight": ["compounding"], "items": ["a", "b"]}, 1.0, 4.0, 540, 960, look, Path("."), Path("."))
    assert 'class="sc-bg"' in html and html.count("sc-row") == 2 and 'video.base' in js and "scale:0.44" in js
    assert davnai.fit_title("Tax-sheltered compounding", 465, 60, 59) < davnai.fit_title("Tax-sheltered compounding", 465, 200, 59)
    paper, _ = davnai.motion_item(1, {"type": "scene", "background": "light", "title": "$0 tax", "highlight": ["$0"]}, 0, 3, 540, 960, look, Path("."), Path("."))
    assert "background:" + look["accent"] in paper  # a highlighter behind the word on paper, not yellow text
    assert davnai.readable_accent("#FFE14D", True) == "#1F1F1F" and davnai.readable_accent("#1E40AF", True) == "#1E40AF"
    with pytest.raises(davnai.Problem):
        davnai.motion_item(2, {"type": "scene", "layout": "diamond"}, 0, 3, 540, 960, look, Path("."), Path("."))


def test_words_inside_a_line_can_time_things():
    words = [["a", 1.0, 1.2, 4], ["b", 1.3, 1.5, 4], ["c", 1.6, 1.9, 4], ["d", 2.5, 2.8, 5]]
    assert davnai.word_span(words, [4, 2], [5, 1]) == (1.3, 2.8)
    assert davnai.word_span(words, [4, 3]) == (1.6, 1.9)
    assert davnai.word_span(words, [9, 1]) is None
    assert davnai.fx_window({"type": "bw", "from": [4, 2], "to": [4, 3]}, words, 10) == pytest.approx((1.25, 1.95))


def test_captions_shift_for_an_intro_and_step_aside_for_scenes(tmp_path):
    text = "Dialogue: 0,0:00:01.50,0:00:02.00,Davnai,,0,0,0,,hi"
    assert "0:00:03.50,0:00:04.00" in davnai.shift_ass(text, 2.0)
    words = [["hello", 0.5, 0.8, 1], ["there", 0.9, 1.2, 1], ["after", 5.0, 5.3, 2]]
    ass = tmp_path / "c.ass"
    davnai.write_ass(ass, 540, 960, {"captions": True, "caption_words": 2}, {}, words, 6, hide=[(0.0, 2.0)])
    events = [ln for ln in ass.read_text().splitlines() if ln.startswith("Dialogue")]
    low = [e for e in events if "hello" in e.lower()]
    assert low and all(",0,0,53,," in e and "\\an2" in e for e in low)  # still shown, at the bottom of the frame
    assert any("after" in e.lower() and ",0,0,0,," in e for e in events)


def test_pace_and_picture_sounds():
    nums = davnai.pace_numbers([2.0, 4.0, 9.0], 10.0, [["a", 0.5, 0.7, 1], ["b", 0.8, 1.0, 1]])
    assert nums["visual_changes"] == 3 and nums["longest_still_seconds"] == 5.0 and nums["first_word_seconds"] == 0.5
    words = [["a", 1.0, 1.2, 1], ["b", 1.25, 1.4, 1], ["c", 3.0, 3.3, 2]]
    sounds = davnai.picture_sounds({"zoom": [{"lines": [1, 1]}, {"lines": [2, 2], "style": "smooth"}], "fx": [{"type": "behind", "text": "X", "lines": [1, 1]}, {"type": "glitch", "lines": [2, 2]}]}, words, 5, [])
    assert [n for _, n in sounds] == ["impact", "whoosh"]  # the zoom's swoosh would land on the hit: thinned
    assert "sidechaincompress" in davnai.DUCK and "dynaudnorm" in davnai.VOICE_CLEAN
