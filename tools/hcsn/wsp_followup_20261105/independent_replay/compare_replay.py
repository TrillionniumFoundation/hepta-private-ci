"""Compare a complete frozen replay with the first execution, not a new holdout.

Only the explicitly listed resource measurements are excluded. Model values,
world contents, all other trajectory diagnostics, decisions, gates and primary
statistics must compare exactly as parsed JSON, without numerical tolerance.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

TRAJECTORY_RESOURCE_FIELDS = frozenset({
    "arm_initialization_cpu_seconds", "cpu_seconds", "wall_seconds",
    "full_cold_preparation_cpu_seconds", "full_cold_preparation_wall_seconds",
    "policy_cpu_seconds", "verification_cpu_seconds", "world_feature_cpu_seconds",
})
SUMMARY_RESOURCE_FIELDS = frozenset({"cpu_seconds", "wall_seconds", "peak_rss_bytes"})


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def read(path):
    payload = path.read_bytes()
    return json.loads(gzip.decompress(payload) if path.suffix == ".gz" else payload)


def strip(value, omitted):
    if isinstance(value, dict):
        return {key: strip(item, omitted) for key, item in value.items() if key not in omitted}
    if isinstance(value, list):
        return [strip(item, omitted) for item in value]
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def compare(original, replay):
    models = sorted(path.relative_to(original) for path in (original / "models").glob("*.json.gz"))
    worlds = sorted(path.relative_to(original) for path in (original / "worlds").glob("*.json.gz"))
    trajectories = sorted(path.relative_to(original) for path in original.glob("*_RESULTS.json.gz"))
    assert (len(models), len(worlds), len(trajectories)) == (35, 20, 20)
    groups = [(models, frozenset(), "model"), (worlds, frozenset(), "world"),
              (trajectories, TRAJECTORY_RESOURCE_FIELDS, "trajectory"),
              ([Path("RESULTS.json")], SUMMARY_RESOURCE_FIELDS, "summary"),
              ([Path("ALL_GATES_BEFORE_TEST.json")], frozenset(), "gate")]
    checks = []
    for paths, omitted, category in groups:
        for relative in paths:
            first = strip(read(original / relative), omitted)
            second = strip(read(replay / relative), omitted)
            assert first == second, str(relative)
            checks.append({"path": relative.as_posix(), "category": category,
                           "original_file_sha256": sha((original / relative).read_bytes()),
                           "replay_file_sha256": sha((replay / relative).read_bytes()),
                           "compared_semantic_sha256": sha(canonical(first)),
                           "exact_json_equal": True})
    all_files = [{"path": path.relative_to(replay).as_posix(),
                  "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}
                 for path in sorted(replay.rglob("*")) if path.is_file()]
    return {"schema": "hepta.wsp.frozen-full-replay-comparison.v1", "passed": True,
            "models_compared": 35, "world_files_compared": 20,
            "trajectory_files_compared": 20, "worlds_scored": 480,
            "all_comparisons": len(checks), "comparisons": checks,
            "trajectory_resource_fields_excluded": sorted(TRAJECTORY_RESOURCE_FIELDS),
            "summary_resource_fields_excluded": sorted(SUMMARY_RESOURCE_FIELDS),
            "numeric_tolerance": 0, "replay_file_manifest": all_files,
            "scope": "Full frozen execution replay; same checkpoints and exposed schedules, not a fresh holdout or independent implementation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = compare(args.original, args.replay)
    with args.output.open("x") as handle:
        json.dump(result, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"comparisons", "replay_file_manifest"}}, sort_keys=True))
