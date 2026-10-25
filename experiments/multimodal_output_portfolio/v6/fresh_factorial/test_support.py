"""Clearly synthetic nonmodel fixtures for provenance rejection tests only."""

from pathlib import Path

from . import io
from .data_prepare import planned_cases
from .gates import model_binding
from .infer import PLANS
from .models import generation_id


def plan(owner=None):
    value = io.read_json(Path(__file__).with_name("template.json"))
    value["exposed_source_pixels"] = [io.digest(f"synthetic-old-{i}".encode()) for i in range(360)]
    if owner is not None:
        value["source_owner_directory"] = str(owner)
    return value


def source_ids():
    return {split: [f"mnist:{origin}:{i}:" + io.digest(f"synthetic-{split}-{i}".encode()) for i in range(count)]
            for split, origin, count in (("future", "test", 2000), ("retention", "train", 1000))}


def synthetic_rows(protocol):
    cases, _ = planned_cases(protocol, source_ids())
    rows = []
    for seed_index, seed in enumerate(protocol["seeds"]):
        for case_index, case in enumerate(cases):
            stratum = protocol["corruptions"].index(case["corruption"])
            for arm in protocol["arms"]:
                base, gate = int(arm[1]), int(arm[3])
                loss = .60 + stratum * .005 + seed_index * .01 - base * .1 - gate * .04 - base * gate * .02
                rows.append({"seed": seed, "arm": arm, **case,
                             "metrics": {"joint_loss": loss, "joint_fact_correct": int(case_index % 2 == 0)}})
    return rows


def synthetic_data(owner, protocol):
    root = owner / "data"
    root.mkdir()
    cases, reserved = planned_cases(protocol, source_ids())
    files = {}
    for name in ("training.npz", "observer-training.npz", "observations.npz", "final-targets.npz"):
        (root / name).write_bytes(b"synthetic-nonpayload")
        files[name] = io.identity(root / name)
    ids = [f"mnist:train:{i}:" + io.digest(f"synthetic-observer-{i}".encode()) for i in range(10000)]
    for name, value in (("training-source.json", {}), ("observer-source.json", {"source_ids": ids}),
                        ("cases.json", {"cases": cases}), ("reserved-sources.json", {"source_ids": reserved})):
        files[name] = io.write(root / name, value)
    receipt = {"schema": "hepta.ndu-fresh-factorial.prepared-data.v1", "protocol_canonical_sha256": io.digest(protocol),
               "source_count": 90, "environment": {}, "files": files}
    io.write(root / "data-receipt.json", receipt)
    return receipt, cases, ids


