---
name: davnai-posts
description: Write, grade and schedule social media posts with Davnai, in the person's own voice. Use when the person wants captions or posts for a video or idea, wants a draft scored and improved, or wants one video turned into a week of content, and Davnai is connected.
---

# Davnai posts

Write the words yourself (it keeps their Davnai AI allowance for what only Davnai can do), then hand them to Davnai with `create_posts`. Nothing is published until they approve it in Davnai.

## Before writing

- `get_brand_kit`: their voice, words they use, words to avoid, their handle and link. Match it; if there's no voice yet, ask for two posts they liked and copy the rhythm.
- `list_accounts`: which platforms are connected. Write only for those.
- For a video: what it says (the transcript, or `get_video`), its best moment and its single takeaway.

## Writing a post

1. **Hook first line** (use the davnai-hooks skill): it must make the right person stop. No "In this video…".
2. **One idea**, said simply, with something concrete (a number, a step, a mini-story).
3. **A reason to act**: one call to action (comment a word, save, follow, the link in bio). If they have a comment-to-DM automation, use its keyword.
4. **Fit the platform**:
   - TikTok, Reels, Shorts: 1–3 short lines; the video does the work. 3–5 specific hashtags at most.
   - Instagram feed: hook line, short paragraphs with line breaks, a question or call to action, then hashtags.
   - LinkedIn: no hashtag walls; a strong first two lines (the rest is hidden behind "more"), white space, a real lesson.
   - X: one tight thought; a thread only if it earns it.
   - Facebook, Threads: conversational; a question invites comments.
   - YouTube: a searchable title (what they'll learn) and a description whose first lines say why to watch.
   Davnai checks each platform's length when you call `create_posts`; if it says a post is too long, shorten it.
5. **Never**: invented facts or results, fake urgency, other people's words as theirs, engagement bait the platforms punish ("like if…").

## Grading a draft (when asked, or before you hand posts over)

Score 0–10 on each, then give the **3 fixes** that would help most, with a rewritten version:

| | asks |
|---|---|
| Hook | Would the right person stop scrolling in the first line? |
| Clarity | One idea, plain words, no filler? |
| Value | Do they learn, feel or get something? |
| Voice | Does it sound like them (Brand Kit), not like an AI? |
| Action | One clear next step? |
| Fit | Right length, format and hashtags for this platform? |

## Repurpose one video into a week

From one recording: 3–5 Shorts (the davnai-video skill picks and edits them), a post for each platform per Short, one longer post (the full lesson as a LinkedIn or Instagram carousel text), and one question post to start conversations. Spread them over the week with `posting_times` (their best times), show the plan as a short table (day, platform, post), and only then `create_posts` with those times. They approve in Davnai.

## Handing over

`create_posts` with the video id (from the upload) or picture, the words per platform and the times. Tell them it's waiting for their approval in Davnai, and where (Calendar).
