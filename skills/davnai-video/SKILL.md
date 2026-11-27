---
name: davnai-video
description: Edit videos on the person's own computer the Davnai way, then post them with Davnai. Use when the person asks to edit a recording, cut pauses or mistakes, make Shorts, Reels or TikToks, add captions, or make a faceless video from stock clips and a voice-over, and wants it done here. Not for edits the person wants Davnai's own app to make.
---

# Davnai video editing on this computer

You edit with free tools on this computer (ffmpeg and a local speech-to-text model) using the `davnai.py` script. Davnai (the connected app) gives you the person's Brand Kit, takes the finished video and posts it.

## Rules

1. **Edit here, not in Davnai.** For an edit on this computer, never call Davnai's editing tools (ai_edit, make_ai_edit_video, make_shorts, find_shorts, trim_video, cut_out, split_video, join_videos, resize_video, add_captions, add_music, polish_video, add_branding, quick_tool, edit_and_post). Use Davnai only for the Brand Kit (get_brand_files), the upload (upload_from_computer) and posting. If it isn't clear where they want it edited, ask once: "Edit on your computer, or let Davnai do it?" If they say "always", save it with set_editing_place.
2. **Never change the original.** The script works in a `<video name>.davnai` folder next to it.
3. **You never write times.** Pick numbered transcript lines (and word numbers inside a line). The script turns them into exact times.
4. **The person reviews before anything is final:** preview, their notes, a new version, the final only when they say it's the one, then ask before uploading. In Davnai the posts still wait for their approval.
5. **Cheapest source first** for clips and pictures: the person's own files; then free stock sites (check each site's licence); then pictures your own app can make; Davnai's make_picture only when the person asks for Davnai's.
6. **Save tokens.** Run the script and read its short output. Read the transcript once. Don't open the video files; look at one still (`davnai.py frame`) only when you must see something.

## Setup (once)

- Run `python davnai.py check`. If something is missing, ask the person ("Davnai needs ffmpeg and a speech-to-text model on your computer. Install them?"), then run `python davnai.py setup --yes`. Add `--motion` for motion graphics (it installs Node.js, HyperFrames and GSAP; a few hundred MB). On Windows, run `check` again in a new terminal after installing.
- No Python? Windows: `winget install -e --id Python.Python.3.12`; Mac: `brew install python`. Then open a new terminal.
- The script is `scripts/davnai.py` in this skill. Without the skill installed, download it from https://davnai.com/skills/davnai.py.

## Steps

1. **Brand Kit:** call Davnai's `get_brand_files`, then run `python davnai.py brand "<brand_url>"`. It saves the colours, caption style, logo and their own intro and outro in `~/.davnai/brand` (redo it when the person changes their Brand Kit; the link lasts an hour).
2. **Transcript:** `python davnai.py transcribe "<video>"` prints numbered lines like `#12 (4.1s) the three mistakes everyone makes`. A second run reuses it.
3. **Plan:** write `plan.json` in the `.davnai` folder (format below). For Shorts, read `reference/shorts.md`; long edits `reference/long-edit.md`; faceless videos `reference/faceless.md`; captions `reference/captions.md`; effects `reference/effects.md`; motion graphics `reference/motion.md`; stock `reference/stock.md`.
4. **Storyboard:** `python davnai.py storyboard "<plan.json>"` prints each scene (lines, length, what's said, what happens on screen) and makes a picture page (`plan_storyboard.html`). Show the person the scene list and the page, and change the plan until they approve it. Skip it only for a simple cut they've already described.
5. **Preview:** `python davnai.py render "<plan.json>"` makes a small, fast preview for each output and prints where it is. Tell the person to watch it.
6. **Changes:** change the plan and render again; each round is a new version (v2, v3…) and earlier ones are kept. "Go back to v2": `--from-version 2`.
7. **Final:** only when they say it's the one: `python davnai.py render "<plan.json>" --final`.
8. **Upload:** ask "Upload this to Davnai?". Then `python davnai.py probe "<final>"`, call Davnai's `upload_from_computer` with what it printed, and run `python davnai.py upload "<final>" "<ticket>"`. It prints the video id.
9. **Post:** write the captions yourself in their Brand Kit voice and use Davnai's `create_posts` with the video id. Posts wait for their approval in Davnai unless they've said otherwise.

## Plan format

```json
{
  "source": "talk.mp4",
  "outputs": [
    { "name": "short-1", "aspect": "9:16", "keep": [[14, 19]], "captions": true, "tighten": true, "outro": true },
    { "name": "full", "aspect": "source", "keep": [[1, 40], [44, 120]], "tighten": true, "logo": true }
  ]
}
```

- `keep`: transcript line ranges `[first, last]`, played in the order listed. To start or end inside a line: `{ "from": [14, 3], "to": [19, 12] }` (line 14 from its 3rd word to line 19's 12th word).
- `aspect`: `9:16`, `1:1`, `4:5`, `16:9` or `source`. `focus_x` (0 to 1, default 0.5) moves a tall crop left or right.
- `tighten`: shortens pauses longer than 0.6 s. `captions`: burns captions in the Brand Kit style. `logo`, `intro`, `outro`: from the Brand Kit (intro and outro only when it has their own video).
- `music`: a file of theirs, with `music_volume` (default 0.12).
- Faceless videos use `voice` and `scenes` instead of `keep` (see `reference/faceless.md`).
- **Motion graphics** (animated titles, lower thirds, callouts, emoji, counters, lists, charts, quote and chapter cards, end screens, or your own HyperFrames HTML): `"motion": [...]`, see `reference/motion.md`. Needs `setup --motion`.
- **Effects** (animated captions, hook titles, text callouts, auto zoom, transitions, B-roll, picture-in-picture, blurred background, colour looks, progress bar, sound effects, speed, cleaner voice, end card): `reference/effects.md`.

## Long videos

- Transcripts over 400 lines print in parts: `transcribe "<video>" --lines 401-800`.
- Previews are half size and quick; a full-quality final takes roughly as long as the video, or longer on older computers. Run it with a long timeout or in the background, and tell the person.
- Change one output at a time with `--only <name>`.
