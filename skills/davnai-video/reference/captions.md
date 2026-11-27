# Captions

- `"captions": true` burns captions in the person's Brand Kit caption style (font, colours, outline, words per line, the word being said in its own colour, and where they sit). Run `davnai.py brand` first; without it the script uses Davnai's default style.
- Tall videos keep captions clear of TikTok, Reels and Shorts' buttons (the bottom third), using Davnai's own margins.
- `"caption_position": "top" | "middle" | "bottom"` overrides the Brand Kit for one output.
- `"caption_words": 3` changes the words per line for one output.
- Spelling: the transcript can mishear names. Fix a word with `"fix": { "davnay": "Davnai" }` in the output (applied to captions only).
- The fonts come from Davnai's caption library. If a font can't be used, the script says so and uses a standard bold font; `pip install fonttools brotli` usually fixes it.
