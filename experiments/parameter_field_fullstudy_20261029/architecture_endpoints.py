"""Final C endpoints: complete 48-checkpoint barrier, immutable emissions, two observers.

Importing this module opens no data. Training and controller fitting are absent.
The final source roles are loaded only after all 32 paths and 16 own warmstarts
have passed their source-bound completion and literal-byte checks.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import torch

from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_common import require
from experiments.multimodal_output_portfolio.v6.data import make_batch, render_tokens
from experiments.multimodal_output_portfolio.v6.neural import parameter_hash
from experiments.multimodal_output_portfolio.v6.observer import observe_tensors
from .architecture import REFERENCE_COMMIT
from .architecture_kernel import ArchitecturePlan, Work, output, tape_seed
from .architecture_run import runtime_identity
from .architecture_state import digest, read_checkpoint
from .architecture_training import load_generator_checkpoint
from .bank import write_json
from .endpoints import save_score
from .run import ROOT, file_hash, verify_freeze
from . import sources

SEEDS, MODES = tuple(range(801, 809)), ("ordinary", "dual")
POLICIES = {"baseline": "ordinary", "field": "field12"}
ROLES = {"task": "final_task", "clean": "final_clean"}
SCHEMA = "hepta.fullstudy.C.endpoints.1"


def expected_ids():
    return {f"{mode}-seed-{seed}-{method}": (seed, mode, method, None if method == "frozen" else 8000)
            for seed in SEEDS for mode in MODES for method in ("ordinary", "field12", "frozen")}


def checked_file(root, entry):
    relative = Path(entry["path"])
    target = (root / relative).resolve()
    require(not relative.is_absolute() and ".." not in relative.parts and target.is_relative_to(root)
            and target.is_file() and type(entry.get("bytes")) is int and entry["bytes"] > 0
            and target.stat().st_size == entry["bytes"] and file_hash(target) == entry.get("sha256"),
            "Missing, unsafe or changed literal evidence bytes")
    return target


def work_delta(before, after):
    counts = {key: value - before["counts"].get(key, 0) for key, value in after["counts"].items()}
    require(set(before["counts"]) <= set(after["counts"])
            and all(type(value) is int and value >= 0 for value in counts.values()), "Invalid work count delta")
    result = {"counts": {key: value for key, value in counts.items() if value},
              **{key: after[key] - before[key] for key in ("cpu_seconds", "wall_seconds")}}
    require(all(np.isfinite(result[key]) and result[key] >= 0 for key in ("cpu_seconds", "wall_seconds")),
            "Invalid measured work time delta")
    return result


def collect_checkpoints(root, plan, freeze, freeze_sha256, protocol_sha256, runtime=None):
    stage = Path(root).resolve() / "stage_C"
    require(not (stage / "FAILED.json").exists(), "Failed C training cannot open final endpoints")
    complete_path = stage / "COMPLETE.json"
    require(complete_path.is_file(), "All C training must complete before final endpoint access")
    seal = json.loads(complete_path.read_text())
    require(seal.get("schema") == "hepta.fullstudy.C.complete-seal.1" and seal.get("complete") is True
            and seal.get("training_complete") is True and seal.get("new_endpoint_roles_opened") == []
            and ArchitecturePlan.from_mapping(seal["plan"]) == plan and seal.get("audit_count") == 4
            and seal.get("literal_tensor_checkpoints") == 52 and seal.get("physical_gradient_microsteps") == 57536
            and seal.get("scientific_gradient_microsteps") == 57152 and seal.get("replay_gradient_microsteps") == 384,
            "C completion, replay or registered work inventory differs")
    binding = seal["binding"]
    require(binding["registered_commit"] == freeze["registered_commit"]
            and binding["source_freeze_sha256"] == freeze_sha256 and binding["protocol_sha256"] == protocol_sha256
            and binding["hcsn_reference_commit"] == REFERENCE_COMMIT, "C training source binding differs")
    require(runtime is None or binding["runtime"] == runtime, "C scoring runtime differs from training")
    expected_work = {"warmup": 8000, "bank": 46080, "evaluation": 3072, "replay_audit": 384}
    require(all(seal["work"]["counts"].get(key + ".scheduled_gradient_microsteps") == value
                for key, value in expected_work.items()), "C physical work ledger differs")
    seen_files = set()
    for artifact in seal["artifacts"]:
        target = checked_file(stage, artifact)
        require(target not in seen_files, "Duplicate C artifact path")
        seen_files.add(target)
    warm_grid = {(seed, mode, role) for role, seeds in (("development", plan.development_seeds),
                 ("evaluation", plan.evaluation_seeds)) for seed in seeds for mode in MODES}
    warmstarts, entries = {}, {}
    require(len(seal["warmstarts"]) == 20 and len(seal["paths"]) == 32, "Incomplete C checkpoint population")
    for warm, rows in ((True, seal["warmstarts"]), (False, seal["paths"])):
        for row in rows:
            seed, mode = row["seed"], row["mode"]
            target = checked_file(stage, row["checkpoint"])
            require(target in seen_files, "Checkpoint is absent from the sealed artifact inventory")
            record = read_checkpoint(target)
            state, meta = record["state"], record["metadata"]
            config = {"hidden": plan.hidden, "noise_scale": plan.noise_scale, "mode": mode, "seed": seed,
                      "architecture": "fullstudy-hcsn-temporal-v1", "reference_commit": REFERENCE_COMMIT}
            require(state["schema"] == "hepta.fullstudy.C.training-state.1"
                    and record["state_sha256"] == row["state_sha256"] and state["model_config"] == config
                    and meta["config"] == config and meta["binding"] == binding and meta["seed"] == seed
                    and meta["mode"] == mode and meta["plan_sha256"] == digest(plan.to_dict())
                    and set(state["gradients"]) == set(state["parameter_names"])
                    and len(state["requires_grad"]) == len(state["parameter_names"]) and all(state["requires_grad"])
                    and all(value is None for value in state["gradients"].values()), "C checkpoint state binding differs")
            costs = work_delta(meta["work_before"], meta["work_after"])
            if warm:
                coordinate = (seed, mode, row["role"])
                require(coordinate in warm_grid and (seed, mode) not in warmstarts
                        and meta["schema"] == "hepta.fullstudy.C.warmstart.1" and meta["role"] == row["role"]
                        and meta["warmup_steps"] == plan.warmup_steps and meta["optimizer_state_carried"] is True
                        and set(meta["gradient_seen"]) == set(state["parameter_names"])
                        and set(meta["changed_parameters"]) == set(state["parameter_names"]),
                        "C own warmstart population or training identity differs")
                warmstarts[(seed, mode)] = record["state_sha256"]
                if row["role"] == "development":
                    continue
                method, schedule = "frozen", None
            else:
                require(row["policy"] in POLICIES, "Unknown C policy")
                method, schedule = POLICIES[row["policy"]], plan.evaluation_schedule
                require(meta["schema"] == "hepta.fullstudy.C.endpoint.1" and meta["policy"] == row["policy"]
                        and meta["clock"] == plan.steps and meta["schedule"] == schedule
                        and meta["warmstart_state_sha256"] == warmstarts.get((seed, mode)),
                        "C terminal checkpoint or own warmstart differs")
            identity = f"{mode}-seed-{seed}-{method}"
            require(identity in expected_ids() and identity not in entries, "Unexpected or duplicate C endpoint")
            entries[identity] = {"id": identity, "seed": seed, "architecture": mode, "method": method,
                                 "schedule_id": schedule, **row["checkpoint"], "state_sha256": record["state_sha256"],
                                 "parameter_sha256": meta["parameter_sha256"], "costs": costs,
                                 "own_warmstart_id": f"{mode}-seed-{seed}-frozen"}
    require(set(entries) == set(expected_ids()) and len(warmstarts) == 20, "Every C endpoint and own warmstart is required")
    return {"stage": str(stage), "entries": [entries[key] for key in sorted(entries)], "seal": seal,
            "complete_sha256": file_hash(complete_path)}


def load_endpoint_corpus(asset_root, inventory, source_manifest, freeze, freeze_sha256):
    require(len(inventory["entries"]) == 48 and {x["id"] for x in inventory["entries"]} == set(expected_ids()),
            "Final access cannot select a C checkpoint subset")
    stage = Path(inventory["stage"])
    checkpoint_path, access_path = stage / "ENDPOINT_CHECKPOINTS.json", stage / "FINAL_ACCESS_FREEZE.json"
    write_json(checkpoint_path, {"schema": sources.CHECKPOINT_SCHEMA, "phase": "final", "training_complete": True,
               "checkpoints": [{key: row[key] for key in ("id", "path", "bytes", "sha256")} for row in inventory["entries"]],
               "complete_sha256": inventory["complete_sha256"]})
    checkpoint_sha = file_hash(checkpoint_path)
    write_json(access_path, {"schema": sources.FREEZE_SCHEMA, "phase": "final",
               "source_manifest_sha256": file_hash(source_manifest), "checkpoint_manifest_sha256": checkpoint_sha,
               "allowed_roles": list(ROLES.values()), "required_checkpoint_ids": sorted(expected_ids()),
               "scorer_freeze_sha256": freeze_sha256, "scorer_registered_commit": freeze["registered_commit"]})
    access = {"phase": "final", "freeze_path": str(access_path), "expected_freeze_sha256": file_hash(access_path),
              "checkpoint_manifest_path": str(checkpoint_path), "expected_checkpoint_manifest_sha256": checkpoint_sha}
    return sources.load_new_roles(asset_root, source_manifest, list(ROLES.values()), **access), access


def panels(corpus, role, seed, plan):
    require(role in ROLES.values() and len(corpus.splits[role]) == 1976, "C final source population differs")
    result, count = [], len(corpus.splits[role]) // 2
    for condition in (plan.conditions if role == "final_task" else ("clean",)):
        for offset in range(0, count, plan.panel_batch_size):
            batch = make_batch(corpus, role, min(plan.panel_batch_size, count - offset),
                               tape_seed(seed, "panel:" + role, 0, offset, condition), corruption=condition, offset=offset)
            result.append((condition, batch, tape_seed(seed, "panel-noise:" + role, 0, offset, condition)))
    return result


@torch.inference_mode()
def hard_panel(model, panel, observers, plan, work, check_budget):
    values, pixels, captions, ids, conditions, hashes = {name: [] for name in observers}, [], [], [], [], []
    for condition, batch, noise_seed in panel:
        check_budget()
        predicted = output(model, batch, noise_seed, ("couple",), False, work, "generator")
        quantized = (predicted.image_logits.sigmoid() * 255).round().to(torch.uint8)
        emitted = [render_tokens(row).encode("utf-8").decode("utf-8") for row in predicted.token_ids]
        for name, observer in observers.items():
            work.add(name + "_observer_calls", 2)
            work.add(name + "_observer_digit_examples", 2 * len(batch.source_ids))
            scored = observe_tensors(observer, quantized.float() / 255, emitted, batch.target.pixels, batch.target.labels)
            values[name].extend(row["utility"] - plan.refinement_charge for row in scored)
        hashes.extend(hashlib.sha256(pixel.numpy().tobytes() + text.encode()).hexdigest()
                      for pixel, text in zip(quantized, emitted, strict=True))
        pixels.append(quantized.numpy())
        captions.extend(emitted)
        ids.extend(batch.source_ids)
        conditions.extend([condition] * len(batch.source_ids))
    arrays = {name: np.asarray(value, dtype=np.float64) for name, value in values.items()}
    require(set(arrays) == {"reward", "audit"} and all(np.isfinite(v).all() for v in arrays.values()),
            "Both independent observers and finite endpoint values are required")
    return {"values": arrays, "means": {k: float(v.mean()) for k, v in arrays.items()}, "output_sha256": hashes,
            "conditions": conditions, "source_ids": ids, "pixels_u8": np.concatenate(pixels),
            "captions_utf8": np.asarray(captions, dtype=str)}


def load_records(manifest_path, expected_sha256=None):
    path = Path(manifest_path).resolve()
    require(not (path.parent / "FAILED.json").exists() and (expected_sha256 is None or file_hash(path) == expected_sha256),
            "Failed or changed C endpoint manifest")
    manifest = json.loads(path.read_text())
    require(manifest.get("schema") == SCHEMA and manifest.get("complete") is True and manifest.get("phase") == "C"
            and manifest.get("training_path_count") == 32 and manifest.get("own_warmstart_count") == 16
            and manifest.get("observers") == ["reward", "audit"], "Analysis requires completed C endpoints")
    grid = {identity + "-" + role: (*coordinate, role) for identity, coordinate in expected_ids().items() for role in ROLES}
    rows = manifest["records"]
    require(len(rows) == 96 and {row["id"] for row in rows} == set(grid), "Incomplete 96-record C analysis grid")
    result, seen = [], set()
    for row in rows:
        require((row["seed"], row["architecture"], row["method"], row["schedule_id"], row["role"]) == grid[row["id"]]
                and row["source_role"] == ROLES[row["role"]]
                and row["own_warmstart_id"] == f"{row['architecture']}-seed-{row['seed']}-frozen",
                "C endpoint identity or own warmstart differs")
        target = checked_file(path.parent, row)
        require(target not in seen, "Duplicate C score path")
        seen.add(target)
        with np.load(target, allow_pickle=False) as saved:
            values = {name: saved["values_" + name].copy() for name in ("reward", "audit")}
            ids, conditions = saved["source_ids"].copy(), saved["conditions"].copy()
            pixels, captions, hashes = saved["pixels_u8"], saved["captions_utf8"], saved["output_sha256"]
            count = row["rows"]
            require(type(count) is int and count > 0 and ids.shape == (count, 2) and conditions.shape == (count,)
                    and pixels.shape == (count, 1, 28, 56) and pixels.dtype == np.uint8
                    and captions.shape == hashes.shape == (count,)
                    and all(v.shape == (count,) and np.isfinite(v).all() for v in values.values()), "Invalid C hard-output layout")
            require(all(hashlib.sha256(pixel.tobytes() + str(text).encode()).hexdigest() == code
                        for pixel, text, code in zip(pixels, captions, hashes, strict=True)), "C emitted-output digest differs")
        result.append({**row, "values": values, "source_ids": ids, "conditions": conditions})
    return result


def execute(args):
    freeze, protocol = verify_freeze(args.freeze, "C"), json.loads(Path(args.protocol).read_text())
    require(args.execute and protocol.get("execution_ready") is True and file_hash(args.protocol) == freeze["protocol_sha256"],
            "C endpoints require explicit execution and an execution-ready frozen protocol")
    mapping = protocol["stage_C"]["execution_plan"]
    plan = ArchitecturePlan.from_mapping(mapping)
    require(set(mapping) == set(ArchitecturePlan.__dataclass_fields__) and plan == ArchitecturePlan(), "C frozen plan differs")
    prefix = Path(__file__).resolve().parent.relative_to(ROOT)
    required = ("architecture_endpoints", "architecture", "architecture_kernel", "architecture_state", "architecture_training",
                "architecture_run", "endpoints", "sources", "analysis", "run")
    require(all((prefix / (name + ".py")).as_posix() in freeze["source_files"] for name in required),
            "C endpoint, analysis and source barrier dependencies must be frozen")
    torch.set_num_threads(plan.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    root, work = Path(args.root).resolve(), Work()
    work.phase = "endpoint"
    runtime = runtime_identity()
    inventory = collect_checkpoints(root, plan, freeze, file_hash(args.freeze), file_hash(args.protocol), runtime)
    stage = Path(inventory["stage"])
    directory = stage / "endpoint_evaluation"
    directory.mkdir(exist_ok=False)
    (directory / "scores").mkdir()

    def check_budget(additional=0):
        stat, elapsed = os.statvfs(root), work.snapshot()
        require(stat.f_bavail * stat.f_frsize >= 2 * 1024 ** 3 + additional and stat.f_favail >= 2000, "C endpoint disk/inode reserve exhausted")
        require(sum(p.stat().st_size for p in stage.rglob("*") if p.is_file() and not p.is_relative_to(directory)) <= 350 * 1024 ** 2
                and sum(p.stat().st_size for p in root.rglob("*") if p.is_file()) + additional <= 1024 ** 3, "C/global raw evidence cap exhausted")
        require(elapsed["cpu_seconds"] + inventory["seal"]["work"]["cpu_seconds"] <= 12 * 3600
                and elapsed["wall_seconds"] + inventory["seal"]["work"]["wall_seconds"] <= 6 * 3600, "C measured time ceiling exhausted")

    try:
        check_budget()
        corpus, access = load_endpoint_corpus(args.assets, inventory, args.source_manifest, freeze, file_hash(args.freeze))
        unused, observers, assets = load_assets(args.assets, [], ["reward", "audit"])
        require({k: v for k, v in assets.items() if k != "loaded_observers"}
                == {k: v for k, v in inventory["seal"]["binding"]["assets"].items() if k != "loaded_observers"},
                "C endpoint original asset binding differs")
        rows = []
        for seed in SEEDS:
            panel = {role: panels(corpus, source, seed, plan) for role, source in ROLES.items()}
            for entry in (row for row in inventory["entries"] if row["seed"] == seed):
                check_budget()
                target = checked_file(stage, entry)
                model, optimizer, record = load_generator_checkpoint(target, args.reference_root, plan)
                require(record["state_sha256"] == entry["state_sha256"] and parameter_hash(model) == entry["parameter_sha256"],
                        "Restored C endpoint model differs")
                model.eval().requires_grad_(False)
                before_model = digest(model.state_dict())
                for role, source_role in ROLES.items():
                    before = work.snapshot()
                    score = hard_panel(model, panel[role], observers, plan, work, check_budget)
                    path = directory / "scores" / (entry["id"] + "-" + role + ".npz")
                    meta = save_score(path, score, check_write=check_budget)
                    work.add("output_bytes", meta["bytes"])
                    require(digest(model.state_dict()) == before_model, "C scoring mutated model state")
                    rows.append({**{k: entry[k] for k in ("seed", "architecture", "method", "schedule_id", "own_warmstart_id")},
                                 "id": entry["id"] + "-" + role, "role": role, "source_role": source_role,
                                 "path": path.relative_to(directory).as_posix(), "sha256": meta["file_sha256"],
                                 "bytes": meta["bytes"], "rows": meta["rows"], "means": meta["means"],
                                 "readback_equal": meta["readback_equal"], "checkpoint_sha256": entry["sha256"],
                                 "costs": entry["costs"] if role == "task" else {}, "scoring_costs": work_delta(before, work.snapshot())})
                    check_budget()
                del model, optimizer, record
                print(json.dumps({"phase": "C", "endpoint_scored": entry["id"]}), flush=True)
        require(len(rows) == 96, "Incomplete C score population")
        result = {"schema": SCHEMA, "complete": True, "phase": "C", "training_path_count": 32, "own_warmstart_count": 16,
                  "records": rows, "observers": ["reward", "audit"], "training_stage_work": inventory["seal"]["work"],
                  "training_complete_sha256": inventory["complete_sha256"], "scoring_work": work.snapshot(),
                  "runtime": runtime, "assets": assets, "source_roles_opened": list(ROLES.values()), "access": access,
                  "source_freeze_sha256": file_hash(args.freeze), "registered_commit": freeze["registered_commit"],
                  "output_action": 0, "latent_actions": ["couple"], "refinement_charge": plan.refinement_charge,
                  "panel_tape": "C panel/panel-noise tape_seed(seed, role, schedule=0, offset, condition); shared across all arms",
                  "frozen_reuse": "Each architecture/seed own warmstart, scored once per role; warm-up costs counted once."}
        pending = directory / "ENDPOINTS.pending.json"
        write_json(pending, result)
        load_records(pending, file_hash(pending))
        check_budget()
        pending.rename(directory / "ENDPOINTS.json")
        return result
    except BaseException as error:
        failure = {"complete": False, "phase": "C", "error_type": type(error).__name__, "message": str(error),
                   "partial_evidence_preserved": True, "scoring_work": work.snapshot()}
        try:
            write_json(directory / "FAILED.json", failure)
        except OSError:
            print(json.dumps(failure), flush=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    for option in ("assets", "root", "reference-root", "freeze", "protocol", "source-manifest"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--execute", action="store_true")
    execute(parser.parse_args())


if __name__ == "__main__":
    main()
