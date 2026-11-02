"""Export exact frozen V10 parameters, then validate a real NumPy inference port.

Torch is required only here for export and local reference execution. The
separately frozen numpy_runtime imports no Torch and never replays predictions.
"""

import argparse
import gzip
import json
from pathlib import Path
import shutil

import numpy as np
import scipy
import torch

from . import numpy_runtime as runtime
from experiments.hcsn_v10_followup_20261101.persistent_av import candidate as reference


ROOT = Path(__file__).resolve().parents[3]
RTOL, ATOL = 1e-10, 1e-12
SOURCES = (
    "experiments/hcsn_v12_followup_20261101/model_runtime/numpy_runtime.py",
    "experiments/hcsn_v12_followup_20261101/model_runtime/export_validate.py",
    "experiments/hcsn_v7_support_20261101/content_interface/content_interface.py",
    "experiments/hcsn_v8_execution_20261101/frontend/legacy_v3.py",
    "experiments/hcsn_v8_execution_20261101/scheduler/execution.py",
    "experiments/hcsn_v8_execution_20261101/scheduler/planning.py",
    "experiments/hcsn_v8_execution_20261101/scheduler/historical_service.py",
    "experiments/hcsn_causal_execution_v3/av_probe.py",
)


def export(source, output):
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads((source / "FROZEN.json").read_text())
    protocol = {"schema": "hcsn-v12-frozen-model-numpy-port.v1", "rtol": RTOL, "atol": ATOL,
        "semantic_gate": "Class labels, selected actions/plans, request count and fees exact; numeric forwards fixed rtol/atol",
        "local_stricter_gate": "Same-platform Torch/NumPy common-head output dictionary and serialized hash also exact",
        "cross_host_rule": "Actual probabilities fixed rtol/atol; record actual serialized hash, do not demand identical BLAS last bits",
        "near_ties": "No margin/tolerance relaxation or action replacement; actual differences reject",
        "scope": "Inference-only export of all 16 frozen V10 models; old AV packets, original head and scheduler",
        "torch_reference_version": torch.__version__, "numpy": np.__version__, "scipy": scipy.__version__,
        "source_v10_freeze_sha256": runtime.sha(source / "FROZEN.json"),
        "same_law_model": "Finite fitted CTMC path filter, not HX free boundary or new training",
        "costs": "Each export/reference/runtime stage is externally metered; nested forwards not added twice"}
    runtime.write(output / "PROTOCOL.json", protocol)
    for path, expected in frozen["sources"].items():
        if runtime.sha(Path(path)) != expected:
            raise RuntimeError("Frozen V10 source changed: " + path)
    shutil.copyfile(source / "FROZEN.json", output / "SOURCE_V10_FROZEN.json")
    models = []
    for task in ("async_av", "av_binding"):
        destination = output / task; destination.mkdir()
        data = reference.base.legacy_data(task, "test")
        expected = json.loads((source / task / "HISTORICAL_TEST_INPUTS.json").read_text())
        if reference.base.data_identity(data) != expected:
            raise RuntimeError("Historical input differs from V10")
        np.savez_compressed(destination / "test-packets.npz", **{k: data[k] for k in (
            "x", "observed", "valid", "relative_times", "ids", "group_ids")},
            labels=reference.base.labels_of(data))
        adapter = json.loads((source / task / f"{task}_ADAPTERS.json").read_text())
        from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import LegacyV3Head, restored_checkpoint
        head = LegacyV3Head(task)
        shutil.copyfile(restored_checkpoint(task), destination / "head.npz")
        runtime.write(destination / "head.json", {"head_id": head.head_id,
            "source_checkpoint_sha256": head.checkpoint_sha256, "calibrator": adapter["calibrator"]})
        runtime.write(destination / "INPUT_IDENTITY.json", expected)
        for seed in (91101, 91103):
            shutil.copyfile(source / task / f"LAW-{seed}.json", destination / f"law-{seed}.json")
    for item in frozen["models"]:
        original = source / item["path"]
        if runtime.sha(original) != item["sha256"]:
            raise RuntimeError("Frozen selected model changed")
        parameters = torch.load(original, weights_only=True)
        arrays = {k: value.detach().cpu().numpy().copy() for k, value in parameters.items()}
        if not all(v.dtype == np.float64 and np.isfinite(v).all() for v in arrays.values()):
            raise ValueError("Only finite FP64 frozen parameters are accepted")
        name = f"{item['task']}/{item['family']}-{item['seed']}.npz"
        np.savez_compressed(output / name, **arrays)
        models.append({"task": item["task"], "seed": item["seed"], "family": item["family"],
            "numpy_path": name, "source_pt_sha256": item["sha256"],
            "source_pt_path": item["path"], "shapes": {k: list(v.shape) for k, v in arrays.items()},
            "parameters": sum(v.size for v in arrays.values())})
    artifacts = {str(p.relative_to(output)): runtime.sha(p) for p in output.rglob("*") if p.is_file()}
    runtime.write(output / "MANIFEST.json", {"schema": "hcsn-v12-numpy-bundle.v1", "models": models,
        "source_sha256": {p: runtime.sha(ROOT / p) for p in SOURCES}, "artifact_sha256": artifacts,
        "CI_dependencies": {"numpy": "2.3.5", "scipy": "1.17.0"},
        "torch_required_by_runtime": False, "scientific_admission": False})


