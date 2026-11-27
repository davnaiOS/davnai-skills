# Davnai skills

**Edit with your own AI. Post and grow with Davnai.**

Skills that teach your AI (Claude, ChatGPT and Codex, Gemini, Cursor and other apps that read [Agent Skills](https://agentskills.io)) to edit videos on your own computer the Davnai way, then hand the finished video to [Davnai](https://davnai.com) to post everywhere, answer comments and grow your contacts.

- **Shorts, Reels and TikToks** from one recording: the best moments, hook first.
- **Full edits** for YouTube, lessons and podcasts: mistakes, repeats and dead air removed.
- **Faceless videos** from stock clips or pictures and a voice-over.
- **Your brand everywhere:** captions in your Brand Kit style, your logo, your own intro and outro.
- **Effects:** animated captions, hook titles, text callouts, auto zoom, transitions, B-roll and picture-in-picture, blurred backgrounds, colour looks, progress bars, sound effects, music, end cards.
- **You approve everything:** quick previews first, the final only when you say so, and posts wait for your OK in Davnai.
- **Cheaper:** the editing runs on your computer with free tools (ffmpeg and a local speech model), and the AI picks moments by line number instead of guessing times, so it uses far fewer tokens.

## Get started

1. **Connect Davnai** to your AI app: add the connector with the address `https://davnai.com/mcp` and sign in. (In Claude and ChatGPT, look for Davnai in the connectors list.)
2. **Install the skill:**
   - **Claude Code:** `/plugin marketplace add davnaiOS/davnai-skills`, then `/plugin install davnai@davnai` (this also connects Davnai).
   - **Codex:** `$skill-installer` with `https://github.com/davnaiOS/davnai-skills/tree/main/skills/davnai-video`, or copy `skills/davnai-video` to `~/.codex/skills/`.
   - **Gemini CLI, Cursor, Copilot and others:** copy `skills/davnai-video` into the app's skills folder (for example `.agents/skills/`, `.gemini/skills/`, `.github/skills/`).
   - **No skill installed?** Davnai's connector serves the same guide (`get_editing_guide`), so connecting Davnai is enough to start.
3. **Ask**, for example:
   - "Make 3 Shorts from interview.mp4 and post them to TikTok and Instagram on Friday."
   - "Edit my lesson recording for YouTube: remove the mistakes and add my intro."
   - "Make a 30-second faceless video from my voice-over and the clips in my B-roll folder."

## What you need

- Python 3.9 or newer and [ffmpeg](https://ffmpeg.org/download.html) (Windows: `winget install ffmpeg`; Mac: `brew install ffmpeg`).
- `pip install faster-whisper` for transcripts (runs on your computer; the first run downloads a speech model).
- Optional: `pip install fonttools brotli` for the exact Brand Kit caption fonts.
- An AI app that can run commands on your computer (Claude Code, Claude desktop with a folder, Codex, Gemini CLI, Cursor). In ChatGPT or Claude in the browser, upload your video with Davnai's upload card and Davnai edits it instead.
- A [Davnai](https://davnai.com) account (free to start) to post, schedule and automate.

Run `python skills/davnai-video/scripts/davnai.py check` to see what's missing.

## What's inside

```
skills/davnai-video/
  SKILL.md            the steps and rules your AI follows
  reference/          Shorts, long edits, faceless videos, captions, effects, stock, uploading
  scripts/davnai.py   the editing script (Python + ffmpeg)
.claude-plugin/       Claude Code plugin and marketplace
.mcp.json             connects Davnai (https://davnai.com/mcp)
AGENTS.md, CLAUDE.md  short instructions for agents working in this folder
```

Your originals are never changed: everything goes in a `<video>.davnai` folder next to the video.

## Privacy

Your videos are edited on your computer. Only the final you choose to upload goes to Davnai. The Brand Kit download link lasts one hour and only reads your own Brand Kit.

## Licence

MIT. See [LICENSE](LICENSE). "Davnai" and the Davnai logo are Davnai's; the licence covers this folder's code and text only.

Questions: support@davnai.com
