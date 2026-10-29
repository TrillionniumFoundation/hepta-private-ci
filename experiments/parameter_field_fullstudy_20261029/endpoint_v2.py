"""Registered storage/ancestry wrapper; all scientific scorers remain unchanged.

The original training source identities and the v2 scorer identity are distinct.
No endpoint role opens until the original complete checkpoint collector passes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import time

from .resource_v2 import StorageBudget, load_registration, training_slot
from .resource_io_v2 import guarded_writes

ROOT = Path(__file__).resolve().parents[2]
ab = c = sources = None


def load_science():
    global ab, c, sources
    from . import architecture_endpoints, endpoints, sources as source_module
    ab, c, sources = endpoints, architecture_endpoints, source_module


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_freeze(path, phase):
    freeze = json.loads(Path(path).read_text())
    require(phase in freeze["allowed_phases"] and len(freeze["registered_commit"]) == 40, "Phase is not source-registered")
    verify_source_closure(freeze, ROOT)
    return freeze

KNOWN_PARENTS = {
    "A": ("2a5219147d38ebb6514059bd69e2d3489bf7d69d213cd01343455f63a08a53d2", "68b4ecc44cea5f5bc7478ea1008adb1ab81098c6"),
    "C": ("5f427c8a8cebe8c96a2a0d81318e22d286dc0aaa8b3dbf4d5844df2177949c6d", "4fc9ce3744525a5b916dd31a13ebcbe05d07cea1"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_source_closure(freeze, source_root):
    source_root = Path(source_root).resolve()
    require(freeze.get("source_files"), "Training parent has no frozen source closure")
    for relative, expected in freeze["source_files"].items():
        target = (source_root / relative).resolve()
        require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                and target.is_relative_to(source_root) and file_hash(target) == expected, "Training source closure differs")
    for name, expected in freeze.get("artifacts", {}).items():
        require(file_hash(name) == expected, "Training artifact differs")


def parent_freeze(phase, descriptor, registration):
    """Require an actual attempt02 training freeze with an exact original scientific ancestor."""
    require(registration.get("attempt_id") == "attempt02", "Endpoint wrapper requires the registered attempt02")
    require(file_hash(descriptor["path"]) == descriptor["sha256"], "Training-parent freeze bytes differ")
    parent = json.loads(Path(descriptor["path"]).read_text())
    require(phase in parent["allowed_phases"] and parent["registered_commit"] == descriptor["registered_commit"]
            and parent["protocol_sha256"] == descriptor["protocol_sha256"] == registration["original_protocol"]["sha256"],
            "Training-parent phase, commit or scientific protocol differs")
    require(parent.get("operational_amendment_sha256") == registration["_sha256"]
            and parent.get("execution_kind") == "training" and parent.get("attempt_id") == "attempt02",
            "Actual checkpoint parent must be attempt02 training, not the incomplete original attempt")
    scientific = parent["scientific_parent"]
    origin = "C" if phase == "C" else "A"
    require((scientific["sha256"], scientific["registered_commit"]) == KNOWN_PARENTS[origin], "Unregistered original scientific ancestor")
    original = registration["original_source_freezes"][origin]
    require(all(scientific[key] == original[key] for key in ("path", "sha256", "registered_commit", "protocol_sha256")),
            "Scientific ancestor differs from the operational registration")
    require(file_hash(scientific["path"]) == scientific["sha256"], "Original scientific freeze bytes differ")
    old = json.loads(Path(scientific["path"]).read_text())
    require(old["registered_commit"] == scientific["registered_commit"]
            and old["protocol_sha256"] == parent["protocol_sha256"]
            and all(parent["source_files"].get(key) == value for key, value in old["source_files"].items()),
            "Attempt02 changed an originally frozen scientific source")
    verify_source_closure(old, scientific["source_root"])
    verify_source_closure(parent, descriptor["source_root"])
    return parent


def registration_for(args):
    require(args.execute, "Explicit endpoint execution is required")
    registration = load_registration(args.amendment, args.amendment_sha256)
    freeze = verify_freeze(args.freeze, args.phase)
    require(freeze.get("operational_amendment_sha256") == registration["_sha256"]
            and freeze.get("execution_kind") == "endpoint_scoring" and freeze.get("attempt_id") == "attempt02",
            "Scorer is not registered for this operational amendment/attempt")
    require(file_hash(args.protocol) == freeze["protocol_sha256"] == registration["original_protocol"]["sha256"],
            "The original scientific protocol must remain unchanged")
    prefix = Path(__file__).resolve().parent.relative_to(ROOT)
    required = ("endpoint_v2", "resource_v2", "resource_io_v2", "run_v2", "endpoints", "architecture_endpoints", "architecture", "architecture_kernel",
                "architecture_state", "architecture_training", "architecture_run", "sources", "bank", "branching", "analysis", "run")
    require(all((prefix / (name + ".py")).as_posix() in freeze["source_files"] for name in required),
            "Operational/scientific endpoint dependencies are not source-frozen")
    descriptor = freeze["training_parents"][args.phase]
    parent = parent_freeze(args.phase, descriptor, registration)
    ancestry = {"schema": "hepta.fullstudy.endpoint-operational-ancestry.2", "phase": args.phase,
                "operational_amendment_sha256": registration["_sha256"], "attempt_id": "attempt02",
                "original_scientific_parent": parent["scientific_parent"],
                "scientific_training_registered_commit": parent["registered_commit"],
                "scientific_training_source_freeze_sha256": descriptor["sha256"],
                "scorer_or_operations_registered_commit": freeze["registered_commit"],
                "scorer_or_operations_source_freeze_sha256": file_hash(args.freeze),
                "parent_protocol_sha256": parent["protocol_sha256"],
                "original_whole_study_1GiB_contract_completed": False, "scientific_functions_unchanged": True}
    return registration, freeze, descriptor, parent, ancestry


class EndpointBudget:
    """Amended storage plus the unchanged phase CPU/wall/microstep ceilings."""

    def __init__(self, root, costs, phase, registration):
        self.storage, self.costs, self.phase = StorageBudget(root, registration), costs, phase
        self.wall, self.cpu, self.training_work = time.monotonic(), time.process_time(), {}

    def __call__(self, additional=0):
        self.storage.check(additional=additional)
        if self.phase == "C":
            self.storage.check(c_training=True, check_memory=False)  # Endpoint media are outside the C training cap.
        cpu = time.process_time() - self.cpu + self.training_work.get("cpu_seconds", 0.)
        wall = time.monotonic() - self.wall + self.training_work.get("wall_seconds", 0.)
        require(cpu <= (43200 if self.phase == "C" else 7200)
                and wall <= (21600 if self.phase == "C" else 10800), "Original endpoint CPU/wall ceiling exhausted")
        if self.phase in ("A", "B"):
            require(self.costs.values.get("scheduled_gradient_microsteps", 0) <= (39168 if self.phase == "A" else 23040),
                    "Original scheduled gradient ceiling exceeded")


def write_json(path, value, budget):
    payload = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    budget(len(payload))
    target = Path(path).resolve()
    if isinstance(budget, EndpointBudget) and budget.phase == "C" and "endpoint_evaluation" not in target.relative_to(budget.storage.root / "stage_C").parts:
        budget.storage.check(additional=len(payload), c_training=True, check_memory=False)
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    require(Path(path).read_bytes() == payload, "Operational JSON readback differs")


def operation_complete(root, phase, seed, descriptor, parent):
    root = Path(root).resolve()
    name = "C-all" if phase == "C" else f"{phase}-seed-{seed}"
    directory = root / "operations"
    receipt = directory / (name + ".COMPLETE.json")
    require(receipt.is_file() and not (directory / (name + ".FAILED.json")).exists(), "Training operation did not complete its resource gates")
    value = json.loads(receipt.read_text())
    require(value.get("schema") == "hepta.fullstudy.training-operation.2" and value.get("complete") is True
            and value.get("attempt_id") == "attempt02" and value.get("phase") == phase and value.get("seed") == seed
            and value.get("source_freeze_sha256") == descriptor["sha256"]
            and value.get("operational_amendment_sha256") == parent["operational_amendment_sha256"]
            and value.get("post_execution_storage_check") is True, "Training operation ancestry or post-execution gate differs")
    target = root / ("stage_C/COMPLETE.json" if phase == "C" else f"stage_{phase}/seed-{seed}/COMPLETE.json")
    artifact = value["scientific_complete"]
    require(artifact["path"] == target.relative_to(root).as_posix() and target.stat().st_size == artifact["bytes"]
            and file_hash(target) == artifact["sha256"], "Operation does not bind the actual scientific completion")
    return value


def collect_ab(root, phase, runtime_sha, descriptor, parent):
    for seed in ab.SEEDS:
        operation_complete(root, phase, seed, descriptor, parent)
    inventory = ab.collect_checkpoints(root, phase, runtime_sha)
    for complete in inventory["completions"].values():
        require(complete["source_freeze_sha256"] == descriptor["sha256"]
                and complete["registered_commit"] == parent["registered_commit"], "A/B completion has an unregistered training ancestor")
    for entry in inventory["entries"]:
        raw = (Path(inventory["stage"]) / entry["path"]).read_bytes()
        record = ab.codec.loads(raw, entry["sha256"], entry["bytes"])
        require(record["binding"]["source_freeze_sha256"] == descriptor["sha256"]
                and record["binding"]["protocol_sha256"] == parent["protocol_sha256"], "A/B checkpoint protocol ancestry differs")
    return inventory


def collect_c(root, plan, runtime, descriptor, parent):
    # Pass the actual attempt02 training parent, never its historical ancestor or the scorer freeze.
    operation_complete(root, "C", None, descriptor, parent)
    return c.collect_checkpoints(root, plan, parent, descriptor["sha256"], parent["protocol_sha256"], runtime)


def endpoint_corpus(args, inventory, freeze, budget):
    """The original source loader enforces the unchanged complete population barrier."""
    if args.phase == "A":
        return sources.load_training_roles(args.assets, "A", ["development_task", "development_clean"]), {}
    final = args.phase == "C"
    expected = c.expected_ids() if final else ab.expected_ids("B")
    require(len(inventory["entries"]) == len(expected) and {row["id"] for row in inventory["entries"]} == set(expected),
            "Endpoint access cannot select a checkpoint subset")
    stage = Path(inventory["stage"])
    phase, roles = ("final", ["final_task", "final_clean"]) if final else ("qualification", ["qualification_task", "qualification_clean"])
    checkpoint_path = stage / "ENDPOINT_CHECKPOINTS.json"
    access_path = stage / ("FINAL_ACCESS_FREEZE.json" if final else "QUALIFICATION_ACCESS_FREEZE.json")
    manifest = {"schema": sources.CHECKPOINT_SCHEMA, "phase": phase, "training_complete": True,
                "checkpoints": [{key: row[key] for key in ("id", "path", "bytes", "sha256")} for row in inventory["entries"]]}
    manifest.update({"complete_sha256": inventory["complete_sha256"]} if final else {"training_manifest_hashes": inventory["training_manifest_hashes"]})
    write_json(checkpoint_path, manifest, budget)
    checkpoint_sha = file_hash(checkpoint_path)
    write_json(access_path, {"schema": sources.FREEZE_SCHEMA, "phase": phase,
               "source_manifest_sha256": file_hash(args.source_manifest), "checkpoint_manifest_sha256": checkpoint_sha,
               "allowed_roles": roles, "required_checkpoint_ids": sorted(expected),
               "scorer_freeze_sha256": file_hash(args.freeze), "scorer_registered_commit": freeze["registered_commit"]}, budget)
    access = {"phase": phase, "freeze_path": str(access_path), "expected_freeze_sha256": file_hash(access_path),
              "checkpoint_manifest_path": str(checkpoint_path), "expected_checkpoint_manifest_sha256": checkpoint_sha}
    sources._barrier(args.source_manifest, roles, **access)
    return sources.load_new_roles(args.assets, args.source_manifest, roles, **access), access


def execute_ab(args, registration, freeze, descriptor, parent, ancestry):
    ab.torch.set_num_threads(2)
    ab.torch.set_num_interop_threads(1)
    ab.torch.use_deterministic_algorithms(True)
    root, costs = Path(args.root).resolve(), ab.Costs()
    budget = EndpointBudget(root, costs, args.phase, registration)
    budget()
    runtime = ab.strict.runtime_descriptor()
    inventory = ab.timed(costs, "endpoint_inventory_verify", lambda: collect_ab(root, args.phase, ab.codec.digest(runtime), descriptor, parent))
    directory = root / ("stage_" + args.phase) / "endpoints"
    directory.mkdir(exist_ok=False)
    (directory / "scores").mkdir()
    try:
        write_json(directory / "OPERATIONAL_ANCESTRY.json", ancestry, budget)
        corpus, access = ab.timed(costs, "endpoint_source_access", lambda: endpoint_corpus(args, inventory, freeze, budget))
        protocol = json.loads(Path(ab.learning.__file__).with_name("PROTOCOL.json").read_text())
        originals, observers, assets = ab.timed(costs, "endpoint_asset_load", lambda: ab.load_assets(args.assets, list(ab.SEEDS), ["reward", "audit"]))
        training = ab.timed(costs, "endpoint_training_context_load", lambda: sources.load_training_roles(args.assets, args.phase, ab.TRAINING_ROLES))
        roles = {role: ("development_" if args.phase == "A" else "qualification_") + role for role in ("task", "clean")}
        rows = []
        for seed in ab.SEEDS:
            budget()
            context = ab.timed(costs, "endpoint_context_construction", lambda: ab.learning.make_context(
                originals[seed], training, {"reward": observers["reward"]}, seed, "development", protocol, costs))
            panels = {role: ab.learning.panels(corpus, source_role, seed,
                      protocol["training"]["conditions"] if role == "task" else ["clean"], protocol) for role, source_role in roles.items()}
            for role, source_role in roles.items():
                rows.append(ab.score_one(originals[seed], panels[role], observers, context.action, protocol, costs,
                            directory, f"seed-{seed}-frozen", seed, None, "frozen", role, source_role, {}, budget))
            for entry in (row for row in inventory["entries"] if row["seed"] == seed):
                budget()
                raw = (Path(inventory["stage"]) / entry["path"]).read_bytes()
                record = ab.codec.loads(raw, entry["sha256"], entry["bytes"])
                adapter = ab.timed(costs, "endpoint_model_construction", lambda: ab.initialize(context, record["binding"], entry["schedule_id"], entry["method"]))
                adapter.restore(raw, entry["sha256"])
                for role, source_role in roles.items():
                    row = ab.score_one(adapter.model, panels[role], observers, context.action, protocol, costs, directory,
                          entry["id"], seed, entry["schedule_id"], entry["method"], role, source_role,
                          entry["costs"] if role == "task" else {}, budget, entry["sha256"])
                    row.update({key: entry.get(key) for key in ("first_legal_divergence_decision", "terminal_reference_tail_state_equal")})
                    rows.append(row)
                print(json.dumps({"phase": args.phase, "endpoint_scored": entry["id"]}), flush=True)
        require(len(rows) == 2 * (len(inventory["entries"]) + len(ab.SEEDS)), "Incomplete endpoint population")
        result = {"schema": "hepta.fullstudy.AB.endpoints.1", "complete": True, "phase": args.phase,
                  "training_path_count": len(inventory["entries"]), "records": rows, "observers": ["reward", "audit"],
                  "training_manifest_hashes": inventory["training_manifest_hashes"],
                  "training_stage_costs": {seed: entry["costs"] for seed, entry in inventory["completions"].items()},
                  "scoring_costs": costs.snapshot(), "wall_seconds": time.monotonic() - budget.wall,
                  "cpu_seconds": time.process_time() - budget.cpu,
                  "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
                  "runtime": runtime, "assets": assets,
                  "access": access, "source_roles_opened": list(roles.values()), "operations": ancestry,
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "frozen_original_reuse": "One score per seed/role; reuse for paired comparisons, never independent schedule samples."}
        publish(directory, result, ab.load_records, budget)
        return result
    except BaseException as error:
        failure(directory, args.phase, error, costs.snapshot(), ancestry)
        raise


def execute_c(args, registration, freeze, descriptor, parent, ancestry):
    protocol = json.loads(Path(args.protocol).read_text())
    require(protocol.get("execution_ready") is True, "The scientific protocol is not execution-ready")
    mapping = protocol["stage_C"]["execution_plan"]
    plan = c.ArchitecturePlan.from_mapping(mapping)
    require(set(mapping) == set(c.ArchitecturePlan.__dataclass_fields__) and plan == c.ArchitecturePlan(), "C frozen plan differs")
    c.torch.set_num_threads(plan.threads)
    c.torch.set_num_interop_threads(1)
    c.torch.use_deterministic_algorithms(True)
    root, work = Path(args.root).resolve(), c.Work()
    work.phase = "endpoint"
    budget = EndpointBudget(root, work, "C", registration)
    budget()
    runtime = c.runtime_identity()
    inventory = collect_c(root, plan, runtime, descriptor, parent)
    budget.training_work = inventory["seal"]["work"]
    stage = Path(inventory["stage"])
    directory = stage / "endpoint_evaluation"
    directory.mkdir(exist_ok=False)
    (directory / "scores").mkdir()
    try:
        write_json(directory / "OPERATIONAL_ANCESTRY.json", ancestry, budget)
        corpus, access = endpoint_corpus(args, inventory, freeze, budget)
        unused, observers, assets = c.load_assets(args.assets, [], ["reward", "audit"])
        require({k: v for k, v in assets.items() if k != "loaded_observers"}
                == {k: v for k, v in inventory["seal"]["binding"]["assets"].items() if k != "loaded_observers"}, "C original asset binding differs")
        rows = []
        for seed in c.SEEDS:
            panels = {role: c.panels(corpus, source_role, seed, plan) for role, source_role in c.ROLES.items()}
            for entry in (row for row in inventory["entries"] if row["seed"] == seed):
                budget()
                target = c.checked_file(stage, entry)
                model, optimizer, record = c.load_generator_checkpoint(target, args.reference_root, plan)
                require(record["state_sha256"] == entry["state_sha256"] and c.parameter_hash(model) == entry["parameter_sha256"], "Restored C model differs")
                model.eval().requires_grad_(False)
                original_model = c.digest(model.state_dict())
                for role, source_role in c.ROLES.items():
                    before = work.snapshot()
                    score = c.hard_panel(model, panels[role], observers, plan, work, budget)
                    path = directory / "scores" / (entry["id"] + "-" + role + ".npz")
                    meta = c.save_score(path, score, check_write=budget)
                    work.add("output_bytes", meta["bytes"])
                    require(c.digest(model.state_dict()) == original_model, "C scoring mutated model state")
                    rows.append({**{key: entry[key] for key in ("seed", "architecture", "method", "schedule_id", "own_warmstart_id")},
                                 "id": entry["id"] + "-" + role, "role": role, "source_role": source_role,
                                 "path": path.relative_to(directory).as_posix(), "sha256": meta["file_sha256"],
                                 "bytes": meta["bytes"], "rows": meta["rows"], "means": meta["means"],
                                 "readback_equal": meta["readback_equal"], "checkpoint_sha256": entry["sha256"],
                                 "costs": entry["costs"] if role == "task" else {}, "scoring_costs": c.work_delta(before, work.snapshot())})
                    budget()
                del model, optimizer, record
                print(json.dumps({"phase": "C", "endpoint_scored": entry["id"]}), flush=True)
        require(len(rows) == 96, "Incomplete C endpoint population")
        result = {"schema": c.SCHEMA, "complete": True, "phase": "C", "training_path_count": 32, "own_warmstart_count": 16,
                  "records": rows, "observers": ["reward", "audit"], "training_stage_work": inventory["seal"]["work"],
                  "training_complete_sha256": inventory["complete_sha256"], "scoring_work": work.snapshot(),
                  "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
                  "runtime": runtime, "assets": assets, "source_roles_opened": list(c.ROLES.values()), "access": access,
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"], "operations": ancestry,
                  "output_action": 0, "latent_actions": ["couple"], "refinement_charge": plan.refinement_charge,
                  "panel_tape": "C panel/panel-noise tape_seed(seed, role, schedule=0, offset, condition); shared across all arms",
                  "frozen_reuse": "Each architecture/seed own warmstart, scored once per role; warm-up costs counted once."}
        publish(directory, result, c.load_records, budget)
        return result
    except BaseException as error:
        failure(directory, "C", error, work.snapshot(), ancestry)
        raise


def publish(directory, result, loader, budget):
    pending = directory / "ENDPOINTS.pending.json"
    write_json(pending, result, budget)
    loader(pending, file_hash(pending))
    budget()
    pending.rename(directory / "ENDPOINTS.json")


def failure(directory, phase, error, work, ancestry):
    record = {"complete": False, "phase": phase, "error_type": type(error).__name__, "message": str(error),
              "partial_evidence_preserved": True, "scoring_work": work, "operations": ancestry}
    try:
        # A tiny failure receipt may be needed after a resource gate stopped scoring.
        ab.write_json(directory / "FAILED.json", record)
    except (OSError, ValueError, RuntimeError, MemoryError):
        print(json.dumps(record), flush=True)


def execute(args):
    registration, freeze, descriptor, parent, ancestry = registration_for(args)
    root = Path(args.root).resolve()
    require(root.is_dir(), "Training evidence root is missing")
    require(args.phase == "A" or args.source_manifest, "Withheld endpoints require the explicit source manifest")
    require(args.phase != "C" or args.reference_root, "C requires the pinned HCSN source root")
    with training_slot(root, registration), guarded_writes(root, registration):
        load_science()  # Torch/model imports occur only after memory admission.
        from .run_v2 import ensure_loaded_closure
        ensure_loaded_closure(freeze)
        return (execute_c if args.phase == "C" else execute_ab)(args, registration, freeze, descriptor, parent, ancestry)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["A", "B", "C"])
    for option in ("assets", "root", "freeze", "amendment", "amendment-sha256", "protocol"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--source-manifest")
    parser.add_argument("--reference-root")
    parser.add_argument("--execute", action="store_true")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
