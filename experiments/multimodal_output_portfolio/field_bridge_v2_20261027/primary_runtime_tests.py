"""Synthetic contracts for the complete frozen native/history runtime recipe."""

import argparse
import json
from pathlib import Path

import numpy as np

from ..field_bridge_20261027.controls import choose, history_features
from ..field_bridge_v2_20261027_review.hybrid_control import native_residual, fourier_residual
from . import primary_runtime as R
from .native_fast import NativeFastBridge, Q24, native_features_fast


def _expect_rejected(operation):
    try:
        operation()
    except (ValueError, TypeError):
        return
    raise AssertionError("Invalid fitting/deployment input was accepted")


def run(ffi, out):
    out.mkdir(parents=True, exist_ok=False)
    bridge = NativeFastBridge(ffi, R.LIBRARY_SHA)
    rng = np.random.default_rng(271031)
    coefficient = rng.normal(size=(16, 5))
    banks = []
    for role, count in (("train", 64), ("development", 32)):
        x0, x1 = rng.uniform(0.01, 0.99, size=(2, count, 8))
        returns = 0.5 + 0.04 * np.tanh(np.column_stack((x0, x1)) @ coefficient)
        banks.append({"role": role, "x0": x0, "x1": x1, "returns": returns})
    train, dev = banks
    before_inputs = [R.matrix_sha(b[key]) for b in banks for key in ("x0", "x1", "returns")]
    result = R.fit_controllers(train, dev, bridge, "contract", feature_destination=out / "features.npz")
    assert result["heads_fitted"] == 48
    assert result["original_sparse_tick_calls"] == 8*(64+32)
    assert len(result["candidates"]) == 48
    with np.load(out / "features.npz", allow_pickle=False) as archive:
        persisted = {key: archive[key].copy() for key in archive.files}
    assert len(persisted) == 32
    assert result["feature_evidence"]["sha256"] == R.file_sha(out / "features.npz")
    for representation in R.FAMILIES:
        group = [c for c in result["candidates"] if c["representation"] == representation]
        assert {c["candidate_index"] for c in group} == set(range(24))
        assert {c["family"] for c in group} == set(R.FAMILIES[representation])
        assert {c["alpha"] for c in group} == set(R.ALPHAS)

    max_coefficient_error = max_prediction_error = 0.0
    parity_count = action_checks = 0
    train_raw = np.column_stack((train["x0"], train["x1"]))
    dev_raw = np.column_stack((dev["x0"], dev["x1"]))
    weights = np.random.default_rng(271029).normal(size=(16, 12))/np.sqrt(16)
    for transform_index, transformation in enumerate(result["transformations"]):
        spec = transformation["transform"]
        u0, u1 = R._transform(train["x0"], train["x1"], spec)
        v0, v1 = R._transform(dev["x0"], dev["x1"], spec)
        native_train = native_features_fast(bridge, u0, u1, f"verify-{transform_index}-train")
        native_dev = native_features_fast(bridge, v0, v1, f"verify-{transform_index}-dev")
        nt, nd, _ = native_residual(train_raw, dev_raw, native_train, native_dev)
        ht, hd, _ = fourier_residual(train_raw, dev_raw, np.column_stack((u0, u1)),
                                    np.column_stack((v0, v1)), weights)
        pairs = {"pure_native40": (native_train, native_dev), "raw16_native24": (nt, nd),
                 "original_history40": (history_features(u0, u1), history_features(v0, v1)),
                 "raw16_rff24": (ht, hd)}
        for family, (train_x, dev_x) in pairs.items():
            assert R.matrix_sha(train_x) == transformation["feature_matrix_sha256"][family]["train"]
            assert R.matrix_sha(dev_x) == transformation["feature_matrix_sha256"][family]["development"]
            assert np.array_equal(train_x, persisted[f"{transform_index}.{family}.train"])
            assert np.array_equal(dev_x, persisted[f"{transform_index}.{family}.development"])
            if family.startswith("raw16_"):
                assert np.array_equal(train_x[:, :16], train_raw)
                assert np.array_equal(dev_x[:, :16], dev_raw)
            for candidate in (c for c in result["candidates"] if c["family"] == family and c["transform"] == spec["name"]):
                controller, alpha = candidate["controller"], candidate["alpha"]
                head = controller["head"]
                mean, scale = np.asarray(head["normalizer"]["mean"]), np.asarray(head["normalizer"]["scale"])
                z = np.column_stack(((train_x-mean)/scale, np.ones(len(train_x))))
                penalty = np.diag(np.r_[np.sqrt(alpha)*np.ones(40), 0.])
                independent = np.linalg.lstsq(np.vstack((z, penalty)),
                    np.vstack((train["returns"], np.zeros((41, 5)))), rcond=None)[0]
                fitted = np.asarray(head["coefficient"])
                assert fitted.shape == (41, 5)
                max_coefficient_error = max(max_coefficient_error, float(np.max(np.abs(independent-fitted))))
                dz = np.column_stack(((dev_x-mean)/scale, np.ones(len(dev_x))))
                max_prediction_error = max(max_prediction_error, float(np.max(np.abs(dz @ (independent-fitted)))))
                reference = np.argmax(dz @ independent, axis=1)
                assert np.array_equal(reference, candidate["dev_action_indices"])
                serialized = json.loads(json.dumps(controller, allow_nan=False))
                selected, summary = R.select(serialized, dev["x0"], dev["x1"], bridge,
                                              f"roundtrip-{family}-{transform_index}-{alpha}")
                assert np.array_equal(selected, reference)
                assert summary["feature_matrix_sha256"] == R.matrix_sha(dev_x)
                assert summary["target_accesses"] == 0 and summary["authority"] == "DENY_ALL"
                parity_count += 1
                action_checks += len(reference)
    assert parity_count == 48 and max_coefficient_error < 1e-6 and max_prediction_error < 1e-7

    sentinel = {"role": "development", "x0": np.full_like(dev["x0"], 0.99),
                "x1": np.full_like(dev["x1"], 0.01), "returns": np.zeros_like(dev["returns"])}
    changed = R.fit_controllers(train, sentinel, bridge, "heldout-sentinel")
    for original, altered in zip(result["candidates"], changed["candidates"], strict=True):
        assert original["controller"] == altered["controller"]
    assert all(value["candidate_index"] == 0 for value in changed["selected"].values())
    assert before_inputs == [R.matrix_sha(b[key]) for b in banks for key in ("x0", "x1", "returns")]

    hybrid = next(c["controller"] for c in result["candidates"] if c["family"] == "raw16_native24")
    controller_hash = R.object_sha(hybrid)
    receipt_path = out / "reset-native.jsonl"
    actions, summary = R.select(hybrid, dev["x0"][:3], dev["x1"][:3], bridge,
                                "reset-contract", True, receipt_path)
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    assert len(receipts) == 3
    native_reset = []
    for receipt in receipts:
        ticks = receipt["native"]["ticks"]
        assert len(ticks) == 2 and all(t["authority"] == "DENY_ALL" and t["requires_calibration"] for t in ticks)
        assert ticks[1]["sequence"] == 1 and set(ticks[1]["checkpoint_before"]) == {"0"}
        native_reset.append(np.asarray(ticks[1]["activation_q24"]+ticks[1]["eligibility_q24"])/Q24)
    reset_x = np.column_stack((dev_raw[:3], np.asarray(native_reset)[:, hybrid["native_selector"]["indices"]]))
    assert np.array_equal(actions, choose(hybrid["head"], reset_x))
    assert summary["feature_matrix_sha256"] == R.matrix_sha(reset_x)
    assert summary["raw_history_preserved"] and summary["complete_receipts_written"]
    assert R.object_sha(hybrid) == controller_hash

    solve = np.linalg.solve
    def forbidden(*args, **kwargs):
        raise AssertionError("Deployment tried to fit")
    np.linalg.solve = forbidden
    try:
        for representation, controller in result["models"].items():
            R.select(controller, dev["x0"][:2], dev["x1"][:2], bridge, "no-fit")
    finally:
        np.linalg.solve = solve
    history = result["models"]["history"]
    invalid = [lambda: R.fit_controllers(train | {"role": "test"}, dev, bridge, "invalid"),
        lambda: R.fit_controllers(train, dev | {"role": "audit"}, bridge, "invalid"),
        lambda: R.select(history, dev["x0"], dev["x1"], reset=True),
        lambda: R.select(hybrid, dev["x0"], dev["x1"], bridge=None),
        lambda: R.select(history, np.full_like(dev["x0"], np.nan), dev["x1"]),
        lambda: R.select(history, dev["x0"], dev["x1"][:-1]),
        lambda: R.select(history | {"authority": "ALLOW"}, dev["x0"], dev["x1"]),
        lambda: R.select(history, dev["x0"], dev["x1"], receipt_path=out / "unexpected.jsonl")]
    for operation in invalid:
        _expect_rejected(operation)
    receipt = {"schema": "hepta.field-bridge-v2.primary-runtime-contract.v1", "passed": True,
        "fixture": "synthetic only; no study banks, model outputs or audit/retention outcomes read",
        "heads_checked": parity_count, "individual_action_parity_checks": action_checks,
        "independent_augmented_lstsq_coefficient_max_abs_error": max_coefficient_error,
        "independent_prediction_max_abs_error": max_prediction_error,
        "all_development_sentinel_controllers_unchanged": True, "first_candidate_tie_verified": True,
        "legacy_hybrid_feature_parity": True, "json_roundtrip_predictions_exact": True,
        "persisted_feature_matrices_exact": len(persisted),
        "native_full_receipt_reset_cases": len(receipts), "reset_keeps_raw_first_event": True,
        "no_fit_on_select": True, "controller_and_inputs_unchanged": True,
        "invalid_inputs_rejected": len(invalid), "native_requests": bridge.request_count,
        "source_sha256": R.file_sha(R.__file__), "test_source_sha256": R.file_sha(__file__),
        "library_sha256": bridge.binary_sha256}
    R._write(out / "PRIMARY_RUNTIME_CONTRACT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.ffi, args.out), indent=2))


if __name__ == "__main__":
    main()
