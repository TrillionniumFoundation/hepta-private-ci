"""Behavioral contracts for the development-only hybrid representation study."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from ..field_bridge_20261027.controls import fit_readout, choose
from .analyze_native_representation import heads
from .hybrid_control import native_residual, fourier_residual, matrix_sha, sha, best


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Refusing to overwrite contract evidence")
    rng = np.random.default_rng(271030)
    raw_train, raw_dev = rng.random((32, 16)), rng.random((12, 16))
    native_train, native_dev = rng.normal(size=(32, 40)), rng.normal(size=(12, 40))
    original_native = native_train.copy()
    train, dev, selector = native_residual(raw_train, raw_dev, native_train, native_dev)
    changed_train, changed_dev, changed_selector = native_residual(raw_train, raw_dev, native_train, native_dev * 1e6)
    assert np.array_equal(train[:, :16], raw_train) and np.array_equal(dev[:, :16], raw_dev)
    assert np.array_equal(changed_train, train) and changed_selector == selector
    assert not np.array_equal(changed_dev[:, 16:], dev[:, 16:])
    assert np.array_equal(native_train, original_native)
    variance = native_train.var(0)
    independent = sorted(range(40), key=lambda index: (-variance[index], index))[:24]
    assert independent == selector["native_coordinate_indices"]
    _, _, tied = native_residual(raw_train, raw_dev, np.ones((32, 40)), np.zeros((12, 40)))
    assert tied["native_coordinate_indices"] == list(range(24))
    weights = np.random.default_rng(271029).normal(size=(16, 12)) / np.sqrt(16)
    weight_identity = matrix_sha(weights)
    weight_digests = []
    for offset in (0., .1, .2):
        transformed_train, transformed_dev = raw_train + offset, raw_dev - offset
        rff_train, rff_dev, meta = fourier_residual(raw_train, raw_dev, transformed_train, transformed_dev, weights)
        repeat_train, _, repeat_meta = fourier_residual(raw_train, raw_dev, transformed_train, transformed_dev * 1000, weights)
        assert meta == repeat_meta and np.array_equal(rff_train, repeat_train)
        assert np.array_equal(rff_train[:, :16], raw_train) and np.array_equal(rff_dev[:, :16], raw_dev)
        mean, scale = transformed_train.mean(0), np.maximum(transformed_train.std(0), 1e-6)
        projected = ((transformed_dev - mean) / scale) @ weights
        expected = np.column_stack((np.cos(projected), np.sin(projected))) / np.sqrt(12)
        assert np.array_equal(expected, rff_dev[:, 16:])
        weight_digests.append(meta["weight_sha256"])
    assert weight_digests == [weight_identity] * 3 and matrix_sha(weights) == weight_identity
    train_returns, dev_returns = rng.normal(size=(32, 5)), rng.normal(size=(12, 5))
    train_copy, train_return_copy = train.copy(), train_returns.copy()
    candidates = heads(train, train_returns, dev, dev_returns, ["one", "two", "three", "four"])
    v1 = fit_readout(train, train_returns, dev, dev_returns)
    selected = max(candidates, key=lambda row: row["dev_value"])
    assert selected["alpha"] == v1["chosen_alpha"]
    assert np.array_equal(selected["model"]["coefficient"], v1["coefficient"])
    assert np.array_equal(selected["model"]["normalizer"]["mean"], v1["normalizer"]["mean"])
    assert np.array_equal(selected["model"]["normalizer"]["scale"], v1["normalizer"]["scale"])
    assert np.array_equal(choose(selected["model"], dev), choose(v1, dev))
    changed = heads(train, train_returns, dev * 1000, -dev_returns, ["one", "two", "three", "four"])
    assert all(first["model"] == second["model"] for first, second in zip(candidates, changed, strict=True))
    assert np.array_equal(train_copy, train) and np.array_equal(train_return_copy, train_returns)
    tied = [{"candidate_index": index, "dev_value": .1} for index in (23, 9, 0, 15)]
    assert best(tied)["candidate_index"] == 0
    result = {"schema": "hepta.field-bridge.v2.hybrid-control-contract.1", "status": "pass",
        "native_hybrid_raw16_exact": True, "native_variance_fit_training_only": True,
        "native_variance_selector_independent_sort_matches": True,
        "native_variance_equal_ties_choose_lower_original_index": True,
        "fourier_hybrid_raw16_exact": True, "fourier_normalizer_training_only": True,
        "fourier_definition_exact": True, "same_frozen_fourier_matrix_three_calls": True,
        "head_coefficients_normalization_and_choices_match_v1": True,
        "development_features_and_labels_do_not_change_fitted_coefficients": True,
        "source_training_features_and_returns_unmodified": True,
        "exact_selection_ties_use_registered_order": True,
        "synthetic_fixture_is_efficacy_evidence": False,
        "source_sha256": sha(__file__), "fourier_weight_sha256": weight_identity}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
