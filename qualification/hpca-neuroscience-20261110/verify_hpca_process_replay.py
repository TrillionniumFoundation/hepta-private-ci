#!/usr/bin/env python3
"""Recorded CPU-forward replay consistency verifier; never authenticates execution."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path

ORIGINAL_SHA = "3002553ec485b19247f510863e9c78d2cce7747434ad7737f68b7dd3f9a74a2a"
REPLAY_SHA = "a5e40b990dc2b02b7c689c3ed5332a0c10348d04f0ee8e6bcc8d49b3b58dcc4b"
EXPECTED_CONDITIONS = ["base"] + [
    f"seed{seed} {arm}" for seed in (11, 17, 23, 29)
    for arm in ("interleaved", "bursty")
]
SOURCE_SCRIPT_SHA = "b9f61e8133f67af2d126c3730588c1386efcfb2788259f618e092081c2454af8"
PLAN_SHA = "acb16047e5942d317262ddb8273a2d62e9131e758d6627dcf1c2f42081d98043"
TRAINING_SHA = "9512849b90964c35951bb8bb2226b3f2f6d3ec0da1e9a3b98467c8970afbe39c"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verified_compare(original: dict, replay: dict) -> dict:
    for label, report in (("original", original), ("replay", replay)):
        require(report.get("schema") == "HPCA-V2-OOD-REAL-CPU-READONLY-V1", label + ": schema")
        require(report.get("cpu_only") is True and report.get("threads") == 4, label + ": CPU opportunity")
        require(report.get("authority") == "DENY_ALL_HOLD_NO_GO", label + ": authority")
        require(report.get("evaluation") == "PUBLIC_OPERATOR_OOD_EXPLORATORY_NOT_INDEPENDENT", label + ": independence")
        require(report.get("selection") == "NO_UPDATE_RECOMMENDED_RESEARCH_ONLY_NOT_OWNER_DECISION", label + ": selection")
        require(report.get("conditions") == EXPECTED_CONDITIONS, label + ": conditions")
        require(report.get("script_sha256") == SOURCE_SCRIPT_SHA, label + ": script pin")
        require(report.get("plan_sha256") == PLAN_SHA, label + ": plan pin")
        require(report.get("original_training_result_sha256") == TRAINING_SHA, label + ": training pin")
        require(len(report.get("runs", [])) == 9, label + ": number of model conditions")
        for field in ("wall_seconds", "process_cpu_seconds", "ru_maxrss_kib_lifetime_peak"):
            v = report.get("full_run_cost", {}).get(field)
            require(type(v) in (int, float) and math.isfinite(v) and v > 0, label + ": cost " + field)
    for field in ("script_sha256", "plan_sha256", "original_training_result_sha256",
                  "model_identities", "conditions", "threads", "torch_version",
                  "transformers_version", "peft_version"):
        require(original.get(field) == replay.get(field), "identity drift " + field)

    exact_scores = 0
    matched_rows = 0
    for condition, a, b in zip(EXPECTED_CONDITIONS, original["runs"], replay["runs"]):
        require(a.get("condition") == condition and b.get("condition") == condition, "condition mismatch")
        require(a.get("seed") == b.get("seed") and a.get("arm") == b.get("arm"), "seed or arm mismatch")
        ar, br = a.get("predictions", []), b.get("predictions", [])
        require(len(ar) == len(br) == 24, condition + ": incomplete task panel")
        require(len({r.get("id") for r in ar}) == len({r.get("id") for r in br}) == 24,
                condition + ": duplicate task")
        for old, new in zip(ar, br):
            for field in ("id", "family", "truth", "prompt_sha256", "prediction", "correct"):
                require(old.get(field) == new.get(field), condition + ": task or decision mismatch " + field)
            for field in ("p_yes", "log_loss", "brier"):
                x, y = old.get(field), new.get(field)
                require(type(x) in (int, float) and type(y) in (int, float)
                        and math.isfinite(x) and math.isfinite(y), condition + ": nonfinite score")
                require(x == y, condition + ": distinct CPU score " + field)
                exact_scores += 1
            require(0 <= new["p_yes"] <= 1, condition + ": invalid probability")
            require(new["prediction"] == ("yes" if new["p_yes"] >= .5 else "no"),
                    condition + ": prediction contradicts score")
            require(new["correct"] is (new["prediction"] == new["truth"]),
                    condition + ": invalid truth score")
            matched_rows += 1
        require(a["scores"] == b["scores"], condition + ": aggregate mismatch")
        for field in ("load_wall_seconds", "inference_wall_seconds",
                      "load_plus_inference_wall_seconds", "process_cpu_seconds"):
            cost = b.get("cost", {}).get(field)
            require(type(cost) in (int, float) and math.isfinite(cost) and cost >= 0,
                    condition + ": invalid cost " + field)
    require(matched_rows == 216 and exact_scores == 648, "incomplete exact reexecution")
    require(original.get("paired") == replay.get("paired"), "paired contrasts diverged")
    return {"schema": "hpca-process-reexecution-verified-v1",
            "recorded_ood_task_origin": "public operator; NOT independent B",
            "same_host": True, "same_program": True, "new_training": False,
            "owner_attested": False, "production_qualified": False,
            "conditions": 9, "model_forwards": matched_rows,
            "identical_decisions": matched_rows, "bit_exact_score_fields": exact_scores,
            "replay_cpu_seconds": replay["full_run_cost"]["process_cpu_seconds"],
            "replay_wall_seconds": replay["full_run_cost"]["wall_seconds"],
            "replay_peak_rss_kib": replay["full_run_cost"]["ru_maxrss_kib_lifetime_peak"],
            "authority": "DENY_ALL", "qualification": "HOLD_NO_GO"}


def main() -> None:
    folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", type=Path,
                        default=folder / "ACTUAL_OOD_FORWARD_RESULT.json")
    parser.add_argument("--replay", type=Path,
                        default=folder / "HPCA_V2_PROCESS_REPLAY_RESULT.json")
    args = parser.parse_args()
    files = ((args.original, ORIGINAL_SHA), (args.replay, REPLAY_SHA))
    for path, expected in files:
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "archive byte pin drift: " + str(path))
    print(json.dumps(verified_compare(json.loads(args.original.read_text()),
                                      json.loads(args.replay.read_text())), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
