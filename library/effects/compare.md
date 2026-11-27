# Before and after

The left half shows the picture before looks and effects, the right half the finished edit, with labels and a divider.

**Use it for:** Showing off the edit, tutorials, transformations.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "compare", "labels": ["RAW", "EDIT"], "lines": [3, 4] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
