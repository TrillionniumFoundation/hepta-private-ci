"""Frozen-grid train/dev comparison of raw-preserving native/history features."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_20261027.controls import choose, history_features
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from .analyze_native_representation import native, heads, rank_report

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE / "HYBRID_CONTROL_PROTOCOL.json"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def matrix_sha(matrix):
    return hashlib.sha256(np.asarray(matrix, dtype="<f8").tobytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def source_hashes():
    paths = [Path(__file__), PROTOCOL_PATH, HERE / "analyze_native_representation.py",
             HERE.parent / "field_bridge_v2_20261027" / "native_fast.py",
             HERE.parent / "field_bridge_20261027" / "controls.py",
             HERE.parent / "field_bridge_20261027" / "native_bridge.py"]
    return {str(path.relative_to(HERE.parent)): sha(path) for path in paths}


def native_residual(train_raw, dev_raw, train_native, dev_native):
    """Select coordinates using only training features, never outcome labels."""
    variance = np.var(train_native, axis=0, ddof=0)
    selected = np.lexsort((np.arange(40), -variance))[:24]
    train = np.column_stack((train_raw, train_native[:, selected]))
    dev = np.column_stack((dev_raw, dev_native[:, selected]))
    metadata = {"training_native_variance": variance.tolist(), "native_coordinate_indices": selected.tolist(),
                "selector_scope": "training_features_only; no labels or development statistics"}
    return train, dev, metadata


def fourier_residual(train_raw, dev_raw, train_transformed, dev_transformed, weights):
    mean = train_transformed.mean(0)
    scale = np.maximum(train_transformed.std(0, ddof=0), 1e-6)
    outputs = []
    for raw, transformed in ((train_raw, train_transformed), (dev_raw, dev_transformed)):
        projection = ((transformed - mean) / scale) @ weights
        extras = np.column_stack((np.cos(projection), np.sin(projection))) / np.sqrt(12)
        outputs.append(np.column_stack((raw, extras)))
    return *outputs, {"mean": mean.tolist(), "scale": scale.tolist(), "fit_scope": "training_features_only",
                       "weight_sha256": matrix_sha(weights)}


def best(candidates):
    return max(candidates, key=lambda candidate: (candidate["dev_value"], -candidate["candidate_index"]))


def brief(candidate, baseline):
    return {key: candidate[key] for key in ("candidate_index", "family", "transform", "alpha", "train_value",
        "dev_value", "dev_oracle_regret", "development_by_condition")} | {
        "dev_minus_strong_fixed": candidate["dev_value"] - baseline["development"]["best_fixed_on_this_split"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--registered-commit", required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError("Refusing to overwrite a hybrid control run")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    sources = source_hashes()
    args.out.mkdir(parents=True)
    write(args.out / "SOURCE_FREEZE.json", {"source_files": sources, "registered_commit": args.registered_commit,
          "protocol_sha256": sha(PROTOCOL_PATH), "created_monotonic_ns": time.monotonic_ns(),
          "stage": "before opening numeric banks or fitting any head"})
    bridge = NativeFastBridge(args.ffi, protocol["native_library_sha256"])
    weights = np.random.default_rng(protocol["fourier_features"]["seed"]).normal(size=(16, 12)) / np.sqrt(16)
    write(args.out / "FOURIER_WEIGHTS.json", {"weights": weights.tolist(), "sha256": matrix_sha(weights)})
    results, all_heads, started = {}, 0, time.perf_counter_ns()
    for seed in protocol["seeds"]:
        name = f"{seed}-frozen-banks.npz"
        path = args.inputs / name
        if sha(path) != protocol["allowed_banks"][name]:
            raise ValueError("Input bank identity differs from registration")
        with np.load(path, allow_pickle=False) as source:
            if set(source.files) != set(protocol["allowed_keys"]):
                raise ValueError("Unexpected bank keys")
            bank = {key: source[key].copy() for key in source.files}
        for key, matrix in bank.items():
            if list(matrix.shape) != protocol["expected_shapes"][key] or not np.isfinite(matrix).all():
                raise ValueError("Invalid bank dimensions or nonfinite values")
        train_raw = np.column_stack((bank["train_x0"], bank["train_x1"]))
        dev_raw = np.column_stack((bank["dev_x0"], bank["dev_x1"]))
        train_joint = np.concatenate((bank["train_x0"], bank["train_x1"]))
        mean, scale = train_joint.mean(0), np.maximum(train_joint.std(0), 1e-6)
        train_returns, dev_returns = bank["train_returns"], bank["dev_returns"]
        fixed = int(train_returns.mean(0).argmax())
        baseline = {"training_best_fixed_action": fixed,
                    "development_best_fixed_action": int(dev_returns.mean(0).argmax())}
        for split, returns in (("train", train_returns), ("development", dev_returns)):
            baseline[split] = {"stop": float(returns[:, 0].mean()),
                "training_selected_fixed": float(returns[:, fixed].mean()),
                "best_fixed_on_this_split": float(returns.mean(0).max()),
                "row_oracle": float(returns.max(1).mean()), "all_fixed_values": returns.mean(0).tolist()}
        candidates, transformations, matrices_to_save = [], [], {}
        for transform_index, transform in enumerate(protocol["common_transform"]["grid_order"]):
            transformed = {}
            for split in ("train", "dev"):
                for event in ("x0", "x1"):
                    raw = bank[f"{split}_{event}"]
                    transformed[f"{split}_{event}"] = raw.copy() if transform["k"] is None else (
                        np.clip((raw - mean) / (scale * transform["k"]), -1, 1) + 1) / 2
            feature_started = time.perf_counter_ns()
            train_native, train_activity = native(bridge, transformed["train_x0"], transformed["train_x1"],
                                                   f"hybrid-{seed}-{transform_index}-train")
            dev_native, dev_activity = native(bridge, transformed["dev_x0"], transformed["dev_x1"],
                                               f"hybrid-{seed}-{transform_index}-dev")
            shared_native_ns = time.perf_counter_ns() - feature_started
            hybrid_started = time.perf_counter_ns()
            hybrid_train, hybrid_dev, hybrid_meta = native_residual(train_raw, dev_raw, train_native, dev_native)
            hybrid_ns = time.perf_counter_ns() - hybrid_started
            history_started = time.perf_counter_ns()
            history_train = history_features(transformed["train_x0"], transformed["train_x1"])
            history_dev = history_features(transformed["dev_x0"], transformed["dev_x1"])
            history_ns = time.perf_counter_ns() - history_started
            rff_started = time.perf_counter_ns()
            rff_train, rff_dev, rff_meta = fourier_residual(train_raw, dev_raw,
                np.column_stack((transformed["train_x0"], transformed["train_x1"])),
                np.column_stack((transformed["dev_x0"], transformed["dev_x1"])), weights)
            rff_ns = time.perf_counter_ns() - rff_started
            pairs = {"pure_native40": (train_native, dev_native), "raw16_native24": (hybrid_train, hybrid_dev),
                     "original_history40": (history_train, history_dev), "raw16_rff24": (rff_train, rff_dev)}
            for family in ("raw16_native24", "raw16_rff24"):
                assert np.array_equal(pairs[family][0][:, :16], train_raw)
                assert np.array_equal(pairs[family][1][:, :16], dev_raw)
            metadata = {"transform": transform, "common_normalizer": {"mean": mean.tolist(), "scale": scale.tolist()},
                        "native_selector": hybrid_meta, "fourier_normalizer": rff_meta,
                        "timing": {"shared_native_extraction_ns": shared_native_ns, "native_hybrid_extra_ns": hybrid_ns,
                                   "original_history_ns": history_ns, "fourier_history_ns": rff_ns},
                        "native_activity": {"train": train_activity, "development": dev_activity}, "families": {}}
            for representation, definition in protocol["representations"].items():
                for family_index, family in enumerate(definition["family_order"]):
                    train_x, dev_x = pairs[family]
                    assert train_x.shape == (768, 40) and dev_x.shape == (384, 40)
                    fit_started = time.perf_counter_ns()
                    fitted = heads(train_x, train_returns, dev_x, dev_returns, protocol["conditions"])
                    elapsed = time.perf_counter_ns() - fit_started
                    for alpha_index, candidate in enumerate(fitted):
                        train_actions, dev_actions = choose(candidate["model"], train_x), choose(candidate["model"], dev_x)
                        candidate.update(representation=representation, family=family, transform=transform["name"],
                            candidate_index=family_index * 12 + transform_index * 3 + alpha_index,
                            train_action_indices=train_actions.tolist(), dev_action_indices=dev_actions.tolist())
                        assert np.asarray(candidate["model"]["coefficient"]).shape == (41, 5)
                        candidates.append(candidate)
                        all_heads += 1
                    metadata["families"][family] = {"train_feature_sha256": matrix_sha(train_x),
                        "dev_feature_sha256": matrix_sha(dev_x), "three_head_fit_wall_ns": elapsed,
                        "train_rank": rank_report(train_x, train_x), "dev_rank": rank_report(train_x, dev_x)}
                    matrices_to_save[f"{transform_index}.{family}.train"] = train_x
                    matrices_to_save[f"{transform_index}.{family}.dev"] = dev_x
            transformations.append(metadata)
        selected, family_selected = {}, {}
        for representation, definition in protocol["representations"].items():
            group = [candidate for candidate in candidates if candidate["representation"] == representation]
            assert len(group) == 24 and {x["candidate_index"] for x in group} == set(range(24))
            selected[representation] = brief(best(group), baseline)
            for family in definition["family_order"]:
                family_selected[family] = brief(best([x for x in group if x["family"] == family]), baseline)
        candidates.sort(key=lambda x: (x["representation"], x["candidate_index"]))
        feature_path = args.out / f"{seed}-features.npz"
        np.savez_compressed(feature_path, **matrices_to_save)
        record_path = args.out / f"{seed}-HEADS.json"
        record = {"seed": seed, "input_sha256": sha(path), "baselines": baseline, "candidates": candidates,
                  "selected": selected, "family_selected": family_selected, "transformations": transformations,
                  "features_file": feature_path.name, "features_sha256": sha(feature_path),
                  "raw_residual_exact": True, "head_count": len(candidates)}
        write(record_path, record)
        results[str(seed)] = {"input_sha256": sha(path), "baselines": baseline, "selected": selected,
            "family_selected": family_selected, "native_minus_history_development": selected["native"]["dev_value"] - selected["history"]["dev_value"],
            "heads_file": record_path.name, "heads_sha256": sha(record_path),
            "features_file": feature_path.name, "features_sha256": sha(feature_path)}
        print(json.dumps({"seed": seed, "selected": selected, "family_selected": family_selected}), flush=True)
    assert all_heads == protocol["head"]["total_heads"]
    if source_hashes() != sources:
        raise RuntimeError("Analysis source changed during fitting")
    report = {"schema": "hepta.field-bridge.v2.hybrid-control-development-result.1", "results": results,
        "heads_fitted": all_heads, "native_requests": bridge.request_count, "native_tick_calls": 2 * bridge.request_count,
        "wall_ns": time.perf_counter_ns() - started, "protocol_sha256": sha(PROTOCOL_PATH), "source_files": sources,
        "registered_commit": args.registered_commit, "library_sha256": bridge.binary_sha256,
        "fourier_weights_file": "FOURIER_WEIGHTS.json", "fourier_weight_sha256": matrix_sha(weights),
        "development_only": True, "test_retention_accessed": False, "new_model_outputs_generated": False,
        "formal_efficacy_claim": False, "no_development_refit": True,
        "pooled_native_minus_history_development": float(np.mean([x["native_minus_history_development"] for x in results.values()]))}
    write(args.out / "HYBRID_CONTROL_RESULT.json", report)
    print(json.dumps({key: report[key] for key in ("heads_fitted", "native_tick_calls", "pooled_native_minus_history_development")}))


if __name__ == "__main__":
    main()
