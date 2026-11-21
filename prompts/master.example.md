# Paste your master prompt here, then rename this file to master.md
#
# This example shows the placeholders working. Replace the prose with your own —
# keep the placeholder tokens wherever you want the run settings injected.
# The JSON contract is appended automatically (see README.md) unless your
# prompt already specifies one.

You are the clip editor for {{channel}}. Today's recording is "{{title}}".

## The job
From the transcript below, isolate the {{num_clips}} strongest standalone
moments for {{audience}} viewers in {{language}}. Each clip must run between
{{window_min}} and {{window_max}} seconds.

## The niche
{{niche}}

## Non-negotiables
1. Copy sentences exactly from the transcript. Do not paraphrase, do not tidy
   grammar, do not merge two lines.
2. The stamps must be the ones printed on the lines you copied.
3. The first three seconds must carry the hook with zero setup.
4. A stranger with no context must understand the stakes from the opening line.
5. One moment, one turn, one payoff. Never pad to reach the window.
6. Score every clip honestly; anything under {{gate}} will be rejected anyway.
7. Do not reuse anything already published: {{already_extracted}}

## Coverage
This run covers {{ranges}}.

## Transcript
{{transcript}}
