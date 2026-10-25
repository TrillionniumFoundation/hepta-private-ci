"""Freeze and physically execute the complete new-role repair comparison."""

import argparse
import json
from pathlib import Path
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...abc_next.settings import CACHE, MANIFEST, SEEDS, OBSERVER_SHA, observers
from ...v6.neural import parameter_hash
from ...v7.data import VIEWS
from ..training.evaluate import evaluate_model
from .assigned_source import ASSIGNMENT, ROLE, ORIGIN_ROLE, materialize, verify_assignment
from .protocol import ALL_ARMS, ARMS, HERE, PLAN, RUNS, source_identity, source_pins
from .protocol import verify as verify_training


def freeze(training_path, output):
    training = json.loads(training_path.read_text())
    verify_training(training)
    result_path = Path(training["output"]) / "result.json"
    result = json.loads(result_path.read_text())
    if (result["status"] != "completed" or result["protocol_sha256"] != file_sha(training_path)
            or training["steps"] != 400 or tuple(training["seeds"]) != SEEDS):
        raise ValueError("Only the complete prespecified ten-model training may open the new final")
    expected = {(seed, arm) for seed in SEEDS for arm in ARMS}
    seen, models = set(), []
    for row in result["models"]:
        key = row["seed"], row["arm"]
        if key in seen or key not in expected or file_sha(row["model_path"]) != row["model_file_sha256"]:
            raise ValueError("Missing, duplicated or modified new candidate")
        seen.add(key)
        models.append({"seed": row["seed"], "arm": row["arm"],
                       "path": row["model_path"], "sha256": row["model_file_sha256"]})
    if seen != expected:
        raise ValueError("Every repair seed and arm must finish before opening the new sources")
    for seed in SEEDS:
        for arm in ("mean", "old_constraint"):
            models.append({"seed": seed, "arm": arm, **training["baselines"][str(seed)][arm]})
    spec = {"schema": "hepta.abc4.reference-repair-evaluation.v1", "unix_ns": time.time_ns(),
        "training_protocol": str(training_path.resolve()), "training_protocol_sha256": file_sha(training_path),
        "training_result_sha256": file_sha(result_path), "source_pins": source_pins(),
        "source_allocation_sha256": file_sha(HERE / "SOURCE_ALLOCATION.json"),
        "role_assignment_sha256": file_sha(ASSIGNMENT),
        "source_identity": source_identity(), "manifest_sha256": file_sha(MANIFEST),
        "origin_role": ORIGIN_ROLE, "role": ROLE, "start": 0, "count": 1000, "scenarios": 2,
        "seeds": SEEDS, "views": VIEWS, "arms": ALL_ARMS, "models": models,
        "plan": PLAN, "gamma": 2., "observer_sha256": OBSERVER_SHA,
        "output": str(RUNS / "evaluation-001"), "formal_new_holdout_opened": False,
        "primary": {"candidate": "matched_floor_warmdual", "reference": "mean", "confidence": .975,
            "endpoints": ["joint_CE", "exact_success"], "success_margin": 0.,
            "gate": "CE lower>0 AND success lower>=0"},
        "descriptive": "matched_floor versus old_constraint isolates reference; warmdual versus matched_floor isolates initial multiplier; neither replaces primary candidate",
        "bootstrap": {"replicates": 4000, "seed": 2026102531,
            "resampling": "paired source and training-seed axes, preserving all views/scenarios/arms",
            "nominal_intervals_only": True},
        "analysis_of_prior_final_changed": False, "global_cross_round_error_control_claimed": False,
        "cost_scope": "actual batched quality evaluation; no single-request latency claim",
        "outcome_dependent_refitting_or_checkpoint_selection_allowed": False}
    write_json(output, spec)
    verify(spec)
    print(json.dumps({"protocol_sha256": file_sha(output), "models": len(models)}), flush=True)


def verify(spec):
    verify_assignment()
    if (spec["schema"] != "hepta.abc4.reference-repair-evaluation.v1"
            or spec["source_pins"] != source_pins()
            or spec["source_allocation_sha256"] != file_sha(HERE / "SOURCE_ALLOCATION.json")
            or spec["role_assignment_sha256"] != file_sha(ASSIGNMENT)
            or spec["source_identity"] != source_identity()
            or spec["manifest_sha256"] != file_sha(MANIFEST)
            or (spec["role"], spec["origin_role"], spec["start"], spec["count"], spec["scenarios"]) != (ROLE, ORIGIN_ROLE, 0, 1000, 2)
            or tuple(spec["arms"]) != ALL_ARMS or tuple(spec["seeds"]) != SEEDS
            or tuple(spec["views"]) != VIEWS or tuple(spec["plan"]) != PLAN
            or spec["observer_sha256"] != OBSERVER_SHA):
        raise ValueError("New final protocol identity changed")
    actual = [(r["seed"], r["arm"]) for r in spec["models"]]
    expected = {(seed, arm) for seed in SEEDS for arm in ALL_ARMS}
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("New final model census differs")
    training_path = Path(spec["training_protocol"])
    if file_sha(training_path) != spec["training_protocol_sha256"]:
        raise ValueError("Training registration changed")
    training = json.loads(training_path.read_text())
    verify_training(training)
    if file_sha(Path(training["output"]) / "result.json") != spec["training_result_sha256"]:
        raise ValueError("Actual completed training result changed")
    for row in spec["models"]:
        if file_sha(row["path"]) != row["sha256"]:
            raise ValueError("A registered candidate or baseline changed")


def run(protocol_path):
    spec = json.loads(protocol_path.read_text())
    verify(spec)
    root = Path(spec["output"])
    root.mkdir(parents=True, exist_ok=False)
    write_json(root / "access-registration.json", {"unix_ns": time.time_ns(),
        "protocol_sha256": file_sha(protocol_path), "role": spec["role"],
        "origin_role": spec["origin_role"], "role_assignment_sha256": file_sha(ASSIGNMENT),
        "start": spec["start"], "count": spec["count"], "source_identity": spec["source_identity"]})
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    rows = []
    try:
        torch.set_num_threads(2)
        corpus = materialize(CACHE, protocol_path)
        judges = observers()
        before = {k: parameter_hash(v) for k, v in judges.items()}
        for row in spec["models"]:
            rows.append(evaluate_model(row, spec, corpus, judges, root / f"seed-{row['seed']}" / row["arm"]))
            print(json.dumps({"completed": len(rows), "seed": row["seed"], "arm": row["arm"]}), flush=True)
        verify(spec)
        if before != {k: parameter_hash(v) for k, v in judges.items()}:
            raise ValueError("Frozen evaluation observers changed")
        write_json(root / "result.json", {"schema": "hepta.abc4.reference-repair-evaluation-result.v1",
            "status": "completed", "protocol_sha256": file_sha(protocol_path), "models": rows,
            "source_identity": spec["source_identity"], "wall_ns": time.perf_counter_ns() - started,
            "cpu_ns": time.process_time_ns() - cpu, "outcomes_used_for_selection": False})
    except BaseException as error:
        write_json(root / "failure.json", {"error": repr(error), "completed_models": len(rows)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--training-protocol", type=Path, default=HERE / "TRAINING_PROTOCOL.json")
    args = parser.parse_args()
    freeze(args.training_protocol, args.protocol) if args.phase == "freeze" else run(args.protocol)
