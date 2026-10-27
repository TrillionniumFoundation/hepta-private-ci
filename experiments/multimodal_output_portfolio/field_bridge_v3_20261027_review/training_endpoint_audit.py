"""Audit completed V3 endpoint evidence, development choice, and rollout gates.

Requires all three phase COMPLETE files before reading any outcome arrays.
Reconstructs no model and performs no generator or observer forward calls.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

import numpy as np

from analysis_contract import bootstrap_family
from endpoint_arrays import OBSERVERS, adapt, development_selection, object_sha, require, stack_panels, verify_panel_identity


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_npz(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].copy() for key in archive.files}


def same(actual, expected, location="root"):
    """Exact discrete assertions, explicitly bounded floating arithmetic error."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and set(actual) == set(expected), f"Object keys differ: {location}")
        return max([same(actual[key], value, location + "." + key) for key, value in expected.items()] or [0.])
    if isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), f"List dimensions differ: {location}")
        return max([same(a, b, f"{location}[{i}]") for i, (a, b) in enumerate(zip(actual, expected, strict=True))] or [0.])
    if isinstance(expected, float):
        require(isinstance(actual, (int, float)) and not isinstance(actual, bool) and np.isfinite(actual), f"Invalid number: {location}")
        error = abs(actual - expected)
        require(error <= 1e-12, f"Arithmetic differs by {error}: {location}")
        return error
    require(type(actual) is type(expected) and actual == expected, f"Discrete value differs: {location}")
    return 0.


def checked_child(root, relative):
    value = (root / relative).resolve()
    require(value.is_relative_to(root.resolve()), "Unsafe manifest path")
    return value


def verify_hard(path, expected_values, expected_ids, expected_conditions):
    data = read_npz(path)
    require(data["source_ids"].tolist() == expected_ids and data["conditions"].tolist() == expected_conditions,
            "Saved hard output source/condition rows differ")
    for index, observer in enumerate(OBSERVERS):
        require(np.array_equal(data["values_" + observer], expected_values[index]), "Saved hard values disagree with ENDPOINTS")
    pixels, captions = data["pixels_u8"], data["captions_utf8"]
    count = len(expected_ids)
    require(pixels.dtype == np.uint8 and pixels.shape == (count, 1, 28, 56) and captions.shape == (count,),
            "Incomplete quantized image/caption evidence")
    hashes = [hashlib.sha256(image.tobytes() + str(caption).encode("utf-8")).hexdigest()
              for image, caption in zip(pixels, captions, strict=True)]
    require(hashes == data["output_sha256"].tolist(), "Hard output byte identities differ")
    return count


def verify_policy_binding(record, method, controllers, ordinary_index=None):
    if method.startswith("ordinary"):
        expected = int(method.rsplit("_", 1)[-1]) if method != "ordinary" else ordinary_index
        require(type(expected) is int and 0 <= expected < 4 and record["controller_sha256"] is None and
                all(row["action_index"] == expected for row in record["decisions"]),
                "Ordinary endpoint did not follow its registered constant")
    else:
        require(method in controllers and record["controller_sha256"] == object_sha(controllers[method]),
                "Endpoint path used a different fitted controller")


