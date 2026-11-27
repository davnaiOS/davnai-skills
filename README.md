# Davnai skills

**Edit with your own AI. Post and grow with Davnai.**

Skills that teach your AI (Claude, ChatGPT and Codex, Gemini, Cursor and other apps that read [Agent Skills](https://agentskills.io)) to edit videos on your own computer the Davnai way, then hand the finished video to [Davnai](https://davnai.com) to post everywhere, answer comments and grow your contacts.

- **Shorts, Reels and TikToks** from one recording: the best moments, hook first.
- **Full edits** for YouTube, lessons and podcasts: mistakes, repeats and dead air removed.
- **Faceless videos** from stock clips or pictures and a voice-over.
- **12 themes:** clean, bold, editorial, neon, minimal, playful, news, tech, retro, luxury, handwritten and podcast. Each is a complete look (caption font and animation, titles, graphic shapes, transitions, colour grade and sounds), recoloured with your brand, or build your own.
- **Your brand everywhere:** captions in your Brand Kit style, your logo, your own intro and outro.
- **Effects:** animated captions, hook titles, text callouts, auto zoom, transitions, B-roll and picture-in-picture, blurred backgrounds, colour looks, progress bars, sound effects, music, end cards.
- **Motion graphics** with [HyperFrames](https://github.com/heygen-com/hyperframes): animated titles, lower thirds, callouts, counters, lists, charts, quote and chapter cards, end screens, a feed scroll (your video inside a social post), a 3D chapter flythrough, any of HyperFrames' 448 catalog pieces, or anything your AI writes in HTML, all in your brand.
- **Signature effects:** big words behind you (the person is cut out on your computer), sliced on the music's beat, poster moments (the frame freezes into a halftone poster), before and after, relighting (spotlight, neon glow, silhouette, rim light, golden hour), shake, flash, colour split, glitch, VHS, grain, light leaks, split screen (gameplay or B-roll underneath) and zoom pulses on the music's beat.
- **Face-aware:** the speaker stays in frame when a wide video becomes vertical, and captions and titles move off their face.
- **Storyboard first:** a scene-by-scene plan and a picture page to approve before anything is rendered.
- **Free voice-overs** made on your computer for faceless videos, and built-in sound effects (whoosh, pop, impact, riser...).
- **Quality checks** on every render: black or frozen picture, loudness for social apps, long silences, captions covering a face.
- **Review page:** you mark moments on the video (change, cut, keep, question) and your AI gets your notes as transcript lines; it remembers your lasting preferences and can match the style of a reel you like.
- **You approve everything:** quick previews first, the final only when you say so, and posts wait for your OK in Davnai.
- **Cheaper:** the editing runs on your computer with free tools (ffmpeg and a local speech model), and the AI picks moments by line number instead of guessing times, so it uses far fewer tokens.

## The skills

| Skill | What it does |
|---|---|
| `davnai-video` | Edits on your computer: Shorts, full edits, faceless videos, 12 themes, motion graphics, effects, storyboard, review page, quality checks, upload to Davnai. |
| `davnai-posts` | Writes posts in your voice for each platform, grades drafts (with the 3 fixes that matter most), turns one video into a week of content and schedules it in Davnai for your approval. |
| `davnai-hooks` | 100 hook formulas in ten families for first lines, Short titles and the first words on camera. |
| `davnai-coach` | The front door: works out your goal, reads what Davnai knows (Brand Kit, accounts, results) and runs the right skill or Davnai tool, including comment-to-DM automations. |

## Get started

1. **Connect Davnai** to your AI app: add the connector with the address `https://davnai.com/mcp` and sign in. (In Claude and ChatGPT, look for Davnai in the connectors list.)
2. **Install the skill:**
   - **Claude Code:** `/plugin marketplace add davnaiOS/davnai-skills`, then `/plugin install davnai@davnai` (this also connects Davnai).
   - **Codex:** `$skill-installer` with `https://github.com/davnaiOS/davnai-skills/tree/main/skills/davnai-video` (and the other skills), or copy the folders in `skills/` to `~/.codex/skills/`.
   - **Gemini CLI, Cursor, Copilot and others:** copy the folders in `skills/` into the app's skills folder (for example `.agents/skills/`, `.gemini/skills/`, `.github/skills/`).
   - **No skill installed?** Davnai's connector serves the same guide (`get_editing_guide`), so connecting Davnai is enough to start.
3. **Ask**, for example:
   - "Make 3 Shorts from interview.mp4 and post them to TikTok and Instagram on Friday."
   - "Edit my lesson recording for YouTube: remove the mistakes and add my intro."
   - "Make a 30-second faceless video from my voice-over and the clips in my B-roll folder."

## What you need

Your AI sets this up for you: it runs `python davnai.py check`, asks you, then `python davnai.py setup` installs what's missing (ffmpeg, the speech-to-text model and the brand fonts; add `--motion` for motion graphics, which adds Node.js, HyperFrames and GSAP).

- Python 3.9 or newer (Windows: `winget install -e --id Python.Python.3.12`; Mac: `brew install python`).
- [ffmpeg](https://ffmpeg.org/download.html) and `faster-whisper` (installed by `setup`; transcripts run on your computer, and the first one downloads a speech model).
- Optional, for motion graphics and voice-overs: Node.js 22+ and HyperFrames (`setup --motion`, a few hundred MB).
- An AI app that can run commands on your computer (Claude Code, Claude desktop with a folder, Codex, Gemini CLI, Cursor). In ChatGPT or Claude in the browser, upload your video with Davnai's upload card and Davnai edits it instead.
- A [Davnai](https://davnai.com) account (free to start) to post, schedule and automate.

## Browse what it can do

- **[library/](library/)**: every theme, effect, motion graphic, transition, colour look, caption animation and sound, with the plan line to use it (and the sounds to listen to).
- **[examples/](examples/)**: ready plans to copy: talking-head Short, podcast clip, faceless video, YouTube edit, split-screen gameplay, words behind you.
- **[skills/davnai-video/themes/](skills/davnai-video/themes/)**: the 12 themes as files. Copy one to `~/.davnai/themes/` and change it to make your own.

## What's inside

```
skills/davnai-video/
  SKILL.md            the steps and rules your AI follows
  reference/          Shorts, long edits, faceless videos, captions, themes, effects, motion graphics, stock, uploading
  themes/             the 12 themes, one file each
  scripts/davnai.py   the editing script (Python + ffmpeg)
library/              one page per theme, effect, graphic, transition, look and sound
examples/             ready plans to copy
skills/davnai-posts/  writing, grading, repurposing and scheduling posts
skills/davnai-hooks/  100 hook formulas
skills/davnai-coach/  the front door
tools/                builds library/ from the script (python tools/build_library.py)
tests/                tests for the script (python -m pytest tests)
.claude-plugin/       Claude Code plugin and marketplace
.mcp.json             connects Davnai (https://davnai.com/mcp)
AGENTS.md, CLAUDE.md  short instructions for agents working in this folder
```

Your originals are never changed: everything goes in a `<video>.davnai` folder next to the video.

## Privacy

Your videos are edited on your computer. Only the final you choose to upload goes to Davnai. The Brand Kit download link lasts one hour and only reads your own Brand Kit.

## Third-party tools

Setup installs tools under their own licences: ffmpeg (LGPL/GPL), faster-whisper (MIT), OpenCV (Apache 2.0), HyperFrames (Apache 2.0), GSAP (GreenSock's free licence), the Kokoro voices (Apache 2.0) and the theme fonts from Google Fonts (Open Font License; Permanent Marker under Apache 2.0). The built-in sounds are generated by ffmpeg on your computer. HyperFrames usage data is switched off when the script runs it.

## Licence

MIT. See [LICENSE](LICENSE). "Davnai" and the Davnai logo are Davnai's; the licence covers this folder's code and text only.

Questions or ideas: [Contact Davnai](https://davnai.com/contact)
