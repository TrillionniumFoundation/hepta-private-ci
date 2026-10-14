"""Read-only phase attribution for both completed and rejected view attempts.

Never discards an overrun or treats a completed workflow as budget stability.
No model import, no policy choice, no scientific acceptance or owner authority.
"""
from collections import Counter
from pathlib import Path
import hashlib
import math

from four_gate_common import digest, require, strict_loads


def summarize_attempts(directory):
    root = Path(directory)
    counts, phase_totals, rows, failures = Counter(), Counter(), [], []
    by_key, journals = {}, {}
    for split in ("validation", "test"):
        path = root / f"{split}-view-attempts.jsonl"
        if not path.exists():
            continue
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64*1024*1024,
                "regular bounded attempt journal")
        raw = path.read_bytes()
        require(not raw or raw.endswith(b"\n"), "partial journal line")
        previous = None
        for seq, line in enumerate(raw.splitlines()):
            item = strict_loads(line)
            identity = item.pop("attempt_sha256")
            require(identity == digest(item) and item["sequence"] == seq and
                    item["previous_sha256"] == previous and item["split"] == split,
                    "attempt chain mismatch")
            require(type(item["cpu_ns"]) is int and item["cpu_ns"] >= 0 and
                    type(item["wall_ns"]) is int and item["wall_ns"] >= 0 and
                    item["limit_ns"] == 100_000_000, "original CPU budget required")
            phase = item["phase_cpu_ns"]
            require(all(type(v) is int and v >= 0 for v in phase.values()),
                    "invalid phase CPU")
            status = item["status"]
            require(status in ("returned", "budget_exceeded", "execution_error"),
                    "attempt status")
            if status != "execution_error":
                require(sum(phase.values()) == item["cpu_ns"], "phase total mismatch")
                require(((status == "returned") == (item["cpu_ns"] <= item["limit_ns"]))
                        and item["prediction_returned"] == (status == "returned"),
                        "budget status contradiction")
            else:
                require(item["prediction_returned"] is False, "failed prediction returned")
            counts[status] += 1
            phase_totals.update(phase)
            key = (item["text_sha256"], item["head_sha256"], item["view"])
            by_key.setdefault(key, []).append(item)
            if status != "returned":
                main = max(phase, key=phase.get) if phase else None
                failures.append({"id": item["id"], "split": split, "arm": item["arm"],
                    "view": item["view"], "status": status, "cpu_ns": item["cpu_ns"],
                    "wall_ns": item["wall_ns"], "phase_cpu_ns": phase,
                    "dominant_measured_phase": main,
                    "dominant_phase_share": phase[main] / item["cpu_ns"]
                        if main and item["cpu_ns"] else None,
                    "attempt_sha256": identity, "cause_established": False,
                    "text_sha256": item["text_sha256"], "head_sha256": item["head_sha256"]})
            rows.append(item)
            previous = identity
        journals[split] = {"bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "last_attempt_sha256": previous, "attempts": len(raw.splitlines())}
    require(rows, "no attempted work to diagnose")
    for failure in failures:
        key = (failure["text_sha256"], failure["head_sha256"], failure["view"])
        same = [r["cpu_ns"] for r in by_key[key] if r["status"] == "returned"]
        failure["same_input_head_returned_count"] = len(same)
        failure["same_input_head_returned_range_ns"] = [min(same), max(same)] if same else None
    times = sorted(r["cpu_ns"] for r in rows)
    return {"schema": "hepta.acquisition.budget-diagnostic.v1",
        "attempts": len(rows), "statuses": dict(counts),
        "phase_cpu_totals_ns": dict(phase_totals), "failures": failures,
        "all_attempt_cpu_quantiles_ns": {
            str(q): times[max(0, math.ceil(q * len(times))-1)] for q in (.5, .95, .99, 1.)},
        "journals": journals, "budget_unchanged_ns": 100_000_000,
        "no_rejected_attempts_observed": not failures,
        "trial_completion_not_inferred": True, "budget_stability_established": False,
        "same_input_repetitions_are_not_independent": True,
        "production_promotion_permitted": False}
