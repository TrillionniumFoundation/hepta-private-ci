"""Independent complete-tree feature, own-policy-target and ridge-fit audit.

Only completed fitting evidence enters this verifier. No generator, observer,
source corpus, held-out audit outcome, or candidate selection is executed here.
Re-solving frozen regressions and replaying original native features are extra
verification work, not additional treatment candidates or observations.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from .native_session_audit import (Q24, SEEDS, SOURCE_PIN, array_digest, bound,
    bridge_type, digest, inventory, member, read, require)


REPRESENTATIONS = ("current", "history", "native", "reset_native")
TRANSFORMS = (("raw", None), ("k1", 1), ("k2", 2), ("k4", 4))
RIDGES = (.0001, .01, 1.)
STAGES = ((0,), (1, 2, 3, 4), tuple(range(5, 21)))
RFF_SEED = 271033
COEFFICIENT_TOLERANCE = {"atol": 1e-7, "rtol": 1e-8}
PREDICTION_TOLERANCE = {"atol": 1e-8, "rtol": 1e-9}


def ancestry(node):
    nodes = [node]
    while node:
        node = (node - 1) // 4
        nodes.insert(0, node)
    return nodes


def plan(node):
    path = ancestry(node)
    return [child - 4 * parent for parent, child in zip(path[:-1], path[1:], strict=True)]


def normalizer(values):
    return {"mean": np.mean(values, axis=0).tolist(), "scale": np.maximum(np.std(values, axis=0, ddof=0), 1e-6).tolist(),
            "ddof": 0, "std_floor": 1e-6, "scope": "runtime_fit_only"}


def transformed(values, specification):
    if specification["k"] is None:
        return values.copy()
    norm = specification["normalizer"]
    return np.clip((values - np.asarray(norm["mean"])) / np.asarray(norm["scale"]) / specification["k"], -1, 1)


def fourier(width, frequencies):
    weights = np.random.default_rng(RFF_SEED).normal(size=(width, frequencies)) / np.sqrt(width)
    return {"seed": RFF_SEED, "input_width": width, "frequencies": frequencies, "weights": weights.tolist(),
        "weight_sha256": array_digest(weights),
        "formula": "concat(cos(xW),sin(xW))/sqrt(frequencies); fixed weights independent of labels",
        "contraction": "numpy.einsum('bi,ij->bj', optimize=False); batch-independent reduction"}


def rebuild_features(events, representation, transform, bridge, role):
    """Independent ancestry construction and direct original-kernel fork replay."""
    output = np.empty((len(events), 21, 88), dtype=np.float64)
    if representation in ("current", "history"):
        spec = fourier(16, 36) if representation == "current" else fourier(48, 20)
        weight = np.asarray(spec["weights"])
        for node in range(21):
            history = events[:, ancestry(node)]
            adjusted = transformed(history, transform)
            if representation == "current":
                raw, projected = history[:, -1], adjusted[:, -1]
            else:
                raw, projected = np.zeros((len(events), 48)), np.zeros((len(events), 48))
                raw[:, :history.shape[1] * 16] = history.reshape(len(events), -1)
                projected[:, :history.shape[1] * 16] = adjusted.reshape(len(events), -1)
            angles = np.einsum("bi,ij->bj", projected, weight, optimize=False)
            residual = np.concatenate((np.cos(angles), np.sin(angles)), axis=1) / np.sqrt(spec["frequencies"])
            output[:, node] = np.concatenate((raw, residual), axis=1)
        return output
    before = bridge.tick_count
    prefix = f"v3-{'fit' if role == 'train' else 'select'}-{transform['name']}-{representation}"
    for index, events_for_case in enumerate(events):
        handles = []
        try:
            for node in range(21):
                handle = bridge.open(f"{prefix}:{index}") if node == 0 else handles[(node - 1) // 4].fork()
                handles.append(handle)
                history = events_for_case[ancestry(node)]
                raw = history.astype("<f8").tobytes()
                binding = hashlib.sha256(b"hepta.field-v3.public-history.v1" + bytes.fromhex(bound(transform)) + raw).hexdigest()
                encoded = np.rint(transformed(history[-1], transform) * Q24).astype(np.int64).tolist()
                if representation == "reset_native" and node:
                    handle.reset()
                for offset in (0, 8):
                    latent, receipt = handle.tick(encoded[offset:offset + 8], readback_digest=binding)
                    require(receipt["authority"] == "DENY_ALL" and receipt["requires_calibration"] is True
                            and receipt["native_owner_integration"] is False, "Native verification authority differs")
                padded = np.zeros(48)
                padded[:history.size] = history.reshape(-1)
                output[index, node] = np.r_[padded, latent]
        finally:
            for handle in handles:
                handle.close()
    require(bridge.tick_count - before == 42 * len(events), "Complete-tree native verification work differs")
    return output


def scores(head, values):
    norm = head["normalizer"]
    z = (values - norm["mean"]) / norm["scale"]
    return np.einsum("bi,ij->bj", np.column_stack((z, np.ones(len(z)))), np.asarray(head["coefficient"]), optimize=False)


def terminal_nodes(heads, features, starting_nodes):
    """Follow the candidate's own future heads, including its explicit stop."""
    nodes = np.asarray(starting_nodes, dtype=np.int64).copy()
    active = nodes < 21
    rows = np.arange(len(features))
    for stage in range(3):
        in_stage = active & np.isin(nodes, STAGES[stage])
        indices = rows[in_stage]
        if not len(indices):
            continue
        chosen = scores(heads[stage], features[indices, nodes[indices]]).argmax(1)
        stopping = indices[chosen == 0]
        active[stopping] = False
        moving = indices[chosen != 0]
        nodes[moving] = 4 * nodes[moving] + chosen[chosen != 0]
    return nodes


