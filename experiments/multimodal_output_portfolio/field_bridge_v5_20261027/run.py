"""Execute one frozen V5 development census, then separately score old endpoints."""

import argparse
import json
from pathlib import Path
import re
import time
import traceback

import numpy as np

from ..field_bridge_v3_20261027.training_common import (
    Costs, file_hash, require, write_json,
)
from .calibration import decision, load_saved
from .records import Journal, complete, verify_complete


HERE = Path(__file__).parent
V3 = HERE.parent / "field_bridge_v3_20261027"
METHODS = ("ordinary_48", "field_48", "richer_48", "ordinary_8", "field_8", "richer_8")
TRAIN_ROLES = ["development_" + suffix for suffix in ("gradient", "rehearsal", "probe", "guard")]
EVALUATION_ROLES = ["development_task", "development_clean"]


def check_freeze(freeze_path):
    freeze = json.loads(Path(freeze_path).read_text())
    require(freeze["schema"] == "hepta.field-bridge.v5.source-freeze.1", "Unknown freeze")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]), "Source must be committed before execution")
    required = [str(p.relative_to(HERE.parent)) for p in HERE.glob("*.py")]
    required += [str((HERE / name).relative_to(HERE.parent)) for name in ("PROTOCOL.json", "evidence/CALIBRATION.json")]
    require(set(required) <= set(freeze["files"]), "Incomplete V5 source freeze")
    for name, expected in freeze["files"].items():
        path = (HERE.parent / name).resolve()
        require(path.is_relative_to(HERE.parent.resolve()) and file_hash(path) == expected,
                "Frozen source/input changed: " + name)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    require(protocol["methods"] == list(METHODS) and protocol["seeds"] == [17, 29, 43]
            and protocol["schedules"] == [6000, 6001, 6002, 6003]
            and not protocol["new_holdout_access"]
            and protocol["source_roles_training"] == TRAIN_ROLES
            and protocol["source_roles_evaluation"] == EVALUATION_ROLES,
            "Unregistered scientific scope")
    calibration = json.loads((HERE / "evidence/CALIBRATION.json").read_text())["seeds"]
    for seed in protocol["seeds"]:
        bank, _, _ = load_saved(V3 / "evidence", seed)
        require(protocol["baseline_actions"][str(seed)] == calibration[str(seed)]["baseline_action"]
                and protocol["label_reference_actions"][str(seed)] == bank["reference_action_index"],
                "Calibration and label policy differ from protocol")
    return protocol, freeze


def binding(args, protocol):
    return {"study_id": protocol["study_id"], "freeze_sha256": file_hash(args.freeze),
            "protocol_sha256": file_hash(HERE / "PROTOCOL.json"), "new_holdout_access": False}


