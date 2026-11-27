# Your own effect

Any ffmpeg filter chain your AI writes, timed to transcript lines and checked on a blank frame first. For looks the list doesn't have yet.

**Use it for:** Anything: thermal camera, colour cycling, mirror, pixelate, edge glow.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "custom", "filter": "hue=h=90*t,eq=contrast=1.3", "lines": [8, 9] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