def targets_for(heads, features, values, stage):
    targets = np.empty((len(features), len(STAGES[stage]), 5), dtype=np.float64)
    rows = np.arange(len(features))
    for column, node in enumerate(STAGES[stage]):
        targets[:, column, 0] = values[:, node]
        for action in range(1, 5):
            reached = terminal_nodes(heads, features, np.full(len(features), 4 * node + action))
            targets[:, column, action] = values[rows, reached]
    return targets.reshape(-1, 5)


def check_numeric(actual, expected, tolerance, label):
    actual, expected = np.asarray(actual), np.asarray(expected)
    require(actual.shape == expected.shape and np.isfinite(actual).all() and np.isfinite(expected).all()
            and np.allclose(actual, expected, equal_nan=False, **tolerance), label)
    return float(np.max(np.abs(actual - expected), initial=0.))


def audit_candidate(candidate, training, selection, tx, sx, transform, rep, alpha, index, identity, library_sha):
    model = candidate["controller"]
    expected_fourier = fourier(16, 36) if rep == "current" else fourier(48, 20) if rep == "history" else None
    require(candidate["representation"] == model["representation"] == rep and candidate["candidate_index"] == model["candidate_index"] == index
            and model["transform"] == transform and model["alpha"] == alpha and model["fourier"] == expected_fourier
            and model["feature_width"] == 88 and model["head_coefficients"] == 1335 and len(model["heads"]) == 3
            and model["schema"] == "hepta.field-bridge-v3.runtime-controller.v1" and model["fit_identities"] == identity
            and model["authority"] == "DENY_ALL" and model["native_owner_integration"] is False
            and model["native_library_sha256"] == (library_sha if rep in ("native", "reset_native") else None)
            and model["future_value_definition"] == "same candidate later frozen heads"
            and model["head_contraction"] == "numpy.einsum('bi,ij->bj', optimize=False); batch-independent reduction",
            "Candidate family, opportunity, provenance or authority differs")
    coefficient_error = prediction_error = mse_error = 0.
    actions, all_rebuilt_heads, nonoracle = np.empty((len(tx), 21), dtype=np.int64), [], 0
    for stage, nodes in enumerate(STAGES):
        head = model["heads"][stage]
        y = targets_for(model["heads"], tx, training, stage)
        x = tx[:, nodes].reshape(-1, 88)
        norm = normalizer(x)
        require(head["normalizer"] == norm and head["targets_sha256"] == array_digest(y)
                and head["stage"] == stage and head["alpha"] == alpha and head["parameter_count"] == 445
                and head["intercept_penalized"] is False and head["fit_rows"] == len(x),
                "A fitted head used different normalization, own-policy targets, rows or regularization")
        z = np.column_stack(((x - norm["mean"]) / norm["scale"], np.ones(len(x))))
        gram = z.T @ z
        gram[np.arange(88), np.arange(88)] += alpha
        coefficient = np.linalg.solve(gram, z.T @ y)
        coefficient_error = max(coefficient_error, check_numeric(coefficient, head["coefficient"], COEFFICIENT_TOLERANCE,
                                                                "Independent ridge coefficients differ beyond fixed tolerance"))
        rebuilt = {**head, "coefficient": coefficient.tolist()}
        all_rebuilt_heads.append(rebuilt)
        for data in (x, sx[:, nodes].reshape(-1, 88)):
            expected, actual = scores(head, data), scores(rebuilt, data)
            prediction_error = max(prediction_error, check_numeric(actual, expected, PREDICTION_TOLERANCE,
                                                                  "Independent ridge predictions differ beyond fixed tolerance"))
            require(np.array_equal(actual.argmax(1), expected.argmax(1)), "Rebuilt head changed a train/selection action")
        measured_mse = float(np.mean((z @ coefficient - y) ** 2))
        mse_error = max(mse_error, check_numeric(measured_mse, head["fit_mse"], {"atol": 1e-12, "rtol": 1e-10},
                                               "Independent training MSE differs"))
        actions[:, nodes] = scores(rebuilt, x).argmax(1).reshape(len(tx), -1)
        if stage == 1:
            reshaped = y.reshape(len(tx), 4, 5)
            for column, node in enumerate(nodes):
                for action in range(1, 5):
                    child = 4 * node + action
                    clairvoyant = np.max(training[:, [child, *range(4 * child + 1, 4 * child + 5)]], axis=1)
                    nonoracle += int(np.sum(reshaped[:, column, action] < clairvoyant))
    require(array_digest(actions) == candidate["training_all_node_actions_sha256"], "Full fitted train-node actions changed")
    results = {}
    for label, x, values in (("training", tx, training), ("selection", sx, selection)):
        reached = terminal_nodes(all_rebuilt_heads, x, np.zeros(len(x), dtype=np.int64))
        actual = values[np.arange(len(x)), reached]
        require(reached.tolist() == candidate[label + "_terminal_nodes"]
                and float(actual.mean()) == candidate[label + "_mean_value"], "Candidate's actual policy rollout or mean differs")
        results[label + "_mean_value"] = float(actual.mean())
    return {"representation": rep, "candidate_index": index, **results, "own_tail_target_hashes_checked": 3,
        "ridge_heads_rebuilt": 3, "max_coefficient_abs_error": coefficient_error, "max_prediction_abs_error": prediction_error,
        "max_fit_mse_abs_error": mse_error, "strictly_below_clairvoyant_stage1_targets": nonoracle,
        "exact_action_checks": 21 * (len(tx) + len(sx)), "controller_sha256": bound(model)}


