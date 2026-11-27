# Studio effects (51)

Ready-made effects that track the face and can sit behind the person: orbiting pictures, glass widgets, comment boxes, tier lists, checklists, magazine covers and more. The full list is on its own page.

**Use it for:** Hooks, lists, proof, reveals: see the list.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "studio", "effect": "orbit", "images": ["shots/1.png", "shots/2.png", "shots/3.png"], "lines": [4, 5] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
