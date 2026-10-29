"""Read original Torch weights and bind an explicit verified source migration."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

from export_native import canonical, export, load_original_checkpoint, sha
from owner_input import load_owner
from reference import decode, scalar_forward


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-snapshot", type=Path, required=True)
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    old_code = Path(__file__).resolve().parents[1] / "memory-cell-adapters"
    sys.path.insert(0, str(old_code))
    from encoder import PinnedMiniLMEncoder
    from tensor_cell import TensorCell
    import torch

    torch.set_num_threads(1)
    owner = load_owner(args.owner_snapshot)
    sources_raw = (args.legacy_root / "sources.json").read_bytes()
    sources = json.loads(sources_raw)
    owner_rows = {(row["kind"], row["key"]): row for row in owner["records"]}
    encoder = PinnedMiniLMEncoder(args.encoder_dir)
    result = {"schema": "hepta.memory.v10.legacy-torch-bridge.v1", "models": {},
              "source_input_sha256": owner["source_input_sha256"], "old_sources_sha256": sha(sources_raw),
              "old_code_sha256": {name: sha((old_code / name).read_bytes()) for name in ("encoder.py", "tensor_cell.py")},
              "torch_version": torch.__version__, "training_performed": False, "held_files_read": False}
    with np.load(args.legacy_root / "canonical.npz", allow_pickle=False) as original_features:
        for old_kind, kind in (("semantic", "semantic"), ("skill", "procedure")):
            rows = sorted((row for row in sources if row["kind"] == old_kind), key=lambda row: row["index"])
            if len(rows) != 8 or [row["index"] for row in rows] != list(range(8)):
                raise ValueError("original canonical population changed")
            x = original_features[old_kind].astype("<f4")
            if x.shape != (8, 384):
                raise ValueError("original feature population changed")
            addresses, mapping, migrations, targets = [], {}, [], []
            for row in rows:
                key = f"inventory:{kind}:{row['index']}"
                current = owner_rows[(kind, key)]
                expected = dict(zip(("reserve", "pack", "limit"), row["value"], strict=True)) if kind == "semantic" else {"opcodes": row["value"]}
                if current["value"] != expected:
                    raise ValueError("canonical owner value does not match the original authored source")
                text = f"{'Inventory policy' if kind == 'semantic' else 'Operational procedure'} record: {row['name']}."
                addresses.append({"key": key, "canonical_text": text, "source_ids": [row["source_id"]]})
                mapping[row["source_id"]] = current["source_id"]
                migrations.append({"old_index": row["index"], "old_name": row["name"], "old_kind": old_kind,
                                   "old_source_id": row["source_id"], "canonical_key": key,
                                   "canonical_owner_source_id": current["source_id"],
                                   "owner_memory_id": current.get("owner_memory_id"), "revision": current.get("revision"),
                                   "value_sha256": sha(canonical(expected)), "canonical_text": text})
                targets.append(row["value"])
            checkpoint_dir = args.legacy_root / "models" / "seed-731" / old_kind
            arrays, manifest, checkpoint_sha = load_original_checkpoint(checkpoint_dir)
            old = TensorCell.load(checkpoint_dir, expected_encoder_sha=encoder.base_encoder_sha)
            if old.parameter_digest() != manifest["parameter_sha256"]:
                raise ValueError("original TensorCell identity differs from decoded NPZ")
            if any(not np.array_equal(old._arrays()[name], value) for name, value in arrays.items()):
                raise ValueError("original TensorCell float32 bits changed")
            raw_torch = old.raw_outputs(x)
            raw_native = scalar_forward(arrays, x)
            regenerated = encoder.encode([row["canonical_text"] for row in addresses])
            typed_torch, typed_native = decode(raw_torch, kind), decode(raw_native, kind)
            payload, exported = export(arrays, kind=kind, encoder_sha256=manifest["base_encoder_sha"],
                                       owner_cut_sha256=owner["owner_cut_sha256"], checkpoint_sha256=checkpoint_sha,
                                       training_history=manifest["training_history"], source_ids=manifest["source_ids"],
                                       addresses=addresses, features=x, source_map=mapping)
            (args.output / f"{kind}.json").write_bytes(payload)
            (args.output / f"{kind}-export.json").write_bytes(canonical(exported))
            np.savez_compressed(args.output / f"{kind}-canonical.npz", features=x)
            result["models"][kind] = {
                "old_checkpoint_sha256": checkpoint_sha, "parameter_sha256": old.parameter_digest(),
                "migrations": migrations, "export": exported,
                "original_checkpoint_source_ids": manifest["source_ids"],
                "canonical_rows": [{"address_sha256": sha(a["key"].encode()), "raw_logits": raw.tolist(), **typed}
                                   for a, raw, typed in zip(addresses, raw_torch, typed_torch, strict=True)],
                "torch_vs_scalar_max_absolute_error": float(np.max(np.abs(raw_torch - raw_native))),
                "torch_vs_scalar_within_tolerance": bool(np.allclose(raw_torch, raw_native, atol=1e-4, rtol=1e-5)),
                "torch_vs_scalar_typed_equal": [row["value"] for row in typed_torch] == [row["value"] for row in typed_native],
                "canonical_target_exact": sum(row["value"] == expected for row, expected in zip(typed_native, targets, strict=True)),
                "regenerated_features_bitwise_equal": bool(np.array_equal(regenerated, x)),
                "regenerated_features_max_absolute_error": float(np.max(np.abs(regenerated - x))),
                "export_cache_uses_original_bytes": True,
                "original_training_history": manifest["training_history"]}
    result["encoder"] = encoder.receipt()
    (args.output / "LEGACY_TORCH.json").write_bytes(canonical(result))
    (args.output / "OWNER_INPUT.json").write_bytes(canonical(owner))


if __name__ == "__main__":
    main()
