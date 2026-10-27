"""Bind scored candidates to the completed training run before model selection."""

import json

from .protocol import PROTOCOL as P, checksum


def verify_development_run(run):
    completed = json.loads((run / "COMPLETED.json").read_text())
    runtime = json.loads((run / "RUNTIME.json").read_text())
    protocol_hash = checksum(run / "PROTOCOL.json")
    for record in (completed, runtime):
        if record["steps"] != P["steps"] or record["seeds"] != P["seeds"] or record["protocol_sha256"] != protocol_hash:
            raise ValueError("The completed development runtime differs")
    if runtime["audit_observer_loaded"] or runtime["new_qualification_scored"]:
        raise ValueError("Development accessed qualification information")
    for name, digest in runtime["sources"].items():
        if checksum(run / "executed-source" / name) != digest:
            raise ValueError("Executed development source changed")
    if checksum(run / "SELECTIONS.json") != completed["selection_sha256"]:
        raise ValueError("The completed validation aggregate changed")
    reports = json.loads((run / "SELECTIONS.json").read_text())
    expected = {(seed, arm) for seed in P["seeds"] for arm in ("direct_mean", "direct_risk")}
    if len(reports) != len(expected) or {(r["seed"], r["arm"]) for r in reports} != expected:
        raise ValueError("The completed validation model grid differs")
    counts = {"actor_examples": P["steps"] * P["batch_size"],
              "encoder_examples": P["steps"] * P["batch_size"],
              "gate_examples": P["steps"] * P["batch_size"],
              "transition_examples": 2 * P["steps"] * P["batch_size"],
              "decoder_examples": 2 * P["directions"] * P["steps"] * P["batch_size"],
              "actual_png_roundtrips": 2 * P["directions"] * P["steps"] * P["batch_size"],
              "observer_digit_examples": 4 * P["directions"] * P["steps"] * P["batch_size"],
              "optimizer_updates": P["steps"]}
    training_pins = {}
    for report in reports:
        seed, arm = report["seed"], report["arm"]
        individual = run / f"SELECTION-{seed}-{arm}.json"
        if json.loads(individual.read_text()) != report:
            raise ValueError("A candidate report differs from its sealed aggregate")
        path = run / f"TRAINING-{seed}-{arm}.json"
        training = json.loads(path.read_text())
        if (training["seed"], training["arm"], training["steps"]) != (seed, arm, P["steps"]) or training["training_counts"] != counts:
            raise ValueError("Actual training budget or model identity differs")
        if checksum(run / f"TRACE-{seed}-{arm}.npz") != training["trace_sha256"]:
            raise ValueError("The actual outcome/gradient trace changed")
        if [x["step"] for x in training["history"]] != list(range(1, P["steps"] + 1)):
            raise ValueError("The complete training step history is required")
        checkpoints = training["checkpoints"]
        if [c["step"] for c in checkpoints] != P["checkpoints"]:
            raise ValueError("The trained checkpoint grid differs")
        for checkpoint in checkpoints:
            expected_name = f"seed-{seed}-{arm}-step-{checkpoint['step']}.pt"
            if checkpoint["path"] != expected_name or checksum(run / expected_name) != checkpoint["sha256"]:
                raise ValueError("A scored training checkpoint changed")
        candidates = report["candidates"]
        if [c["step"] for c in candidates] != [0, *P["checkpoints"]] or candidates[0]["checkpoint"] is not None:
            raise ValueError("The scored candidate grid differs")
        for candidate, checkpoint in zip(candidates[1:], checkpoints):
            if candidate["checkpoint"] != checkpoint["path"]:
                raise ValueError("A validation candidate refers to a different training checkpoint")
        for candidate in candidates:
            eligible = candidate["metrics"]["retention"]["ce"] >= report["original_ce"]["retention"] - P["validation_retention_tolerance"]
            if candidate["eligible"] != eligible:
                raise ValueError("A validation retention decision differs")
        training_pins[f"{seed}/{arm}"] = {"training_sha256": checksum(path),
                                           "selection_sha256": checksum(individual)}
    return {"runtime_sha256": checksum(run / "RUNTIME.json"),
            "completed_sha256": checksum(run / "COMPLETED.json"),
            "baselines_sha256": checksum(run / "BASELINES.json"),
            "training": training_pins}
