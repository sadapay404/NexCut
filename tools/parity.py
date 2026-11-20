"""Parity harness: run a *recorded* model answer through our parser + gate.

This is the acceptance test for the whole reconstruction. Point it at a real
`oracle_report` and the transcript it came from, and it prints exactly what our
gate would have kept, what it would have dropped, and why:

    python3 -m tools.parity --report oracle.json --transcript ep.txt --window E

If the reference tool delivered N clips and we keep the same N with the same
timestamps, the rule ordering and the 8.0 math are behaviourally equivalent.
Any disagreement is a concrete, fixable bug -- which is the point.

Exit code: 0 when every returned clip survives, 3 when we would drop something
(so it can be used in CI), 2 on input problems.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nexcut.parse import ExtractError, build_result, ensure_timestamps  # noqa: E402
from nexcut.schema import WINDOWS  # noqa: E402
from nexcut.validate import apply_rules, check_clip, normalize_transcript  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="parity", description="Gate a recorded model answer.")
    ap.add_argument("--report", required=True, type=Path, help="raw model answer (text or .json)")
    ap.add_argument("--transcript", required=True, type=Path, help="transcript the answer came from")
    ap.add_argument("--window", default="E", choices=sorted(WINDOWS))
    ap.add_argument("--custom-min", type=int, default=None)
    ap.add_argument("--custom-max", type=int, default=None)
    ap.add_argument("--gate", type=float, default=8.0)
    ap.add_argument("--clips", type=int, default=None, help="top-N limit (default: no limit)")
    ap.add_argument("--json", action="store_true", help="dump the resulting payload")
    args = ap.parse_args(argv)

    try:
        transcript = args.transcript.read_text(encoding="utf-8", errors="replace")
        answer = args.report.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"✗ cannot read input: {exc}", file=sys.stderr)
        return 2

    try:
        ensure_timestamps(transcript)
        result = build_result(answer, window_label=args.window)
    except ExtractError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    norm = normalize_transcript(transcript)
    print(f"report: {len(result.clips)} clip(s) parsed · longlist {result.sweep.longlist or len(result.longlist)}")
    print(f"transcript: {len(transcript.splitlines())} lines · {len(norm):,} chars normalised")
    print(f"window {args.window} · gate {args.gate}\n")

    width = max((len(str(c.hook_summary)) for c in result.clips), default=20)
    width = min(max(width, 20), 42)
    print(f"{'#':>2}  {'avg':>4}  {'dur':>8}  {'verdict':<8}  reason")
    print("-" * 96)
    dropped = 0
    for c in result.clips:
        reason = check_clip(
            c, norm, window=args.window, custom_min=args.custom_min,
            custom_max=args.custom_max, gate=args.gate,
        )
        verdict = "DROP" if reason else "keep"
        dropped += bool(reason)
        avg = f"{c.scores.avg:.1f}" if c.scores.avg is not None else "—"
        label = (c.hook_summary or "")[:width] or f"clip {c.n}"
        print(f"{c.n:>2}  {avg:>4}  {c.duration_str:>8}  {verdict:<8}  {reason or label}")

    gated = apply_rules(
        result, transcript, window=args.window,
        custom_min=args.custom_min, custom_max=args.custom_max,
        gate=args.gate, limit=args.clips,
    )
    print(f"\nkept {len(gated.clips)} · dropped {len(gated.dropped)}")
    if gated.dropped:
        print("\nreasons:")
        for d in gated.dropped:
            print(f"  #{d.clip}: {d.reason}")

    if args.json:
        print("\n" + json.dumps(gated.to_dict(), indent=2, ensure_ascii=False))
    return 3 if dropped else 0


if __name__ == "__main__":
    raise SystemExit(main())
