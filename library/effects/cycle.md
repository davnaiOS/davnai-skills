# Pictures cycling behind you

Pictures (screenshots, products, places, stock) flick past behind the person on each beat of the music (or every 0.4 s), with the person cut out in front. Add "behind": false to flick them over the whole frame instead.

**Use it for:** Lists, "I tried 10 apps", travel, hooks.

**In the plan** (inside `"fx": [...]`):

```json
{ "type": "cycle", "images": ["pics/1.jpg", "pics/2.jpg", "pics/3.jpg"], "lines": [4, 5] }
```

Optional: `"strength"` (default 1). Place it with `"lines"`, `"all": true` or `"at": "start"`/`"end"`.
