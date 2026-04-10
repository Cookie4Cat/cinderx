#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_summary(path: Path) -> dict[str, float]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return {
        row["name"]: float(row["median"])
        for row in data.get("benchmarks", [])
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--warn-threshold-pct", type=float, default=5.0)
    args = parser.parse_args()

    base = load_summary(Path(args.base))
    current = load_summary(Path(args.current))
    names = sorted(set(base) | set(current))

    rows = []
    regressions = []
    for name in names:
        base_val = base.get(name)
        current_val = current.get(name)
        if base_val is None or current_val is None:
            rows.append(
                {
                    "name": name,
                    "base_median": base_val,
                    "current_median": current_val,
                    "delta_pct": None,
                }
            )
            continue
        delta_pct = ((current_val / base_val) - 1.0) * 100.0
        row = {
            "name": name,
            "base_median": base_val,
            "current_median": current_val,
            "delta_pct": delta_pct,
        }
        rows.append(row)
        if delta_pct >= args.warn_threshold_pct:
            regressions.append(row)

    payload = {
        "rows": rows,
        "warn_threshold_pct": args.warn_threshold_pct,
        "regressions": regressions,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
