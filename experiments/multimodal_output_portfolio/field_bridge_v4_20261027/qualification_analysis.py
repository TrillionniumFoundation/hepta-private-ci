"""One-shot V4 qualification, with independent paired NumPy inference.

Arrays have axes [fixed model, complete rollout, source pair, condition].
The three models and condition weights are fixed; only complete rollout IDs
within each model and whole source-pair clusters are resampled. No model,
observer, native, training, or controller module is imported here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np


SEEDS = (17, 29, 43)
SCHEDULES = (14000, 14001, 14002, 14003)
OBSERVERS = ("reward", "audit")
METHODS = ("ordinary_0", "ordinary_1", "ordinary_2", "ordinary_3", "raw_field",
           "origin_field", "origin_generic", "origin_richer", "origin_h7")
ORDINARY = ("ordinary_2", "ordinary_3", "ordinary_3")
DRAW_COUNT, RNG_SEED, FAMILY_ALPHA, FAMILY_SIZE = 4000, 271042, .05, 6
COMPARISONS = (
    ("ordinary-frozen", "task", "selected_ordinary", "frozen", "gain", 0.),
    ("origin_field-ordinary", "task", "origin_field", "selected_ordinary", "gain", 0.),
    ("origin_field-origin_richer", "task", "origin_field", "origin_richer", "gain", 0.),
    ("ordinary-clean-NI", "clean", "selected_ordinary", "frozen", "noninferiority", -.01),
    ("origin_field-clean-NI", "clean", "origin_field", "frozen", "noninferiority", -.01),
    ("origin_richer-clean-NI", "clean", "origin_richer", "frozen", "noninferiority", -.01),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _validate_panels(panels):
    require(tuple(panels) == ("task", "clean"), "Task/clean panel order differs")
    deltas, descriptive, shapes = {}, {}, {}
    for panel_name, panel in panels.items():
        require(tuple(panel) == OBSERVERS, "Observer membership/order differs")
        shape, arrays, descriptive[panel_name] = None, {}, {}
        for observer in OBSERVERS:
            require(set(panel[observer]) == {*METHODS, "frozen"}, "Missing or expanded method family")
            arrays[observer], descriptive[panel_name][observer] = {}, {}
            for method in (*METHODS, "frozen"):
                values = np.asarray(panel[observer][method], dtype=np.float64)
                require(values.ndim == 4 and values.shape[:2] == (3, 4) and
                        all(size > 0 for size in values.shape), "Expected fixed 3-model/4-rollout panel")
                require(np.isfinite(values).all(), "Missing/nonfinite values cannot be dropped")
                shape = values.shape if shape is None else shape
                require(values.shape == shape, "Method/observer dimensions are unpaired")
                arrays[observer][method] = values
                descriptive[panel_name][observer][method] = {
                    "mean": float(values.mean()),
                    "per_model_mean": dict(zip(map(str, SEEDS), values.mean(axis=(1, 2, 3)).tolist())),
                }
            arrays[observer]["selected_ordinary"] = np.stack([
                arrays[observer][method][index] for index, method in enumerate(ORDINARY)])
        shapes[panel_name] = shape
        rows = [item for item in COMPARISONS if item[1] == panel_name]
        deltas[panel_name] = np.stack([np.stack([
            (arrays[observer][left] - arrays[observer][right]).mean(axis=3)
            for _, _, left, right, _, _ in rows]) for observer in OBSERVERS])
    return deltas, descriptive, shapes


def analyze_panels(panels):
    """Evaluate the fixed six-test contract; no tuning arguments or selection."""
    deltas, descriptive, shapes = _validate_panels(panels)
    samples = np.empty((DRAW_COUNT, 2, FAMILY_SIZE), dtype=np.float64)
    rng, draw_digest = np.random.default_rng(RNG_SEED), hashlib.sha256()
    for replicate in range(DRAW_COUNT):
        rollouts = rng.integers(0, 4, size=(3, 4))
        draw_digest.update(np.asarray(rollouts, dtype="<i8").tobytes())
        for panel_index, panel_name in enumerate(("task", "clean")):
            source_count = shapes[panel_name][2]
            source_ids = rng.integers(0, source_count, size=source_count)
            draw_digest.update(np.asarray(source_ids, dtype="<i8").tobytes())
            estimate = np.zeros((2, 3), dtype=np.float64)
            for model_index in range(3):
                paired = np.take(deltas[panel_name][:, :, model_index], rollouts[model_index], axis=2)
                estimate += np.take(paired.mean(axis=2), source_ids, axis=2).mean(axis=2) / 3
            samples[replicate, :, panel_index * 3:(panel_index + 1) * 3] = estimate
    tail = FAMILY_ALPHA / (2 * FAMILY_SIZE)
    bounds = np.quantile(samples, [tail, 1 - tail], axis=0, method="linear")
    results = []
    for index, (name, panel_name, left, right, kind, threshold) in enumerate(COMPARISONS):
        values, observers = deltas[panel_name][:, index % 3], {}
        for oi, observer in enumerate(OBSERVERS):
            per_model = values[oi].mean(axis=(1, 2))
            lower, upper = map(float, bounds[:, oi, index])
            signs_pass = kind != "gain" or bool(np.all(per_model > 0))
            observers[observer] = {
                "mean": float(values[oi].mean()),
                "per_model_mean": dict(zip(map(str, SEEDS), per_model.tolist())),
                "interval": [lower, upper], "strict_lower_threshold": threshold,
                "lower_pass": lower > threshold, "model_signs_pass": signs_pass,
                "passed": lower > threshold and signs_pass,
            }
        results.append({"name": name, "panel": panel_name, "left": left, "right": right,
                        "kind": kind, "observers": observers,
                        "passed": all(row["passed"] for row in observers.values())})
    return {
        "schema": "hepta.field-bridge.v4.qualification-statistics.1",
        "passed": all(row["passed"] for row in results), "comparisons": results,
        "bootstrap_samples": DRAW_COUNT, "bootstrap_seed": RNG_SEED,
        "rng": "numpy.random.default_rng(PCG64)", "draw_sha256": draw_digest.hexdigest(),
        "draw_order": "per replicate: 3x4 rollout indices; task source indices; clean source indices",
        "family_alpha": FAMILY_ALPHA, "family_comparisons": FAMILY_SIZE,
        "per_observer_two_sided_coverage": 1 - 2 * tail, "quantile": "linear",
        "fixed_models": list(SEEDS), "panel_shapes": {key: list(value) for key, value in shapes.items()},
        "descriptive_only_all_methods": descriptive,
        "scope": "Qualification screening only, conditional on three fixed historical models; approximate paired source/rollout bootstrap and conjunctive observer gates. Not final confirmation or simultaneous coverage of both observer families.",
    }


def validate_protocol(protocol):
    """Fail closed if the executable six-test contract has been weakened."""
    q, resources = protocol["qualification"], protocol["numerics_and_resources"]
    expected = {"methods": list(METHODS), "schedule_ids": list(SCHEDULES),
                "observers": list(OBSERVERS), "ordinary_action_indices": {"17": 2, "29": 3, "43": 3},
                "adaptive_comparator": "origin_richer", "bootstrap_samples": DRAW_COUNT,
                "bootstrap_seed": RNG_SEED, "family_alpha": FAMILY_ALPHA, "comparison_family": FAMILY_SIZE,
                "gain_ci_lower_strict_min": 0., "gain_each_fixed_model_mean_strict_min": 0.,
                "clean_ci_lower_strict_min": -.01, "retention_margin": .01,
                "formal_gain_contrasts": [row[0] for row in COMPARISONS[:3]],
                "clean_noninferiority_candidates": ["ordinary", "origin_field", "origin_richer"],
                "clean_noninferiority_reference": "frozen", "max_outcome_looks": 1,
                "all_methods_retained": True, "single_outcome_look": True}
    require(protocol["schema"] == "hepta.field-bridge.v4.panel-origin-protocol.1" and
            protocol["study_id"] == "hepta.field-bridge.v4.panel-origin-qualification.20261027.1" and
            protocol["seeds"] == list(SEEDS), "Wrong registered V4 study/model identity")
    require(all(q.get(key) == value for key, value in expected.items()), "Qualification contract changed")
    require(resources["task_pairs"] == 512 and resources["clean_pairs"] == 1024 and
            resources["task_conditions"] == protocol["training"]["conditions"] and
            resources["clean_conditions"] == ["clean"] and resources["complete_paths"] == 108,
            "Endpoint shape or complete-path budget changed")
    require(protocol["historical_boundary"]["v3_training_gate_passed"] is False and
            protocol["historical_boundary"]["v3_frozen_runtime_gate_passed"] is False,
            "Historical failed gates cannot be rewritten")


def _read_json(path):
    return json.loads(Path(path).read_text())


def _scope_check(scope, protocol, protocol_sha):
    required = {"study_id": protocol["study_id"], "protocol_sha256": protocol_sha,
                "source_allocation_sha256": protocol["source_allocation_sha256"],
                "source_manifest_sha256": protocol["source_manifest_sha256"],
                "old_training_protocol_sha256": protocol["old_training_protocol_sha256"]}
    require(all(scope.get(key) == value for key, value in required.items()), "Phase scope changed")


def verify_evidence(root, protocol):
    """Bind all completed paths before opening any numeric endpoint values."""
    from .training_qualification import verify_files, verify_seal
    from .source_roles import verify_registry

    validate_protocol(protocol)
    root, here = Path(root).resolve(), Path(__file__).resolve().parent
    require(protocol == _read_json(here / "PROTOCOL.json"), "Analysis uses a different local protocol")
    protocol_sha = file_sha(here / "PROTOCOL.json")
    for phase in ("train", "seal-training", "evaluate", "qualify"):
        require(not list((root / phase).rglob("FAILED.json")), "A recorded phase failure invalidates qualification")
    registry, manifest = verify_registry()
    require(file_sha(here / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"] and
            manifest["manifest_sha256"] == protocol["source_manifest_sha256"] and
            file_sha(here / "SOURCE_IDENTITIES.json.gz") == protocol["source_registry_gzip_sha256"],
            "Registered source identities changed")
    seal = verify_seal(root, protocol)
    seal_sha = file_sha(root / "TRAINING_SEAL.json")
    _scope_check(seal["scope"], protocol, protocol_sha)
    files, policies = {"TRAINING_SEAL.json": seal_sha, **seal["files"]}, {}
    common_source_digest = None
    for seed in SEEDS:
        directory = root / "evaluate" / str(seed)
        start, complete = _read_json(directory / "START.json"), _read_json(directory / "COMPLETE.json")
        require(start["schema"] == "hepta.field-bridge.v4.phase-start.1" and
                start["phase"] == "evaluate" and start["seed"] == seed and
                start["study_id"] == protocol["study_id"] and start["training_seal_sha256"] == seal_sha and
                start["started_unix_ns"] > seal["sealed_unix_ns"], "Endpoint access did not follow complete training seal")
        require(start["requested_roles"] == ["qualification_task", "qualification_clean"] and
                start["loaded_observer_names"] == list(OBSERVERS), "Endpoint phase roles/observers differ")
        _scope_check(start["scope"], protocol, protocol_sha)
        require(start["scope"]["source_files_sha256"] == canonical_sha(start["source_files"]), "Source closure digest changed")
        source_digest = start["scope"]["source_files_sha256"]
        common_source_digest = source_digest if common_source_digest is None else common_source_digest
        require(source_digest == common_source_digest == seal["scope"]["source_files_sha256"], "Sources changed between phases")
        require(start["source_files"].get("field_bridge_v4_20261027/qualification_analysis.py") == file_sha(__file__),
                "Analyzer was not present in the pre-endpoint source freeze")
        verify_files(here.parent, start["source_files"])
        require(complete["schema"] == "hepta.field-bridge.v4.evaluated-seed.1" and
                complete["study_id"] == protocol["study_id"] and complete["seed"] == seed and
                complete["scope"] == start["scope"] and complete["training_seal_sha256"] == seal_sha,
                "Endpoint seed receipt identity changed")
        expected = {f"{method}/schedule-{sid}" for method in METHODS for sid in SCHEDULES}
        require(set(complete["paths"]) == expected and
                complete["source_roles"] == ["qualification_task", "qualification_clean"], "Incomplete endpoint paths/roles")
        required_files = {"START.json", "ASSET_IDENTITIES.json", "ENDPOINTS.npz", "ENDPOINT_IDENTITIES.json",
                          "original-task.npz", "original-clean.npz"}
        required_files.update(f"{path}/{name}" for path in expected for name in ("COMPLETE.json", "task.npz", "clean.npz"))
        require(set(complete["files"]) == required_files, "Incomplete/expanded endpoint evidence inventory")
        verify_files(directory, complete["files"])
        actual_files = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
        require(actual_files == required_files | {"COMPLETE.json"}, "Endpoint files differ from complete inventory")
        files.update({f"evaluate/{seed}/{name}": digest for name, digest in complete["files"].items()})
        files[f"evaluate/{seed}/COMPLETE.json"] = file_sha(directory / "COMPLETE.json")
        for relative, receipt_sha in complete["paths"].items():
            path, trained = directory / relative, root / "train" / str(seed) / relative
            done, previous = _read_json(path / "COMPLETE.json"), _read_json(trained / "COMPLETE.json")
            require(file_sha(path / "COMPLETE.json") == receipt_sha and
                    done["schema"] == "hepta.field-bridge.v4.evaluated-path.1" and done["seed"] == seed and
                    done["study_id"] == protocol["study_id"] and
                    relative == f"{done['method']}/schedule-{done['schedule_id']}", "Endpoint path identity differs")
            require(done["policy_sha256"] == previous["policy_sha256"] and
                    done["trained_checkpoint_sha256"] == previous["checkpoint"]["file_sha256"] and
                    set(done["files"]) == {"task.npz", "clean.npz"}, "Endpoint policy/checkpoint/media binding changed")
            require(all(complete["files"][f"{relative}/{name}"] == digest for name, digest in done["files"].items()),
                    "Nested endpoint media inventory disagrees")
            policies[f"{seed}/{relative}"] = {"policy_sha256": done["policy_sha256"],
                "trained_checkpoint_sha256": done["trained_checkpoint_sha256"], "endpoint_receipt_sha256": receipt_sha}
    return registry, {"protocol_sha256": protocol_sha, "training_seal_sha256": seal_sha,
                      "source_manifest_sha256": manifest["manifest_sha256"],
                      "source_registry_sha256": manifest["registry_sha256"],
                      "source_files_sha256": common_source_digest, "source_files": start["source_files"],
                      "files": files, "paths": policies}


def panel_from_flat(data, panel_name, expected_pairs, conditions):
    """Validate canonical source/condition order before restoring cluster axes."""
    pairs, condition_count = len(expected_pairs), len(conditions)
    rows = pairs * condition_count
    source_ids, row_conditions = data[panel_name + "_source_ids"], data[panel_name + "_conditions"]
    require(np.array_equal(source_ids, np.tile(expected_pairs, (condition_count, 1))) and
            np.array_equal(row_conditions, np.repeat(conditions, pairs)), "Source-pair/condition order changed")
    values = np.asarray(data[panel_name + "_values"], dtype=np.float64)
    original = np.asarray(data["original_" + panel_name], dtype=np.float64)
    require(values.shape == (9, 4, 2, rows) and original.shape == (2, rows), "Wrong flat endpoint dimensions")
    require(np.isfinite(values).all() and np.isfinite(original).all(), "Missing/nonfinite endpoint values")
    values = values.reshape(9, 4, 2, condition_count, pairs).transpose(2, 0, 1, 4, 3)
    original = original.reshape(2, condition_count, pairs).transpose(0, 2, 1)
    return {observer: {**{method: values[oi, mi] for mi, method in enumerate(METHODS)},
                       "frozen": np.broadcast_to(original[oi], (4, pairs, condition_count))}
            for oi, observer in enumerate(OBSERVERS)}


def _verify_media(path, values, source_ids, conditions):
    with np.load(path, allow_pickle=False) as media:
        require(set(media.files) == {"values_reward", "values_audit", "source_ids", "conditions",
                                    "output_sha256", "pixels_u8", "captions_utf8"}, "Incomplete retained hard-output evidence")
        require(np.array_equal(media["source_ids"], source_ids) and
                np.array_equal(media["conditions"], conditions), "Media source/condition alignment differs")
        for oi, observer in enumerate(OBSERVERS):
            require(np.array_equal(media["values_" + observer], values[oi]), "Exported values differ from retained media values")
        hashes = media["output_sha256"]
        require(hashes.shape == (len(conditions),) and all(
            len(value) == 64 and not (set(value) - set("0123456789abcdef")) for value in hashes.tolist()),
            "Output identity inventory is incomplete")


def load_panels(root, protocol, registry):
    combined = {name: {observer: {method: [] for method in (*METHODS, "frozen")} for observer in OBSERVERS}
                for name in ("task", "clean")}
    for seed in SEEDS:
        directory = Path(root) / "evaluate" / str(seed)
        with np.load(directory / "ENDPOINTS.npz", allow_pickle=False) as archive:
            data = {name: archive[name] for name in archive.files}
        require(data["methods"].tolist() == list(METHODS) and data["schedule_ids"].tolist() == list(SCHEDULES) and
                data["observer_names"].tolist() == list(OBSERVERS), "Endpoint axes differ from the locked inventory")
        for panel in ("task", "clean"):
            ids = registry["roles"]["qualification_" + panel]["identities"]
            pairs = np.asarray(ids, dtype=str).reshape(-1, 2)
            conditions = protocol["numerics_and_resources"][panel + "_conditions"]
            reshaped = panel_from_flat(data, panel, pairs, conditions)
            source_ids, row_conditions = data[panel + "_source_ids"], data[panel + "_conditions"]
            _verify_media(directory / ("original-" + panel + ".npz"), data["original_" + panel], source_ids, row_conditions)
            for mi, method in enumerate(METHODS):
                for ri, sid in enumerate(SCHEDULES):
                    _verify_media(directory / method / ("schedule-" + str(sid)) / (panel + ".npz"),
                                  data[panel + "_values"][mi, ri], source_ids, row_conditions)
            for observer in OBSERVERS:
                for method in (*METHODS, "frozen"):
                    combined[panel][observer][method].append(reshaped[observer][method])
    return {name: {observer: {method: np.stack(values) for method, values in methods.items()}
                  for observer, methods in panel.items()} for name, panel in combined.items()}


def qualify(root, protocol):
    """Create one decision from all frozen endpoints; never overwrite or retune."""
    root = Path(root).resolve()
    require(not any((root / name).exists() for name in ("QUALIFICATION.json", "QUALIFICATION_START.json",
                                                       "QUALIFICATION_FAILED.json")), "Qualification was already attempted")
    start_wall, start_cpu = time.perf_counter_ns(), time.process_time_ns()
    registry, bindings = verify_evidence(root, protocol)
    start = {"schema": "hepta.field-bridge.v4.qualification-start.1", "study_id": protocol["study_id"],
             "started_unix_ns": time.time_ns(), "bindings_sha256": canonical_sha(bindings),
             "analysis_source_sha256": file_sha(__file__), "bootstrap_seed": RNG_SEED}
    with (root / "QUALIFICATION_START.json").open("x") as stream:
        json.dump(start, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    try:
        result = analyze_panels(load_panels(root, protocol, registry))
        from .training_qualification import verify_files
        verify_files(root, bindings["files"])
        verify_files(Path(__file__).resolve().parent.parent, bindings["source_files"])
        result.update(schema="hepta.field-bridge.v4.qualification.1", study_id=protocol["study_id"],
                      bindings=bindings, bindings_sha256=canonical_sha(bindings),
                      analysis_source_sha256=start["analysis_source_sha256"],
                      start_sha256=file_sha(root / "QUALIFICATION_START.json"), numpy_version=np.__version__,
                      status="QUALIFICATION_PASSED" if result["passed"] else "QUALIFICATION_FAILED",
                      all_original_substantive_blockers_closed=False, final_or_runtime_authorized=False,
                      model_observer_native_network_calls=0,
                      resources={"wall_ns": time.perf_counter_ns() - start_wall,
                                 "cpu_ns": time.process_time_ns() - start_cpu})
        require(file_sha(__file__) == start["analysis_source_sha256"], "Analysis source changed during execution")
        with (root / "QUALIFICATION.json").open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    except BaseException as error:
        with (root / "QUALIFICATION_FAILED.json").open("x") as stream:
            json.dump({"error_type": type(error).__name__, "error": str(error), "start": start,
                       "partial_evidence_preserved": True, "passed": False}, stream, indent=2, sort_keys=True)
            stream.write("\n")
        raise
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, default=Path(__file__).with_name("PROTOCOL.json"))
    args = parser.parse_args()
    result = qualify(args.run, _read_json(args.protocol))
    print(json.dumps({"study_id": result["study_id"], "passed": result["passed"],
                      "status": result["status"], "draw_sha256": result["draw_sha256"]}))