def verify_seed(root, phase, seed, source, protocol, registry, freeze, freeze_sha):
    directory = root / phase / str(seed)
    complete = json.loads((directory / "COMPLETE.json").read_text())
    require((complete["seed"], complete["stage"], complete["group"]) == (seed, phase, phase), "Phase COMPLETE scope differs")
    expected_inventory = {str(path.relative_to(directory)) for path in directory.rglob("*")
                          if path.is_file() and path != directory / "COMPLETE.json"}
    require(set(complete["files"]) == expected_inventory and "FAILED.json" not in expected_inventory,
            "Phase file inventory is incomplete or contains a failure")
    for relative, digest in complete["files"].items():
        require(file_sha(checked_child(directory, relative)) == digest, "Complete phase file hash differs: " + relative)
    start = json.loads((directory / "START.json").read_text())
    require(start["phase"] == phase and start["seed"] == seed and
            start["protocol_sha256"] == file_sha(source / "PROTOCOL.json") and
            start["freeze_sha256"] == freeze_sha and start["registered_commit"] == freeze["registered_commit"],
            "Phase START is not bound to this registered freeze")
    roles = [phase + suffix for suffix in ("_gradient", "_rehearsal", "_probe", "_guard", "_task", "_clean")]
    require(start["requested_roles"] == complete["source_roles"] == roles and
            complete["primary_or_final_retention_loaded"] is False, "Endpoint phase role allowlist differs")
    for relative, digest in start["source_files"].items():
        require(freeze["source_files"].get(relative) == digest and file_sha(checked_child(source.parent, relative)) == digest,
                "A required frozen scientific source changed")
    assets = json.loads((directory / "ASSET_IDENTITIES.json").read_text())
    require(assets["loaded_observers"] == list(OBSERVERS) and set(assets["models"]) == {str(seed)},
            "Unexpected model or observer access in endpoint phase")
    data = read_npz(directory / "ENDPOINTS.npz")
    require(file_sha(directory / "ENDPOINTS.npz") == complete["endpoint_values_sha256"], "Endpoint aggregate identity differs")
    converted = adapt(data, seed, phase, protocol, registry)
    require(complete["methods"] == converted["methods"] and complete["schedule_ids"] == converted["schedules"] and
            complete["endpoints_shared_across_paths_and_methods"] is True, "Complete endpoint grid differs")
    controller_path = root / "fit" / str(seed) / "CONTROLLERS.json"
    controllers = json.loads(controller_path.read_text())
    require(file_sha(controller_path) == complete["controller_file_sha256"] and controllers["seed"] == seed and
            controllers["training_configuration_sha256"] == object_sha(protocol["training"]),
            "Endpoint stage controller/configuration binding differs")
    ordinary_index = None
    if phase == "audit":
        require(freeze.get("artifacts", {}).get(str(controller_path.relative_to(root))) == file_sha(controller_path),
                "Controller artifact was not frozen before endpoint audit")
        ordinary_index = json.loads((root / "DEVELOPMENT_SELECTION.json").read_text())["ordinary_action_indices"][str(seed)]
    identities = json.loads((directory / "ENDPOINT_IDENTITIES.json").read_text())
    hard_rows, arithmetic_error = 0, 0.
    for name in ("task", "clean"):
        verify_panel_identity(identities[name], converted, name, protocol, registry)
        hard_rows += verify_hard(directory / ("original-" + name + ".npz"), data["original_" + name],
                                data[name + "_source_ids"].tolist(), data[name + "_conditions"].tolist())
    expected_paths = {f"{method}/{schedule}" for method in converted["methods"] for schedule in converted["schedules"]}
    require(set(complete["paths"]) == expected_paths, "A complete endpoint method/path is missing")
    for method_index, method in enumerate(converted["methods"]):
        for path_index, schedule in enumerate(converted["schedules"]):
            path = directory / method / f"schedule-{schedule}"
            record = json.loads((path / "COMPLETE.json").read_text())
            bound = complete["paths"][f"{method}/{schedule}"]
            require(file_sha(path / "COMPLETE.json") == bound["complete_sha256"] and
                    file_sha(path / "checkpoint.pt") == bound["checkpoint_sha256"] == record["checkpoint"]["file_sha256"],
                    "Saved complete path/checkpoint identity differs")
            require((record["seed"], record["stage"], record["group"], record["method"], record["schedule_id"], record["final_step"]) ==
                    (seed, phase, phase, method, schedule, 288) and record["best_step_selection"] is False,
                    "Unexpected endpoint checkpoint/policy/schedule")
            decisions = record["decisions"]
            require([row["step"] for row in decisions] == list(range(0, 288, 48)) and
                    all(type(row["action_index"]) is int and 0 <= row["action_index"] < 4 for row in decisions),
                    "Incomplete path decision sequence")
            verify_policy_binding(record, method, controllers["controllers"], ordinary_index)
            require(all(left["after"] == right["before"] for left, right in zip(decisions[:-1], decisions[1:], strict=True)) and
                    decisions[-1]["after"] == record["final_identity"], "Complete path state chain differs")
            require(record["resources"]["scheduled_gradient_microsteps"] == 288 and
                    record["resources"]["directional_gradient_measurements"] == 6, "Path gradient work differs")
            for name in ("task", "clean"):
                output = path / (name + ".npz")
                hard_rows += verify_hard(output, data[name + "_values"][method_index, path_index],
                                        data[name + "_source_ids"].tolist(), data[name + "_conditions"].tolist())
                require(record["endpoint_files"][name]["file_sha256"] == file_sha(output), "Path output binding differs")
                expected_means = {observer: float(data[name + "_values"][method_index, path_index, oi].mean())
                                  for oi, observer in enumerate(OBSERVERS)}
                arithmetic_error = max(arithmetic_error, same(record["endpoint_files"][name]["means"], expected_means))
    path_count = len(expected_paths)
    require(complete["resources"]["scheduled_gradient_microsteps"] == path_count * 288 and
            complete["resources"]["directional_gradient_measurements"] == path_count * 6, "Stage gradient accounting differs")
    evidence = {"seed": seed, "complete_sha256": file_sha(directory / "COMPLETE.json"),
                "endpoints_sha256": file_sha(directory / "ENDPOINTS.npz"), "files_hashed": len(complete["files"]),
                "paths": path_count, "hard_output_rows_byte_verified": hard_rows,
                "score_values_checked": converted["score_values_checked"], "endpoint_means_max_abs_error": arithmetic_error}
    return converted, evidence


