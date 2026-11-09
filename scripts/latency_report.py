"""Summarise per-stage latency from reports/latency.jsonl.

Usage:
    python scripts/latency_report.py [path] [--markdown out.md]

Prints the median and 90th percentile for each stage, overall and per STT
provider. These are measured numbers for Demo Day; report them as measured,
with the sample size, and never as vendor claims.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

STAGES = [
    "vad_ms",
    "stt_ttfp_ms",
    "stt_final_ms",
    "stt_wait_ms",
    "intent_ms",
    "name_enquiry_ms",
    "tts_ttfa_ms",
    "reply_ms",
]
TARGET_MEDIAN_MS = 2000
TARGET_SLOW_MS = 3500


def percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    k = max(0, min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1))))
    return ordered[k]


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def table(rows: list[dict]) -> list[str]:
    out = ["| Stage | n | median ms | p90 ms |", "| --- | ---: | ---: | ---: |"]
    for stage in STAGES:
        values = [int(r[stage]) for r in rows if isinstance(r.get(stage), (int, float))]
        if not values:
            continue
        out.append(f"| {stage} | {len(values)} | {int(statistics.median(values))} | {percentile(values, 90)} |")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="reports/latency.jsonl")
    parser.add_argument("--markdown", help="also write the report to this file")
    args = parser.parse_args(argv)
    path = Path(args.path)
    if not path.exists():
        print(f"no latency log at {path}; run some voice turns first", file=sys.stderr)
        return 1
    rows = load(path)
    lines = [f"# Avenza measured latency ({len(rows)} turns)", ""]
    lines += ["## All turns", ""] + table(rows) + [""]
    by_provider: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_provider[str(row.get("provider", "unknown"))].append(row)
    for provider, group in sorted(by_provider.items()):
        lines += [f"## {provider}", ""] + table(group) + [""]

    # Headline: end of speech to start of read-back, excluding the VAD wait.
    reply = [int(r["reply_ms"]) for r in rows if isinstance(r.get("reply_ms"), (int, float))]
    if reply:
        med, p90 = int(statistics.median(reply)), percentile(reply, 90)
        verdict = "meets" if med <= TARGET_MEDIAN_MS and p90 <= TARGET_SLOW_MS else "misses"
        lines += [
            f"End of speech to reply: median {med} ms, p90 {p90} ms over {len(reply)} turns "
            f"({verdict} the target of about {TARGET_MEDIAN_MS} ms median and under {TARGET_SLOW_MS} ms slow). "
            "VAD silence tolerance is logged separately as vad_ms.",
        ]
    report = "\n".join(lines)
    print(report)
    if args.markdown:
        Path(args.markdown).write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
