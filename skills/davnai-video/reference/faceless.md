# Faceless videos (stock clips or pictures + a voice-over)

1. **Voice-over:** the person's own recording (a file they give you), or a free voice made on this computer: write the script, then `python davnai.py voice script.txt -o voiceover.wav --voice af_heart` (needs `setup --motion`; voices include af_heart, af_nova, am_michael, bf_emma, bm_george). Tell the person it's an AI voice, and use paid voice services only if they ask.
2. **Transcribe the voice-over:** `python davnai.py transcribe "<voice file>"`.
3. **Clips and pictures** (cheapest source first, see `stock.md`): put them in a folder next to the voice-over.
4. **Plan:** one scene per idea, covering transcript lines in order, with no gaps. Every line must be in exactly one scene.

```json
{
  "outputs": [
    {
      "name": "faceless-1",
      "aspect": "9:16",
      "voice": "voiceover.mp3",
      "scenes": [
        { "lines": [1, 2], "clip": "clips/city-morning.mp4" },
        { "lines": [3, 5], "clip": "clips/laptop.jpg" },
        { "lines": [6, 9], "clip": "clips/coffee.mp4", "start": 2 }
      ],
      "captions": true,
      "music": "music/calm.mp3"
    }
  ]
}
```

- A scene lasts as long as its lines are spoken. A short clip loops; a long one is cut. `start` skips that many seconds into the clip (a number about the clip, not the voice, so it's fine to write).
- Pictures are shown with a slow zoom.
- Change the clip every 2 to 5 seconds for Shorts; longer for calm videos.
- Captions matter most here: keep `"captions": true`.
