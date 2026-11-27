# Poster moment

The picture freezes and turns into a poster: a halftone background in your brand colour, a huge title behind the person and a paper border, while the voice carries on.

**Use it for:** The big line, a chapter opener, a thumbnail-worthy moment.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "poster", "text": "LEVEL UP", "sub": "Episode 4", "lines": [9, 9] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
