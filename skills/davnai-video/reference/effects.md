# Effects

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
| Colour look | `"look": "warm"` | warm, cool, vivid, punchy, bw, cinematic, soft, vintage. |
| Progress bar | `"progress_bar": true` | Thin bar in the brand colour (bottom; `"top"` for the top). |
| Sound effects | `"sfx": [{ "line": 14, "file": "sounds/whoosh.mp3", "volume": 0.6 }]` | Plays as that line starts. Their own or free sound files. |
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
