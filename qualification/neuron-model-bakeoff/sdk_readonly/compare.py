"""Fail-closed comparison of two separately recorded diagnostic profiles."""
if not __debug__:
    raise SystemExit("optimized Python disables evidence checks; run without -O")

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from provenance import validate_workspace

CODE = Path(__file__).resolve().parent


def compare_arrays(left, right):
    if left.dtype != right.dtype or left.shape != right.shape:
        raise ValueError("array dtype/shape mismatch")
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("nonfinite comparison input")
    if left.tobytes() != right.tobytes():
        raise ValueError("array bytes differ")
    return {"bit_identical": True, "max_abs_delta": float(np.max(np.abs(left.astype(np.float64) - right.astype(np.float64)))) if left.size else 0.0}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_recorded_array(directory, entry):
    path = directory / entry["file"]
    if path.name != entry["file"] or sha(path) != entry["sha256"]:
        raise ValueError("array path/hash mismatch")
    array = np.load(path, allow_pickle=False)
    if list(array.shape) != entry["shape"]:
        raise ValueError("array metadata shape mismatch")
    if str(array.dtype) != entry["dtype"].removeprefix("torch."):
        raise ValueError("array metadata dtype mismatch")
    return array


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    ROOT = args.workspace.resolve()
    dirs = [ROOT / name for name in ("official_reference", "readonly_candidate")]
    a, b = [json.loads((d / "report.json").read_text()) for d in dirs]
    assert a["profile"] == "official_reference" and b["profile"] == "readonly_candidate"
    cases = json.loads((ROOT / "cases.json").read_text())
    expected_names = [case["name"] for case in cases]
    assert len(expected_names) == 7 and len(set(expected_names)) == 7
    for report in (a, b):
        for key, file in (("source_manifest_sha256", "source-manifest.json"), ("cases_sha256", "cases.json")):
            if report[key] != sha(ROOT / file):
                raise ValueError("recorded identity differs from current file: " + file)
        assert len(report["forward_observations"]) == 7
        assert [record["case"] for record in report["forward_observations"]] == expected_names
    if a["provenance_sha256"] != sha(CODE / "provenance.py"):
        raise ValueError("provenance helper changed since execution")
    if a["driver_sha256"] != sha(CODE / "run_probe.py"):
        raise ValueError("probe driver changed since the recorded execution")
    if (ROOT / "cases.json").read_bytes() != (CODE / "cases.json").read_bytes():
        raise ValueError("workspace cases differ from the source fixture")
    manifest = validate_workspace(ROOT)
    vendor = ROOT / "vendor/laya"
    assert {str(path.relative_to(vendor)): sha(path) for path in sorted(vendor.rglob("*.py"))} == manifest["derived_files"]
    assert b["derived_profile"] == manifest["profile"]
    for key in ("driver_sha256", "provenance_sha256", "source_manifest_sha256", "cases_sha256", "original_snapshot", "source_guard_commit", "source_guard_sha256", "source_run_models_sha256", "packages", "cpu_threads", "cpu_affinity", "device", "dtype", "calibration_identity", "parameters", "raw_temperature", "effective_temperature", "raw_buckets", "effective_buckets", "cpu_fallback_count", "forward_calls"):
        if a[key] != b[key]:
            raise ValueError("profile mismatch: " + key)
    assert a["original_snapshot_unchanged"] and b["original_snapshot_unchanged"]
    assert a["runtime_copy_observed_changes"] == ["tokenizer/tokenizer_config.json"]
    assert b["runtime_copy_observed_changes"] == []
    assert a["forward_calls"] == b["forward_calls"] == 7
    assert sum(x["inputs"]["input_ids"]["shape"][0] for x in a["forward_observations"]) == 17
    assert len(a["results"]) == 7
    for index in (4, 5):
        assert a["results"][index][0]["usage"]["truncated"]
        assert a["results"][index][0]["usage"]["state_tokens_dropped"] > 0
    observations = []
    actual_rows = 0
    if len(a["forward_observations"]) != len(b["forward_observations"]):
        raise ValueError("forward count mismatch")
    required = {"input_ids", "attention_mask", "marker_pos", "marker_mask", "qtype"}
    for case, left, right in zip(cases, a["forward_observations"], b["forward_observations"]):
        assert left["case"] == right["case"]
        assert set(left["inputs"]) == required, "pinned sequential layout must have exactly five inputs"
        assert set(left["outputs"]) == {"option_logits", "action_logits"}
        for section in ("inputs", "outputs"):
            assert set(left[section]) == set(right[section])
            for name in left[section]:
                arrays = []
                for d, entry in zip(dirs, (left[section][name], right[section][name])):
                    arrays.append(load_recorded_array(d, entry))
                if section == "inputs" and name == "input_ids":
                    assert arrays[0].shape[0] == len(case["states"]) * len(case["questions"])
                    actual_rows += arrays[0].shape[0]
                observations.append({"case": left["case"], "section": section, "name": name, **compare_arrays(*arrays)})
    assert actual_rows == 17
    assert a["results"] == b["results"], "decoded SDK results differ"
    result = {"kind": "BOUNDED_READONLY_SDK_PARITY_NOT_QUALIFICATION", "status": "exact_parity_observed", "profile": b["derived_profile"], "reference_report_sha256": sha(dirs[0] / "report.json"), "candidate_report_sha256": sha(dirs[1] / "report.json"), "comparison_driver_sha256": sha(Path(__file__)), "manifest_sha256": sha(ROOT / "source-manifest.json"), "cases_sha256": a["cases_sha256"], "forward_calls_per_profile": a["forward_calls"], "forward_rows_per_profile": actual_rows, "tensor_comparisons": len(observations), "all_model_inputs_and_both_raw_outputs_bit_identical": True, "decoded_results_identical": True, "original_unchanged": True, "candidate_artifacts_unchanged": True, "official_reference_mutation_retained": a["runtime_copy_observed_changes"], "calibration_unchanged": True, "observations": observations, "limits": ["Pinned Multilingual checkpoint, CPU fp32 eager, only enumerated public example/mechanical fixture inputs", "Not all inputs, devices, batch sizes or SDK releases", "Original Laya SDK still rewrites tokenizer config", "English/Typed 11+ calibration mismatch remains blocked under the unchanged strict default", "Derived candidate removes tokenizer cache; no startup/performance equivalence claim", "Local-only/no-custom-code assurance is for the validated snapshot and diagnostic driver, not arbitrary Agent inputs", "No task quality, independent dataset, future benefit, performance parity or acceptance claim"], "original_protocol_changed": False, "independent_acceptance": False, "all_blockers_closed": False}
    (ROOT / "parity-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "observations"}, indent=2))


if __name__ == "__main__":
    main()
