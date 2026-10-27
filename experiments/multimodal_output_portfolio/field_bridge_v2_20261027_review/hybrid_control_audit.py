"""Recompute the recorded hybrid development comparison without its fit helpers."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def matrix_sha(matrix):
    return hashlib.sha256(np.asarray(matrix, dtype="<f8").tobytes()).hexdigest()


def near(first, second, tolerance=1e-12):
    assert np.max(np.abs(np.asarray(first) - np.asarray(second))) <= tolerance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result_path = args.run / "HYBRID_CONTROL_RESULT.json"
    result = json.loads(result_path.read_text())
    base = Path(__file__).resolve().parent.parent
    for relative, expected in result["source_files"].items():
        assert sha(base / relative) == expected
    freeze = json.loads((args.run / "SOURCE_FREEZE.json").read_text())
    assert freeze["source_files"] == result["source_files"]
    protocol = json.loads((Path(__file__).parent / "HYBRID_CONTROL_PROTOCOL.json").read_text())
    assert result["protocol_sha256"] == sha(Path(__file__).parent / "HYBRID_CONTROL_PROTOCOL.json")
    weights_record = json.loads((args.run / "FOURIER_WEIGHTS.json").read_text())
    weights = np.random.default_rng(271029).normal(size=(16, 12)) / 4
    assert np.array_equal(weights, weights_record["weights"])
    assert matrix_sha(weights) == result["fourier_weight_sha256"] == weights_record["sha256"]
    previous = json.loads((args.inputs / "NATIVE_REPRESENTATION_RESULT.json").read_text())
    heads_checked, native_matrices_matched, maximum_coefficient_difference = 0, 0, 0.
    independent_choice_disagreements, maximum_prediction_difference = 0, 0.
    comparisons = {}
    for seed in protocol["seeds"]:
        summary = result["results"][str(seed)]
        head_path, feature_path = args.run / summary["heads_file"], args.run / summary["features_file"]
        assert sha(head_path) == summary["heads_sha256"] and sha(feature_path) == summary["features_sha256"]
        record = json.loads(head_path.read_text())
        input_path = args.inputs / f"{seed}-frozen-banks.npz"
        assert sha(input_path) == summary["input_sha256"] == protocol["allowed_banks"][input_path.name]
        with np.load(input_path, allow_pickle=False) as data:
            bank = {key: data[key] for key in data.files}
        with np.load(feature_path, allow_pickle=False) as data:
            features = {key: data[key] for key in data.files}
        raw = {split: np.column_stack((bank[f"{split}_x0"], bank[f"{split}_x1"])) for split in ("train", "dev")}
        joint = np.concatenate((bank["train_x0"], bank["train_x1"]))
        common_mean, common_scale = joint.mean(0), np.maximum(joint.std(0), 1e-6)
        for index, specification in enumerate(protocol["common_transform"]["grid_order"]):
            transformed = {}
            for split in ("train", "dev"):
                for event in ("x0", "x1"):
                    observed = bank[f"{split}_{event}"]
                    transformed[f"{split}_{event}"] = observed if specification["k"] is None else (
                        np.clip((observed - common_mean) / (common_scale * specification["k"]), -1, 1) + 1) / 2
            native_train = features[f"{index}.pure_native40.train"]
            variance = native_train.var(0)
            indices = sorted(range(40), key=lambda column: (-variance[column], column))[:24]
            assert indices == record["transformations"][index]["native_selector"]["native_coordinate_indices"]
            rff_train = np.column_stack((transformed["train_x0"], transformed["train_x1"]))
            mean, scale = rff_train.mean(0), np.maximum(rff_train.std(0), 1e-6)
            for split in ("train", "dev"):
                u, v = transformed[f"{split}_x0"], transformed[f"{split}_x1"]
                native = features[f"{index}.pure_native40.{split}"]
                prior = previous["results"][str(seed)]["transforms"][index]["representations"]["native"]
                assert matrix_sha(native) == prior[f"{split}_feature_sha256"]
                native_matrices_matched += 1
                expected = np.column_stack((raw[split], native[:, indices]))
                assert np.array_equal(expected, features[f"{index}.raw16_native24.{split}"])
                # The existing V1 history implementation first promotes public
                # observations to float64; preserve that declared arithmetic.
                u64, v64 = u.astype(np.float64), v.astype(np.float64)
                expected = np.column_stack((u64, v64, u64 * u64, v64 * v64, v64 - u64))
                assert np.array_equal(expected, features[f"{index}.original_history40.{split}"])
                projected = ((np.column_stack((u, v)) - mean) / scale) @ weights
                expected = np.column_stack((raw[split], np.column_stack((np.cos(projected), np.sin(projected))) / np.sqrt(12)))
                assert np.array_equal(expected, features[f"{index}.raw16_rff24.{split}"])
        assert len(record["candidates"]) == 48
        for candidate in record["candidates"]:
            index = next(i for i, transform in enumerate(protocol["common_transform"]["grid_order"])
                         if transform["name"] == candidate["transform"])
            train = features[f"{index}.{candidate['family']}.train"]
            dev = features[f"{index}.{candidate['family']}.dev"]
            mean, scale = train.mean(0), np.maximum(train.std(0), 1e-6)
            model = candidate["model"]
            assert np.array_equal(mean, model["normalizer"]["mean"])
            assert np.array_equal(scale, model["normalizer"]["scale"])
            design = np.column_stack(((train - mean) / scale, np.ones(len(train))))
            penalty = np.diag(np.r_[np.full(40, np.sqrt(candidate["alpha"])), 0.])
            independently_fitted = np.linalg.lstsq(np.vstack((design, penalty)),
                np.vstack((bank["train_returns"], np.zeros((41, 5)))), rcond=None)[0]
            coefficient = np.asarray(model["coefficient"])
            difference = float(np.max(np.abs(independently_fitted - coefficient)))
            maximum_coefficient_difference = max(maximum_coefficient_difference, difference)
            assert difference < 1e-7
            for split, matrix in (("train", train), ("dev", dev)):
                values = ((matrix - mean) / scale) @ coefficient[:-1] + coefficient[-1]
                action = values.argmax(1)
                independent_values = ((matrix - mean) / scale) @ independently_fitted[:-1] + independently_fitted[-1]
                independent_choice_disagreements += int(np.sum(action != independent_values.argmax(1)))
                maximum_prediction_difference = max(maximum_prediction_difference, float(np.max(np.abs(values - independent_values))))
                assert action.tolist() == candidate[f"{split}_action_indices"]
                actual = bank[f"{split}_returns"][np.arange(len(action)), action]
                near(actual.mean(), candidate[f"{split}_value"])
                near(bank[f"{split}_returns"].max(1).mean() - actual.mean(), candidate[f"{split}_oracle_regret"])
                if split == "dev":
                    for condition, rows in zip(protocol["conditions"], np.split(actual, 4), strict=True):
                        near(rows.mean(), candidate["development_by_condition"][condition])
            heads_checked += 1
        for representation, definition in protocol["representations"].items():
            options = [c for c in record["candidates"] if c["representation"] == representation]
            assert len(options) == 24 and {c["candidate_index"] for c in options} == set(range(24))
            chosen = sorted(options, key=lambda c: (-c["dev_value"], c["candidate_index"]))[0]
            assert chosen["candidate_index"] == summary["selected"][representation]["candidate_index"]
            for family in definition["family_order"]:
                selected = sorted([c for c in options if c["family"] == family], key=lambda c: (-c["dev_value"], c["candidate_index"]))[0]
                assert selected["candidate_index"] == summary["family_selected"][family]["candidate_index"]
        difference = summary["selected"]["native"]["dev_value"] - summary["selected"]["history"]["dev_value"]
        near(difference, summary["native_minus_history_development"])
        comparisons[str(seed)] = difference
    assert heads_checked == 144 == result["heads_fitted"]
    assert native_matrices_matched == 24
    assert result["native_tick_calls"] == 3 * 4 * (768 + 384) * 2 == 27648
    near(np.mean(list(comparisons.values())), result["pooled_native_minus_history_development"])
    report = {"schema": "hepta.field-bridge.v2.hybrid-control-arithmetic-audit.1", "status": "pass",
        "heads_independently_refitted": heads_checked, "maximum_augmented_lstsq_coefficient_difference": maximum_coefficient_difference,
        "independent_refit_choice_disagreements": independent_choice_disagreements,
        "maximum_independent_refit_prediction_difference": maximum_prediction_difference,
        "native_matrices_matching_prior_diagnostic": native_matrices_matched,
        "all_raw_residuals_feature_definitions_and_train_only_normalizers_verified": True,
        "all144_action_vectors_means_regrets_and_family_selections_recomputed": True,
        "comparisons": comparisons, "pooled_native_minus_history_development": result["pooled_native_minus_history_development"],
        "new_outputs_or_holdouts_accessed": False, "source_sha256": sha(__file__), "result_sha256": sha(result_path)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
