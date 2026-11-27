# Effects

Start with a theme (`themes.md`): it sets captions, titles, graphics, transitions, colour and sounds in one word. Then add effects below for this video.

Animated graphics (titles, lower thirds, counters, lists, charts, end screens) are in `motion.md`. Add these to an output in `plan.json`. Lines are transcript line numbers (never times). Use a few that fit the video; more isn't better. Captions, a strong hook and pace matter most; the rest is seasoning.

| What | In the plan | Notes |
|---|---|---|
| Animated captions | `"captions": true, "caption_animation": "pop"` | pop, bounce, fade, slide, type (word by word), none. Default: the Brand Kit's. |
| Key words stand out | `"emphasis": ["free", "mistake"]` | Bigger, in the accent colour. |
| Hook title | `"hook_text": "3 mistakes nobody tells you", "hook_seconds": 3` | Big title in the brand colour at the start. `\n` for a new line. |
| Text callouts | `"texts": [{ "lines": [20, 21], "text": "Step 2", "position": "top" }]` | Shown while those lines are spoken. top, middle, bottom. |
| Auto zoom | `"auto_zoom": true` | Jump-cut punch-ins: every other line slightly closer. |
| Zoom on a moment | `"zoom": [{ "lines": [14, 15], "amount": 1.2, "style": "smooth" }]` | punch (instant) or smooth (slow push-in). |
| Transitions | `"transition": "flash"` | Between the parts in `keep` (or scenes): cut, flash, fade, dissolve, whip, slide, slide_up, zoom, wipe, circle, glitch, blur. Talking videos: cut or flash. |
| B-roll cutaway | `"broll": [{ "lines": [20, 22], "clip": "clips/office.mp4" }]` | Covers the speaker while they keep talking. A picture works too. `start` skips into the clip. |
| Picture-in-picture | `"broll": [{ "lines": [30, 31], "clip": "shots/app.png", "mode": "pip", "position": "top-right" }]` | Small framed window. `"mode": "sticker"` for a small picture without a frame (an emoji or icon). |
| Blurred background | `"fill": "blur"` | A wide video in a tall frame without cropping: the whole picture over a blurred copy (podcasts, screen recordings). |
| Colour look | `"look": "warm"` | warm, cool, vivid, punchy, bw, cinematic, soft, vintage, retro (with film grain). |
| Progress bar | `"progress_bar": true` | Thin bar in the brand colour (bottom; `"top"` for the top). |
| Sound effects | `"sfx": [{ "line": 14, "file": "whoosh", "volume": 0.6 }]` | Plays as that line starts. Built-in sounds (made on the computer, nothing to licence): whoosh, swoosh, pop, click, ding, impact, riser, glitch; or a file of theirs. Themes add a sound on each transition and graphic; `"sounds": false` turns those off. |
| Music | `"music": "music/calm.mp3", "music_volume": 0.12` | Under the voice, for the whole video. |
| Speed | `"speed": 1.1` | 0.5 to 2. 1.05 to 1.15 tightens a slow talker. |
| Cleaner voice | `"clean_audio": true` | Takes out hum and background hiss. |
| Even loudness | on by default | Levels the sound for social apps; `"loudness": false` to turn it off. |
| Logo | `"logo": true` | The Brand Kit logo, top corner. |
| End card | `"end_card": { "text": "Follow @handle", "seconds": 2.5 }` | Brand colour card at the end. Text defaults to their handle. |
| Intro and outro | `"intro": true, "outro": true` | Their own intro and outro videos from the Brand Kit. |

## Styles that work

- **Talking head Short:** captions (pop), hook_text, auto_zoom, tighten, transition cut or flash, progress_bar, end_card.
- **Podcast clip:** fill blur (if wide), captions, emphasis, zoom on the punchline, clean_audio.
- **Tutorial:** texts for each step, pip for close-ups, captions optional, no music under explanations.
- **Faceless:** captions (bounce or type), scenes every 2 to 5 s, transition slide or dissolve, music, look.
- **Calm or premium:** captions fade, look soft or cinematic, transition dissolve, no sound effects.
- **Long YouTube edit:** tighten, logo, intro and outro, a few texts, zooms on key moments only.

## Signature effects (timed by lines)

Add `"fx": [ ... ]` to an output. Each effect has a `type` and `"lines": [first, last]` (or `"all": true`, `"at": "start"`/`"end"` with `"seconds"`), plus optional `"strength"` (default 1).