def train(args, protocol, destination, accounting):
    from ..field_bridge_v3_20261027.assets import load_assets
    from ..field_bridge_v3_20261027.source_roles import load_corpus_roles
    from ..field_bridge_v3_20261027.learning import make_context, make_model, new_optimizer, save_checkpoint
    from ..field_bridge_v3_20261027.training_features import measure_state
    from ..field_bridge_v4_20261027_review.training_panel_origin import fit_origin, translate
    from .transactions import execute

    v3 = json.loads((V3 / "PROTOCOL.json").read_text())
    calibration = json.loads((HERE / "evidence/CALIBRATION.json").read_text())["seeds"][str(args.seed)]
    bank, fitted, _ = load_saved(V3 / "evidence", args.seed)
    origin = fit_origin(bank)
    baseline = protocol["baseline_actions"][str(args.seed)]
    originals, observers, assets = load_assets(args.assets, [args.seed], ["reward"])
    corpus = load_corpus_roles(Path(args.assets) / "ndu-data", TRAIN_ROLES)
    accounting["costs"] = Costs()
    context = make_context(originals[args.seed], corpus, observers, args.seed, "development", v3,
                           costs=accounting["costs"])
    write_json(destination / "ASSETS.json", assets)
    paths = []
    for method in METHODS:
        mode, grain = method.split("_")
        for schedule_id in protocol["schedules"]:
            out = destination / method / str(schedule_id)
            out.mkdir(parents=True, exist_ok=False)
            costs, cpu, wall = context.costs.snapshot(), time.process_time_ns(), time.perf_counter_ns()
            accounting["active_path"] = {"method": method, "schedule_id": schedule_id,
                                         "path": str(out.relative_to(destination)), "cost_start": costs,
                                         "cpu_start_ns": cpu, "wall_start_ns": wall}
            model = make_model(context.original, args.seed, v3)
            optimizer = new_optimizer(model, v3)
            observed_initial, decisions, transactions = None, [], []
            with Journal(out / "trace.jsonl.gz") as journal:
                for step in range(0, 288, 48):
                    if mode == "ordinary":
                        selected = {"chosen": baseline, "baseline_action": baseline, "override": False,
                                    "certificate": False, "prediction_performed": False}
                    else:
                        raw, _, feature = measure_state(context, model, optimizer, step, schedule_id)
                        if observed_initial is None:
                            observed_initial = list(raw)
                        mapped = translate(raw, observed_initial, origin)
                        selected = decision(fitted["controllers"][mode], mapped, baseline, calibration["tau"])
                        selected.update(raw=raw, mapped=mapped.tolist(), feature_receipt=feature,
                                        label_reference_action=bank["reference_action_index"])
                    journal.append({"kind": "decision", "step": step, **selected})
                    receipts = execute(context, model, optimizer, step, int(selected["chosen"]),
                                       schedule_id, int(grain), journal)
                    decisions.append({"step": step, "chosen": selected["chosen"], "override": selected["override"]})
                    transactions.extend(receipts)
            metadata = {"seed": args.seed, "study_id": protocol["study_id"], "method": method,
                        "schedule_id": schedule_id, "role_group": "development"}
            checkpoint = save_checkpoint(out / "checkpoint.pt", model, optimizer, v3, metadata)
            resources = context.costs.since(costs)
            require(resources["scheduled_gradient_microsteps"] == 288, "Incomplete physical schedule")
            record = {**metadata, "checkpoint": checkpoint, "decisions": decisions,
                "transactions": len(transactions), "accepted": sum(r["accepted"] for r in transactions),
                "accepted_nonzero": sum(r["accepted"] and r["action_index"] != 0 for r in transactions),
                "resources": resources, "cpu_ns": time.process_time_ns() - cpu,
                "wall_ns": time.perf_counter_ns() - wall, "state": checkpoint,
                "trace_head_sha256": journal.head, "trace_records": journal.count,
                "final_step": 288, "endpoint_access": False}
            write_json(out / "PATH.json", record)
            paths.append({"path": str(out.relative_to(destination)), "record_sha256": file_hash(out / "PATH.json")})
            accounting.pop("active_path")
            print(json.dumps({"phase": "train", "seed": args.seed, "method": method,
                              "schedule": schedule_id, "accepted_nonzero": record["accepted_nonzero"]}), flush=True)
    return {"seed": args.seed, "paths": paths, "resources": context.costs.snapshot(),
            "train_paths": len(paths), "endpoint_access": False}


