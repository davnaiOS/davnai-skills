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
- No Python? Windows: `winget install -e --id Python.Python.3.12`; Mac: `brew install python`. Then open a new terminal. On Windows, if `python` opens the Microsoft Store or does nothing, use `py davnai.py ...` instead.
- **Their style:** run `python davnai.py style` at the start. It shows what the person prefers (saved from earlier videos); the script uses it for every video unless the plan says otherwise.
- The script is `scripts/davnai.py` in this skill. Without the skill installed, download it from https://davnai.com/skills/davnai.py.

## Steps

1. **Brand Kit:** call Davnai's `get_brand_files`, then run `python davnai.py brand "<brand_url>"`. It saves the colours, caption style, logo and their own intro and outro in `~/.davnai/brand` (redo it when the person changes their Brand Kit; the link lasts an hour). If it says parts are missing (no colours, logo, handle or voice), tell the person and offer to set the basics now with Davnai's `update_brand_kit` (their colours, handle, and a voice you write from two posts they like; a logo is uploaded on Davnai's Brand Kit page), then run `get_brand_files` and `brand` again. If they'd rather not, carry on: the theme's own colours are used.
2. **Transcript:** `python davnai.py transcribe "<video>"` prints numbered lines like `#12 (4.1s) the three mistakes everyone makes`. A second run reuses it.
3. **Plan:** for any Short, Reel or TikTok, first read `reference/visual-plan.md` and write the beats (`beats.md`: job, kind, what we see, a beat every 1 to 4 seconds, scenes for the key ideas). Then write `plan.json` in the `.davnai` folder (format below). For Shorts, read `reference/shorts.md`; long edits `reference/long-edit.md`; faceless videos `reference/faceless.md`; captions `reference/captions.md`; themes `reference/themes.md`; effects `reference/effects.md`; motion graphics `reference/motion.md`; studio effects `reference/studio.md`; stock `reference/stock.md`.
4. **Storyboard:** `python davnai.py storyboard "<plan.json>"` prints each scene (lines, length, what's said, what happens on screen) and makes a picture page (`plan_storyboard.html`). Show the person the scene list and the page, and change the plan until they approve it. Skip it only for a simple cut they've already described.
5. **Preview:** `python davnai.py render "<plan.json>"` makes a small, fast preview for each output, checks it, and prints where it is. Outputs that didn't change since the last version are kept, not made again. Then `python davnai.py pace "<preview>"`: if the longest still stretch is over 4 seconds, add beats before showing the person. You can't watch or hear video: look at stills of the busiest beats (`davnai.py frame`) and ask the person to judge motion and sound.
6. **Review:** `python davnai.py review "<plan.json>" --only <name>` opens a review page in their browser: the video, its scenes and graphics, and the transcript. They mark moments (change, cut, keep, question) with notes and press Done; you get the notes as line numbers. Run it with a long timeout or in the background (it waits up to 30 minutes). If it can't open, they can paste notes into the chat ("Copy notes").
7. **Changes:** change the plan and render again; each round is a new version (v2, v3…) and earlier ones are kept. "Go back to v2": `--from-version 2`. When a note is a lasting preference ("always smaller captions", "I like warm colour"), save it: `python davnai.py style --set caption_words=3 --set look=warm --note "smaller captions, warm colour"`.
8. **Final:** only when they say it's the one: `python davnai.py render "<plan.json>" --final`.
9. **Upload:** ask "Upload this to Davnai?". Then `python davnai.py probe "<final>"`, call Davnai's `upload_from_computer` with what it printed, and run `python davnai.py upload "<final>" "<ticket>"`. It prints the video id.
10. **Post:** write the captions yourself in their Brand Kit voice and use Davnai's `create_posts` with the video id. Posts wait for their approval in Davnai unless they've said otherwise.

## Matching a reel they like

`python davnai.py match "<reel.mp4>"` reads its pace (cuts a minute), colour, loudness and shape, suggests a theme and settings, and saves six stills to look at for the caption style. Set the plan from it, and save it with `style` if they want it every time.

## Quality checks

Every render ends with checks: black or frozen picture, loudness (social apps like about -14 LUFS), long silences, length for the platform, and captions covering a face (when OpenCV is installed). Fix anything marked ⚠ before showing the person, or tell them why it's fine. `python davnai.py qc "<video>" --captions` checks any video.

## Plan format

```json
{
  "source": "talk.mp4",
  "theme": "clean",
  "outputs": [
    { "name": "short-1", "aspect": "9:16", "keep": [[14, 19]], "captions": true, "tighten": true, "outro": true },
    { "name": "full", "aspect": "source", "keep": [[1, 40], [44, 120]], "tighten": true, "logo": true }
  ]
}
```

- `theme`: a complete look in one word (clean, bold, editorial, neon, minimal, playful, news, tech, retro, luxury, handwritten, podcast) recoloured by the Brand Kit, or your own; see `reference/themes.md`. Pick one with the person (show them the list) unless they've said what they like.
- `keep`: transcript line ranges `[first, last]`, played in the order listed. To start or end inside a line: `{ "from": [14, 3], "to": [19, 12] }` (line 14 from its 3rd word to line 19's 12th word).
- `aspect`: `9:16`, `1:1`, `4:5`, `16:9` or `source`. `focus_x` (0 to 1, default 0.5) moves a tall crop left or right.
- `tighten`: shortens pauses longer than 0.6 s. `captions`: burns captions in the Brand Kit style. `logo`, `intro`, `outro`: from the Brand Kit (intro and outro only when it has their own video).
- `music`: a track from Davnai's library (`list_music`, then `get_music_file` and `python davnai.py music "<url>"`) or a file of theirs. It dips under the voice by itself (`"duck": false` to stop that); `music_volume` (default 0.2).
- **Scenes** (`{ "type": "scene", "layout": "card|window|split", "background": "grid", "title": "...", "lines": [8, 9] }` in `motion`): the speaker moves into a card, a window or the lower half over a designed background, with a headline, list or counting number. The main tool for making a talking video feel designed; see `reference/visual-plan.md` and `reference/motion.md`.
- Faceless videos use `voice` and `scenes` instead of `keep` (see `reference/faceless.md`).
- **Motion graphics** (animated titles, lower thirds, callouts, emoji, counters, lists, charts, quote and chapter cards, end screens, a feed scroll, a chapter flythrough opener, glass panels, a picture carousel, or your own HyperFrames HTML): `"motion": [...]`, see `reference/motion.md`. Needs `setup --motion`.
- **Signature effects** (`"fx"`: words behind the person (sliced on the beat), poster moments, before and after, pictures cycling behind you, your own ffmpeg effect (`custom`), relighting (spotlight, neon, silhouette and more), shake, flash, colour split, glitch, blur, black and white, VHS, grain, light leak), **split screen** (`"split"`) and **beat sync** (`"beat_pulse"`, `"beat_cuts"`): see `reference/effects.md`. **51 studio effects** (`{ "type": "studio", "effect": "orbit", ... }`: orbiting pictures, glass widgets, comment box, tier list, checklist, magazine cover and more), see `reference/studio.md`. Captions and graphics keep off the speaker's face on their own (`"face_aware": false` turns it off).
- **Effects** (animated captions, hook titles, text callouts, auto zoom, transitions, B-roll, picture-in-picture, blurred background, colour looks, progress bar, sound effects, speed, cleaner voice, end card): `reference/effects.md`.

## Long videos

- Transcripts over 400 lines print in parts: `transcribe "<video>" --lines 401-800`.
- Previews are half size and quick; a full-quality final takes roughly as long as the video, or longer on older computers. Run it with a long timeout or in the background, and tell the person.
- Change one output at a time with `--only <name>`.
