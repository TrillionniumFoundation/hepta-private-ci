"""Complete-inventory endpoint barrier and paired A/B hard-output scoring.

Importing this module opens no scientific assets. Qualification access requires
all 240 B checkpoints; frozen originals are scored once per seed and role.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np
import torch

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning
from ..multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_common import Costs
from .bank import initialize, write_json
from .branching import BASELINES, SCHEMA, codec, strict, timed
from .run import Budget, ROOT, file_hash, verify_freeze
from . import sources


SEEDS = (17, 29, 43)
METHODS = ("ordinary", "field12", "full_current_state", "history6")
TRAINING_ROLES = ["development_gradient", "development_rehearsal", "development_probe", "development_guard"]


class EndpointBudget(Budget):
    """Check the actual compressed payload before consuming the reserved bytes."""

    def __call__(self, additional=0):
        super().__call__()
        if type(additional) is not int or additional < 0:
            raise ValueError("Invalid pending evidence size")
        if additional:
            stat = os.statvfs(self.root)
            raw = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
            if stat.f_bavail * stat.f_frsize < 2 * 1024 ** 3 + additional or raw + additional > 1024 ** 3:
                raise RuntimeError("Pending evidence would consume the registered reserve or raw cap")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def phase_spec(phase):
    require(phase in ("A", "B"), "Unknown endpoint study phase")
    return ((range(6000, 6004), METHODS, 39168) if phase == "A" else
            (range(106000, 106016), METHODS + ("fixed_taper",), 23040))


def expected_ids(phase):
    schedules, methods, _ = phase_spec(phase)
    return {f"seed-{seed}-schedule-{schedule}-{method}": (seed, schedule, method)
            for seed in SEEDS for schedule in schedules for method in methods}


def collect_checkpoints(root, phase, runtime_sha256=None):
    """Validate every required completion, path identity and literal checkpoint."""
    stage = Path(root).resolve() / ("stage_" + phase)
    expected, found, completions, manifests = expected_ids(phase), {}, {}, {}
    _, _, steps = phase_spec(phase)
    for seed in SEEDS:
        directory = stage / f"seed-{seed}"
        require(not (directory / "FAILED.json").exists(), "A failed training phase cannot open endpoints")
        complete_path, paths_path = directory / "COMPLETE.json", directory / "paths" / "PATHS.json"
        require(complete_path.is_file() and paths_path.is_file(), "All three training seeds must complete before endpoint access")
        complete, paths = json.loads(complete_path.read_text()), json.loads(paths_path.read_text())
        count = len(expected) // len(SEEDS)
        require(complete.get("complete") is True and complete.get("phase") == phase and complete.get("seed") == seed
                and complete.get("path_count") == count
                and complete.get("costs", {}).get("scheduled_gradient_microsteps") == steps,
                "Training completion or registered work inventory differs")
        require(paths.get("complete") is True and paths.get("training_complete") is True
                and paths.get("phase") == phase and paths.get("seed") == seed
                and paths.get("new_endpoint_roles_opened") == [] and len(paths.get("paths", [])) == count,
                "Paired training paths are incomplete or endpoints were already opened")
        require(type(complete.get("registered_commit")) is str and len(complete["registered_commit"]) == 40,
                "Training source commit is missing")
        completions[str(seed)] = complete
        manifests[str(seed)] = {"complete_sha256": file_hash(complete_path), "paths_sha256": file_hash(paths_path)}
        for row in paths["paths"]:
            identity = row.get("id")
            require(identity in expected and identity not in found, "Unexpected or duplicate endpoint checkpoint")
            require((row.get("seed"), row.get("schedule_id"), row.get("method")) == expected[identity]
                    and row["seed"] == seed, "Endpoint path identity differs")
            relative = Path(row["path"])
            target = (paths_path.parent / relative).resolve()
            require(relative == Path(identity + ".state") and target.is_relative_to(stage)
                    and target.is_file(), "Unsafe or missing endpoint checkpoint path")
            require(type(row.get("bytes")) is int and row["bytes"] > 0
                    and target.stat().st_size == row["bytes"] and file_hash(target) == row.get("sha256"),
                    "Endpoint checkpoint bytes changed")
            raw = target.read_bytes()
            record = codec.loads(raw, row["sha256"], row["bytes"])
            cursor, binding = record["cursor"], record["binding"]
            require(record["schema"] == SCHEMA and cursor["seed"] == seed
                    and cursor["schedule_id"] == row["schedule_id"] and cursor["path_kind"] == row["method"]
                    and cursor["clock"] == 288 and cursor["remaining_steps"] == 0 and cursor["total_steps"] == 288
                    and cursor["guard_grain"] == 48 and cursor["baseline_action"] == BASELINES[seed],
                    "Checkpoint is not the declared terminal learning state")
            require(binding["source_freeze_sha256"] == complete["source_freeze_sha256"],
                    "Checkpoint training freeze differs from its completion")
            if runtime_sha256 is not None:
                require(binding["runtime_sha256"] == runtime_sha256, "Endpoint runtime differs from the training branch runtime")
            require(type(row.get("costs")) is dict and all(type(v) is int and v >= 0 for v in row["costs"].values()),
                    "Invalid training path work ledger")
            found[identity] = {**row, "path": target.relative_to(stage).as_posix()}
    require(set(found) == set(expected), "The complete expected endpoint checkpoint population is required")
    return {"phase": phase, "stage": str(stage), "entries": [found[key] for key in sorted(expected)],
            "completions": completions, "training_manifest_hashes": manifests}


def make_qualification_barrier(inventory, source_manifest, scorer_freeze, scorer_freeze_sha256):
    """Write one immutable manifest for all B paths, never a chosen subset."""
    require(inventory["phase"] == "B" and len(inventory["entries"]) == 240
            and {row["id"] for row in inventory["entries"]} == set(expected_ids("B")),
            "Qualification requires the complete 240-checkpoint population")
    stage = Path(inventory["stage"])
    checkpoints_path = stage / "ENDPOINT_CHECKPOINTS.json"
    access_path = stage / "QUALIFICATION_ACCESS_FREEZE.json"
    require(not checkpoints_path.exists() and not access_path.exists(), "Endpoint access evidence already exists")
    manifest = {"schema": sources.CHECKPOINT_SCHEMA, "phase": "qualification", "training_complete": True,
                "checkpoints": [{key: row[key] for key in ("id", "path", "bytes", "sha256")}
                                for row in inventory["entries"]],
                "training_manifest_hashes": inventory["training_manifest_hashes"]}
    write_json(checkpoints_path, manifest)
    checkpoints_sha = file_hash(checkpoints_path)
    access = {"schema": sources.FREEZE_SCHEMA, "phase": "qualification",
              "source_manifest_sha256": file_hash(source_manifest),
              "checkpoint_manifest_sha256": checkpoints_sha,
              "allowed_roles": list(sources.PHASE_ROLES["qualification"]),
              "required_checkpoint_ids": sorted(expected_ids("B")),
              "scorer_freeze_sha256": scorer_freeze_sha256,
              "scorer_registered_commit": scorer_freeze["registered_commit"]}
    write_json(access_path, access)
    access_sha = file_hash(access_path)
    kwargs = {"phase": "qualification", "freeze_path": access_path, "expected_freeze_sha256": access_sha,
              "checkpoint_manifest_path": checkpoints_path, "expected_checkpoint_manifest_sha256": checkpoints_sha}
    sources._barrier(source_manifest, list(sources.PHASE_ROLES["qualification"]), **kwargs)
    return kwargs


def load_endpoint_corpus(asset_root, phase, inventory, source_manifest, scorer_freeze, scorer_freeze_sha256):
    # This function is deliberately downstream of the complete checkpoint check.
    require(inventory["phase"] == phase and {row["id"] for row in inventory["entries"]} == set(expected_ids(phase)),
            "Endpoint loading cannot select a checkpoint subset")
    if phase == "A":
        return sources.load_training_roles(asset_root, "A", ["development_task", "development_clean"]), {}
    require(source_manifest is not None, "Qualification requires the frozen new source allocation")
    barrier = make_qualification_barrier(inventory, source_manifest, scorer_freeze, scorer_freeze_sha256)
    corpus = sources.load_new_roles(asset_root, source_manifest, list(sources.PHASE_ROLES["qualification"]), **barrier)
    return corpus, {key: str(value) if isinstance(value, Path) else value for key, value in barrier.items()}


def save_score(path, score, check_write=None):
    """Persist actual emissions, re-read every array, and hash the saved bytes."""
    expected = {"values_" + name: values for name, values in score["values"].items()}
    expected.update({key: np.asarray(score[key], dtype=str) for key in ("source_ids", "conditions", "output_sha256")})
    expected.update({key: score[key] for key in ("pixels_u8", "captions_utf8")})
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **expected)
    payload = buffer.getvalue()
    if check_write is not None:
        check_write(len(payload))
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    metadata = {"file_sha256": hashlib.sha256(payload).hexdigest(), "means": score["means"],
                "rows": len(score["output_sha256"])}
    with np.load(path, allow_pickle=False) as saved:
        require(set(saved.files) == set(expected), "Saved hard-output inventory differs")
        for key, value in expected.items():
            require(np.array_equal(saved[key], value), "Saved hard output differs: " + key)
    require(file_hash(path) == metadata["file_sha256"], "Hard-output readback hash differs")
    return {**metadata, "bytes": Path(path).stat().st_size, "readback_equal": True}


def load_records(manifest_path, expected_sha256=None):
    """Verify the complete score grid and bytes before exposing analysis arrays."""
    path = Path(manifest_path).resolve()
    require(not (path.parent / "FAILED.json").exists(), "A failed endpoint phase cannot be analyzed as complete")
    if expected_sha256 is not None:
        require(file_hash(path) == expected_sha256, "Endpoint manifest hash differs")
    manifest = json.loads(path.read_text())
    require(manifest.get("schema") == "hepta.fullstudy.AB.endpoints.1" and manifest.get("complete") is True,
            "Analysis requires a completed endpoint manifest")
    phase = manifest["phase"]
    expected = expected_ids(phase)
    require(manifest.get("training_path_count") == len(expected)
            and manifest.get("observers") == ["reward", "audit"], "Endpoint phase or observer population differs")
    expected.update({f"seed-{seed}-frozen": (seed, None, "frozen") for seed in SEEDS})
    grid = {identity + "-" + role: (*coordinate, role)
            for identity, coordinate in expected.items() for role in ("task", "clean")}
    rows = manifest["records"]
    require(len(rows) == len(grid) and {row["id"] for row in rows} == set(grid), "Incomplete endpoint analysis grid")
    result, seen_paths = [], set()
    for row in rows:
        require((row["seed"], row["schedule_id"], row["method"], row["role"]) == grid[row["id"]],
                "Endpoint analysis identity differs")
        source_role = ("development_" if phase == "A" else "qualification_") + row["role"]
        require(row["source_role"] == source_role, "Endpoint source role differs")
        relative = Path(row["path"])
        target = (path.parent / relative).resolve()
        require(not relative.is_absolute() and ".." not in relative.parts and target.is_relative_to(path.parent)
                and target not in seen_paths and target.is_file()
                and target.stat().st_size == row["bytes"] and file_hash(target) == row["sha256"],
                "Endpoint output path or literal bytes differ")
        seen_paths.add(target)
        with np.load(target, allow_pickle=False) as saved:
            values = {observer: saved["values_" + observer].copy() for observer in ("reward", "audit")}
            ids, conditions = saved["source_ids"].copy(), saved["conditions"].copy()
        count = row["rows"]
        require(type(count) is int and count > 0 and ids.shape == (count, 2) and conditions.shape == (count,)
                and all(value.shape == (count,) and np.isfinite(value).all() for value in values.values()),
                "Invalid endpoint values or paired source layout")
        result.append({**row, "values": values, "source_ids": ids, "conditions": conditions})
    return result


def score_one(model, panel, observers, action, protocol, costs, directory, identity, seed, schedule, method,
              role, source_role, training_costs, check_budget, checkpoint_sha256=None):
    check_budget()
    before = costs.snapshot()
    wall, cpu = time.perf_counter(), time.process_time()
    score = timed(costs, "endpoint_scoring", lambda: learning.hard_panel(
        model, panel, observers, action, protocol, costs, "endpoint_" + role, retain=True))
    target = directory / "scores" / (identity + "-" + role + ".npz")
    metadata = timed(costs, "endpoint_persist_readback", lambda: save_score(target, score, check_write=check_budget))
    costs.add("endpoint_output_bytes", metadata["bytes"])
    check_budget()
    return {"id": identity + "-" + role, "seed": seed, "schedule_id": schedule, "method": method,
            "role": role, "source_role": source_role, "path": target.relative_to(directory).as_posix(),
            "sha256": metadata["file_sha256"], "bytes": metadata["bytes"], "rows": metadata["rows"],
            "means": metadata["means"], "checkpoint_sha256": checkpoint_sha256,
            "readback_equal": metadata["readback_equal"], "costs": training_costs,
            "scoring_costs": costs.since(before), "scoring_wall_seconds": time.perf_counter() - wall,
            "scoring_cpu_seconds": time.process_time() - cpu}


def execute(args):
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    freeze = verify_freeze(args.freeze, args.phase)
    prefix = Path(__file__).resolve().parent.relative_to(ROOT)
    required = ["endpoints.py", "sources.py", "bank.py", "branching.py", "run.py", "analysis.py"]
    require(all((prefix / name).as_posix() in freeze["source_files"] for name in required),
            "Scorer, analysis and barrier dependencies must be source-frozen before endpoint access")
    root = Path(args.root).resolve()
    require(root.is_dir(), "Training evidence root is missing")
    costs = Costs()
    budget = EndpointBudget(root, costs, args.phase)
    budget()
    runtime = strict.runtime_descriptor()
    inventory = timed(costs, "endpoint_inventory_verify", lambda: collect_checkpoints(
        root, args.phase, codec.digest(runtime)))
    directory = root / ("stage_" + args.phase) / "endpoints"
    require(not directory.exists(), "Refusing to overwrite or silently restart endpoint evidence")
    directory.mkdir()
    (directory / "scores").mkdir()
    try:
        # New endpoint tensors are materialized only after all required terminal files have passed.
        endpoint_corpus, access = timed(costs, "endpoint_source_access", lambda: load_endpoint_corpus(
            args.assets, args.phase, inventory, args.source_manifest, freeze, file_hash(args.freeze)))
        protocol = json.loads(Path(learning.__file__).with_name("PROTOCOL.json").read_text())
        originals, observers, assets = timed(costs, "endpoint_asset_load", lambda: load_assets(args.assets, list(SEEDS), ["reward", "audit"]))
        training_corpus = timed(costs, "endpoint_training_context_load", lambda: sources.load_training_roles(
            args.assets, args.phase, TRAINING_ROLES))
        roles = {"task": "development_task", "clean": "development_clean"} if args.phase == "A" else {
            "task": "qualification_task", "clean": "qualification_clean"}
        rows = []
        for seed in SEEDS:
            budget()
            context = timed(costs, "endpoint_context_construction", lambda: learning.make_context(
                originals[seed], training_corpus, {"reward": observers["reward"]}, seed, "development", protocol, costs))
            panels = {role: learning.panels(endpoint_corpus, source_role, seed,
                      protocol["training"]["conditions"] if role == "task" else ["clean"], protocol)
                      for role, source_role in roles.items()}
            for role, source_role in roles.items():
                rows.append(score_one(originals[seed], panels[role], observers, context.action, protocol, costs,
                    directory, f"seed-{seed}-frozen", seed, None, "frozen", role, source_role, {}, budget))
            for path in inventory["entries"]:
                if path["seed"] != seed:
                    continue
                budget()
                target = Path(inventory["stage"]) / path["path"]
                raw = target.read_bytes()
                record = codec.loads(raw, path["sha256"], path["bytes"])
                adapter = timed(costs, "endpoint_model_construction", lambda: initialize(
                    context, record["binding"], path["schedule_id"], path["method"]))
                adapter.restore(raw, path["sha256"])
                for role, source_role in roles.items():
                    row = score_one(adapter.model, panels[role], observers, context.action, protocol, costs, directory,
                        path["id"], seed, path["schedule_id"], path["method"], role, source_role,
                        path["costs"] if role == "task" else {}, budget, path["sha256"])
                    row["first_legal_divergence_decision"] = path.get("first_legal_divergence_decision")
                    row["terminal_reference_tail_state_equal"] = path.get("terminal_reference_tail_state_equal")
                    rows.append(row)
                print(json.dumps({"phase": args.phase, "endpoint_scored": path["id"]}), flush=True)
        require(len(rows) == 2 * (len(inventory["entries"]) + len(SEEDS)), "Incomplete endpoint score population")
        budget()
        result = {"schema": "hepta.fullstudy.AB.endpoints.1", "complete": True, "phase": args.phase,
                  "training_path_count": len(inventory["entries"]), "records": rows, "observers": ["reward", "audit"],
                  "training_manifest_hashes": inventory["training_manifest_hashes"],
                  "training_stage_costs": {seed: entry["costs"] for seed, entry in inventory["completions"].items()},
                  "scoring_costs": costs.snapshot(), "wall_seconds": time.monotonic() - budget.wall,
                  "cpu_seconds": time.process_time() - budget.cpu, "runtime": runtime, "assets": assets,
                  "access": access, "source_roles_opened": list(roles.values()),
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "frozen_original_reuse": "One score per seed/role; reuse for paired comparisons, never independent schedule samples."}
        pending = directory / "ENDPOINTS.pending.json"
        budget(len(json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode()) + 1)
        write_json(pending, result)
        require(json.loads(pending.read_text()) == result, "Endpoint manifest readback differs")
        budget()
        pending.rename(directory / "ENDPOINTS.json")
        print(json.dumps({"phase": args.phase, "complete": True, "endpoint_records": len(rows)}), flush=True)
        return result
    except BaseException as error:
        failed = {"complete": False, "phase": args.phase, "error_type": type(error).__name__, "message": str(error),
                  "partial_evidence_preserved": True, "scoring_costs": costs.snapshot()}
        try:
            write_json(directory / "FAILED.json", failed)
        except OSError:
            print(json.dumps(failed), flush=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True, choices=["A", "B"])
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--source-manifest")
    parser.add_argument("--freeze", required=True)
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
