# Library

Everything the Davnai skill can put in a video. Each page says what it does, when to use it and the exact plan line. Pictures of each are in [gallery/](../gallery/) as they're added.

## Themes (12)

| theme | feels | fonts | defaults |
|---|---|---|---|
| [clean](themes/clean.md) | Friendly and modern: rounded brand-colour boxes, soft shadows, gentle pops. | Poppins / Poppins ExtraBold | transition dissolve, look soft |
| [bold](themes/bold.md) | Loud and punchy: big uppercase words, hard shadows, flashes and zooms. For hooks and fast talkers. | Anton / Anton | transition flash, look punchy, auto_zoom True, progress_bar True |
| [editorial](themes/editorial.md) | Calm and premium: serif titles, one quiet line of captions at the top, film-like colour. | Poppins Medium / DM Serif Display | transition fade, look cinematic |
| [neon](themes/neon.md) | Night-time and techy: glowing outlines, dark panels, glitch cuts. | Audiowide / Audiowide | transition glitch, look cool |
| [minimal](themes/minimal.md) | Quiet and simple: small captions at the top, plain cuts, no boxes. | Poppins Medium / Poppins | none |
| [playful](themes/playful.md) | Bright and bouncy: rounded tilted stickers, big friendly letters, pops. For lifestyle, kids' and food content. | Righteous / Bungee | transition slide_up, look vivid |
| [news](themes/news.md) | Newsroom: solid bars, uppercase headlines, straight wipes. For updates, explainers and commentary. | Archivo Black / Bebas Neue | transition wipe |
| [tech](themes/tech.md) | Developer and product: monospace type, typed-in captions, dark panels with a code feel. | Space Mono / Space Mono | transition glitch, look cool |
| [retro](themes/retro.md) | Retro: chunky letters, offset shadows, warm faded colour and film grain. | Bungee / Bungee | transition dissolve, look retro |
| [luxury](themes/luxury.md) | Luxury: elegant display serif, thin gold lines, slow dissolves. For fashion, property and beauty. | Poppins Medium / Abril Fatface | transition dissolve, look soft |
| [handwritten](themes/handwritten.md) | Creator notebook: marker handwriting, tilted notes, casual pops. | Permanent Marker / Permanent Marker | transition whip |
| [podcast](themes/podcast.md) | Podcast clips: the whole wide shot on a blurred background, big centred captions, key words stand out. | Poppins ExtraBold / Poppins ExtraBold | fill blur, clean_audio True |

## Signature effects (16)

| effect | what it does | plan |
|---|---|---|
| [Big words behind the person](effects/behind.md) | The person is cut out and put back in front of huge words, so the words sit behind them. | `"type": "behind"` |
| [Poster moment](effects/poster.md) | The picture freezes and turns into a poster: a halftone background in your brand colour, a huge title behind the person and a paper border, while the voice carries on. | `"type": "poster"` |
| [Before and after](effects/compare.md) | The left half shows the picture before looks and effects, the right half the finished edit, with labels and a divider. | `"type": "compare"` |
| [Relight the person](effects/relight.md) | Changes the light around the speaker: spotlight, low_key, silhouette, neon, rim, under_light or golden_hour. The person is cut out so the light hits the room and the person separately (golden_hour needs no cut-out). | `"type": "relight"` |
| [Pictures cycling behind you](effects/cycle.md) | Pictures (screenshots, products, places, stock) flick past behind the person on each beat of the music (or every 0.4 s), with the person cut out in front. Add "behind": false to flick them over the whole frame instead. | `"type": "cycle"` |
| [Studio effects (51)](effects/studio.md) | Ready-made effects that track the face and can sit behind the person: orbiting pictures, glass widgets, comment boxes, tier lists, checklists, magazine covers and more. The full list is on its own page. | `"type": "studio"` |
| [Your own effect](effects/custom.md) | Any ffmpeg filter chain your AI writes, timed to transcript lines and checked on a blank frame first. For looks the list doesn't have yet. | `"type": "custom"` |
| [Camera shake](effects/shake.md) | A short handheld shake. | `"type": "shake"` |
| [Flash](effects/flash.md) | A quick bright flash (0.15 s). | `"type": "flash"` |
| [Colour split](effects/rgb.md) | Red and blue separate for a chromatic look. | `"type": "rgb"` |
| [Glitch](effects/glitch.md) | Colour split, noise and jitter. | `"type": "glitch"` |
| [Blur](effects/blur.md) | A soft blur. | `"type": "blur"` |
| [Black and white](effects/bw.md) | Black and white for a moment. | `"type": "bw"` |
| [VHS tape](effects/vhs.md) | Faded colour, scan lines, noise. | `"type": "vhs"` |
| [Film grain](effects/grain.md) | Fine moving grain. | `"type": "grain"` |
| [Light leak](effects/light_leak.md) | Warm light washes across the picture. | `"type": "light_leak"` |