class Comparison:
    def __init__(self):
        self.counts, self.maximum = {}, {}

    def close(self, name, actual, expected):
        a, b = np.asarray(actual), np.asarray(expected)
        if a.shape != b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
            raise AssertionError("Invalid forward shape/value: " + name)
        difference = float(np.max(np.abs(a - b))) if a.size else 0.0
        self.maximum[name] = max(self.maximum.get(name, 0.0), difference)
        self.counts[name] = self.counts.get(name, 0) + 1
        np.testing.assert_allclose(a, b, rtol=RTOL, atol=ATOL, err_msg=name)


class CheckedModel(runtime.Model):
    def __init__(self, item, bundle, original, comparison):
        super().__init__(item["family"], bundle / item["numpy_path"])
        self.original, self.comparison = original, comparison

    def update_state(self, row, h):
        actual = super().update_state(row, h)
        with torch.no_grad():
            expected = self.original.update_state(torch.tensor(row), torch.tensor(h)).numpy()
        self.comparison.close("one_forward_hidden", actual, expected)
        return actual

    def predict(self, history, h, belief):
        actual = super().predict(history, h, belief)
        with torch.no_grad():
            expected = self.original.predict(torch.tensor(history), torch.tensor(h), torch.tensor(belief)).numpy()
        self.comparison.close("one_forward_logit", actual, expected)
        return actual


def torch_episode(item, original, head, law, data, index, policy, implementation):
    holder = reference.Holder(original, head, law, item["source_pt_sha256"][:32], implementation)
    object_id = f"v10-{item['task']}-{index}-{item['seed']}-{item['family']}-{implementation}-{policy}"
    valid = data["valid"][index]
    arrays = data["x"][index, valid], data["observed"][index, valid], data["relative_times"][index, valid]
    result = reference.base.run_episode(object_id, reference.base.CacheBudget(65536), head, reference.Forecast(holder),
        reference.base.FixedServiceModel(), reference.base.PreparedPrefixService(*arrays, object_id), lambda _: None,
        clock=reference.base.LogicalClock(), core=holder, horizon=6 if policy == "fixed" else 2,
        fixed_plans=reference.base.fixed_plans("common_full") if policy == "fixed" else None)
    return result, holder.events


def compare_episode(actual, expected, a_updates, e_updates, comparison):
    exact = ("output", "requested_observations", "observation_fee", "latency_fee", "deadline_penalty",
             "timely_output", "output_elapsed_seconds", "source_window_updates", "serialized_output_sha256")
    if any(actual[k] != expected[k] for k in exact):
        raise AssertionError("Actual Torch/NumPy output, request, clock or fees differ")
    if len(actual["decisions"]) != len(expected["decisions"]) or len(a_updates) != len(e_updates):
        raise AssertionError("Actual Torch/NumPy action trajectory differs")
    for a, b in zip(actual["decisions"], expected["decisions"], strict=True):
        if a["selected"] != b["selected"] or a.get("mode") != b.get("mode"):
            raise AssertionError("Actual Torch/NumPy selected plan differs")
        if "plans" in a:
            if [p["plan"] for p in a["plans"]] != [p["plan"] for p in b["plans"]]:
                raise AssertionError("Actual candidate roster differs")
            for ap, bp in zip(a["plans"], b["plans"], strict=True):
                comparison.close("candidate_probability_score", [ap[k] for k in ("correctness", "score", "increment_over_stop")],
                                 [bp[k] for k in ("correctness", "score", "increment_over_stop")])
    for a, b in zip(a_updates, e_updates, strict=True):
        if a["event_id"] != b["event_id"] or a["row"] != b["row"]:
            raise AssertionError("Actual accepted observation differs")
        comparison.close("whole_trajectory_hidden", a["hidden"], b["hidden"])
        comparison.close("whole_trajectory_path", a["path_probability"], b["path_probability"])


