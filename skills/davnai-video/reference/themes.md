# Themes

A theme is a complete look in one word: caption font, size, colours and animation, where captions sit, the title style, the shapes of motion graphics, the default transition and colour grade, and sounds on transitions and graphics. Add `"theme": "bold"` to an output (or to the plan for all outputs). `python davnai.py themes` lists them.

| theme | feels | good for |
|---|---|---|
| `clean` | friendly, rounded brand-colour boxes, gentle pops | most creators, coaches, business |
| `bold` | huge uppercase words, hard shadows, flashes, auto zoom, progress bar | hooks, hype, fast talkers |
| `editorial` | serif titles, one quiet caption line at the top, film colour | essays, storytelling, premium brands |
| `neon` | glowing outlines, dark panels, glitch cuts | tech, gaming, night content |
| `minimal` | small top captions, plain cuts, no boxes | calm talks, lets the footage speak |
| `playful` | tilted stickers, chunky friendly letters, bounces | lifestyle, food, kids, fun |
| `news` | solid caption bars, uppercase headlines, wipes | updates, explainers, commentary |
| `tech` | monospace, typed-in captions, code-like panels | developers, product demos, AI |
| `retro` | chunky letters, offset shadows, warm faded colour, grain | nostalgia, music, vintage |
| `luxury` | display serif, thin gold lines, slow dissolves | fashion, property, beauty |
| `handwritten` | marker handwriting, sticky-note titles | creators, study, casual tips |
| `podcast` | whole wide shot on a blurred background, big centred captions, cleaner voice | podcast and interview clips |

- **The Brand Kit recolours every theme:** graphics use their brand colours, and captions use their caption accent. `"theme_colours": true` keeps the theme's own colours.
- **The plan wins:** anything set in the output (a transition, a look, `caption_position`, `"sounds": false`) replaces the theme's choice.
- **Your own theme:** start from one and change parts:

```json
"theme": {
  "base": "bold",
  "caption": { "words": 3, "place": "bottom", "anim": "pop" },
  "defaults": { "transition": "whip", "look": "warm" },
  "sounds": { "transition": "swoosh", "motion": "pop" },
  "title_font": "BebasNeue-Regular.ttf"
}
```

Fonts you can pick: Poppins-Medium, Poppins-Bold, Poppins-ExtraBold, Anton-Regular, BebasNeue-Regular, DMSerifDisplay-Regular, DMSerifDisplay-Italic, Audiowide-Regular, Bungee-Regular, SpaceMono-Bold, ArchivoBlack-Regular, PermanentMarker-Regular, AbrilFatface-Regular, Righteous-Regular (all `.ttf`, free Google Fonts, downloaded once).

To match a reel the person likes, pick the nearest theme and override `caption` (size, colours, words per line, place) and `defaults` (transition, look, speed) to match what you see in a few stills of it.