## Studio effects (51)

They track the face and can sit behind the person. Options for each: [reference/studio.md](../skills/davnai-video/reference/studio.md).

| effect | what it does |
|---|---|
| `noise` | Reels pile up behind your head, one every quarter second |
| `lineup` | Numbered tiles fan out in an arc above your head |
| `locked-on` | Corner brackets snap onto your face and the camera follows you |
| `orbit` | Your reels circle your head: in front at the bottom, behind you at the top |
| `lean-in` | A fast punch-in on one word |
| `backdrop-word` | A giant word drops in behind you |
| `spotlight` | Kill the lights, keep you lit |
| `the-bill` | Prints every instruction like a ticket, into the wall above your head |
| `moody` | A moody colour grade: darker, softer, teal shadows |
| `swipe` | A before and after slider that sweeps across you |
| `todo` | A checklist card beside your head that ticks off as you talk |
| `tap` | A Follow button pops up and flips to Following |
| `pause-point` | Freeze the frame and point at something with a hand-drawn arrow |
| `uninstall` | A glitchy uninstall bar that breaks the frame apart |
| `reel-frame` | Your video shrinks into a social reel card |
| `shortcut-rain` | Keyboard keys rain down behind you |
| `reject-stamp` | A big red stamp slams onto the screen |
| `countdown-flip` | A 3, 2, 1 flip clock above your head |
| `rabbit-hole` | The frame tunnels into itself, spinning |
| `cover-star` | You become a magazine cover, with the title behind your head |
| `scribble` | Marker doodles draw themselves around you |
| `red-collage` | Black and white you, a giant red word behind, kinetic type stacked beside you |
| `split-headline` | A clean headline card slides down and pushes you into the bottom of the frame |
| `pastel-word` | A soft lavender backdrop, a giant word behind you and a profile card that gets followed |
| `check-pills` | Grid-paper room, your reels pinned behind you and blue pills that get clicked |
| `headline-box` | A punch-in with a clean two-line headline, the second line in a white box |
| `profile-wall` | Your profile grid fills the wall behind you while a counter ticks up |
| `tier-list` | A tier list drops in front of you and your pick flies into S tier |
| `broll-split` | Split screen: b-roll on top with a price-tag sticker, you on the bottom |
| `phone-fan` | Your reels fan out like a hand of phones in front of you, under a two-line headline |
| `dot-reveal` | Your shot builds itself out of glowing dots, then snaps into the full picture |
| `headline-wall` | A wall of your own reel headlines piles up behind your head, then your total views pop in front |
| `checklist` | A task list builds under your chin: each step spins, then ticks green |
| `glass-widgets` | Frosted glass phone widgets and mini artifacts float around your head, with an Edited with Davnai pill |
| `timeline` | A dark red cinematic grade with an editing timeline, a REC timecode and a glowing playhead |
| `comment-box` | A comments sheet above your head types your word, posts it, gets a heart and your reply |
| `liquid-glass-graph` | A liquid glass card floats under your chin while a graph climbs and the number counts up |
| `carousel-spin` | Your reels spin around you in a 3D carousel, then slow to a stop |
| `match-cut` | News pages cut on one word, locked in place behind your head |
| `settings-toggles` | A phone settings card under your chin flips its switches on, one line at a time |
| `led-sign` | The lights drop and a glowing LED sign types itself out behind you |
| `slow-push` | A slow cinematic push-in from the wide shot to your face, the room melting out of focus |
| `over-the-shoulder-zoom` | The camera pushes into one top corner, a liquid glass graph pops beside your head, then the other corner with a second graph |
| `messages` | Message notifications pop in one after another, creamy glass with a soft glow, stacking up above the bottom of the frame |
| `place-in-grid` | You shrink into the centre tile of your 3x3 profile grid on frosted glass, then 8 of your reels pop in around you, one per frame, view counts on every tile |
| `tape-label` | A strip of yellow tape with your line lands on your chest |
| `select-resize` | A blue selection box grabs your number and a cursor drags it bigger |
| `wave-trim` | The silent parts of your voice are trimmed away on screen until only your words are left |
| `huge-strike` | One huge serif word fills the wall behind you, then a red line crosses it out |
| `crayon-write` | A red crayon writes your word behind your head, then underlines it |
| `fan-build` | Your reel covers deal into a fan behind your head, one card at a time |

