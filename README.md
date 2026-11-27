# Davnai skills

**Edit with your own AI. Post and grow with Davnai.**

Skills that teach your AI to edit videos on your own computer the Davnai way, then hand the finished video to [Davnai](https://davnai.com) to post everywhere, answer comments and grow your contacts. They work in Claude, ChatGPT and Codex, Gemini, Cursor and other apps that read [Agent Skills](https://agentskills.io).

## The skills

- **[davnai-video](skills/davnai-video/SKILL.md)**: edits on your computer. Shorts, full edits, faceless videos, 12 themes, motion graphics, effects, storyboard, review page, quality checks and upload to Davnai.
- **[davnai-posts](skills/davnai-posts/SKILL.md)**: writes posts in your voice for each platform, grades drafts (with the 3 fixes that matter most), turns one video into a week of content and schedules it in Davnai for your approval.
- **[davnai-hooks](skills/davnai-hooks/SKILL.md)**: 100 hook formulas in ten families for first lines, Short titles and the first words on camera.
- **[davnai-coach](skills/davnai-coach/SKILL.md)**: the front door. Works out your goal, reads what Davnai knows (Brand Kit, accounts, results) and runs the right skill or Davnai tool, including comment-to-DM automations.

## What it can do

### Edits

- **Shorts, Reels and TikToks** from one recording: the best moments, hook first.
- **Full edits** for YouTube, lessons and podcasts: mistakes, repeats and dead air removed.
- **Faceless videos** from stock clips or pictures and a voice-over, with free voice-overs made on your computer.
- **Face-aware:** the speaker stays in frame when a wide video becomes vertical, and captions and titles move off their face.

### Your look

- **12 themes:** clean, bold, editorial, neon, minimal, playful, news, tech, retro, luxury, handwritten and podcast. Each is a complete look (fonts, caption animation, titles, transitions, colour and sounds), recoloured with your brand. Or build your own.
- **Your brand everywhere:** captions in your Brand Kit style, your logo, your own intro and outro.
- **The basics:** animated captions, hook titles, callouts, auto zoom, transitions, B-roll and picture-in-picture, colour looks, progress bars, music, sound effects (whoosh, pop, impact, riser...) and end cards.

### Effects

- **Scenes:** the video moves into a card, a small window or the lower half over a designed background, with a headline, a list or a counting number, then back to full screen. Your AI plans a new beat every few seconds, so a talking video feels designed, not just captioned.
- **51 studio effects** that track your face and can sit behind you: pictures orbiting your head, glass widgets, comment boxes, tier lists, checklists, magazine covers, message pop-ups, an LED sign and more ([the list](skills/davnai-video/reference/studio.md)).
- **Signature effects:** big words behind you (sliced on the music's beat), poster moments, before and after, pictures cycling behind you, relighting (spotlight, neon glow, silhouette, rim light, golden hour), shake, flash, glitch, VHS, grain, light leaks, split screen and beat pulses.
- **Motion graphics** with [HyperFrames](https://github.com/heygen-com/hyperframes): animated titles, lower thirds, counters, lists, charts, chapter cards, end screens, a feed scroll, a 3D chapter flythrough, glass panels, a 3D picture carousel and HyperFrames' 448 catalog pieces, all in your brand.
- **No ceiling:** your AI can write its own effects (any ffmpeg filter) and its own graphics (HTML), timed to your words.

### You stay in control

- **Storyboard first:** a scene-by-scene plan and a picture page to approve before anything is rendered.
- **Review page:** mark moments on the video (change, cut, keep, question) and your AI gets your notes as transcript lines. It remembers your lasting preferences and can match the style of a reel you like.
- **Quality checks** on every render: black or frozen picture, loudness for social apps, long silences, captions covering a face.
- **You approve everything:** quick previews first, the final only when you say so, and posts wait for your OK in Davnai.
- **Sound that's mixed:** a whoosh or hit on every zoom and effect, your voice cleaned and evened out, and music from Davnai's instrumental library (or your own) that dips while you speak.
- **Cheaper:** the editing runs on your computer with free tools, and the AI picks moments by line number instead of guessing times, so it uses far fewer tokens.

## Get started

1. **Connect Davnai** to your AI app: add the connector with the address `https://davnai.com/mcp` and sign in. In Claude and ChatGPT, look for Davnai in the connectors list.
2. **Install the skills:**
   - **Claude Code:** `/plugin marketplace add davnaiOS/davnai-skills`, then `/plugin install davnai@davnai` (this also connects Davnai).
   - **Codex:** `$skill-installer` with `https://github.com/davnaiOS/davnai-skills/tree/main/skills/davnai-video` (and the other skills), or copy the folders in `skills/` to `~/.codex/skills/`.
   - **Gemini CLI, Cursor, Copilot and others:** copy the folders in `skills/` into the app's skills folder (for example `.agents/skills/`, `.gemini/skills/` or `.github/skills/`).
   - **No skill installed?** Davnai's connector serves the same guide (`get_editing_guide`), so connecting Davnai is enough to start.
3. **Ask**, for example:
   - "Make 3 Shorts from interview.mp4 and post them to TikTok and Instagram on Friday."
   - "Edit my lesson recording for YouTube: remove the mistakes and add my intro."
   - "Make a 30-second faceless video from my voice-over and the clips in my B-roll folder."

## What you need

Your AI sets this up for you: it runs `python davnai.py check`, asks you, then `python davnai.py setup` installs what's missing.

- **Python 3.9 or newer.** Windows: `winget install -e --id Python.Python.3.12`. Mac: `brew install python`.
- **[ffmpeg](https://ffmpeg.org/download.html), a speech-to-text model and the effect parts** (installed by `setup`). Everything runs on your computer.
- **Optional, for motion graphics and voice-overs:** Node.js 22+ and HyperFrames (`setup --motion`, a few hundred MB).
- **An AI app that can run commands on your computer:** Claude Code, Claude desktop with a folder, Codex, Gemini CLI or Cursor. In ChatGPT or Claude in the browser, upload your video with Davnai's upload card and Davnai edits it instead.
- **A [Davnai](https://davnai.com) account** (free to start) to post, schedule and automate.

## Browse what it can do

- **[library/](library/)**: every theme, effect, motion graphic, transition, colour look, caption animation and sound, with the plan line to use it.
- **[examples/](examples/)**: ready plans to copy (talking-head Short, podcast clip, faceless video, YouTube edit, split-screen gameplay, words behind you, signature pieces).
- **[skills/davnai-video/themes/](skills/davnai-video/themes/)**: the 12 themes as files. Copy one to `~/.davnai/themes/` and change it to make your own.

## What's inside

- **`skills/davnai-video/`**: the editing skill
  - `SKILL.md`: the steps and rules your AI follows
  - `reference/`: Shorts, long edits, faceless videos, captions, themes, effects, studio effects, motion graphics, stock, uploading
  - `engine/`: the studio effects engine (see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md))
  - `themes/`: the 12 themes, one file each
  - `scripts/davnai.py`: the editing script (Python + ffmpeg)
- **`skills/davnai-posts/`**: writing, grading, repurposing and scheduling posts
- **`skills/davnai-hooks/`**: 100 hook formulas
- **`skills/davnai-coach/`**: the front door
- **`library/`**: one page per theme, effect, graphic, transition, look and sound
- **`examples/`**: ready plans to copy
- **`tools/`**: builds `library/` from the script (`python tools/build_library.py`)
- **`tests/`**: tests for the script (`python -m pytest tests`)
- **`.claude-plugin/`** and **`.mcp.json`**: the Claude Code plugin, and the Davnai connection (`https://davnai.com/mcp`)
- **`AGENTS.md`** and **`CLAUDE.md`**: short instructions for agents working in this folder

Your originals are never changed: everything goes in a `<video>.davnai` folder next to the video.

## Privacy

Your videos are edited on your computer. Only the final you choose to upload goes to Davnai. The Brand Kit download link lasts one hour and only reads your own Brand Kit.

## Third-party tools

Setup installs tools under their own licences: ffmpeg (LGPL/GPL), faster-whisper (MIT), OpenCV (Apache 2.0), MediaPipe (Apache 2.0) with the YuNet face model (MIT), HyperFrames (Apache 2.0), GSAP (GreenSock's free licence), the Kokoro voices (Apache 2.0) and the theme fonts from Google Fonts (Open Font License; Permanent Marker under Apache 2.0). The built-in sounds are made by ffmpeg on your computer. HyperFrames usage data is switched off when the script runs it.

Some parts come from other open-source projects: see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Licence

MIT. See [LICENSE](LICENSE). "Davnai" and the Davnai logo are Davnai's; the licence covers this folder's code and text only.

Questions or ideas: [contact Davnai](https://davnai.com/contact).
