# Motion graphics (HyperFrames)

Animated graphics drawn in the person's Brand Kit (colours, caption font, logo), placed by transcript lines. They're made with [HyperFrames](https://github.com/heygen-com/hyperframes) (open source, Apache 2.0) on this computer: `python davnai.py setup --motion` once. Only the moments with graphics are rendered by HyperFrames, so long videos stay quick.

Add `"motion": [ ... ]` to an output. Each graphic has a `type` and either `"lines": [first, last]` (shown while those lines are spoken), `"at": "start"` or `"at": "end"` with `"seconds"`. Optional: `"position"` (top, upper, middle, lower, bottom; corners for callouts), `"hold"` (seconds it stays after the lines, default 0.3).

| type | fields | what it does |
|---|---|---|
| `title` | `text`, `style`: pop, slide, bounce, words, typewriter, glow | Big animated headline in a brand-colour box. |
| `lower_third` | `name`, `role` | Name and role slide in with an accent bar. |
| `callout` | `text`, `emoji` (optional), `position` (top-left, top-right, middle, bottom-left, bottom-right) | Bubble pops in and wiggles. |
| `emoji` | `emoji`, `position` | Big emoji pops in and wiggles. |
| `counter` | `from`, `to`, `prefix`, `suffix`, `label`, `decimals` | Number counts up ("0 → 10,000+ followers"). |
| `list` | `title`, `items` | Steps or points tick in one by one. |
| `chart` | `title`, `bars`: [{ `label`, `value`, `display` }] | Bars grow in. |
| `quote` | `text`, `author` | Full-screen quote card in the brand colour. |
| `chapter` | `number`, `text`, `seconds` (default 2.2) | Full-screen chapter card that wipes in and out. |
| `end_screen` | `text`, `handle`, `button` | Logo, text, handle and a pulsing button (`"at": "end"`). |
| `feed` | `caption`, `likes`, `handle` (Brand Kit handle by default) | Your video plays inside a social post that scrolls up a phone feed into place, gets a like, then zooms back to full screen. 3 to 5 seconds works best. |
| `flythrough` | `chapters`: `[{ "text": "The setup", "line": 4 }, ...]`, `title` (default "Coming up") | A "coming up" opener: a card per chapter (a still from that line and its title) flies past in 3D. Use `"at": "start"`; it lasts about 1 s per chapter. Great for long videos. |
| `block` | `name` (catalog) or `html` (your copy), `vars`, `fit` | A whole catalog scene (see below). |
| `custom` | `html`: a file you write | Anything else (see below). |

```json
"motion": [
  { "type": "title", "text": "3 mistakes nobody tells you", "style": "words", "at": "start", "seconds": 2.5 },
  { "type": "lower_third", "name": "Ada Obi", "role": "Founder, Studio Ada", "lines": [2, 3] },
  { "type": "counter", "from": 0, "to": 10000, "suffix": "+", "label": "followers", "lines": [9, 9] },
  { "type": "list", "title": "3 steps", "items": ["Plan", "Film", "Post"], "lines": [14, 18] },
  { "type": "end_screen", "text": "Follow for more", "at": "end", "seconds": 3 }
]
```

Good taste: one graphic at a time; keep them off faces (use `position`); titles under 7 words; let a graphic stay at least 1.5 s.

## Your own graphic (`custom`)

Write an HTML fragment (no `<html>` or `<body>`) with its elements and a script that registers its animation. Size things from `BRAND.width`/`BRAND.height`; colours from `BRAND.primary`, `BRAND.secondary`, `BRAND.accent`; font `BRAND.font`. Animate only through the GSAP timeline you're given (no timers or CSS transitions), so every frame renders the same.

```html
<div class="burst" style="position:absolute;left:10%;top:20%;font-size:120px">💥</div>
<script>
registerDavnai(function (tl, root, start, duration, BRAND) {
  tl.from(root.querySelector(".burst"), { scale: 0, rotation: -90, duration: 0.5, ease: "back.out(3)" }, start);
  tl.to(root.querySelector(".burst"), { autoAlpha: 0, duration: 0.3 }, start + duration - 0.3);
});
</script>
```

Then: `{ "type": "custom", "html": "motion/burst.html", "lines": [12, 12] }`.

## Catalog scenes (`block`)

HyperFrames' catalog has 448 ready-made pieces (transitions, caption styles, lower thirds, effects, charts, 3D, phone screens, follow buttons...). `python davnai.py catalog <words>` searches it (`--type block` for whole scenes).

- A whole scene goes straight in: `{ "type": "block", "name": "tiktok-follow", "at": "end", "seconds": 3 }`. It's fitted to the video (`"fit": "cover"` to fill it) and can take `"vars"` if the scene declares variables.
- Catalog scenes come with sample names, pictures and logos. Before using one, run `python davnai.py catalog-get <name>`, copy the file next to the plan, replace the samples with the person's own (handle, photo, brand colours) and use `{ "type": "block", "html": "motion/tiktok-follow.html", ... }`. Never show another company's name or logo as if it were the person's, and don't make a video look like an official post from an app.
- Components (single effects) come the same way: adapt one into a `custom` graphic below.

HyperFrames also has a large catalog of ready-made pieces (captions, transitions, lower thirds, charts, 3D, backgrounds): `node ~/.davnai/motion/node_modules/hyperframes/bin/hyperframes.mjs catalog <words>` to search, `add <name>` to get one; adapt it into a `custom` fragment with the person's brand colours.
