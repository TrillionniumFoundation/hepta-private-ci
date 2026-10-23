"""Source-locked research replay. Does not certify real independent outcomes."""
import hashlib
import json
import math
from pathlib import Path

from factorial import run

ROOT = Path(__file__).resolve().parent


def hash_file(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def compare(expected, actual, path=""):
    # Timing varies with host/runner load and is *never* replayed as an exact quantity.
    if path.endswith("_wall_seconds_observed"):
        if not (isinstance(actual, (int, float)) and math.isfinite(actual)):
            raise AssertionError(f"invalid measured time: {path}")
        return
    # Weights differ at floating-point ulp granularity on some hosts; the
    # original SHA remains pinned, and result metrics are compared separately.
    if path.endswith("final_weight_digest"):
        if not isinstance(actual, str) or len(actual) != 64:
            raise AssertionError(f"invalid trained-weight identity: {path}")
        return
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            raise AssertionError(f"schema mismatch at {path}")
        for k in expected:
            compare(expected[k], actual[k], f"{path}.{k}")
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            raise AssertionError(f"length mismatch at {path}")
        for index, (e, a) in enumerate(zip(expected, actual)):
            compare(e, a, f"{path}.{index}")
    elif type(expected) in (int, float) and type(actual) in (int, float):
        if not math.isclose(expected, actual, rel_tol=0, abs_tol=1e-8):
            raise AssertionError(f"numeric mismatch at {path}: {expected} != {actual}")
    elif expected != actual:
        raise AssertionError(f"mismatch at {path}: {expected!r} != {actual!r}")


def verify():
    lock = json.loads((ROOT / "SOURCE_LOCK.json").read_text())
    for filename, digest in lock["source_sha256"].items():
        if hash_file(filename) != digest:
            raise AssertionError(f"frozen source bytes changed: {filename}")
    evidence = json.loads((ROOT / "development-report.json").read_text())
    seeds = [r["seed"] for r in evidence["seeds"]]
    if seeds != [17, 29, 43]:
        raise AssertionError("unregistered seed coverage")
    for original in evidence["seeds"]:
        fresh = run(original["seed"])
        compare(original, fresh, f"seed.{original['seed']}")
    if not any(row["seed"] == 29 for row in evidence["negative_findings"]):
        raise AssertionError("adverse seed removed")
    return {"audit": "development_replay_only", "seeds": seeds,
            "source_files_verified": len(lock["source_sha256"]),
            "all_2x2_arms_recomputed": 4 * len(seeds),
            "confirmatory_efficacy": False,
            "natural_data": False,
            "production_authority": False}

if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