def audit_fit(fitted, train, selection, feature_path, bridge, progress=None):
    te, tv, se, sv = train["events"], train["terminal_values"], selection["events"], selection["terminal_values"]
    identity = fitted["fit_identities"]
    expected_identity = {"training_events_sha256": array_digest(te), "training_values_sha256": array_digest(tv),
        "selection_events_sha256": array_digest(se), "selection_values_sha256": array_digest(sv),
        "training_source_ids_sha256": bound(train["source_ids"].tolist()), "selection_source_ids_sha256": bound(selection["source_ids"].tolist()),
        "metadata": identity["metadata"]}
    require(identity == expected_identity and not (set(train["source_ids"].reshape(-1)) & set(selection["source_ids"].reshape(-1))),
            "Fitting content identity or fit/selection source separation differs")
    require(len(fitted["candidates"]) == fitted["candidate_policies"] == 48 and fitted["stage_head_fits"] == 144
            and fitted["candidates_per_representation"] == 12 and fitted["head_coefficients_per_policy"] == 1335
            and fitted["training_base_trees"] == len(te) and fitted["selection_base_trees"] == len(se)
            and fitted["all_targets_from_fit_only"] is True and fitted["selection_used_only_to_choose_frozen_candidates"] is True
            and fitted["native_tick_calls"] == fitted["native_expected_tick_calls"] == 336 * (len(te) + len(se)),
            "Registered candidate/compute count or fit-only boundary differs")
    common = normalizer(te.reshape(-1, 16))
    checks, matrices, position = [], [], 0
    before, native_before = bridge.tick_count, bridge.native_ns
    expected_matrices = {f"{name}.{rep}.{role}" for name, _ in TRANSFORMS for rep in REPRESENTATIONS for role in ("train", "selection")}
    with np.load(feature_path, allow_pickle=False) as packed:
        require(set(packed.files) == expected_matrices and len(fitted["feature_matrices"]) == 16
                and fitted["feature_evidence"]["matrices"] == 32 and fitted["feature_evidence"]["sha256"] == digest(feature_path),
                "Retained feature inventory differs")
        for transform_index, (name, k) in enumerate(TRANSFORMS):
            transform = {"name": name, "k": k, "normalizer": common}
            for rep in REPRESENTATIONS:
                record = fitted["feature_matrices"][transform_index * 4 + REPRESENTATIONS.index(rep)]
                require(record["representation"] == rep and record["transform"] == name, "Feature-record ordering differs")
                arrays = []
                for role, events in (("train", te), ("selection", se)):
                    key = f"{name}.{rep}.{role}"
                    stored = packed[key]
                    require(stored.dtype == np.float64 and stored.shape == (len(events), 21, 88)
                            and np.isfinite(stored).all(), "Invalid retained feature matrix")
                    rebuilt = rebuild_features(events, rep, transform, bridge, role)
                    require(np.array_equal(stored, rebuilt) and array_digest(rebuilt) == array_digest(stored)
                            == record["training_sha256" if role == "train" else "selection_sha256"],
                            f"Independent event-to-feature reconstruction differs: {key}")
                    matrices.append({"key": key, "rows": len(events) * 21, "sha256": array_digest(stored)})
                    arrays.append(stored)
                for ridge_index, alpha in enumerate(RIDGES):
                    checks.append(audit_candidate(fitted["candidates"][position], tv, sv, *arrays,
                        transform, rep, alpha, transform_index * 3 + ridge_index, identity, bridge.binary_sha256))
                    position += 1
                if progress:
                    progress(name, rep, len(checks))
    for rep in REPRESENTATIONS:
        candidates = [c for c in checks if c["representation"] == rep]
        chosen = sorted(candidates, key=lambda c: (-c["selection_mean_value"], c["candidate_index"]))[0]
        require(fitted["selected"][rep] == {key: chosen[key] for key in ("candidate_index", "training_mean_value", "selection_mean_value")}
                and bound(fitted["models"][rep]) == chosen["controller_sha256"], "Selected model differs from exact means/registered tie order")
    node = int(sv.mean(axis=0).argmax())
    require(fitted["fixed_policy"] == {"node": node, "actions": plan(node), "selection_mean_values_all85": sv.mean(axis=0).tolist(),
        "training_mean_values_all85": tv.mean(axis=0).tolist(), "tie_break": "lowest BFS node; no fitted-family fallback"},
        "The selected fixed plan, all85 means or no-fallback declaration differs")
    require(bridge.tick_count - before == fitted["native_tick_calls"] and not bridge._sessions, "Verification native work or final handle coverage differs")
    return {"candidates": checks, "feature_matrices": matrices, "candidate_policies": len(checks),
        "ridge_heads_rebuilt": sum(row["ridge_heads_rebuilt"] for row in checks),
        "own_tail_target_hashes_checked": sum(row["own_tail_target_hashes_checked"] for row in checks),
        "exact_action_checks": sum(row["exact_action_checks"] for row in checks), "selected": fitted["selected"],
        "selected_controller_sha256": {rep: bound(model) for rep, model in fitted["models"].items()},
        "verification_native_ticks": bridge.tick_count - before, "verification_native_ns": bridge.native_ns - native_before,
        "study_native_fit_ticks": fitted["native_tick_calls"], "fixed_plan": node}


