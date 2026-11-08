"""Bounded real-model pilot entry point; source and attempt roster freeze first."""

import argparse
import json
import random
import time

from .model_backend import MLXBackend
from .model_heads import fit_heads
from .model_policy import Pilot
from .model_protocol import ARMS, Journal, canonical, cases, digest, frozen_plan, load_phase1, public_view


def run(output, phase1_root, asset_manifest, asset_sha):
    plan = frozen_plan()
    roster = [{"case_id": case["goal"]["task_id"], "arm": arm} for case in cases("confirmation") for arm in ARMS]
    random.Random(1771).shuffle(roster)
    interventions = [{"case_id": case["goal"]["task_id"], "arm": "intervention/" + setting["name"]}
                     for case in cases("confirmation") if case["source_group"].endswith("/0") for setting in plan["interventions"]]
    plan.update(asset_manifest_sha256=asset_sha, primary_execution_order=roster, planned_trajectories=roster + interventions)
    journal = Journal(output, plan)
    pilot, failure = None, None
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    try:
        with journal.operation("frozen_dependency_loading", {}) as receipt:
            dependencies = load_phase1(phase1_root)
            receipt["sha256"] = plan["phase1_sha256"]
        backend = MLXBackend(journal, asset_manifest, asset_sha)
        backend_scores = {key: backend.score(key, "neutral", public_view([]), {"split": "backend_check", "model": key}) for key in ("qwen", "smol")}
        backend_feature = backend.features(public_view([]), {"split": "backend_check"})
        journal.write("backend_check.json", {"scores": backend_scores, "qwen_hidden_dimension": len(backend_feature["values"]), "feature_operation_id": backend_feature["operation_id"]})
        pilot = Pilot(journal, dependencies, backend, plan)
        training = pilot.panel("train")
        with journal.operation("readout_training", {"split": "train"}) as receipt:
            pilot.heads = fit_heads(training, backend.identities["qwen"]["base_sha256"])
            labels = {row["case_id"]: row["label"] for row in training}
            pilot.prior = (sum(labels.values()) + 1) / (len(labels) + 2)
            receipt.update(training_cases=len(labels), prior=pilot.prior, adapter_sha256=[head["adapter_sha256"] for head in pilot.heads])
            journal.write("trained_readouts.json", pilot.heads)
        pilot.panel("calibration")
        pilot.calibrate()
        confirmation = {case["goal"]["task_id"]: case for case in cases("confirmation")}
        for task in roster:
            pilot.trajectory(confirmation[task["case_id"]], task["arm"])
        settings = {"intervention/" + item["name"]: item for item in plan["interventions"]}
        for task in interventions:
            pilot.trajectory(confirmation[task["case_id"]], "single", settings[task["arm"]])
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
        journal.append("failures.jsonl", failure)
    finally:
        from .model_summary import summarize
        summary = summarize(journal.directory, failure, time.perf_counter_ns() - started, time.process_time_ns() - cpu)
        journal.write("result.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--phase1-root", required=True)
    parser.add_argument("--asset-manifest", required=True)
    parser.add_argument("--asset-sha", required=True)
    args = parser.parse_args()
    result = run(args.output, args.phase1_root, args.asset_manifest, args.asset_sha)
    print(canonical({"status": result["status"], "observed_trajectories": result["observed_trajectories"], "planned_trajectories": result["planned_trajectories"], "model_forwards": result["model_forwards"], "failure": result["failure"]}))
    return 0 if result["status"] == "CONTROLLED_MODEL_PILOT_COMPLETED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
