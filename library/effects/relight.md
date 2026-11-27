# Relight the person

Changes the light around the speaker: spotlight, low_key, silhouette, neon, rim, under_light or golden_hour. The person is cut out so the light hits the room and the person separately (golden_hour needs no cut-out).

**Use it for:** Hooks, dramatic lines, a mood change, music videos.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "relight", "light": "neon", "lines": [4, 6] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