def load_bound_bank(directory, role, seed, profile, protocol, registry, freeze, run):
    complete = inventory(directory)
    require(freeze["artifacts"].get(str((directory / "COMPLETE.json").relative_to(run))) == digest(directory / "COMPLETE.json"),
            "Bank was not frozen before controller fitting")
    count = protocol["runtime"]["fit_pairs" if role == "runtime_fit" else "selection_pairs"]
    conditions = protocol["runtime"]["conditions"]
    ids = registry["roles"][role]["identities"]
    require(len(ids) == 2 * count and complete["role"] == role and complete["seed"] == seed and complete["profile"] == profile
            and complete["pairs"] == count and complete["rows"] == count * len(conditions)
            and complete["source_manifest_sha256"] == protocol["source_manifest_sha256"]
            and complete["all85_open_loop_plans"] == [plan(node) for node in range(85)], "Runtime bank metadata/role definition differs")
    with np.load(directory / "bank.npz", allow_pickle=False) as packed:
        require(set(packed.files) == {"events", "terminal_values", "source_ids", "case_ids", "conditions"}, "Bank array inventory differs")
        data = {name: packed[name].copy() for name in packed.files}
    require(data["source_ids"].tolist() == [ids[i:i + 2] for i in range(0, len(ids), 2)] * len(conditions)
            and data["conditions"].tolist() == [c for c in conditions for _ in range(count)]
            and data["case_ids"].tolist() == [f"{role}-{seed}-{c}-{i:06d}" for c in conditions for i in range(count)],
            "Bank source pairing or condition/case order differs from the frozen identity manifest")
    x, y = data["events"], data["terminal_values"]
    require(x.shape == (count * len(conditions), 21, 16) and y.shape == (len(x), 85)
            and x.dtype == y.dtype == np.float64 and np.isfinite(x).all() and np.isfinite(y).all()
            and abs(x).max() <= 1 and y.min() >= -1.01 and y.max() <= 1 and np.all(x[:, 0, 8:] == 0), "Bank array bounds differ")
    for node in range(1, 21):
        event = x[:, node]
        require(np.all(event[:, 8] == 1) and np.all(np.abs(event[:, 9:11]) == 1)
                and np.all((event[:, 12:] == 0) | (event[:, 12:] == 1)) and np.all(event[:, 12:].sum(1) == 1)
                and np.all(event[:, 12:].argmax(1) + 1 == (node - 1) % 4 + 1), "Noncausal BFS event/action provenance")
    return data, complete


