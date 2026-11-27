# Big words behind the person

The person is cut out and put back in front of huge words, so the words sit behind them.

**Use it for:** Hooks, a key word, a reveal. Add "slice": true and each word slams in on its own beat of the music.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "behind", "text": "STOP DOING THIS", "slice": true, "lines": [12, 13] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
