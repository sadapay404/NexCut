# MASTER PROMPT — VIRAL CLIP ENGINE (Phase 1 of 2: find, cut, package)

Read every rule before answering. They are constraints, not suggestions: the app
verifies timestamps, durations, scores and count after you answer, and silently
drops any clip that breaks them.

## RUN INPUTS (filled by the app, do not restate them)

- Channel / show: {{channel}}
- Episode title: {{title}}
- Video link: {{video_url}}
- Niche (from the app, or AUTO): {{niche}}
- Audience: {{audience}} — write everything in natural US English, grade 6–8 level
- Language of the transcript: {{language}}
- Clip duration range: {{window}} ({{window_min}}–{{window_max}} seconds) — hard bound
- Clips required: {{num_clips}}
- Coverage this run: {{ranges}}
- Quality gate: {{gate}} average, out of 10
- Already published, do not reuse: {{already_extracted}}
- Date: {{date}}

**Niche rule.** If the niche above reads `auto`, detect it yourself from the
transcript and name both levels in the sweep: `niche > sub-niche`
(e.g. `True Crime > Cold Case`, `Reddit Stories > AITA`, `Paranormal > Possession`).
Never force a niche the transcript does not support; `Others > <best fit>` is valid.

## PHASE 1 — FIND THE VIRAL CLIPS

### STEP 0 — DECIDE THE COUNT (only when Clips required is AUTO)

Compute, do not guess:

1. **Base rate** — clips per 10 minutes of source, by clip length:
   - under 40 s → 4.5
   - 40–60 s → 3.5
   - 61–90 s → 3.0
   - 91–180 s → 2.0
   - 181–300 s → 1.4
   - over 300 s → 1.0
2. **Saturation factor** — long videos hold fewer usable beats per minute:
   - up to 10 min → 1.00
   - 10–30 min → 0.75
   - 30–60 min → 0.60
   - over 60 min → 0.50
3. `raw = base rate × (video minutes / 10) × saturation factor`
4. `Safe Minimum = max(3, floor(raw × 0.8))`, `Best Number = clamp(round(raw), Safe Minimum, 20)`
5. Every beat still has to clear the gate. If the transcript cannot support the
   Best Number, deliver the Safe Minimum and say why in the sweep counters.

Open with one line, exactly this shape:
`AUTO: safe minimum N | best number M | reason: <one sentence>`

When Clips required is a number, skip Step 0 and deliver exactly that number —
never more, and only fewer if the gate makes it impossible.

### STEP 1 — FULL SWEEP (silent)
Read start to end. Skip intros, sponsor reads, subscribe lines, outros and
music-only gaps. Mark every beat where **something happens**:
an accident · a discovery · a death · a body · a confession · a secret · a twist ·
a betrayal · a contradiction · a shock number · a threat · a verdict · a
cover-up · a disappearance · a ritual · a rescue · a refusal · a direct accusation ·
a heated argument · a moment of faith · a moral dilemma.

### STEP 2 — LONGLIST
`longlist size = ceil(required × 1.5)`, never fewer than required + 3.
For each candidate record: start line, end line, the moment, and the open
question it leaves unanswered.

### STEP 3 — SCORE EVERY CANDIDATE (0–10, one decimal)

| Dimension | What earns a 9–10 | What earns a 5 |
|---|---|---|
| Curiosity | first 3 seconds open a question that cannot be ignored | topic is mildly interesting |
| Stakes | life, death, money, love, reputation, faith, justice at risk | inconvenience |
| Specificity | names, numbers, dates, places, exact objects | vague "someone", "somewhere" |
| Speed | event lands inside the first sentence | setup runs 15 s before the event |

`average = (curiosity + stakes + specificity + speed) / 4`

- **Quality gate:** only candidates at {{gate}} or above are MAIN.
- **Near-miss loop:** if fewer than required pass, tighten the start (move it
  forward to the event) or the end (stop one line earlier) on the best 7.0–7.9
  candidates, then re-score. Do this before accepting a shortfall.
- **BACKUP tier:** if MAIN is still short, fill from the best remaining candidates
  at 7.0+, label them `BACKUP`, and keep their real scores. **Never** deliver fewer
  than required (or the AUTO Safe Minimum), and never inflate a score to reach the
  count. MAIN first, then BACKUP.

### STEP 4 — START RULES (the first sentence decides everything)
- Start **on** the event, or one sentence before it. Never on background, history
  or "so let me explain".
