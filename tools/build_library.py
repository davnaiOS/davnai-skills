"""Builds library/ (one page per theme, effect, graphic, transition, look, caption animation and sound) from the
script's own lists, so the pages always match what davnai.py can do. Run: python tools/build_library.py
(tests/test_library.py fails when the pages are out of date)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "davnai-video" / "scripts"))
import davnai  # noqa: E402

LIB = ROOT / "library"

EFFECTS = {
    "behind": ("Big words behind the person", "The person is cut out and put back in front of huge words, so the words sit behind them.", "Hooks, a key word, a reveal. Add \"slice\": true and each word slams in on its own beat of the music.", '{ "type": "behind", "text": "STOP DOING THIS", "slice": true, "lines": [12, 13] }'),
    "poster": ("Poster moment", "The picture freezes and turns into a poster: a halftone background in your brand colour, a huge title behind the person and a paper border, while the voice carries on.", "The big line, a chapter opener, a thumbnail-worthy moment.", '{ "type": "poster", "text": "LEVEL UP", "sub": "Episode 4", "lines": [9, 9] }'),
    "compare": ("Before and after", "The left half shows the picture before looks and effects, the right half the finished edit, with labels and a divider.", "Showing off the edit, tutorials, transformations.", '{ "type": "compare", "labels": ["RAW", "EDIT"], "lines": [3, 4] }'),
    "relight": ("Relight the person", "Changes the light around the speaker: spotlight, low_key, silhouette, neon, rim, under_light or golden_hour. The person is cut out so the light hits the room and the person separately (golden_hour needs no cut-out).", "Hooks, dramatic lines, a mood change, music videos.", '{ "type": "relight", "light": "neon", "lines": [4, 6] }'),
    "cycle": ("Pictures cycling behind you", "Pictures (screenshots, products, places, stock) flick past behind the person on each beat of the music (or every 0.4 s), with the person cut out in front. Add \"behind\": false to flick them over the whole frame instead.", "Lists, \"I tried 10 apps\", travel, hooks.", '{ "type": "cycle", "images": ["pics/1.jpg", "pics/2.jpg", "pics/3.jpg"], "lines": [4, 5] }'),
    "studio": ("Studio effects (51)", "Ready-made effects that track the face and can sit behind the person: orbiting pictures, glass widgets, comment boxes, tier lists, checklists, magazine covers and more. The full list is on its own page.", "Hooks, lists, proof, reveals: see the list.", '{ "type": "studio", "effect": "orbit", "images": ["shots/1.png", "shots/2.png", "shots/3.png"], "lines": [4, 5] }'),
    "custom": ("Your own effect", "Any ffmpeg filter chain your AI writes, timed to transcript lines and checked on a blank frame first. For looks the list doesn't have yet.", "Anything: thermal camera, colour cycling, mirror, pixelate, edge glow.", '{ "type": "custom", "filter": "hue=h=90*t,eq=contrast=1.3", "lines": [8, 9] }'),
    "shake": ("Camera shake", "A short handheld shake.", "Impact moments, punchlines, surprises.", '{ "type": "shake", "lines": [8, 8] }'),
    "flash": ("Flash", "A quick bright flash (0.15 s).", "A cut on the beat, a reveal.", '{ "type": "flash", "lines": [5, 5] }'),
    "rgb": ("Colour split", "Red and blue separate for a chromatic look.", "Energy, tech, music.", '{ "type": "rgb", "lines": [3, 4] }'),
    "glitch": ("Glitch", "Colour split, noise and jitter.", "Tech, gaming, a 'wait, what?' moment.", '{ "type": "glitch", "lines": [9, 9] }'),
    "blur": ("Blur", "A soft blur.", "A dreamy or thinking moment, behind a title.", '{ "type": "blur", "lines": [2, 2] }'),
    "bw": ("Black and white", "Black and white for a moment.", "Flashbacks, 'before', serious points.", '{ "type": "bw", "lines": [6, 7] }'),
    "vhs": ("VHS tape", "Faded colour, scan lines, noise.", "Nostalgia, throwbacks, old clips.", '{ "type": "vhs", "lines": [10, 12] }'),
    "grain": ("Film grain", "Fine moving grain.", "A film feel; usually the whole video.", '{ "type": "grain", "all": true }'),
    "light_leak": ("Light leak", "Warm light washes across the picture.", "Openers, travel, lifestyle, soft transitions.", '{ "type": "light_leak", "lines": [1, 2] }'),
}
MOTION = {
    "title": ("Animated title", "A headline in a brand-colour box: pop, slide, bounce, words, typewriter or glow.", '{ "type": "title", "text": "3 mistakes nobody tells you", "style": "words", "at": "start", "seconds": 2.5 }'),
    "lower_third": ("Name tag", "Name and role slide in with an accent bar.", '{ "type": "lower_third", "name": "Ada Obi", "role": "Founder", "lines": [2, 3] }'),
    "callout": ("Callout", "A bubble that pops in and wiggles.", '{ "type": "callout", "text": "FREE", "emoji": "🔥", "position": "top-right", "lines": [7, 7] }'),
    "emoji": ("Emoji", "A big emoji pops in.", '{ "type": "emoji", "emoji": "😱", "position": "middle", "lines": [4, 4] }'),
    "counter": ("Counter", "A number counts up.", '{ "type": "counter", "from": 0, "to": 10000, "suffix": "+", "label": "followers", "lines": [9, 9] }'),
    "list": ("List", "Points tick in one by one.", '{ "type": "list", "title": "3 steps", "items": ["Plan", "Film", "Post"], "lines": [14, 18] }'),
    "chart": ("Chart", "Bars grow in.", '{ "type": "chart", "title": "Views", "bars": [{ "label": "Jan", "value": 10 }, { "label": "Feb", "value": 40 }], "lines": [20, 21] }'),
    "quote": ("Quote card", "A full-screen quote in the brand colour.", '{ "type": "quote", "text": "Done beats perfect.", "author": "Ada", "lines": [11, 11] }'),
    "feed": ("Feed scroll", "Your video plays inside a social post that scrolls up a phone feed into place (with your handle, a like and a caption), then zooms back to full screen.", '{ "type": "feed", "caption": "this changed everything", "likes": "12.4K", "lines": [5, 6] }'),
    "flythrough": ("Chapter flythrough", "A 'coming up' opener: a card per chapter, with a still from that moment and its title, flies past in 3D.", '{ "type": "flythrough", "at": "start", "chapters": [{ "text": "The setup", "line": 4 }, { "text": "The twist", "line": 18 }] }'),
    "scene": ("Scene", "Your video moves into a card, a small window or the lower half over a designed background (grid, gradient, dark, paper, dots, a colour or a picture), with a headline, a list or a counting number, then back to full screen. The main tool for making a talking video feel designed.", '{ "type": "scene", "layout": "window", "background": "grid", "kicker": "The setup", "title": "$7,000 a year for 30 years", "highlight": ["$7,000"], "lines": [4, 5] }'),
    "glass": ("Glass panel", "A frosted-glass card over the video (the picture shows through, blurred) with an icon, a title, a line or a list, and a light sheen.", '{ "type": "glass", "icon": "💡", "title": "3 quick wins", "items": ["Cut the pauses", "Hook in 2 s"], "lines": [6, 7] }'),
    "carousel": ("Picture carousel", "Pictures on a slowly turning 3D ring over the video, kept off the face and the captions.", '{ "type": "carousel", "images": ["pics/1.jpg", "pics/2.jpg", "pics/3.jpg", "pics/4.jpg"], "lines": [10, 11] }'),
    "chapter": ("Chapter card", "A full-screen chapter card wipes in and out.", '{ "type": "chapter", "number": 2, "text": "Filming", "lines": [15, 15] }'),
    "end_screen": ("End screen", "Logo, text, handle and a pulsing button.", '{ "type": "end_screen", "text": "Follow for more", "at": "end", "seconds": 3 }'),
    "block": ("Catalog scene", "Any of HyperFrames' ready-made scenes (follow buttons, phone screens, charts).", '{ "type": "block", "name": "tiktok-follow", "at": "end", "seconds": 3 }'),
    "custom": ("Your own graphic", "An HTML fragment your AI writes, animated with GSAP.", '{ "type": "custom", "html": "motion/burst.html", "lines": [12, 12] }'),
}
TRANSITIONS = {
    "fade": "Dips to black.", "flash": "A white flash.", "dissolve": "One shot melts into the next.", "whip": "A fast smooth slide.",
    "slide": "Slides left.", "slide_up": "Slides up.", "zoom": "Zooms into the next shot.", "wipe": "A straight wipe.",
    "circle": "Opens in a circle.", "glitch": "A pixel glitch.", "blur": "A horizontal blur.",
}
LOOKS = {
    "warm": "Golden, friendly.", "cool": "Blue, clean.", "vivid": "Rich colour.", "punchy": "Contrast and sharpness.", "bw": "Black and white.",
    "cinematic": "Film colour with a vignette.", "soft": "Gentle and bright.", "vintage": "Faded film.", "retro": "Faded film with grain.",
}
ANIMS = {"pop": "Grows in.", "bounce": "Drops and bounces.", "fade": "Fades in.", "slide": "Tips forward into place.", "type": "Word by word.", "none": "Appears."}
SOUNDS = {"whoosh": "Air rushing past.", "swoosh": "A light quick swish.", "pop": "A bubbly pop.", "click": "A crisp tick.", "ding": "A bell.", "impact": "A deep hit.", "riser": "Rising tension.", "glitch": "A digital stutter."}


def page(title: str, *parts: str) -> str:
    return f"# {title}\n\n" + "\n\n".join(p.strip() for p in parts if p) + "\n"


def build() -> dict[str, str]:
    assert set(EFFECTS) == set(davnai.FX_TYPES), "describe every effect"
    assert set(MOTION) == set(davnai.MOTION_TYPES), "describe every graphic"
    assert set(TRANSITIONS) == set(davnai.TRANSITIONS) and set(LOOKS) == set(davnai.LOOKS) and set(SOUNDS) == set(davnai.SOUND_RECIPES)
    files: dict[str, str] = {}
    index = ["# Library", "", "Everything the Davnai skill can put in a video. Each page says what it does, when to use it and the exact plan line. Pictures of each are in [gallery/](../gallery/) as they're added.", ""]

    index += ["## Themes (12)", "", "| theme | feels | fonts | defaults |", "|---|---|---|---|"]
    for name, t in davnai.THEMES.items():
        fonts = f"{davnai.FONT_SOURCES[t['caption_font']][0]} / {davnai.FONT_SOURCES[t['title_font']][0]}"
        defaults = ", ".join(f"{k} {v}" for k, v in t["defaults"].items()) or "none"
        index.append(f"| [{name}](themes/{name}.md) | {t['about']} | {fonts} | {defaults} |")

    for name, t in davnai.BUILT_IN_THEMES.items():
        cap = t["caption"]
        files[f"themes/{name}.md"] = page(
            f"Theme: {name}", t["about"],
            "| | |\n|---|---|\n"
            f"| Fonts | captions {davnai.FONT_SOURCES[t['caption_font']][0]}, titles {davnai.FONT_SOURCES[t['title_font']][0]} |\n"
            f"| Captions | {cap['words']} words, {cap['place']}, {cap['anim']} animation{', uppercase' if cap.get('upper') else ''}{', glow' if cap.get('glow') else ''}{', in a box' if cap.get('box') else ''} |\n"
            f"| Titles | {', '.join(t.get('title_styles') or [t['title_style']])} |\n"
            f"| Transitions | {t['defaults'].get('transition', 'cut')} (also {', '.join(t.get('other_transitions') or [])}) |\n"
            f"| Colour | {t['defaults'].get('look', 'natural')}{', film grain' if t.get('grain') else ''} |\n"
            f"| Frame | {t.get('frame', 'none')} |\n"
            f"| On emphasised words | {t.get('emphasis_fx', 'none')} |\n"
            f"| Sounds | {', '.join(f'{k}: {v}' for k, v in t['sounds'].items()) or 'none'} |\n"
            f"| Own colours (no Brand Kit) | {' and '.join(t['colours'])} |\n"
            f"| Catalog pieces that suit it | {', '.join(t.get('catalog') or [])} |",
            f'```json\n"theme": "{name}"\n```',
            f"The file: [themes/{name}.json](../../skills/davnai-video/themes/{name}.json). Copy it to `~/.davnai/themes/` to make your own. `\"theme_extras\": false` turns off the frame, grain and emphasis effects.")

    index += ["", f"## Signature effects ({len(EFFECTS)})", "", "| effect | what it does | plan |", "|---|---|---|"]
    for key, (title, what, when, plan) in EFFECTS.items():
        files[f"effects/{key}.md"] = page(title, what, f"**Use it for:** {when}", f'**In the plan** (inside `"fx": [...]`):\n\n```json\n{plan}\n```', "Optional: `\"strength\"` (default 1). Place it with `\"lines\"`, `\"all\": true` or `\"at\": \"start\"`/`\"end\"`.")
        index.append(f"| [{title}](effects/{key}.md) | {what} | `\"type\": \"{key}\"` |")

    studio = davnai.studio_effects()
    assert len(studio) >= 51, "the studio engine lists its effects"
    index += ["", f"## Studio effects ({len(studio)})", "", "They track the face and can sit behind the person. Options for each: [reference/studio.md](../skills/davnai-video/reference/studio.md).", "", "| effect | what it does |", "|---|---|"]
    rows = [f"| `{k}` | {v[:1].upper() + v[1:]} |" for k, v in studio.items()]
    index += rows
    files["studio.md"] = page(f"Studio effects ({len(studio)})", "Ready-made effects that track the face and can sit behind the person, drawn on your computer by the studio engine (set up by `python davnai.py setup`). Time them with transcript lines like any effect.",
                              '```json\n{ "type": "studio", "effect": "glass-widgets", "text": "12", "lines": [9, 10] }\n```', "| effect | what it does |\n|---|---|\n" + "\n".join(rows),
                              "Options for each: [reference/studio.md](../skills/davnai-video/reference/studio.md). The engine is adapted from open-source work: see [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).")

    index += ["", f"## Motion graphics ({len(MOTION)})", "", "In the brand's colours and fonts, made with HyperFrames (`setup --motion`).", "", "| graphic | what it does |", "|---|---|"]
    for key, (title, what, plan) in MOTION.items():
        files[f"motion/{key}.md"] = page(title, what, f'**In the plan** (inside `"motion": [...]`):\n\n```json\n{plan}\n```', "Full options: [reference/motion.md](../../skills/davnai-video/reference/motion.md).")
        index.append(f"| [{title}](motion/{key}.md) | {what} |")

    index += ["", f"## Transitions ({len(TRANSITIONS)})", "", "Between the parts of `keep` (or faceless scenes): `\"transition\": \"<name>\"`.", ""]
    index += [f"- **{k}**: {v}" for k, v in TRANSITIONS.items()]
    files["transitions.md"] = page("Transitions", "\n".join(f"- **{k}**: {v}" for k, v in TRANSITIONS.items()), '```json\n"transition": "flash"\n```', "Themes pick one for you; the plan can change it. Talking videos: cut or flash. Faceless: slide or dissolve.")

    index += ["", f"## Colour looks ({len(LOOKS)})", "", "`\"look\": \"<name>\"`.", ""]
    index += [f"- **{k}**: {v}" for k, v in LOOKS.items()]
    files["looks.md"] = page("Colour looks", "\n".join(f"- **{k}**: {v}" for k, v in LOOKS.items()), '```json\n"look": "warm"\n```')

    index += ["", f"## Caption animations ({len(ANIMS)})", "", "`\"caption_animation\": \"<name>\"` (or the theme's).", ""]
    index += [f"- **{k}**: {v}" for k, v in ANIMS.items()]
    files["captions.md"] = page("Caption animations", "\n".join(f"- **{k}**: {v}" for k, v in ANIMS.items()), '```json\n"captions": true,\n"caption_animation": "pop",\n"emphasis": ["free", "mistake"]\n```', "Captions use the Brand Kit's caption style or the theme's, and keep clear of the app buttons on tall videos.")

    index += ["", f"## Built-in sounds ({len(SOUNDS)})", "", "Made by ffmpeg on your computer: nothing to licence. Listen in [sounds/](sounds/).", ""]
    index += [f"- **{k}** ([listen](sounds/{k}.wav)): {v}" for k, v in SOUNDS.items()]
    files["sounds.md"] = page("Built-in sounds", "\n".join(f"- **{k}** ([listen](sounds/{k}.wav)): {v}" for k, v in SOUNDS.items()), '```json\n"sfx": [{ "line": 14, "file": "whoosh" }]\n```', "Themes add a sound on each transition and graphic; `\"sounds\": false` turns those off.")

    index += ["", "## More", "", "- Split screen, beat sync, B-roll, picture-in-picture, zoom, speed, music, end cards: [reference/effects.md](../skills/davnai-video/reference/effects.md)",
              "- 448 ready-made HyperFrames pieces: `python davnai.py catalog <words>`", "- Ready plans to copy: [examples/](../examples/)"]
    files["README.md"] = "\n".join(index) + "\n"
    return files


def theme_files() -> dict[str, str]:
    """The themes as files, from the script's built-in copy (so the one-file download and the files never differ)."""
    import json

    out = {}
    for name, t in davnai.BUILT_IN_THEMES.items():
        data = {"name": name, **t}
        if name in davnai.BUILT_IN_CSS:
            data["css"] = davnai.BUILT_IN_CSS[name]
        out[name] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return out


def write() -> None:
    folder = ROOT / "skills" / "davnai-video" / "themes"
    for name, text in theme_files().items():
        (folder / f"{name}.json").write_text(text, encoding="utf-8")
    for rel, text in build().items():
        path = LIB / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sounds = LIB / "sounds"
    sounds.mkdir(exist_ok=True)
    davnai.SOUNDS_DIR = sounds
    for name in davnai.SOUND_RECIPES:
        davnai.sound_file(name)
    print(f"Wrote {LIB}")


if __name__ == "__main__":
    write()