def audit(run, profile, source, freeze_path, native=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    run, source, freeze_path = Path(run).resolve(), Path(source).resolve(), Path(freeze_path).resolve()
    directories = {seed: run / "runtime/fit" / f"{seed}-{profile}" for seed in SEEDS}
    require(all((path / "COMPLETE.json").is_file() and not (path / "FAILED.json").exists() for path in directories.values()),
            "Wait for all three completed fitting seeds before opening actual bank arrays")
    freeze_id, freeze, protocol = digest(freeze_path), read(freeze_path), read(source / "PROTOCOL.json")
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and "runtime-fit" in freeze["allowed_phases"]
            and freeze["protocol_sha256"] == digest(source / "PROTOCOL.json"), "Invalid pre-fitting source freeze")
    require(protocol["runtime"]["ridges"] == list(RIDGES)
            and protocol["runtime"]["transforms"] == [name for name, _ in TRANSFORMS]
            and protocol["runtime"]["representations"] == list(REPRESENTATIONS)
            and protocol["runtime"]["rff_seed"] == RFF_SEED, "Protocol's runtime candidate family differs from the audit contract")
    for name, identity in freeze["source_files"].items():
        require(digest(member(source.parent, name)) == identity, f"Frozen source differs: {name}")
    for name, identity in freeze["artifacts"].items():
        require(digest(member(run, name)) == identity, f"Frozen bank member differs: {name}")
    allocation = read(source / "SOURCE_ALLOCATION.json")
    packed_registry = (source / "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw_registry = gzip.decompress(packed_registry)
    require(digest(source / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"]
            and allocation["manifest_sha256"] == protocol["source_manifest_sha256"]
            and hashlib.sha256(packed_registry).hexdigest() == allocation["registry_gzip_sha256"]
            and hashlib.sha256(raw_registry).hexdigest() == allocation["registry_sha256"], "Frozen identity-manifest binding differs")
    registry = json.loads(raw_registry)
    build = read(source / "evidence/NATIVE_BUILD_RECEIPT.json")
    library = Path(native or build["binary"]).resolve()
    require(digest(library) == freeze["native_library_sha256"] == build["binary_sha256"]
            and build["source_sha256"] == digest(source / "native_stream.rs") and build["python_source_sha256"] == digest(source / "native_stream.py")
            and build["original_source_commit"] == SOURCE_PIN, "Frozen native build identity differs")
    results = {}
    with bridge_type(source)(library, freeze["native_library_sha256"]) as bridge:
        for seed, directory in directories.items():
            complete, start = inventory(directory), read(directory / "START.json")
            require(complete["phase"] == start["phase"] == "runtime-fit" and complete["seed"] == start["seed"] == seed
                    and complete["profile"] == start["profile"] == profile and start["freeze_sha256"] == freeze_id
                    and start["registered_commit"] == freeze["registered_commit"] and start["protocol_sha256"] == freeze["protocol_sha256"]
                    and start["native_library_sha256"] == bridge.binary_sha256
                    and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()), "Fit execution provenance differs")
            bank_root = run / "runtime/bank" / f"{seed}-{profile}"
            train, training_complete = load_bound_bank(bank_root / "runtime_fit", "runtime_fit", seed, profile, protocol, registry, freeze, run)
            selection, selection_complete = load_bound_bank(bank_root / "runtime_select", "runtime_select", seed, profile, protocol, registry, freeze, run)
            fitted = read(directory / "READOUTS.json")
            meta = fitted["fit_identities"]["metadata"]
            require(meta["seed"] == seed and meta["profile"] == profile and meta["protocol_sha256"] == freeze["protocol_sha256"]
                    and meta["source_manifest_sha256"] == protocol["source_manifest_sha256"]
                    and meta["model_parameter_sha256"] == training_complete["model_parameter_sha256"] == selection_complete["model_parameter_sha256"]
                    and meta["reward_observer_parameter_sha256"] == training_complete["observer_parameter_sha256"] == selection_complete["observer_parameter_sha256"]
                    and meta["bank_complete_sha256"] == {role: digest(bank_root / role / "COMPLETE.json") for role in ("runtime_fit", "runtime_select")},
                    "Fit and bank model/observer/source identities differ")
            inputs = {"fit_complete_sha256": directory / "COMPLETE.json", "readouts_sha256": directory / "READOUTS.json",
                "features_sha256": directory / "features.npz", "training_bank_sha256": bank_root / "runtime_fit/bank.npz",
                "selection_bank_sha256": bank_root / "runtime_select/bank.npz"}
            identities = {key: digest(path) for key, path in inputs.items()}
            result = audit_fit(fitted, train, selection, directory / "features.npz", bridge,
                lambda transform, rep, count: print(f"fit verification seed={seed} profile={profile} transform={transform} representation={rep} policies={count}/48", flush=True))
            require(complete["candidate_policies"] == result["candidate_policies"] and complete["stage_head_fits"] == result["ridge_heads_rebuilt"]
                    and complete["native_tick_calls"] == result["study_native_fit_ticks"]
                    and identities == {key: digest(path) for key, path in inputs.items()}, "Fit resources or immutable input changed during verification")
            results[str(seed)] = {**result, "inputs": identities, "bank_complete_sha256": meta["bank_complete_sha256"]}
        verification_ticks, native_ns = bridge.tick_count, bridge.native_ns
    require(digest(freeze_path) == freeze_id and all(digest(member(source.parent, name)) == identity
            for name, identity in freeze["source_files"].items()), "Source/freeze changed during fitting verification")
    return {"schema": "hepta.field-bridge.v3.independent-runtime-fit-audit.1", "passed": True, "profile": profile, "seeds": results,
        "freeze_sha256": freeze_id, "registered_commit": freeze["registered_commit"], "protocol_sha256": freeze["protocol_sha256"],
        "source_files": freeze["source_files"], "native_library_sha256": bridge.binary_sha256, "original_source_pin": SOURCE_PIN,
        "auditor_source_sha256": digest(__file__), "helper_source_sha256": digest(Path(__file__).with_name("native_session_audit.py")),
        "feature_matrices_verified": sum(len(r["feature_matrices"]) for r in results.values()),
        "ridge_heads_rebuilt": sum(r["ridge_heads_rebuilt"] for r in results.values()),
        "own_tail_target_hashes_checked": sum(r["own_tail_target_hashes_checked"] for r in results.values()),
        "exact_action_checks": sum(r["exact_action_checks"] for r in results.values()),
        "study_native_fit_ticks": sum(r["study_native_fit_ticks"] for r in results.values()),
        "verification_native_ticks": verification_ticks, "verification_native_ns": native_ns,
        "coefficient_tolerance": COEFFICIENT_TOLERANCE, "prediction_tolerance": PREDICTION_TOLERANCE,
        "feature_target_hash_normalizer_action_selection_comparison": "exact; numeric tolerances apply only to re-solved coefficients/predictions/MSE",
        "generator_forward_calls": 0, "observer_forward_calls": 0, "source_corpus_loads": 0,
        "identity_manifest_only": True, "audit_primary_retention_outcomes_opened": False,
        "terminal_value_truth_scope": "Bound frozen bank values; independent media audit verifies actual-output label arithmetic",
        "additional_verification_only": True, "new_candidates_or_independent_observations": 0,
        "authority": "DENY_ALL", "native_owner_integration": False,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--profile", choices=("frozen", "ordinary", "field"), required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--native", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite independent fit evidence")
    result = audit(args.run, args.profile, args.source, args.freeze, args.native)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "ridge_heads_rebuilt": result["ridge_heads_rebuilt"],
                     "verification_native_ticks": result["verification_native_ticks"], "receipt_sha256": digest(args.output)}))
