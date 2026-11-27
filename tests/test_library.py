"""The visible library, theme files and examples always match the script."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "davnai-video" / "scripts"))
sys.path.insert(0, str(ROOT / "tools"))
import build_library  # noqa: E402
import davnai  # noqa: E402

BUILT_IN = davnai.BUILT_IN_THEMES


def test_library_pages_are_up_to_date():
    for rel, text in build_library.build().items():
        assert (ROOT / "library" / rel).read_text(encoding="utf-8") == text, f"run python tools/build_library.py ({rel})"
    for name in davnai.SOUND_RECIPES:
        assert (ROOT / "library" / "sounds" / f"{name}.wav").exists()


def test_theme_files_are_written_from_the_script():
    for name, text in build_library.theme_files().items():
        assert (ROOT / "skills" / "davnai-video" / "themes" / f"{name}.json").read_text(encoding="utf-8") == text, "run python tools/build_library.py"


def test_theme_files_match_the_built_in_themes():
    """The script carries its own copy so the one-file download still has every theme."""
    files = sorted((ROOT / "skills" / "davnai-video" / "themes").glob("*.json"))
    assert len(files) == 12
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.pop("name")
        css = data.pop("css", None)
        assert data == BUILT_IN[name], path.name
        assert css == davnai.BUILT_IN_CSS.get(name), path.name
    assert davnai.THEME_FILE_PROBLEMS == []


def test_examples_only_use_things_that_exist():
    for path in sorted((ROOT / "examples").glob("*.json")):
        plan = json.loads(path.read_text(encoding="utf-8"))
        assert plan.get("_about"), path.name
        for out in plan["outputs"]:
            theme = out.get("theme") or plan.get("theme")
            assert theme is None or theme in davnai.THEMES, path.name
            assert out.get("transition") in (None, "cut", *davnai.TRANSITIONS), path.name
            assert out.get("look") in (None, *davnai.LOOKS), path.name
            assert all(f["type"] in davnai.FX_TYPES for f in out.get("fx", [])), path.name
            assert all(m["type"] in davnai.MOTION_TYPES for m in out.get("motion", [])), path.name
            assert out.get("keep") or out.get("scenes"), path.name


def test_your_own_theme_file_is_picked_up(tmp_path, monkeypatch):
    monkeypatch.setattr(davnai, "BRAND_DIR", tmp_path / "brand")
    own = tmp_path / "themes"
    own.mkdir()
    (own / "mine.json").write_text(json.dumps({"name": "mine", "base": "bold", "about": "Mine", "caption": {"words": 3}}))
    (own / "broken.json").write_text(json.dumps({"name": "broken", "caption_font": "Comic.ttf"}))
    problems = davnai.load_theme_files()
    try:
        assert davnai.THEMES["mine"]["caption"]["words"] == 3 and davnai.THEMES["mine"]["caption_font"] == "Anton-Regular.ttf"
        assert "broken" not in davnai.THEMES and any("broken.json" in p for p in problems)
    finally:
        davnai.THEMES.pop("mine", None)