| type | what it does |
|---|---|
| `behind` | **Big words behind the person**: `{ "type": "behind", "text": "MONEY", "lines": [12, 13] }`. The person is cut out (on this computer, with HyperFrames; needs `setup --motion`) and put back in front of the words. Captions pause during it. Optional `"y"` (0 to 1, height of the words, default 0.38), `"color"`. Add `"slice": true` and each word slams in on its own line, from alternating sides, on the music's beats (evenly without music); every other word uses the accent (or `"color2"`). Best on a clear shot of one person. |
| `relight` | **Relight the person**: `{ "type": "relight", "light": "neon", "lines": [4, 6] }`. Lights: `spotlight` (room darkens, light on the face), `low_key` (moody, dark room), `silhouette` (dark figure on a bright background), `neon` (coloured glow behind the person; brand accent or `"color"`), `rim` (thin bright edge), `under_light` (warm light from below), `golden_hour` (warm sunset grade, no cut-out needed). Uses the same cut-out as `behind`. |
| `poster` | **Poster moment**: `{ "type": "poster", "text": "LEVEL UP", "sub": "Episode 4", "lines": [9, 9] }`. The picture freezes on that moment and becomes a poster: halftone background in the brand colour (or `"background"`), the title huge behind the person, a paper border. The voice keeps going. Uses the cut-out. |
| `compare` | **Before and after**: `{ "type": "compare", "lines": [3, 4] }`. Left half: the picture before looks and effects; right half: the finished edit; a divider and labels (`"labels": ["RAW", "EDIT"]`). Pair it with a look or effect on the same lines so the difference shows. |
| `cycle` | **Pictures cycling behind you**: `{ "type": "cycle", "images": ["pics/1.jpg", "pics/2.jpg", "pics/3.jpg"], "lines": [4, 5] }`. The pictures change on each beat of the music (or every `"every"` seconds, default 0.4) behind the person, who is cut out in front. `"behind": false` puts them over the whole frame (with `"opacity"`), no cut-out needed. Use the person's own screenshots first, then stock. |
| `studio` | **51 ready-made studio effects** that track the face: `{ "type": "studio", "effect": "orbit", "images": [...], "lines": [4, 5] }`. The list and their options are in `reference/studio.md`. |
| `custom` | **Your own effect**: `{ "type": "custom", "filter": "hue=h=90*t,eq=contrast=1.3", "lines": [8, 9] }`. Any ffmpeg filter chain (one chain, filters joined by commas; `t` is the time). It's tried on a blank frame first, and only plays on its lines. Use it for anything the list doesn't have. |
| `shake` | camera shake for impact |
| `flash` | a quick bright flash (0.15 s) on a punchline or a cut |
| `rgb` | colour-split (chromatic) look |
| `glitch` | glitchy colour split, noise and jitter |
| `blur` | soft blur (a dreamy or "focus" moment) |
| `bw` | black and white for a moment (a flashback, a "before") |
| `vhs` | old tape look: faded colour, scan lines, noise |
| `grain` | film grain (use `"all": true` for the whole video) |
| `light_leak` | warm light washing across; `"colours": ["0xFF8A00", "0xFF2D55"]` to change |

## Face-aware placement

On by default for recordings (needs `opencv-python-headless`, installed by `setup`). The script finds the speaker's face and:
- keeps it in a tall crop when a wide video becomes 9:16 (unless the plan sets `focus_x` or `"fill": "blur"`);
- moves captions to the nearest place that doesn't cover the face (unless the plan sets `caption_position`);
- moves titles, counters, lists, charts and lower thirds off the face (unless the graphic has its own `position`);
- puts relight glows around the face.

The quality check reports "captions clear of faces". Turn it off with `"face_aware": false` on the output.

## Split screen

`"split": { "clip": "clips/gameplay.mp4", "position": "bottom", "share": 0.4 }`: the edit on one part, another clip on the other (gameplay, a demo, B-roll, a reaction). `position` top or bottom, `share` 0.25 to 0.6 of the height. Captions move to the middle line unless you set `caption_position`.

## Music beats

- `"beat_pulse": true` (with `"music"`): a small zoom bump on every beat (`"beat_amount": 0.04`).
- `"beat_cuts": true` (faceless videos with `"music"`): scene changes move onto the nearest beat (within 0.3 s).
