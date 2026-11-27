# Shorts, Reels and TikToks

Pick the moments from the numbered transcript, then one output per Short. Then plan each Short's visuals with `reference/visual-plan.md`: beats every 1 to 4 seconds, scenes for the key ideas, something changing every 1 to 2 seconds.

- **Length:** 20 to 45 seconds unless the person says otherwise. Each line shows its seconds; add them up.
- **Hook first.** The first line must make someone stop: a bold claim, a question, a surprising number, a strong opinion. If the best hook is later in the clip, start there or move that line to the front (`keep` plays ranges in the order listed).
- **One idea per Short**, with a clear ending: a payoff, a punchline or a takeaway. Don't end mid-thought.
- **Cut the warm-up** ("so, um, today I want to talk about…") and repeated takes; when a line was said twice, keep the better one.
- **Stand alone:** no "as I said earlier" or names nobody knows.
- Use `"aspect": "9:16"`, `"captions": true`, `"tighten": true`. If the speaker isn't centred, look at one still (`davnai.py frame "<video>" --line 14`) and set `focus_x`.
- Suggest 2 to 5 Shorts with a one-line reason each, and let the person choose before you render, unless they asked you to just make them.
- Name outputs `short-1`, `short-2`… and give each a `title` (used for the file name and the post).
