"""Optional exact frozen-bundle replay. No downloads, training, or media export."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import time
from oracle import summarize


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def features(np, current, observed, mask):
    if current.ndim == 1:
        padded = np.pad(current, 2, mode="edge")
        neighbors = [padded[1:-3], padded[3:-1], padded[:-4], padded[4:]]
    else:
        padded = np.pad(current, ((0, 0), (1, 1), (1, 1)), mode="edge")
        neighbors = [padded[:, :-2, 1:-1], padded[:, 2:, 1:-1],
                     padded[:, 1:-1, :-2], padded[:, 1:-1, 2:]]
    return np.stack([current, observed, mask, *neighbors], axis=-1).reshape(-1, 7)


def replay(bundle):
    import numpy as np  # Only private replay needs NumPy; data-free tests do not.
    lock = json.loads(Path(__file__).with_name("SOURCE_LOCK.json").read_text())
    for relative, expected in lock["private_files"].items():
        if digest(bundle / relative) != expected:
            raise ValueError("frozen private dependency hash mismatch")
    entry = json.loads((bundle / "evidence/refinement-entry.json").read_text())
    decode = json.loads((bundle / "evidence/decode-validation.json").read_text())
    protocol = json.loads((bundle / "refinement-protocol.json").read_text())
    records = decode["records"]
    if len(records) != 8 or any(record["split"] != "train" for record in records):
        raise ValueError("original eight TRAIN records required")
    rng = np.random.default_rng(protocol["corruption_seed"])
    weights = np.load(bundle / "private-generated/trained_refiners.npz", allow_pickle=False)
    rows, checked_losses, checked_arrays = [], 0, 0
    for index, record in enumerate(records):
        opaque_id = record["opaque_id"]
        if re.fullmatch(r"[0-9a-f]{20}", opaque_id) is None:
            raise ValueError("invalid opaque identifier")
        source = bundle / "decoded" / (opaque_id + ".npz")
        final = bundle / "private-generated" / (opaque_id + "-reconstruction.npz")
        if digest(source) != record["tensor_archive_sha256"]:
            raise ValueError("decoded array hash mismatch")
        final_hash = next(a["sha256"] for a in entry["artifacts"]
                          if a["path"] == str(final.relative_to(bundle)))
        if digest(final) != final_hash:
            raise ValueError("original reconstructed array hash mismatch")
        row = {}
        with np.load(source, allow_pickle=False) as arrays, np.load(final, allow_pickle=False) as original:
            for modality in ("audio", "video"):
                clean = arrays[modality].astype(np.float64)
                if modality == "video":
                    clean /= 255
                mask = (rng.random(clean.shape) >= protocol["dropout_probability"]).astype(np.float64)
                observed = (clean + rng.normal(0, protocol["noise_standard_deviation"], clean.shape)) * mask
                observed = np.clip(observed, -1 if modality == "audio" else 0, 1)
                current = observed.copy()
                losses = [float(np.mean((current - clean)**2))]
                for step in range(1, 4):
                    prefix = modality + "_round_" + str(step) + "_"
                    model = {key: weights[prefix + key] for key in ("w1", "b1", "w2", "b2")}
                    matrix = features(np, current, observed, mask)
                    hidden = np.tanh(matrix @ model["w1"] + model["b1"])
                    residual = (hidden @ model["w2"] + model["b2"])[:, 0]
                    current = np.clip(current + residual.reshape(current.shape),
                                      -1 if modality == "audio" else 0, 1)
                    losses.append(float(np.mean((current - clean)**2)))
                for step, value in enumerate(losses):
                    expected = next(h["per_training_clip_mse"][index] for h in entry["history"]
                                    if h["modality"] == modality and h["round"] == step)
                    if abs(value - expected) > 1e-15:
                        raise ValueError("original stage-loss parity failed")
                    checked_losses += 1
                if current.astype(np.float32).tobytes() != original[modality].tobytes():
                    raise ValueError("original final-array parity failed")
                checked_arrays += 1
                row[modality + "_mse"] = losses
                row[modality + "_scalars"] = int(clean.size)
        rows.append(row)
    weights.close()
    result = summarize(rows)
    result.update(stage_loss_parities=checked_losses, byte_exact_final_array_parities=checked_arrays,
                  actor_groups=len({r["actor_group"] for r in records}), independent_training_seeds=1,
                  new_training=False, heldout_read=False, source_lock_sha256=digest(Path(__file__).with_name("SOURCE_LOCK.json")))
    # Aggregate-only output: no identities, per-clip losses, arrays, or weights.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True, help="privately obtained original frozen pilot bundle")
    args = parser.parse_args()
    start = time.perf_counter()
    result = replay(args.bundle.resolve())
    result["local_replay_wall_seconds"] = time.perf_counter() - start
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
