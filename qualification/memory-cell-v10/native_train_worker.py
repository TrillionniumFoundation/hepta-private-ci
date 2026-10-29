"""Actual fitting child for an already exported canonical native owner cut."""

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

from cells import Cell, SEMANTIC_OUTPUTS, PROCEDURE_OUTPUTS, fit
from export_native import canonical, export, sha, valid_digest
from owner_input import load_owner
from train_inventory_router import train as train_router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-snapshot", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1741)
    args = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    source_bytes = args.owner_snapshot.read_bytes()
    source = load_owner(args.owner_snapshot)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "OWNER_INPUT.json").write_bytes(canonical(source))
    encoder_path = Path(__file__).resolve().parents[1] / "memory-cell-adapters" / "encoder.py"
    spec = importlib.util.spec_from_file_location("v10_pinned_encoder", encoder_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    encoder = module.PinnedMiniLMEncoder(args.encoder_dir)
    result = {"schema": "hepta.memory.v10.native-training.v1", "source_input_sha256": sha(source_bytes),
              "owner_cut_sha256": source["owner_cut_sha256"], "seed": args.seed, "models": {},
              "excluded_non_parameter_record_kinds": sorted({r["kind"] for r in source["records"]
                                                               if r["kind"] not in ("semantic", "procedure")}),
              "held_files_read": False}
    for offset, kind in enumerate(("semantic", "procedure")):
        rows = [row for row in source["records"] if row["kind"] == kind]
        if not 2 <= len(rows) <= 128 or len({row["key"] for row in rows}) != len(rows):
            raise ValueError("native fitting requires 2..128 unique keys per type")
        if any(not valid_digest(row["source_id"]) for row in rows):
            raise ValueError("native source ID is not canonical")
        texts = [row.get("canonical_text", f"{'Inventory policy' if kind == 'semantic' else 'Operational procedure'} record: {row['key']}.")
                 for row in rows]
        x = encoder.encode(texts)
        if kind == "semantic":
            values = [[row["value"][name] for name in ("reserve", "pack", "limit")] for row in rows]
            if any(type(v) is not int or not 0 <= v <= 15 for row in values for v in row):
                raise ValueError("invalid native policy target")
            y = np.asarray([[(v >> bit) & 1 for v in row for bit in range(4)] for row in values], dtype=np.float32)
            outputs, width = SEMANTIC_OUTPUTS, 12
        else:
            values = [row["value"]["opcodes"] for row in rows]
            if any(len(row) != 4 or any(type(v) is not int or not 0 <= v <= 6 for v in row) for row in values):
                raise ValueError("invalid native procedure target")
            y = np.concatenate([np.eye(7, dtype=np.float32)[np.asarray(values)[:, i]] for i in range(4)], axis=1)
            outputs, width = PROCEDURE_OUTPUTS, 28
        np.savez_compressed(args.output / f"{kind}-canonical.npz", features=x)
        np.save(args.output / f"{kind}-targets.npy", y, allow_pickle=False)
        model = Cell(384, width, 4, args.seed + offset)
        initialization = model.identity()
        schedule = np.random.default_rng(args.seed + offset + 10000).integers(
            len(rows), size=(protocol["budget"]["content_steps"], protocol["optimizer"]["batch_size"]), dtype=np.int64)
        np.save(args.output / f"{kind}-schedule.npy", schedule, allow_pickle=False)
        receipt = fit(model, x, y, outputs, schedule, lr=protocol["optimizer"]["learning_rate"],
                      source_ids=[r["source_id"] for r in rows], label=f"native-{kind}")
        checkpoint = model.save(args.output / f"{kind}-checkpoint", encoder_sha256=encoder.base_encoder_sha,
                                outputs=outputs, extra={"source_input_sha256": sha(source_bytes),
                                                        "owner_cut_sha256": source["owner_cut_sha256"]})
        address_rows = [{"key": row["key"], "canonical_text": text, "source_ids": [row["source_id"]]}
                        for row, text in zip(rows, texts, strict=True)]
        payload, exported = export(model.arrays, kind=kind, encoder_sha256=encoder.base_encoder_sha,
                                   owner_cut_sha256=source["owner_cut_sha256"],
                                   checkpoint_sha256=checkpoint["manifest_sha256"], training_history=model.history,
                                   source_ids=sorted(model.lineage), addresses=address_rows, features=x,
                                   source_map={row["source_id"]: row["source_id"] for row in rows})
        (args.output / f"{kind}.json").write_bytes(payload)
        (args.output / f"{kind}-export.json").write_bytes(canonical(exported))
        # A separately saved intervention preserves its own parameter/checkpoint identities.
        ablated = model.fork(seed=args.seed + offset + 20000)
        ablated.arrays["B"].fill(0)
        ablated.history = [{"schema": "hepta.memory.v10.ablation.v1", "intervention": "zero_B_keep_trained_head",
                            "parent_parameter_sha256": model.identity(), "training_performed": False}]
        ablation = ablated.save(args.output / f"{kind}-ablation-checkpoint", encoder_sha256=encoder.base_encoder_sha,
                                outputs=outputs, extra={"purpose": "causal intervention, not a trained replacement"})
        ablated_payload, ablated_receipt = export(ablated.arrays, kind=kind, encoder_sha256=encoder.base_encoder_sha,
                                                  owner_cut_sha256=source["owner_cut_sha256"],
                                                  checkpoint_sha256=ablation["manifest_sha256"], training_history=ablated.history,
                                                  source_ids=sorted(ablated.lineage), addresses=address_rows, features=x,
                                                  source_map={row["source_id"]: row["source_id"] for row in rows})
        (args.output / f"{kind}-ablation.json").write_bytes(ablated_payload)
        (args.output / f"{kind}-ablation-export.json").write_bytes(canonical(ablated_receipt))
        result["models"][kind] = {"fit": receipt, "initial_parameter_sha256": initialization,
                                    "checkpoint": checkpoint, "export": exported,
                                    "ablation_checkpoint": ablation,
                                    "adapter_B_l2": float(np.linalg.norm(model.arrays["B"])),
                                    "canonical_keys": [row["key"] for row in rows]}
    result["inventory_router"] = train_router(encoder, args.output / "inventory-router", args.seed + 5000)
    result["encoder"] = encoder.receipt()
    (args.output / "TRAINING.json").write_bytes(canonical(result))


if __name__ == "__main__":
    main()
