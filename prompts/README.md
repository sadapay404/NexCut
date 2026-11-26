# Prompt folder

Drop **your** master prompt here as `master.md`. No code change, no restart —
the studio reads the file at the start of every run.

| File | Required | What it does |
|---|---|---|
| `master.md` | yes | Your prompt. Placeholders are filled from the run settings. |
| `system.md` | no | Replaces the built-in system instruction. |
| `contract.md` | no | Replaces the machine contract appended for parsing. |

## Placeholders

```
{{transcript}}        the timestamped transcript (the big one)
{{niche}}             "True Crime — Scandal" when a sub-category is chosen
{{niche_base}}        "True Crime"
{{subniche}}          "Scandal" (empty when none)
{{audience}}          "U.S. English"
{{language}}          "Urdu-English mix"
{{window}}            "Option E: 45s-5m25s (Oracle Wide Range - default)"
{{window_min}}        e.g. 45
{{window_max}}        e.g. 325
{{num_clips}}         e.g. 5
{{channel}} {{title}} {{host_guest}} {{video_url}} {{video_id}}
{{already_extracted}} whatever the user typed as already published
{{gate}}              quality gate, e.g. 8.0
{{ranges}}            the coverage plan, e.g. "00:00:00-00:10:00 | 00:09:30-00:20:00"
{{date}}
```

Unknown placeholders are left untouched and reported as a warning in the UI, so
a typo is visible instead of silently becoming an empty string.

## About the JSON contract

The studio must parse the answer. If `master.md` does not mention JSON, a
machine contract is appended automatically describing the exact object shape.
If your prompt already specifies the output format, set:

```bash
NEXCUT_APPEND_CONTRACT=0     # never append
NEXCUT_APPEND_CONTRACT=1     # always append
```

Default is `auto`: append only when your prompt never says "json".

Copy `master.example.md` to `master.md` to start from a working structure.