## Motion graphics (17)

In the brand's colours and fonts, made with HyperFrames (`setup --motion`).

| graphic | what it does |
|---|---|
| [Animated title](motion/title.md) | A headline in a brand-colour box: pop, slide, bounce, words, typewriter or glow. |
| [Name tag](motion/lower_third.md) | Name and role slide in with an accent bar. |
| [Callout](motion/callout.md) | A bubble that pops in and wiggles. |
| [Emoji](motion/emoji.md) | A big emoji pops in. |
| [Counter](motion/counter.md) | A number counts up. |
| [List](motion/list.md) | Points tick in one by one. |
| [Chart](motion/chart.md) | Bars grow in. |
| [Quote card](motion/quote.md) | A full-screen quote in the brand colour. |
| [Feed scroll](motion/feed.md) | Your video plays inside a social post that scrolls up a phone feed into place (with your handle, a like and a caption), then zooms back to full screen. |
| [Chapter flythrough](motion/flythrough.md) | A 'coming up' opener: a card per chapter, with a still from that moment and its title, flies past in 3D. |
| [Scene](motion/scene.md) | Your video moves into a card, a small window or the lower half over a designed background (grid, gradient, dark, paper, dots, a colour or a picture), with a headline, a list or a counting number, then back to full screen. The main tool for making a talking video feel designed. |
| [Glass panel](motion/glass.md) | A frosted-glass card over the video (the picture shows through, blurred) with an icon, a title, a line or a list, and a light sheen. |
| [Picture carousel](motion/carousel.md) | Pictures on a slowly turning 3D ring over the video, kept off the face and the captions. |
| [Chapter card](motion/chapter.md) | A full-screen chapter card wipes in and out. |
| [End screen](motion/end_screen.md) | Logo, text, handle and a pulsing button. |
| [Catalog scene](motion/block.md) | Any of HyperFrames' ready-made scenes (follow buttons, phone screens, charts). |
| [Your own graphic](motion/custom.md) | An HTML fragment your AI writes, animated with GSAP. |

## Transitions (11)

Between the parts of `keep` (or faceless scenes): `"transition": "<name>"`.

- **fade**: Dips to black.
- **flash**: A white flash.
- **dissolve**: One shot melts into the next.
- **whip**: A fast smooth slide.
- **slide**: Slides left.
- **slide_up**: Slides up.
- **zoom**: Zooms into the next shot.
- **wipe**: A straight wipe.
- **circle**: Opens in a circle.
- **glitch**: A pixel glitch.
- **blur**: A horizontal blur.

## Colour looks (9)

`"look": "<name>"`.

- **warm**: Golden, friendly.
- **cool**: Blue, clean.
- **vivid**: Rich colour.
- **punchy**: Contrast and sharpness.
- **bw**: Black and white.
- **cinematic**: Film colour with a vignette.
- **soft**: Gentle and bright.
- **vintage**: Faded film.
- **retro**: Faded film with grain.

## Caption animations (6)

`"caption_animation": "<name>"` (or the theme's).

- **pop**: Grows in.
- **bounce**: Drops and bounces.
- **fade**: Fades in.
- **slide**: Tips forward into place.
- **type**: Word by word.
- **none**: Appears.

## Built-in sounds (8)

Made by ffmpeg on your computer: nothing to licence. Listen in [sounds/](sounds/).

- **whoosh** ([listen](sounds/whoosh.wav)): Air rushing past.
- **swoosh** ([listen](sounds/swoosh.wav)): A light quick swish.
- **pop** ([listen](sounds/pop.wav)): A bubbly pop.
- **click** ([listen](sounds/click.wav)): A crisp tick.
- **ding** ([listen](sounds/ding.wav)): A bell.
- **impact** ([listen](sounds/impact.wav)): A deep hit.
- **riser** ([listen](sounds/riser.wav)): Rising tension.
- **glitch** ([listen](sounds/glitch.wav)): A digital stutter.

## More

- Split screen, beat sync, B-roll, picture-in-picture, zoom, speed, music, end cards: [reference/effects.md](../skills/davnai-video/reference/effects.md)
- 448 ready-made HyperFrames pieces: `python davnai.py catalog <words>`
- Ready plans to copy: [examples/](../examples/)