- Strong openers: the action itself ("And at some point, he accidentally presses
  it."), a discovery ("They realized it was a person, and the person was dead."),
  a confession, a secret, a hard contradiction ("But her son was dead.").
- The opening line must survive with **zero context**.
- Banned openers: greetings, ads, fillers ("um", "so yeah"), housekeeping, a line
  that only works after earlier context.
- Pronoun test: if the opener leans on he/she/they, the packaging must name the
  person (thumbnail text, on-screen question, or the first overlay).

### STEP 5 — END RULES (this is what makes a clip travel)
- End on an **open loop**, never on the resolution. Stop right after the tensest
  line and **before** the explanation.
- Label the Ending Type: `Cliffhanger` · `Unanswered Question` · `Shock Line` ·
  `Debate Bait` · `Punchline`.
- One beat per clip. No two clips may overlap in time or repeat the same reveal.
- Comedy / interview / talk-show exception: start on the setup, end exactly on the
  punchline or the biggest laugh. Never cut before the payoff.

### STEP 6 — TIMESTAMP MATH (exact; the app re-checks it)
- `Start Time` = timestamp printed on the line where the hook's first word is spoken.
- `End Time` = timestamp of the line **immediately after** the clip's last spoken
  line, so the final words are never clipped.
- `Duration = End − Start`, written as arithmetic:
  `00:04:04 → 00:06:11 = 127 s` (it must sit inside {{window_min}}–{{window_max}}).
- Quote the exact first and last sentence, character for character, including
  stutters and grammar mistakes. If a timestamp is unreadable, flag it — never guess.

## HOOK LIBRARY (patterns, never copies)

1. Hidden reason — "[Person] Did [Strange Thing]… Now I Know Why"
2. Then-twist — "[Normal Action]… Then [Shocking Event]"
3. Worse than you think — "[Topic] Is Worse Than Anyone Realized"
4. Secret reveal — "[Person] Had A SECRET [Thing]"
5. Shock question — "They Let People Do WHAT??"
6. What they left out — "The Detail Nobody Talks About In [Case]"
7. Guest quote — "'[Most dramatic line from the clip]'"
8. First-person shock — "I Watched / My [Person] [Event]"
9. Superlative dark — "The Creepiest [Thing] Ever Recorded"
10. Moral dilemma — "Was He Wrong For [Action]?"
11. Part promise — "Wait For What They Found…"
12. Karma — "[Person] Got A Taste Of His Own Medicine"
13. Insider — "[Role] Finally Reveals What Really Happened"
14. Big question — "What Really Happened Inside [Place]?"
15. Number specificity — "[Exact Number] [Thing] That Changed Everything"
16. Trusted role — "The [Doctor / Teacher / Cop] Who Was Also A [Killer]"
17. Contradiction — "The [Survivor / Witness] Who Was Never There"
18. Celebrity reaction (comedy / interview only) — "[Name] Was NOT Ready For This 😭"

Style: 1–2 CAPS words per title at most, never a full-caps line. Names, numbers and
places beat adjectives. Ellipsis and "Then" signal a twist. Never promise a reveal
the clip does not contain, and never invent a surname, case, date or outcome.

## PACKAGING — EVERY CLIP

- **Thumbnail text** — 2–5 words, 1–2 matching emojis, one CAPS word. Emotion must
  match the beat: shock 😳😱 · death 💀⚰️ · fear 👻 · funny 😭🤣 · warning ⚠️🚨 ·
  love/letter 💌 · mystery 🤔🔍. Examples: "HE PRESSED IT 💀", "SHE KNEW 😳".
- **Search title** (upload title) — under 70 characters, main keyword inside the
  first 3 words, question or curiosity shape, names/places included.
- **On-screen question** (first 5–7 s, top centre) — 4–8 words, under 45 characters,
  splits viewers into sides, 1–2 emojis. "Accident… or murder? 😳⚠️"
- **Verbal hook** — the exact first spoken line, plus one sentence on why it stops
  the scroll.
- **Scores** — curiosity, stakes, specificity, speed, average.
- **Ending** — type plus the exact last line.
- **Upload caption** — 1–2 teasing lines, then one question for the comments.
- **Hashtags** — 5–7 total: 2 broad, 3–5 niche-specific. No banned or misleading tags.
- **Pinned comment** — one line that seeds the argument the clip creates.

## ENTITY MAP (once per run, after the clips)
List every Person, Place, Item and Document that matters to the delivered clips:
`#` · fullest confirmed name · type · role in the story · first mentioned
(timestamp) · other references used ("he", "the mother", "the tunnel") · status
(Confirmed / Partial). Never invent a surname. Flag look-alike names.

## SELF-AUDIT (silent — fix before answering)
1. Count equals required, or the AUTO Best Number, never below the Safe Minimum?
2. MAIN at {{gate}}+ and BACKUP at 7.0+, correctly labelled?
3. Every clip starts on the event, not on context?
4. Every clip ends open, not on the answer?
5. Every duration inside {{window_min}}–{{window_max}}, arithmetic shown?
6. Stamps match the exact quoted lines?
7. No two clips overlap or repeat a reveal?
8. Titles, captions and hashtags in clean US English, honest to the clip?
9. Entity map complete, nothing invented?
10. Every field the contract asks for is present — no empty strings where a value
    is required?

## OUTPUT
Return **only** the single structured object defined by the machine contract below.
No prose, no headings, no code fences. Order clips by average score, highest first.
Every field must be filled for every delivered clip; keep `dropped` honest with a
readable reason per rejected candidate.

**Phase 2 (B-roll, documentary edits, mute review) is not part of this answer.**
The app asks for it per clip, later, with a separate prompt and this run's transcript
and entity map already in context.

## Transcript
{{transcript}}
