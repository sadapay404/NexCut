# PHASE 2 PROMPT — B-ROLL, DOCUMENTARY EDITS, MUTE REVIEW (one clip)

You are given one already-approved clip from a run, the full timestamped
transcript of the source video, and the Entity Map from that run. Build the
edit plan for **this clip only**.

- Clip: #{{clip_n}} — {{clip_title}}
- Range: {{clip_start}} → {{clip_end}} ({{clip_duration}})
- Niche: {{niche}}
- Nothing may be invented: no identities, places, evidence, documents or links.

## P1 — CLIP FIRST
The clip's own words are the source of truth. Identify named people, places,
items, documents, key statements, turning points and concepts that need a visual.
Keep exact names exactly as spoken.

## P2 — PRONOUN MATCHING
For he / she / they / this guy / the victim / that place / the letter:
1. Look at the clip's nearby lines first.
2. Assign a name from the Entity Map **only** when exactly one entity fits the role
   or the action.
3. If two could fit: `Unconfirmed (possibly A or B)` and use a non-identifying visual.
4. Never put a real person's photo on a pronoun without a confident match.
5. A pronoun alone never creates a new visual moment — it only decides **who** is
   shown at a moment the timing rules already chose.

## P3 — ADAPTIVE TIMING
Aim for a new visual every 5–7 s when the story supports it, but place the visual
the instant the reference is spoken: a name at second 3 gets its visual at second 3.
If roughly 10 s pass with no specific reference, add one relevant generic visual.
No fixed schedule, no metronome cuts.

## P4 — CONTINUITY
Keep the current visual until a genuine new trigger appears (new name, place, item,
document, or new key statement). Never swap just because time passed.

## P5 — SOURCES
Every source cell starts with `Google Images:`, `Stock Footage:` or `AI-Generated:`
followed by the exact query or a copy-ready prompt.
- Real people and places → Google Images (official, archival, reputable news).
- Never an AI or look-alike face for a real named person.
- Evidence and documents → real if verifiable, otherwise clearly labelled illustrative.
- Generic scenes → stock or AI, realistic US documentary look.
- Historical or foreign stories → match the era and the country.

## P6 — DOCUMENTARY VALUE
Only additions that carry real context: name label, location tag, date or timeline
card, relationship graphic, document close-up, "alleged vs confirmed" label. Give
the exact on-screen text. Never duplicate the auto-captions.

## P7 — ACCURACY & PLATFORM RISK
Separate allegation from fact. Never present an accused person as guilty unless the
verdict supports it. Avoid graphic imagery when a neutral image works. Respect the
victims. Flag anything that could mislead. Never promise monetisation approval.

## P8 — MUTE REVIEW (conservative)
Flag only: slurs, hate speech, hard profanity, direct violent threats, or extremely
graphic gore, torture or self-harm detail. Do **not** flag ordinary true-crime
vocabulary (murder, killed, shot, stabbed, body, blood, abuse used descriptively) or
mild words (damn, hell, crap). Sexual content: flag only crude or graphically
explicit wording. When unsure, do not flag. Most clips should have zero or very few
rows.

## AI PROMPT RULES (every prompt and stock query)
- **Bright and colourful by default:** natural vibrant colour, soft daylight or
  bright overcast, well-exposed subject, lifted shadows, crisp focus, natural skin
  tones, balanced contrast, subtle cinematic depth. Never gloomy, muddy or
  underexposed — even for murder or courtroom topics.
- Scene decides the mood: if the moment truly happens at night, in a tunnel, in a
  storm or in a genuinely frightening place, make it dark **and** high quality —
  clear subject, visible detail, motivating light (moonlight, streetlight,
  flashlight, warm window glow). Never a black, muddy frame.
- Photoreal, original-photo look: a frame from a high-end US news investigation,
  true-crime documentary or film. Real textures, believable light, natural poses,
  sharp detail. Never cartoon, painting, 3D render or plastic skin.
- Authentic US settings when the story is American: homes, suburbs, streets,
  courthouses, interview rooms, legal offices, newsrooms, US vehicles. No automatic
  flags, police lights or paperwork unless relevant. No fake seals, no legible fake
  case documents.
- Real people: never generate a real named face — use a non-identifiable fictional
  person or a contextual scene, and recommend a verified real photo instead.
- No fake evidence or fake crime-scene imagery presented as real.
- Composition: vertical 9:16, one clear subject readable on a phone, balanced, no
  clutter, nothing important at the edges, no logos, watermarks, captions or text.
- Match the target word exactly. One prompt per visual, same order as the timeline.
- Each prompt stands alone and states subject, environment, composition, lighting,
  colour, photorealism and 9:16.

## OUTPUT — one structured object, nothing else

```
{
  "overview": { "duration": "MM:SS", "subject": str, "key_people": [str], "key_places": [str], "key_items": [str] },
  "timeline": [{
    "n": int, "ts": "MM:SS", "line": "8–10 words max, verbatim", "target": "exact word, never blank",
    "visual": str, "source": "Google Images: … | Stock Footage: … | AI-Generated: …",
    "match": "Confirmed | Table-matched | Unconfirmed-generic",
    "duration": "Xs", "note": str
  }],
  "research": [{ "subject": str, "query": str, "source_type": str, "verification": "confirmed | needs check" }],
  "generic": [{ "line": str, "stock_query": str, "ai_prompt": str }],
  "edits": [{ "ts": "MM:SS", "line": str, "addition": str, "spec": "exact on-screen text", "purpose": str }],
  "mute": [{ "ts": "MM:SS", "line": str, "target": str, "reason": str, "action": "keep | review | mute | beep" }],
  "checklist": { "names_covered": bool, "visuals_match": bool, "no_forced_timing": bool,
                 "first_10s_covered": bool, "sources_real_or_labelled": bool,
                 "pronouns_confident": bool, "mute_reviewed": bool, "whole_clip_covered": bool }
}
```

If no line needs muting, return `"mute": []` — never a placeholder row.
Keep every cell short. Mark estimated timestamps as estimates.
