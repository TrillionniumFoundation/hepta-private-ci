"""Source-first V18 replay gate: immutable historical bytes, bounded numeric replay.

Historical receipt SHA is not a tolerance. A new replay can differ by host FP
rounding, but ONLY after the original V15/V16/V17 saved tensors and original
source bytes were independently re-forwarded by the original NumPy evaluator.
This tool never reads the 32 held labels or grants scientific/production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = "hepta.stem.v19.independent-replay-equivalence.no-go"
FROZEN_RECEIPT_SHA = "5c9cf67e1d91ca8ebc5adafd9963357a91ddb45361f43d0311c276150e29edb4"
FROZEN_HOLD_SHA = "1cd975d0ab51fbe90ee161df1a30c8a7dc66b06bd39e46eb19229b699b544372"
FROZEN_V18_SOURCE_SHA = "9693d3a5be2dd4fb50b0e033d9798932237df0cabacd8d0b017d78ca1028d0f4"
# Max permitted literal metric drift on the fixed original calibration case roster.
# Not a confidence interval, validation of a new model, or permission to retune.
MAX_ABSOLUTE_NUMERIC_DRIFT = 0.0000005
ORIGINAL_CASES = 32
ARM_COUNT = 12
SEEDS = ("41", "47", "53")
ALLOWED_REPLAY_CHANGED_IDENTITY = "v17_sealed_sha256"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def unique_pairs(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "duplicate JSON key")
        result[k] = v
    return result


def regular_bytes(path, maximum=700_000):
    p = Path(path)
    require(p.is_file() and not p.is_symlink() and 0 < p.stat().st_size <= maximum,
            "bounded ordinary evidence file required")
    return p.read_bytes()


def parse(raw):
    def reject_constant(x):
        raise ValueError("nonfinite JSON number: " + x)
    result = json.loads(raw, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    canonical(result)
    return result


def history(path, hold_path):
    frozen_raw, hold_raw = regular_bytes(path), regular_bytes(hold_path)
    require(sha(frozen_raw) == FROZEN_RECEIPT_SHA, "historical V18 receipt bytes modified")
    require(sha(hold_raw) == FROZEN_HOLD_SHA, "historical V18 HOLD bytes modified")
    archived, hold = parse(frozen_raw), parse(hold_raw)
    require(archived.get("status") == "RETROSPECTIVE_CLUSTERED_CALIBRATION_ONLY"
            and archived.get("resampling_units") == ORIGINAL_CASES
            and archived.get("candidate_arm_count") == ARM_COUNT
            and archived.get("independent_model_bytes_verified") == 82
            and archived.get("prospective_outcomes") == 0
            and archived.get("production_authorized") is False
            and archived.get("scientific_promotion_authorized") is False,
            "original frozen source is not an admissible research negative receipt")
    require(hold.get("verdict") == "HOLD_MISSING_NEW_INDEPENDENT_WINDOWS"
            and hold.get("new_signed_window_count") == 0
            and hold.get("new_source_roots") == 0
            and hold.get("prospective_future_utility") is None
            and hold.get("production_authorized") is False
            and hold.get("scientific_promotion_authorized") is False,
            "original signed-window HOLD changed")
    return archived, hold


def bounded_compare(frozen, current):
    """Deep exact structure/identity + bounded numeric drift; no self-issued waiver."""
    observed = {"scalar_numbers": 0, "changed_numbers": 0, "max_absolute_delta": 0.0}

    def compare(old, new, path):
        if path == (ALLOWED_REPLAY_CHANGED_IDENTITY,):
            require(type(old) is type(new) is str and len(old) == len(new) == 64
                    and all(c in "0123456789abcdef" for c in new),
                    "invalid complete-run SHA")
            return
        require(type(old) is type(new), "type changed at " + ".".join(map(str, path)))
        if isinstance(old, dict):
            require(set(old) == set(new), "missing or injected fields at " + repr(path))
            for key in sorted(old):
                compare(old[key], new[key], path + (key,))
        elif isinstance(old, list):
            require(len(old) == len(new), "array dimension changed at " + repr(path))
            for i, (left, right) in enumerate(zip(old, new)):
                compare(left, right, path + (i,))
        elif type(old) is float:
            require(math.isfinite(old) and math.isfinite(new), "nonfinite numeric field")
            delta = abs(new - old)
            observed["scalar_numbers"] += 1
            observed["max_absolute_delta"] = max(observed["max_absolute_delta"], delta)
            observed["changed_numbers"] += int(delta != 0)
            require(delta <= MAX_ABSOLUTE_NUMERIC_DRIFT,
                    "unqualified score/numeric change at " + repr(path))
        else:
            require(old == new, "non-numeric identity or decision changed at " + repr(path))

    compare(frozen, current, ())
    require(current["independent_model_bytes_verified"] == 82
            and len(current["arms"]) == ARM_COUNT
            and current["correlated_training_seeds"] == list(SEEDS)
            and current["future_utility_gain"] is None
            and current["negative_transfer_independently_verified"] is None
            and current["source_family_independence_authenticated"] is False
            and current["production_authorized"] is False
            and current["scientific_promotion_authorized"] is False,
            "false epistemic or authorization status")
    return observed


def execute(inputs, v15, v16, v17, historical, historical_hold):
    archived, old_hold = history(historical, historical_hold)
    # A distinct original source module performs physical tensor/source rechecks.
    # Never accept a caller-provided 'model files verified' assertion as proof.
    import v18_source_first_uncertainty as original
    import v18_future_source_intake as future
    require(sha(Path(original.__file__).read_bytes()) == FROZEN_V18_SOURCE_SHA,
            "historical independent source auditor modified")
    current = original.audit(inputs, v15, v16, v17)
    fresh_hold = future.blocked(current)
    require(fresh_hold == old_hold, "replay cannot turn HOLD into future evidence")
    compared = bounded_compare(archived, current)
    fresh_raw = original.canonical(current)
    require(sha(fresh_raw) == sha(canonical(current)), "canonical serializer mismatch")
    return {"schema": SCHEMA, "decision": "REPLAY_NUMERICALLY_EQUIVALENT_NO_FUTURE_ADMISSION",
            "frozen_v18_receipt_sha256": FROZEN_RECEIPT_SHA,
            "replay_v18_receipt_sha256": sha(fresh_raw),
            "byte_identical": sha(fresh_raw) == FROZEN_RECEIPT_SHA,
            "v17_sealed_sha_unchanged": current["v17_sealed_sha256"] == archived["v17_sealed_sha256"],
            "independently_replayed_model_files": 82,
            "historical_calibration_cases": ORIGINAL_CASES,
            "correlated_seeds": list(SEEDS), "candidate_arm_count": ARM_COUNT,
            "numeric_tolerance_absolute": MAX_ABSOLUTE_NUMERIC_DRIFT,
            "numerical_check": compared,
            "original_frozen_model_source_bound": True,
            "independent_future_roots": 0, "signed_future_windows": 0,
            "external_evaluator_qualified": False,
            "new_model_utility_gain": None,
            "independent_negative_transfer": None,
            "target_host_4096_qualified": False,
            "scientific_promotion_authorized": False,
            "production_authorized": False,
            "model_selected": None,
            "authority_posture": "DENY_ALL"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "v15", "v16", "v17", "historical", "historical-hold", "out"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    result = execute(a.inputs, a.v15, a.v16, a.v17, a.historical,
                     getattr(a, "historical_hold"))
    path = Path(a.out)
    require(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
            "create-only ordinary output")
    with path.open("xb") as f:
        f.write(canonical(result))
        f.flush()
    return result


if __name__ == "__main__":
    main()
