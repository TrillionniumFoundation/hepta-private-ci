"""One fitting process for a frozen capacity/seed; never imports held wording."""

import argparse
import json
from pathlib import Path

import numpy as np

from cells import Cell, JointCell, TypedPair, SEMANTIC_OUTPUTS, PROCEDURE_OUTPUTS, JOINT_OUTPUTS, fit
from corpus import pairs, targets
from export_native import canonical, sha
from maintenance_fit import train_maintenance
from routing import CLASSES, expected_route, calibrate, learned_routes, nearest_routes
from structure_fit import train_structure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--capacity", type=int, required=True)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    allowed = args.seed == 90401 if args.development else args.seed in protocol["seeds"]
    if not allowed or args.capacity not in protocol["capacities"]:
        raise ValueError("fit is outside the frozen seed/capacity grid")
    population = json.loads((args.data / "sources.json").read_text())
    if bool(population.get("development_fixture")) != args.development:
        raise ValueError("development fixture and formal execution must be separate")
    encoder_sha = json.loads((args.data.parent / "TRAIN_ENCODER.json").read_text())["base_encoder_sha"]
    with np.load(args.data / "canonical.npz", allow_pickle=False) as archive:
        features = {kind: archive[kind] for kind in ("semantic", "procedure")}
    rows = {kind: [row for row in population["records"] if row["kind"] == kind] for kind in features}
    labels = {kind: targets([row["value"] for row in rows[kind]], kind) for kind in rows}
    outputs = {"semantic": SEMANTIC_OUTPUTS, "procedure": PROCEDURE_OUTPUTS}
    result = {"schema": "hepta.memory.v10.fit-suite.v1", "seed": args.seed, "capacity": args.capacity,
              "data_sha256": sha((args.data / "sources.json").read_bytes()), "models": {}, "held_files_read": False}
    models = {}
    for offset, kind in enumerate(("semantic", "procedure")):
        width, seed = labels[kind].shape[1], args.seed + offset
        schedule = np.random.default_rng(seed + 70000).integers(args.capacity, size=(protocol["budget"]["content_steps"], 32), dtype=np.int64)
        np.save(args.output / f"content-{kind}-schedule.npy", schedule, allow_pickle=False)
        for arm, rank in (("linear", 0), ("residual", 4), ("untrained", 4)):
            model = Cell(384, width, rank, seed)
            receipt = None if arm == "untrained" else fit(model, features[kind], labels[kind], outputs[kind], schedule,
                                                         lr=0.01, source_ids=[row["source_id"] for row in rows[kind]],
                                                         label=f"content-{kind}-{arm}")
            saved = model.save(args.output / f"content-{kind}-{arm}", encoder_sha256=encoder_sha, outputs=outputs[kind])
            result["models"][f"content-{kind}-{arm}"] = {"fit": receipt, "checkpoint": saved}
            models[(kind, arm)] = model
    pair_indices = pairs(args.capacity, "train")
    pair_x = np.asarray([np.concatenate((features["semantic"][i], features["procedure"][j])) for i, j in pair_indices])
    pair_y = np.asarray([np.concatenate((labels["semantic"][i], labels["procedure"][j])) for i, j in pair_indices])
    pair_ids = [[rows["semantic"][i]["source_id"], rows["procedure"][j]["source_id"]] for i, j in pair_indices]
    semantic, procedure = Cell(384, 12, 4, args.seed + 100), Cell(384, 28, 4, args.seed + 101)
    typed = TypedPair(semantic, procedure)
    joint = JointCell(semantic, procedure, args.seed + 102)
    dense = Cell(768, 40, 4, args.seed + 103)
    dense.arrays["head.weight"].fill(0)
    dense.arrays["head.weight"][:12, :384] = semantic.arrays["head.weight"]
    dense.arrays["head.weight"][12:, 384:] = procedure.arrays["head.weight"]
    dense.arrays["head.bias"][:] = np.concatenate((semantic.arrays["head.bias"], procedure.arrays["head.bias"]))
    schedule = np.random.default_rng(args.seed + 72000).integers(len(pair_x), size=(protocol["budget"]["composition_steps"], 32), dtype=np.int64)
    np.save(args.output / "composition-schedule.npy", schedule, allow_pickle=False)
    np.savez_compressed(args.output / "composition-training.npz", features=pair_x, targets=pair_y, pairs=np.asarray(pair_indices))
    for name, model in (("typed", typed), ("joint", joint), ("dense_joint", dense)):
        receipt = fit(model, pair_x, pair_y, JOINT_OUTPUTS, schedule, lr=0.01, source_ids=pair_ids, label="composition-" + name)
        cells = model.cells if isinstance(model, TypedPair) else [model]
        saved = [cell.save(args.output / f"composition-{name}-{i}", encoder_sha256=encoder_sha,
                           outputs=(SEMANTIC_OUTPUTS if i == 0 else PROCEDURE_OUTPUTS) if name == "typed" else JOINT_OUTPUTS)
                 for i, cell in enumerate(cells)]
        result["models"]["composition-" + name] = {"fit": receipt, "checkpoints": saved}
    train_queries = json.loads((args.data / "train-queries.json").read_text())
    cal_queries = json.loads((args.data / "calibration-queries.json").read_text())
    with np.load(args.data / "train-features.npz", allow_pickle=False) as archive:
        train_x = archive["features"]
    with np.load(args.data / "calibration-features.npz", allow_pickle=False) as archive:
        cal_x = archive["features"]
    expected_train, expected_cal = [expected_route(row) for row in train_queries], [expected_route(row) for row in cal_queries]
    router_y = np.concatenate((np.eye(4)[[CLASSES.index(row["operation"]) for row in expected_train]],
                               *[np.eye(args.capacity + 1)[[row[name] if row[name] is not None else args.capacity for row in expected_train]]
                                 for name in ("entity", "workflow")]), axis=1).astype(np.float32)
    router = Cell(384, router_y.shape[1], 4, args.seed + 200)
    router_outputs = (("multiclass", 4), ("multiclass", args.capacity + 1), ("multiclass", args.capacity + 1))
    schedule = np.random.default_rng(args.seed + 74000).integers(len(train_x), size=(protocol["budget"]["router_steps"], 32), dtype=np.int64)
    np.save(args.output / "router-schedule.npy", schedule, allow_pickle=False)
    receipt = fit(router, train_x, router_y, router_outputs, schedule, lr=0.01,
                  source_ids=[sha(canonical(row)) for row in train_queries], label="address-router")
    saved = router.save(args.output / "router", encoder_sha256=encoder_sha, outputs=router_outputs,
                        extra={"predicts_operation_and_registry_addresses_only": True})
    learned = calibrate(learned_routes(router.forward(cal_x), args.capacity), expected_cal)
    nearest = calibrate(nearest_routes(cal_x, train_x, train_queries), expected_cal)
    result["routing"] = {"fit": receipt, "checkpoint": saved, "learned_selection": learned, "nearest_selection": nearest}
    result["structure"] = train_structure(models[("semantic", "residual")], features["semantic"], rows["semantic"],
                                            protocol, args.seed, args.output / "structure", encoder_sha)
    if args.capacity == protocol["budget"]["maintenance_capacity"]:
        result["maintenance"] = train_maintenance(models[("semantic", "residual")], features["semantic"], rows["semantic"],
                                                    protocol, args.seed, args.output / "maintenance", encoder_sha)
    (args.output / "FIT.json").write_bytes(canonical(result))
    print(json.dumps({"seed": args.seed, "capacity": args.capacity, "held_files_read": False}))


if __name__ == "__main__":
    main()
