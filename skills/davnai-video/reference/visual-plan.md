# The visual plan: how to make an edit feel alive

Read this before planning any talking-head Short, Reel or TikTok. A clean cut with captions is not enough: people
scroll away from a video where nothing changes. The plan below is what separates a designed reel from footage with
words on it.

## 1. Beats before pieces

Read the transcript once and split it into **beats**: one phrase each, 1 to 4 seconds (a long sentence is two or three
beats). Write the beats in `beats.md` next to the plan before you choose any graphic. For each beat:

- **said**: the line numbers and words.
- **job**: hook, setup, proof, contrast, turn, payoff or ask. A beat with no job gets cut or merged.
- **kind**: what the viewer sees:
  - `talk`: just the speaker (a breather; it makes the next visual hit harder);
  - `type`: a big word or headline (words behind the speaker, a title, a poster moment);
  - `explain`: a picture that makes the point land in one second with the sound off: a scene with a number, a list,
    a chart, an app screen, a before and after.
- **sound**: only for the moments that carry the story: a riser into a reveal, an impact on the biggest line, silence
  before a punchline. Everyday sounds are automatic.

Then read the beats as a whole:

- never the same kind three beats in a row;
- at least a quarter of the beats are `explain`;
- the strongest visual sits on the strongest line;
- neighbouring beats look different: layout, size, background, colour or direction of motion;
- numbers on screen are the numbers the person says. Never invent figures.

## 2. Pace targets (check them)

- Something changes on screen every **1 to 2 seconds** on a stressed word: a zoom, a scene, a graphic landing, a cut.
- Nothing sits still for more than about **3 seconds**.
- The first second is already interesting: open on a scene or a hook title, not a plain wide shot.

After a preview, run `python davnai.py pace "<preview.mp4>"`. It counts visual changes a second and the longest still
stretch. If the longest still stretch is over 4 seconds or there are fewer than about 0.3 changes a second, add beats
before showing the person. (Graphics that move inside a scene count less than cuts and layout changes, so look at stills
of the busiest beats too.)

## 3. The tools for each kind

- **Scenes** (`"type": "scene"` in `motion`): the speaker's video moves into a **card**, a small **window** or the lower
  half (**split**) over a designed background (`grid`, `gradient`, `dark`, `light`, `dots`, a colour or a picture),
  with a headline, a list or a counting number. This is the main tool for `explain` beats and for contrast. Two scenes
  in a row should use different layouts or backgrounds.
- **Zooms**: a punch (`"style": "punch"`) on stressed words and turns; a slow push (`"smooth"`) under a build-up. Vary
  the sizes (1.08 to 1.25).
- **Type**: words behind the speaker (`behind`, `"slice": true` on the beat), poster moments, titles.
- **Studio effects**: orbiting pictures, glass widgets, comment box, checklist, tier list and more.
- **Graphics**: counters, charts, lists, lower thirds, end screens.

One theme per video: every scene, title and caption comes from it. Don't mix styles in one frame.

## 4. Captions

Captions run the whole way through. While an effect fills the frame they move up out of its way. While a scene shrinks the
speaker, they drop to the bottom of the frame, clear of the scene's headline. Highlight the words that matter
(`emphasis`), 2 to 4 words at a time, placed where they don't cover the face (`caption_y`).

## 5. Sound

- Every punch zoom and effect gets a whoosh or hit automatically, thinned so sounds never crowd; scenes whoosh in.
  Override one with `"sound": "<name>"` or turn it off with `"sound": false`.
- Music sits under the voice and dips while they speak (`"music"`; from Davnai's library or their own file). It fades
  in and out by itself. Pick its mood from the topic and tell the person which track you chose.
- The voice is cleaned and evened out automatically (`"voice": "raw"` turns it off).

## 6. Matching a reference

When the person shares a reel they like, look at it properly before planning: stills across the whole video
(`python davnai.py match "<reel>"`) and its pace (`python davnai.py pace "<reel>"`). Write down the backgrounds,
type, caption style, layouts, graphics, transitions and cut rate. Your edit's pace numbers should be within about 20% of
the reference's before you show the person.

## 7. Example (a 60-second finance tip)

| beat | said | job | kind | on screen |
|---|---|---|---|---|
| 1 | "If you understand compounding..." | hook | type | poster title "TFSA vs taxable", slow push |
| 2 | "Let me show you why." | turn | talk | punch zoom |
| 3 | "$7,000 a year at 8% for 30 years" | setup | explain | window scene on grid: the three numbers |
| 4 | "two Canadians..." | setup | explain | split scene: "TFSA" vs "Taxable" |
| 5 | "about $800,000" | proof | explain | card scene, counter to $800,000, impact |
| 6 | "That's incredible." | payoff | type | word behind the speaker |
| 7 | "...pay capital gains tax" | contrast | explain | dark window scene: "$120K–$200K in tax" |
| 8 | "max out your registered accounts" | payoff | explain | checklist scene |
| 9 | "Follow for more" | ask | type | end card with their handle |