def synthetic_generation(owner, protocol):
    import hashlib
    receipt, cases, ids = synthetic_data(owner, protocol)
    root, source = owner / "bootstrap", {"git_commit": "synthetic-only", "files": {"synthetic": "bound"}}
    root.mkdir()
    data_sha = io.file_hash(owner / "data" / "data-receipt.json")
    generation = generation_id(protocol, data_sha, "synthetic-only")
    io.write(root / "source-freeze.json", source)
    io.write(root / "generation-start.json", {"generation_id": generation, "source_commit": "synthetic-only",
        "protocol_canonical_sha256": io.digest(protocol), "data_receipt_sha256": data_sha, "historical_weights_loaded": False})
    controls, bases, observers = [], [], {}
    for seed in protocol["seeds"]:
        control = {"seed": seed, "base_initial_parameter_sha256": f"initial-{seed}",
            "base_batch_action_schedule_sha256": f"base-schedule-{seed}",
            "gate_initial_parameter_sha256": f"gate-initial-{seed}", "gate_update_schedule_sha256": f"gate-schedule-{seed}",
            "gate_source_ids_sha256": "synthetic-gate-sources", "gate_scenario_seeds": [seed, seed + 1]}
        controls.append(control)
        for profile in ("supervised", "terminal_entropic_ndu"):
            stem = f"seed-{seed}-{profile}"
            (root / (stem + ".pt")).write_bytes(("synthetic-nonmodel-" + stem).encode())
            report = {"profile": profile, "config": {"seed": seed, **protocol["base_training"]},
                "source_manifest_sha256": protocol["dataset_manifest_sha256"], "optimizer_updates": 2000,
                "history": [{"step": i} for i in range(1, 2001)], "parameter_count": 1007464,
                "conditional_noise_scenarios": 2, "initial_parameter_sha256": control["base_initial_parameter_sha256"],
                "batch_action_schedule_sha256": control["base_batch_action_schedule_sha256"],
                "final_parameter_sha256": "parameter-" + stem, "final_snapshot_sha256": "snapshot-" + stem,
                "fresh_generation_id": generation}
            io.write(root / (stem + "-training.json"), report)
            bases.append({"seed": seed, "profile": profile, "path": stem + ".pt", "report_path": stem + "-training.json",
                          "file": io.identity(root / (stem + ".pt")), "snapshot_sha256": report["final_snapshot_sha256"],
                          "parameter_sha256": report["final_parameter_sha256"]})
    io.write(root / "recipe-controls.json", {"controls": controls})
    for ordinal, name in enumerate(("reward", "audit")):
        (root / (name + "-observer.pt")).write_bytes(("synthetic-nonmodel-" + name).encode())
        report = {"seed": protocol["observer_training"]["seeds"][name], "steps": 300, "train_sources": 4000,
            "calibration_sources": 1000, "source_ids_sha256": hashlib.sha256("\n".join(ids[ordinal * 5000:(ordinal + 1) * 5000]).encode()).hexdigest(),
            "initial_parameter_sha256": "synthetic-observer-initial", "parameter_sha256": "synthetic-" + name,
            "selected_by_calibration": False}
        io.write(root / (name + "-observer.json"), report)
        observers[name] = {"path": name + "-observer.pt", "report_path": name + "-observer.json",
            "file": io.identity(root / (name + "-observer.pt")), "parameter_sha256": report["parameter_sha256"]}
    report = {"schema": "hepta.ndu-fresh-factorial.bootstrap.v1", "generation_id": generation,
        "protocol_canonical_sha256": io.digest(protocol), "data_receipt_sha256": data_sha,
        "observers": observers, "bases": bases, "base_optimizer_updates": 12000, "observer_optimizer_updates": 600,
        "historical_weights_loaded": False, "final_targets_opened": False, "environment": {},
        "audit_observer_used_for_training": False, "observer_source_pools_disjoint": True}
    io.write(root / "bootstrap.json", report)
    io.seal(root, "bootstrap-seal.json")
    fitted, training = owner / "training", []
    fitted.mkdir()
    io.write(fitted / "source-freeze.json", source)
    for seed, control in zip(protocol["seeds"], controls, strict=True):
        for arm, factors in protocol["arms"].items():
            stem, base_sha = f"seed{seed}-{arm}", f"snapshot-seed-{seed}-{factors['base']}"
            (fitted / (stem + ".pt")).write_bytes(("synthetic-nonmodel-" + stem).encode())
            gate = {"content_plan_training_profile": factors["gate"], "initial_gate_sha256": control["gate_initial_parameter_sha256"],
                "gate_update_schedule_sha256": control["gate_update_schedule_sha256"], "source_ids_sha256": control["gate_source_ids_sha256"],
                "scenario_seeds": control["gate_scenario_seeds"], "batch_seed": seed * 1000003 + 4409, "plans": PLANS, "optimizer_updates": 120,
                "seed": seed, "fit_split": "train", "content_plan_metric_sha256": protocol["metric_sha256"],
                "content_plan_scenario_count": 2, "content_plan_risk_aversion": 2,
                "fit_pairs": 128, "source_manifest_sha256": protocol["dataset_manifest_sha256"], "base_sha256": base_sha,
                "output_observation_sha256": base_sha, "utility_table": [[seed, base_sha]], "combined_sha256": stem,
                "final_gate_sha256": "gate-" + stem, "fresh_generation_id": generation,
                "content_plan_observer_sha256": "synthetic-reward", "gate_parameter_count": 3236}
            io.write(fitted / (stem + "-training.json"), gate)
            training.append({"seed": seed, "arm": arm, **factors, "path": stem + ".pt", "training_report_path": stem + "-training.json",
                "checkpoint_file_sha256": io.file_hash(fitted / (stem + ".pt")), "snapshot_sha256": stem,
                "base_sha256": base_sha, "gate_sha256": gate["final_gate_sha256"]})
    result = {"schema": "hepta.ndu-fresh-factorial.training.v1", "protocol_canonical_sha256": io.digest(protocol),
        "generation_id": generation, "bootstrap_seal_sha256": io.file_hash(root / "bootstrap-seal.json"),
        "data_receipt_sha256": data_sha, "models": training, "base_updates_during_gate_fit": 0,
        "gate_fits_completed": 12, "gate_optimizer_updates": 1440, "final_targets_opened": False, "environment": {}}
    io.write(fitted / "training.json", result)
    io.seal(fitted, "training-seal.json")
    io.write(owner / "model-seal.json", {**model_binding(protocol), "at_utc": "synthetic-only"})
    return receipt, cases, report, result


def rewrite(path, value):
    path.unlink()
    io.write(path, value)


def reseal(root, name):
    (root / name).unlink()
    io.seal(root, name)
