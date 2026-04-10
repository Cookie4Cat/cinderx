import argparse
import json
import random
import statistics
from pathlib import Path

REQUIRED_MODES = ("nojit", "jitlist", "autojit50")


def summarize_samples(samples):
    if not samples:
        raise ValueError("samples must be non-empty")
    vals = [float(x) for x in samples]
    return {
        "count": len(vals),
        "mean": statistics.mean(vals),
        "median": statistics.median(vals),
        "min": min(vals),
        "max": max(vals),
    }


def bootstrap_mean_ci(samples, iterations=5000, seed=42, alpha=0.05):
    vals = [float(x) for x in samples]
    if not vals:
        raise ValueError("samples must be non-empty")
    if iterations <= 0:
        raise ValueError("iterations must be > 0")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be between 0 and 1")

    rng = random.Random(seed)
    means = []
    n = len(vals)
    for _ in range(iterations):
        resample = [vals[rng.randrange(n)] for _ in range(n)]
        means.append(statistics.mean(resample))

    means.sort()
    lo_idx = int((alpha / 2.0) * iterations)
    hi_idx = int((1.0 - alpha / 2.0) * iterations) - 1
    lo_idx = max(0, min(lo_idx, iterations - 1))
    hi_idx = max(0, min(hi_idx, iterations - 1))
    return means[lo_idx], means[hi_idx]


def _speedup_pct(arm_mean, x86_mean):
    if x86_mean == 0:
        raise ValueError("x86 mean cannot be zero")
    return ((x86_mean - arm_mean) / x86_mean) * 100.0


def compare_arm_vs_x86(arm_samples, x86_samples, iterations=5000, seed=42):
    arm = [float(x) for x in arm_samples]
    x86 = [float(x) for x in x86_samples]
    if not arm or not x86:
        raise ValueError("arm_samples and x86_samples must be non-empty")

    arm_summary = summarize_samples(arm)
    x86_summary = summarize_samples(x86)
    speedup_pct = _speedup_pct(arm_summary["mean"], x86_summary["mean"])

    rng = random.Random(seed)
    bs = []
    for _ in range(iterations):
        arm_resample = [arm[rng.randrange(len(arm))] for _ in range(len(arm))]
        x86_resample = [x86[rng.randrange(len(x86))] for _ in range(len(x86))]
        bs.append(_speedup_pct(statistics.mean(arm_resample), statistics.mean(x86_resample)))
    bs.sort()
    lo = bs[int(0.025 * iterations)]
    hi = bs[int(0.975 * iterations) - 1]

    return {
        "arm": arm_summary,
        "x86": x86_summary,
        "speedup_pct": speedup_pct,
        "speedup_ci95_pct": [lo, hi],
    }


def validate_runner_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    for key in ("host", "benchmark", "mode_samples"):
        if key not in payload:
            raise ValueError(f"missing payload field: {key}")
    mode_samples = payload["mode_samples"]
    if not isinstance(mode_samples, dict):
        raise ValueError("mode_samples must be a dict")
    for mode in REQUIRED_MODES:
        if mode not in mode_samples:
            raise ValueError(f"missing mode: {mode}")
        vals = mode_samples[mode]
        if not isinstance(vals, list) or not vals:
            raise ValueError(f"mode {mode} must contain a non-empty list")
        for v in vals:
            float(v)
    return True


def _load_samples_file(path, mode=None):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    samples = data.get("samples")
    if samples is not None:
        return [float(x) for x in samples]
    mode_samples = data.get("mode_samples")
    if mode_samples is not None:
        if mode is None:
            raise ValueError(f"{path} has mode_samples; mode is required")
        if mode not in mode_samples:
            raise ValueError(f"{path} missing mode_samples[{mode}]")
        return [float(x) for x in mode_samples[mode]]
    raise ValueError(f"{path} missing 'samples' or 'mode_samples'")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm-samples-json", required=True)
    parser.add_argument("--x86-samples-json", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", default=None)
    parser.add_argument("--iterations", type=int, default=5000)
    args = parser.parse_args()

    arm = _load_samples_file(args.arm_samples_json, mode=args.mode)
    x86 = _load_samples_file(args.x86_samples_json, mode=args.mode)
    result = compare_arm_vs_x86(arm, x86, iterations=args.iterations)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(out_path)


if __name__ == "__main__":
    main()
