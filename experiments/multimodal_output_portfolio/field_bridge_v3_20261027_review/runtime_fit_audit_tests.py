"""Synthetic own-tail fitting and complete native-feature audit contracts."""

import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np

from ..field_bridge_v3_20261027.native_stream import NativeStreamBridge
from ..field_bridge_v3_20261027.runtime_controller import fit_controllers
from . import runtime_fit_audit as audit


def fixture(role, count, seed):
    rng = np.random.default_rng(seed)
    events = rng.uniform(-1, 1, (count, 21, 16))
    events[:, 0, 8:] = 0
    for node in range(1, 21):
        events[:, node, 8] = 1
        events[:, node, 9:11] = rng.choice([-1., 1.], size=(count, 2))
        events[:, node, 12:] = 0
        events[:, node, 12 + (node - 1) % 4] = 1
    return {"role": role, "events": events, "terminal_values": rng.uniform(-.9, .9, (count, 85)),
        "source_ids": np.asarray([[f"synthetic-fit-audit:{role}:{i}:L", f"synthetic-fit-audit:{role}:{i}:R"] for i in range(count)])}


def reject(call):
    try:
        call()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("Expected independent fit audit rejection")


def run(library, out):
    started = time.perf_counter_ns()
    out.mkdir(parents=True, exist_ok=False)
    train, selection = fixture("runtime_fit", 6, 271041), fixture("runtime_select", 5, 271042)
    feature_path = out / "features.npz"
    with NativeStreamBridge(library) as bridge:
        fitted = fit_controllers(train, selection, bridge, metadata={"synthetic_only": True}, feature_destination=feature_path)
        verified = audit.audit_fit(fitted, train, selection, feature_path, bridge)
        assert verified["ridge_heads_rebuilt"] == verified["own_tail_target_hashes_checked"] == 144
        assert verified["verification_native_ticks"] == 3696 and len(verified["feature_matrices"]) == 32
        below_oracle = sum(row["strictly_below_clairvoyant_stage1_targets"] for row in verified["candidates"])
        assert below_oracle > 0
        with np.load(feature_path, allow_pickle=False) as packed:
            tx, sx = packed["raw.current.train"], packed["raw.current.selection"]
        original = fitted["candidates"][0]
        args = (train["terminal_values"], selection["terminal_values"], tx, sx, original["controller"]["transform"],
                "current", .0001, 0, fitted["fit_identities"], bridge.binary_sha256)
        guards = 0
        for mutate in (
            lambda c: c["controller"]["heads"][0]["coefficient"][0].__setitem__(0, c["controller"]["heads"][0]["coefficient"][0][0] + 1),
            lambda c: c["controller"]["heads"][0]["normalizer"]["mean"].__setitem__(0, .12345),
            lambda c: c["controller"]["heads"][0].__setitem__("fit_rows", 99),
            lambda c: c["controller"]["heads"][0].__setitem__("intercept_penalized", True),
            lambda c: c["controller"]["heads"][0].__setitem__("targets_sha256", "0" * 64),
            lambda c: c.__setitem__("candidate_index", 1),
            lambda c: c.__setitem__("selection_mean_value", c["selection_mean_value"] + .01),
            lambda c: c["training_terminal_nodes"].__setitem__(0, (c["training_terminal_nodes"][0] + 1) % 85),
            lambda c: c["controller"]["fourier"]["weights"][0].__setitem__(0, .123),
        ):
            bad = copy.deepcopy(original)
            mutate(bad)
            reject(lambda: audit.audit_candidate(bad, *args))
            guards += 1
        bad = copy.deepcopy(original)
        oracle = audit.targets_for(bad["controller"]["heads"], tx, train["terminal_values"], 1).reshape(6, 4, 5)
        for column, node in enumerate((1, 2, 3, 4)):
            for action in range(1, 5):
                child = 4 * node + action
                oracle[:, column, action] = np.max(train["terminal_values"][:, [child, *range(4 * child + 1, 4 * child + 5)]], axis=1)
        bad["controller"]["heads"][1]["targets_sha256"] = audit.array_digest(oracle.reshape(-1, 5))
        reject(lambda: audit.audit_candidate(bad, *args))
        guards += 1
        corrupted_arrays = {}
        with np.load(feature_path, allow_pickle=False) as packed:
            for name in packed.files:
                corrupted_arrays[name] = packed[name]
        corrupted_arrays["raw.current.train"][0, 0, 0] += .1
        corrupt_path = out / "self-consistently-rehashed-corrupt-features.npz"
        np.savez_compressed(corrupt_path, **corrupted_arrays)
        altered = copy.deepcopy(fitted)
        altered["feature_evidence"]["sha256"] = audit.digest(corrupt_path)
        altered["feature_matrices"][0]["training_sha256"] = audit.array_digest(corrupted_arrays["raw.current.train"])
        reject(lambda: audit.audit_fit(altered, train, selection, corrupt_path, bridge))
        guards += 1
        overlap = copy.deepcopy(selection)
        overlap["source_ids"][0] = train["source_ids"][0]
        altered = copy.deepcopy(fitted)
        altered["fit_identities"]["selection_source_ids_sha256"] = audit.bound(overlap["source_ids"].tolist())
        reject(lambda: audit.audit_fit(altered, train, overlap, feature_path, bridge))
        guards += 1
        tie_train, tie_select = fixture("runtime_fit", 4, 271043), fixture("runtime_select", 3, 271044)
        tie_train["terminal_values"].fill(0.)
        tie_select["terminal_values"].fill(0.)
        tie_path = out / "tie-features.npz"
        tied = fit_controllers(tie_train, tie_select, bridge, metadata={"synthetic_only": True}, feature_destination=tie_path)
        tied_result = audit.audit_fit(tied, tie_train, tie_select, tie_path, bridge)
        assert all(row["candidate_index"] == 0 for row in tied_result["selected"].values()) and tied_result["fixed_plan"] == 0
        altered = copy.deepcopy(tied)
        altered["selected"]["current"]["candidate_index"] = 1
        reject(lambda: audit.audit_fit(altered, tie_train, tie_select, tie_path, bridge))
        guards += 1
        assert bridge.library.hepta_stream_live_sessions() == 0
        total_test_ticks = bridge.tick_count
    reject(lambda: audit.audit(out / "uncompleted-run", "frozen", out / "nonexistent-source", out / "no-freeze", library))
    guards += 1
    result = {"schema": "hepta.field-bridge.v3.runtime-fit-audit-contract.1", "passed": True,
        "synthetic_only": True, "real_data_or_registered_source_roles_opened": False,
        "generator_or_observer_calls": 0, "complete_candidate_policies_verified": 96,
        "complete_stage_heads_verified": 288, "feature_matrices_rebuilt": 64,
        "strictly_below_clairvoyant_own_tail_targets": below_oracle,
        "lowest_index_selection_and_fixed_plan_ties_exact": True, "corruption_or_boundary_rejections": guards,
        "max_coefficient_abs_error": max(row["max_coefficient_abs_error"] for row in verified["candidates"]),
        "max_prediction_abs_error": max(row["max_prediction_abs_error"] for row in verified["candidates"]),
        "coefficient_tolerance": audit.COEFFICIENT_TOLERANCE, "prediction_tolerance": audit.PREDICTION_TOLERANCE,
        "all_synthetic_test_native_ticks_including_generation_and_failed_verification": total_test_ticks,
        "source_sha256": audit.digest(__file__), "auditor_source_sha256": audit.digest(audit.__file__),
        "native_library_sha256": audit.digest(library), "wall_ns": time.perf_counter_ns() - started}
    path = out / "RUNTIME_FIT_AUDIT_CONTRACT.json"
    path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"passed": True, "guards": guards, "receipt_sha256": audit.digest(path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.library, args.out)