def validate(source, bundle, output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = runtime.verify(bundle)
    protocol = json.loads((bundle / "PROTOCOL.json").read_text())
    if (protocol["rtol"], protocol["atol"]) != (RTOL, ATOL):
        raise ValueError("Tolerance changed after export")
    comparison, executions, controls, cases = Comparison(), 0, [], []
    with gzip.open(output / "TRACES.jsonl.gz", "xt") as stream:
        for item in manifest["models"]:
            original_path = source / item["source_pt_path"]
            if runtime.sha(original_path) != item["source_pt_sha256"]:
                raise ValueError("Original Torch reference changed")
            original = reference.Model(item["family"])
            original.load_state_dict(torch.load(original_path, weights_only=True)); original.eval()
            model = CheckedModel(item, bundle, original, comparison)
            with np.load(bundle / item["task"] / "test-packets.npz", allow_pickle=False) as arrays:
                data = {k: arrays[k].copy() for k in arrays.files}
            head = runtime.Head(bundle, item["task"])
            law = json.loads((bundle / item["task"] / f"law-{item['seed']}.json").read_text())["selected"]
            for index in range(len(data["labels"])):
                cases = [(policy, implementation) for policy in ("fixed", "value") for implementation in
                         (("expm", "uniformization") if item["family"] == "filter" else ("expm",))]
                for policy, implementation in cases:
                    actual, updates = runtime.episode(bundle, item, data, index, policy, model, implementation)
                    expected, reference_updates = torch_episode(item, original, head, law, data, index, policy, implementation)
                    compare_episode(actual, expected, updates, reference_updates, comparison)
                    executions += 1
                    cases.append({"task": item["task"], "family": item["family"], "seed": item["seed"],
                        "implementation": implementation, "index": index, "policy": policy,
                        "source_pt_sha256": item["source_pt_sha256"],
                        "reference": {k: expected[k] for k in ("output", "requested_observations", "observation_fee",
                            "latency_fee", "deadline_penalty", "source_window_updates", "decisions", "timely_output",
                            "output_elapsed_seconds", "events", "serialized_output_sha256")}})
                    stream.write(json.dumps({"model": item, "index": index, "policy": policy, "implementation": implementation,
                        "numpy": actual, "numpy_updates": updates,
                        "torch": expected, "torch_updates": reference_updates}, allow_nan=False) + "\n")
                    if item["family"] == "gru" and index == 0 and policy == "fixed":
                        row = np.asarray(updates[0]["row"])[None]; h = np.zeros((1, 64))
                        gi = row @ model.weights["update.weight_ih"].T + model.weights["update.bias_ih"]
                        gh = h @ model.weights["update.weight_hh"].T + model.weights["update.bias_hh"]
                        ir, iz, inn = np.split(gi, 3, 1); hr, hz, hn = np.split(gh, 3, 1)
                        wrong = (h - np.tanh(inn + runtime.expit(iz + hz) * hn)) * runtime.expit(ir + hr) + np.tanh(inn + runtime.expit(iz + hz) * hn)
                        actual_h = model.update_state(row, h)
                        if np.allclose(wrong, actual_h, rtol=RTOL, atol=ATOL):
                            raise AssertionError("GRU reset/update gate swap negative control escaped")
                        controls.append({"task": item["task"], "seed": item["seed"],
                                         "gate_swap_difference": float(np.max(np.abs(wrong - actual_h)))})
    runtime.verify(bundle)
    with gzip.open(output / "FROZEN_REFERENCE.json.gz", "xt") as stream:
        json.dump({"schema": "hcsn-v12-fresh-torch-semantic-reference.v1", "cases": cases,
            "bundle_manifest_sha256": runtime.sha(bundle / "MANIFEST.json"),
            "rtol": RTOL, "atol": ATOL, "source": "Fresh Torch execution on exported actual raw causal AV packets"}, stream,
            allow_nan=False)
    runtime.write(output / "VALIDATION.json", {"status": "passed", "executions": executions,
        "per_forward_checks": comparison.counts, "largest_absolute_errors": comparison.maximum,
        "gru_gate_swap_negative_controls": controls, "rtol": RTOL, "atol": ATOL,
        "all_actions_outputs_requests_fees_exact": True,
        "scope": "All 16 actual frozen models and historical objects, both policies; NumPy and fresh Torch forwards",
        "not_claimed": "production, new scientific confirmation, GPU, physical energy or full deployment economics"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("export", "validate"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args(); torch.set_num_threads(1)
    if args.stage == "export":
        export(args.source, args.output)
    elif args.bundle is None:
        raise ValueError("Validation needs a frozen bundle")
    else:
        validate(args.source, args.bundle, args.output)
