"""Read-only, pinned reanalysis of actual CPU LoRA schedule opportunity and costs.

Never interprets public B/C evaluation as independent or grants owner authority.
No model is trained or queried by this file.
"""
import hashlib
import json
from pathlib import Path

ARCHIVE_SHA256 = "caf20e60f0e0dc09b78b9c5433727dd028a2b6627c945d8dee7b54c238a66615"
ARCHIVE = Path(__file__).resolve().with_name("real_cpu_clock_v1_RESULT.json")
ARMS = ("uniform", "heterogeneous")
SEEDS = (11, 17, 23, 29)


def audit_bytes(raw):
    """Fail closed on any byte drift or incomplete/mismatched paired experiment."""
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("original real-model archive bytes changed")
    report = json.loads(raw)
    if (report.get("schema") != "HPCA-REAL-CPU-LORA-CLOCK-V1"
            or report.get("decision") != "HOLD_NO_GO"
            or report.get("seeds") != list(SEEDS)
            or len(report.get("runs", [])) != 2 * len(SEEDS)):
        raise ValueError("not the frozen four-pair HOLD experiment")
    rows = report["runs"]
    if [(r["seed"], r["arm"]) for r in rows] != [
        (seed, arm) for seed in SEEDS for arm in ARMS
    ]:
        raise ValueError("non-counterbalanced archived arm execution order changed")

    pairs = []
    for seed in SEEDS:
        uniform, heterogeneous = [r for r in rows if r["seed"] == seed]
        arms = {"uniform": uniform, "heterogeneous": heterogeneous}
        if (uniform["all_source_events"] != heterogeneous["all_source_events"]
                or uniform["input_tokens_train"] != heterogeneous["input_tokens_train"]
                or uniform["actual_updated_parameter_elements"]
                != heterogeneous["actual_updated_parameter_elements"]):
            raise ValueError("paired total opportunity mismatch")
        details = {}
        for name, row in arms.items():
            schedule = row["schedule"]
            steps = row["step_log"]
            if (row["steps"] != 12 or len(schedule) != 12 or len(steps) != 12
                    or any(s["i"] != i or s["group"] != schedule[i]
                           or s["source_id"] != row["all_source_events"][i]
                           for i, s in enumerate(steps))
                    or sum(s["input_tokens"] for s in steps) != row["input_tokens_train"]
                    or row["actual_updated_parameter_elements"] != 829440):
                raise ValueError("inconsistent source/time/optimizer-step ledger")
            groups = []
            for g in (0, 1):
                picked = [s for s in steps if s["group"] == g]
                groups.append({
                    "updates": len(picked),
                    "tokens": sum(s["input_tokens"] for s in picked),
                    "distinct_source_ids": len({s["source_id"] for s in picked}),
                })
            if [g["updates"] for g in groups] != (
                [6, 6] if name == "uniform" else [9, 3]
            ):
                raise ValueError("incorrect update-clock schedule")
            if sum(g["tokens"] for g in groups) != row["input_tokens_train"]:
                raise ValueError("unaccounted group input tokens")
            details[name] = {
                "groups": groups,
                "wall_seconds": row["train_evaluate_save_reload_wall_seconds"],
                "process_cpu_seconds": row["process_cpu_seconds"],
                "physical_read_bytes": row["io_delta"]["read_bytes"],
            }
            if (details[name]["wall_seconds"] <= 0 or
                    details[name]["process_cpu_seconds"] <= 0 or
                    details[name]["physical_read_bytes"] < 0):
                raise ValueError("invalid measured resources")
        pairs.append({"seed": seed, "input_tokens": uniform["input_tokens_train"],
                      "arm_order": list(ARMS), **details})

    def total(arm, key):
        return sum(p[arm][key] for p in pairs)

    return {
        "status": "HOLD_NO_GO",
        "authority": "READ_ONLY_ARCHIVED_OBSERVATION_NOT_OWNER",
        "archive_sha256": ARCHIVE_SHA256,
        "paired_seeds": len(pairs),
        "arm_execution_counterbalanced": False,
        "paired_input_token_equal": True,
        "paired_optimizer_parameter_element_equal": True,
        "total_cpu_seconds": {a: total(a, "process_cpu_seconds") for a in ARMS},
        "total_arm_wall_seconds": {a: total(a, "wall_seconds") for a in ARMS},
        "total_observed_physical_read_bytes": {
            a: total(a, "physical_read_bytes") for a in ARMS
        },
        "pairs": pairs,
        "missing": ["counterbalanced arm execution", "owner-attested outcomes",
                    "independent B", "real next task C", "energy/network cost",
                    "seven-lineage or NDU comparison", "full-clock opportunity controls"],
    }


def main():
    print(json.dumps(audit_bytes(ARCHIVE.read_bytes()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