def evaluate(args, protocol, destination, accounting):
    from ..field_bridge_v3_20261027.assets import load_assets
    from ..field_bridge_v3_20261027.source_roles import load_corpus_roles
    from ..field_bridge_v3_20261027.learning import hard_panel, panels, save_hard, load_checkpoint
    from ..field_bridge_v3_20261027.training_common import Costs
    from ..field_bridge_v3_20261027.training_stages import panel_identity

    root = Path(args.out)
    expected = binding(args, protocol)
    train_bindings = {str(seed): verify_complete(root / "train" / str(seed),
                     {**expected, "phase": "train", "seed": seed}) for seed in protocol["seeds"]}
    require(all(x["train_paths"] == 24 for x in train_bindings.values()), "All 72 training paths must be sealed")
    started = json.loads((destination / "START.json").read_text())["started_unix_ns"]
    require(started >= max(x["completed_unix_ns"] for x in train_bindings.values()), "Endpoint barrier clock violation")
    v3 = json.loads((V3 / "PROTOCOL.json").read_text())
    originals, observers, assets = load_assets(args.assets, [args.seed], ["reward", "audit"])
    roles = EVALUATION_ROLES
    corpus = load_corpus_roles(Path(args.assets) / "ndu-data", roles)
    endpoints = {"task": panels(corpus, roles[0], args.seed, v3["training"]["conditions"], v3),
                 "clean": panels(corpus, roles[1], args.seed, ["clean"], v3)}
    action, costs = v3["training"]["fixed_actions"][str(args.seed)], Costs()
    accounting["costs"] = costs
    original = {}
    identities = {name: panel_identity(panel) for name, panel in endpoints.items()}
    write_json(destination / "ASSETS.json", assets)
    for name, panel in endpoints.items():
        original[name] = hard_panel(originals[args.seed], panel, observers, action, v3, costs,
                                    "original_" + name, retain=True)
        save_hard(destination / ("original-" + name + ".npz"), original[name])
    arrays = {"task": [], "clean": []}
    for method in METHODS:
        method_values = {"task": [], "clean": []}
        for schedule_id in protocol["schedules"]:
            source = root / "train" / str(args.seed) / method / str(schedule_id) / "checkpoint.pt"
            model, _, checkpoint = load_checkpoint(source, originals[args.seed], args.seed, v3)
            require(checkpoint["metadata"]["method"] == method and
                    checkpoint["metadata"]["schedule_id"] == schedule_id and
                    checkpoint["metadata"]["study_id"] == protocol["study_id"] and
                    checkpoint["metadata"]["role_group"] == "development", "Wrong checkpoint")
            out = destination / method / str(schedule_id)
            out.mkdir(parents=True, exist_ok=False)
            for name, panel in endpoints.items():
                score = hard_panel(model, panel, observers, action, v3, costs, "endpoint_" + name, retain=True)
                require(score["source_ids"] == original[name]["source_ids"] and
                        score["conditions"] == original[name]["conditions"], "Unpaired endpoint")
                save_hard(out / (name + ".npz"), score)
                method_values[name].append(np.stack([score["values"][o] for o in ("reward", "audit")]))
            print(json.dumps({"phase": "evaluate", "seed": args.seed, "method": method,
                              "schedule": schedule_id}), flush=True)
        for name in arrays:
            arrays[name].append(np.stack(method_values[name]))
    require(identities == {name: panel_identity(panel) for name, panel in endpoints.items()}, "Panel mutation")
    with (destination / "ENDPOINTS.npz").open("xb") as stream:
        np.savez_compressed(stream, methods=np.asarray(METHODS), schedules=np.asarray(protocol["schedules"]),
            observers=np.asarray(["reward", "audit"]), task=np.stack(arrays["task"]), clean=np.stack(arrays["clean"]),
            frozen_task=np.stack([original["task"]["values"][o] for o in ("reward", "audit")]),
            frozen_clean=np.stack([original["clean"]["values"][o] for o in ("reward", "audit")]))
    write_json(destination / "PANELS.json", identities)
    return {"seed": args.seed, "resources": costs.snapshot(), "new_holdout_access": False,
            "training_seals": {str(seed): file_hash(root / "train" / str(seed) / "COMPLETE.json")
                               for seed in protocol["seeds"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "evaluate"))
    parser.add_argument("--seed", type=int, required=True, choices=(17, 29, 43))
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze", required=True)
    args = parser.parse_args()
    protocol, freeze = check_freeze(args.freeze)
    import torch
    require(torch.__version__ == "2.8.0+cpu" and np.__version__ == "2.3.5", "Pinned runtime mismatch")
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    destination = Path(args.out) / args.phase / str(args.seed)
    destination.mkdir(parents=True, exist_ok=False)
    write_json(destination / "START.json", {"phase": args.phase, "seed": args.seed, **binding(args, protocol),
        "registered_commit": freeze["registered_commit"],
        "torch": torch.__version__, "numpy": np.__version__, "started_unix_ns": time.time_ns()})
    accounting, cpu, wall = {}, time.process_time_ns(), time.perf_counter_ns()
    try:
        receipt = (train if args.phase == "train" else evaluate)(args, protocol, destination, accounting)
        check_freeze(args.freeze)
        complete(destination, {**receipt, "cpu_ns": time.process_time_ns() - cpu,
                               "wall_ns": time.perf_counter_ns() - wall})
    except BaseException as error:
        resources = accounting["costs"].snapshot() if "costs" in accounting else {}
        active = accounting.get("active_path")
        if active is not None:
            write_json(destination / active["path"] / "PATH_FAILED.json", {
                **active, "error_type": type(error).__name__,
                "resources": accounting["costs"].since(active["cost_start"]),
                "cpu_ns": time.process_time_ns() - active["cpu_start_ns"],
                "wall_ns": time.perf_counter_ns() - active["wall_start_ns"]})
        write_json(destination / "FAILED.json", {"error_type": type(error).__name__, "error": str(error),
            "traceback": traceback.format_exc(), "preserve_partial_outputs": True,
            "resources": resources, "cpu_ns": time.process_time_ns() - cpu,
            "wall_ns": time.perf_counter_ns() - wall})
        raise


if __name__ == "__main__":
    main()