def audit(root, phase, source, freeze_path):
    root, source = Path(root).resolve(), Path(source).resolve()
    protocol = json.loads((source / "PROTOCOL.json").read_text())
    require(all((root / phase / str(seed) / "COMPLETE.json").is_file() for seed in protocol["seeds"]),
            "All three phase COMPLETE records are required before outcome access")
    freeze = json.loads(Path(freeze_path).read_text())
    require(re.fullmatch(r"[0-9a-f]{40}", freeze["registered_commit"]) and phase in freeze["allowed_phases"] and
            freeze["protocol_sha256"] == file_sha(source / "PROTOCOL.json"), "Invalid phase registration/freeze")
    for relative, digest in freeze["source_files"].items():
        require(file_sha(checked_child(source.parent, relative)) == digest, "Frozen source changed: " + relative)
    for relative, digest in freeze.get("artifacts", {}).items():
        require(file_sha(checked_child(root, relative)) == digest, "Frozen prior artifact changed: " + relative)
    allocation = json.loads((source / "SOURCE_ALLOCATION.json").read_text())
    require(file_sha(source / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"] and
            allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Protocol source allocation differs")
    packed = (source / "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(hashlib.sha256(packed).hexdigest() == allocation["registry_gzip_sha256"] and
            hashlib.sha256(raw).hexdigest() == allocation["registry_sha256"], "Source role identities changed")
    registry = json.loads(raw)
    selection_path = root / "DEVELOPMENT_SELECTION.json"
    if phase == "audit":
        relative = str(selection_path.relative_to(root))
        require(freeze.get("artifacts", {}).get(relative) == file_sha(selection_path), "Adaptive/ordinary comparator was not frozen before audit")
        require(json.loads(selection_path.read_text())["passed"], "Audit cannot follow failed development qualification")
    converted, evidence = [], []
    for seed in protocol["seeds"]:
        rows, receipt = verify_seed(root, phase, seed, source, protocol, registry, freeze, file_sha(freeze_path))
        converted.append(rows)
        evidence.append(receipt)
    output = {"schema": "hepta.field-bridge.v3.independent-training-endpoint-audit.1", "status": "pass",
              "phase": phase, "protocol_sha256": file_sha(source / "PROTOCOL.json"), "freeze_sha256": file_sha(freeze_path),
              "source_manifest_sha256": allocation["manifest_sha256"], "seeds": evidence,
              "generator_forwards": 0, "observer_forwards": 0,
              "scope": "Complete endpoint identities, retained hard-byte hashes and arrays, source/freeze/cost bindings and independent statistical arithmetic; no new neural scoring"}
    if phase == "development":
        expected = development_selection(converted, protocol)
        produced = json.loads(selection_path.read_text())
        selected_fields = {key: produced[key] for key in expected if key != "arithmetic_contract"}
        output["selection_max_abs_error"] = same(selected_fields, {k: v for k, v in expected.items() if k != "arithmetic_contract"})
        require(produced["endpoint_file_sha256"] == {str(row["seed"]): row["endpoints_sha256"] for row in evidence}
                and produced["training_configuration_sha256"] == object_sha(protocol["training"])
                and produced["field_family_selection"] is False and produced["no_fresh_audit_outcomes_used"] is True,
                "Development selection provenance differs")
        output.update(passed=expected["passed"], independent_development_selection=expected,
                      selection_matches=True, selection_sha256=file_sha(selection_path))
    else:
        selected = json.loads(selection_path.read_text())["selected_adaptive"]
        all_panels = stack_panels(converted, protocol)
        panels = {name: {observer: {method: values[method if method != "selected_adaptive" else selected]
                        for method in ("frozen", "ordinary", "field", "selected_adaptive")}
                        for observer, values in original.items()} for name, original in all_panels.items()}
        gate = protocol["training_audit_gate"]
        comparisons = [{"name": value, "panel": "task", "left": value.split("-")[0],
                        "right": value.split("-")[1], "kind": "gain"} for value in gate["gain_contrasts"]]
        comparisons += [{"name": method + "-frozen-clean", "panel": "clean", "left": method,
                         "right": gate["retention_reference"], "kind": "noninferiority", "margin": gate["retention_margin"]}
                        for method in gate["retention_candidates"]]
        result = bootstrap_family(panels, comparisons, draws=gate["bootstrap_samples"], rng_seed=gate["bootstrap_seed"],
                                  family_alpha=gate["family_alpha"], family_comparisons=gate["family_comparisons"],
                                  expected_seeds=len(protocol["seeds"]), expected_rollouts=gate["fixed_complete_rollouts_per_seed"])
        output.update(passed=result["complete_family_pass"], independent_audit_gate=result,
                      selected_adaptive=selected, selection_sha256=file_sha(selection_path))
    output["reviewer_source_files"] = {name: file_sha(Path(__file__).with_name(name))
                                      for name in ("training_endpoint_audit.py", "endpoint_arrays.py", "analysis_contract.py")}
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True)
    parser.add_argument("--phase", choices=("development", "audit"), required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--freeze", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    require(not output.is_relative_to((Path(args.run) / args.phase).resolve()), "Audit receipts must stay outside frozen phase evidence")
    started = time.monotonic()
    result = audit(args.run, args.phase, args.source, args.freeze)
    result["elapsed_seconds"] = time.monotonic() - started
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "phase", "passed", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
