# Davnai skills: instructions for agents

This folder holds Davnai's video editing skill: `skills/davnai-video/SKILL.md`. Read it before editing a video for the person, and follow its rules:

- Edit on this computer with `skills/davnai-video/scripts/davnai.py`. Use Davnai (the connected app, https://davnai.com/mcp) only for the Brand Kit (`get_brand_files`), the upload (`upload_from_computer`) and posting. Never call Davnai's own editing tools for an edit made here.
- Never change the original video. Pick transcript line numbers; never write times yourself.
- Show previews and wait for the person's OK before the final; ask before uploading.
- Clips and pictures: the person's own first, then free stock, then your own app's pictures; Davnai's picture tools only when asked.

Working on the skill itself: keep `SKILL.md` short (details go in `reference/`), keep the script to Python's standard library plus ffmpeg (faster-whisper and fonttools are optional), and run `python skills/davnai-video/scripts/davnai.py check` after changes.
