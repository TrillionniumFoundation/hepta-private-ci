"""Read-only audit of completed full-joint training artifacts.

This script imports no model or training code, constructs no task graph, and
reads no evaluation/heldout output. Adam is replayed algebraically from saved
gradient vectors; no candidate is trained, written, selected or replaced.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np


HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[2]
MODES = ("direct", "continuous", "clocked", "first_passage")
SEEDS = tuple(range(11, 16))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_key(path):
    path = Path(path).resolve()
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def group(name):
    if name.startswith("core.raw_diffusion"): return "diffusion"
    if name.startswith("core.raw_boundary"): return "boundary"
    if name.startswith("core.raw_reset"): return "reset"
    if name.startswith("core.raw_recovery"): return "recovery"
    return name.split(".")[0]


def case_audit(item, base, registration, inputs):
    mode, seed = item["mode"], item["seed"]
    key, folder = f"{mode}_{seed}", base / "cases" / f"{mode}_{seed}"
    issues = []

    def check(condition, message):
        if not condition:
            issues.append(message)

    def read(name):
        path = folder / name
        inputs[input_key(path)] = sha(path)
        return json.loads(path.read_text())

    training, initial, final = read("TRAINING.json"), read("initial.json"), read("final.json")
    for filename, field in (("TRAINING.json", "training_sha256"), ("initial.json", "initial_sha256"), ("final.json", "final_sha256")):
        check(sha(folder / filename) == item[field], "manifest identity: " + filename)
    source = HERE.parent / "round7/evidence/fits_primary" / f"{mode}_none_{seed}.json"
    inputs[str(source.relative_to(REPO))] = sha(source)
    check(training["source_checkpoint"] == str(source.relative_to(REPO)), "source checkpoint path")
    check(sha(source) == training["source_checkpoint_sha256"] == registration["sources_checkpoints"][key], "source checkpoint hash")
    original = json.loads(source.read_text())["state_dict"]
    check(training["registration_sha256"] == sha(base / "REGISTRATION.json"), "training registration hash")
    check(training["failure"] is None and training["updates_applied"] == 30, "failure/update count")
    check(len(training["curves"]) == 31 and [r["update"] for r in training["curves"]] == list(range(31)), "31 complete curve records")
    curve_path = folder / "curve.jsonl"
    inputs[input_key(curve_path)] = sha(curve_path)
    check([json.loads(line) for line in curve_path.read_text().splitlines()] == training["curves"], "curve.jsonl agrees with TRAINING")
    check(initial["metadata"]["update"] == 0 and final["metadata"]["update"] == 30, "checkpoint update indices")
    for record in (initial, final):
        check(record["schema"] == "hepta.full-joint-policy.v1", "checkpoint schema")
        check(record["configuration"] == {"hidden": 12, "mode": mode, "n_grid": 15}, "checkpoint configuration")
        version = "r8-full-joint-direct-v1" if mode == "direct" else "r8-brownian-images-v1"
        check(record["kernel_version"] == version, "checkpoint kernel version")
    before = {name: np.asarray(value, dtype=np.float64) for name, value in initial["state_dict"].items()}
    after = {name: np.asarray(value, dtype=np.float64) for name, value in final["state_dict"].items()}
    check(before.keys() == after.keys() == original.keys(), "checkpoint tensor keys")
    for name in before:
        check(np.array_equal(before[name], np.asarray(original[name], dtype=np.float64)), "exact R7 tensor inheritance: " + name)
        check(np.isfinite(before[name]).all() and np.isfinite(after[name]).all(), "finite tensor: " + name)
    active, inactive, layout = training["active_parameters"], training["frozen_parameters"], training["gradient_layout"]
    parameters = {name for name in before if name.startswith(("content.", "drive.", "readout.", "core.raw_"))}
    expected_inactive = {"core.raw_leak"}
    if mode == "direct":
        expected_inactive = {name for name in parameters if name.startswith(("core.", "drive."))}
    elif mode == "continuous":
        expected_inactive |= {"core.raw_reset_plus", "core.raw_reset_minus", "core.raw_recovery"}
    check(set(inactive) == expected_inactive and len(inactive) == len(expected_inactive), "independent frozen parameter registry")
    check(set(active) == parameters-expected_inactive and len(active) == len(parameters-expected_inactive), "independent active parameter registry")
    check([row["name"] for row in layout] == active, "active parameters agree with gradient layout")
    cursor = 0
    for row in layout:
        check(row["offset"] == cursor and row["elements"] == before[row["name"]].size and row["shape"] == list(before[row["name"]].shape), "contiguous correct layout: " + row["name"])
        cursor += row["elements"]
    gradient_path = folder / "gradients.npz"
    inputs[input_key(gradient_path)] = sha(gradient_path)
    with np.load(gradient_path, allow_pickle=False) as archive:
        check(archive.files == ["before_clip"], "gradient archive fields")
        gradients = archive["before_clip"].copy()
    check(gradients.shape == (30, cursor), "gradient shape")
    check(np.isfinite(gradients).all(), "all recorded gradients finite")
    if gradients.shape != (30, cursor) or not np.isfinite(gradients).all():
        return {"case": key, "passed": False, "issues": issues}
    expected_core = [] if mode == "direct" else ["core.raw_diffusion", "core.raw_boundary"]
    if mode in ("clocked", "first_passage"):
        expected_core += ["core.raw_reset_plus", "core.raw_reset_minus", "core.raw_recovery"]
    check([name for name in active if name.startswith("core.")] == expected_core, "effective core registry")
    settings = registration["protocol"]["training"]
    scalar_records = []
    for name in expected_core:
        row = next(row for row in layout if row["name"] == name)
        piece = gradients[:, row["offset"]:row["offset"]+row["elements"]]
        changed = float(np.max(np.abs(after[name]-before[name])))
        nonzero = int(np.count_nonzero(np.max(np.abs(piece), axis=1)))
        check(nonzero > 0 and changed > 0, "effective core is connected and updated: " + name)
        scalar_records.append({"name": name, "initial_raw_value": float(before[name]), "final_raw_value": float(after[name]),
            "absolute_change": changed, "nonzero_gradient_updates": nonzero,
            "minimum_signed_gradient": float(piece.min()), "maximum_signed_gradient": float(piece.max()),
            "minimum_absolute_gradient": float(np.abs(piece).min()), "maximum_absolute_gradient": float(np.abs(piece).max()),
            "maximum_gradient_below_adam_epsilon": bool(np.abs(piece).max() < settings["epsilon"])})
    for name in inactive:
        check(np.array_equal(before[name], after[name]), "inactive parameter unchanged: " + name)
    head0_unchanged = head0_zero_gradient = True
    for name in ("readout.2.weight", "readout.2.bias"):
        head0_unchanged &= np.array_equal(before[name][:4], after[name][:4])
        row = next(row for row in layout if row["name"] == name)
        piece = gradients[:, row["offset"]:row["offset"]+row["elements"]].reshape((30,)+tuple(row["shape"]))
        head0_zero_gradient &= np.count_nonzero(piece[:, :4]) == 0
    check(head0_unchanged and head0_zero_gradient, "head 0 output-layer parameters/gradients")
    for name in set(before)-set(active)-set(inactive):
        check(np.array_equal(before[name], after[name]), "buffer unchanged: " + name)
    for name, record in training["parameter_changes"].items():
        change = after[name]-before[name]
        check(np.isclose(float(np.abs(change).max()), record["max_absolute_change"], rtol=0, atol=1e-15), "reported max change: " + name)
        check(np.isclose(float(np.linalg.norm(change.ravel())), record["l2_change"], rtol=1e-12, atol=1e-15), "reported l2 change: " + name)
        check(record["requires_grad"] == (name in active), "reported trainability: " + name)
    check(settings["optimizer"] == "Adam" and settings["weight_decay"] == 0, "registered Adam formula scope")
    theta = np.concatenate([before[row["name"]].reshape(-1) for row in layout])
    momentum, variance = np.zeros_like(theta), np.zeros_like(theta)
    beta1, beta2 = settings["betas"]
    group_error, norm_error, clipped_steps = 0., 0., 0
    for update, gradient in enumerate(gradients, 1):
        norm = float(np.linalg.norm(gradient))
        curve = training["curves"][update-1]
        norm_error = max(norm_error, abs(norm-curve["unclipped_gradient_norm"]))
        multiplier = min(1., settings["clip_norm"]/(norm+1e-6))
        clipped_steps += int(multiplier < 1.)
        clipped = gradient * multiplier
        norm_error = max(norm_error, abs(float(np.linalg.norm(clipped))-curve["clipped_gradient_norm"]))
        sums = {}
        for row in layout:
            piece = gradient[row["offset"]:row["offset"]+row["elements"]]
            tag = group(row["name"])
            sums[tag] = sums.get(tag, 0.) + float(piece@piece)
        for tag, total in sums.items():
            group_error = max(group_error, abs(math.sqrt(total)-curve["gradient_norm_by_group"][tag]))
        momentum = beta1*momentum + (1-beta1)*clipped
        variance = beta2*variance + (1-beta2)*clipped**2
        theta -= settings["learning_rate"]*(momentum/(1-beta1**update))/(np.sqrt(variance/(1-beta2**update))+settings["epsilon"])
    saved_final = np.concatenate([after[row["name"]].reshape(-1) for row in layout])
    adam_error = float(np.abs(theta-saved_final).max())
    check(adam_error <= 5e-13, "saved gradients independently reproduce final Adam parameters")
    check(norm_error <= 1e-12 and group_error <= 1e-12, "recorded gradient norms")
    return {"case": key, "passed": not issues, "issues": issues,
        "gradient_shape": list(gradients.shape), "gradient_scalar_count": gradients.size,
        "all_gradients_finite": bool(np.isfinite(gradients).all()), "effective_core_scalars": scalar_records,
        "inactive_parameters": inactive, "head0_output_layer_unchanged": bool(head0_unchanged),
        "head0_output_gradient_zero": bool(head0_zero_gradient), "adam_replay_maximum_error": adam_error,
        "maximum_gradient_norm_error": norm_error, "maximum_group_norm_error": group_error,
        "updates_with_active_gradient_clipping": clipped_steps,
        "training_soft_utility_change": training["curves"][-1]["exact_soft_utility"]-training["curves"][0]["exact_soft_utility"],
        "declared_registration_commit": training["declared_registration_commit"]}


def audit(base):
    base = Path(base).resolve()
    started, inputs, issues = time.perf_counter(), {}, []
    registration_path, candidates_path = base / "REGISTRATION.json", base / "CANDIDATES.json"
    registration = json.loads(registration_path.read_text())
    candidates = json.loads(candidates_path.read_text())
    for path in (registration_path, candidates_path, HERE / "FREEZE.json"):
        inputs[input_key(path)] = sha(path)
    expected = {(mode, seed) for mode in MODES for seed in SEEDS}
    actual = [(r["mode"], r["seed"]) for r in candidates["cases"]]
    if set(actual) != expected or len(actual) != 20:
        raise ValueError("candidate manifest must contain exactly the registered 20 distinct fits")
    if candidates["registration_sha256"] != sha(registration_path):
        issues.append("candidate registration identity")
    if registration["base_freeze_sha256"] != sha(HERE / "FREEZE.json"):
        issues.append("original FREEZE identity")
    for name, expected_hash in registration["sources"].items():
        path = (HERE / name).resolve()
        if not path.is_relative_to(REPO):
            raise ValueError("registered source is outside the repository")
        inputs[str(path.relative_to(REPO))] = sha(path)
        if sha(path) != expected_hash:
            issues.append("registered source changed: " + name)
    cases = []
    for item in candidates["cases"]:
        try:
            cases.append(case_audit(item, base, registration, inputs))
        except Exception as error:
            cases.append({"case": f"{item['mode']}_{item['seed']}", "passed": False,
                          "issues": [repr(error)], "traceback": traceback.format_exc()})
    unchanged = all(sha(REPO / name) == value for name, value in inputs.items())
    if not unchanged:
        issues.append("an input changed during the read-only audit")
    valid = [case for case in cases if "gradient_shape" in case]
    return {"schema": "hepta.full-joint.training-artifact-audit.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "diagnostic_source_sha256": sha(__file__),
        "evidence_directory": input_key(base),
        "scope": "Post-training read-only artifact audit. No model imports, task graphs, training calls, candidate writes, evaluation outputs or heldout execution.",
        "passed": not issues and all(case["passed"] for case in cases), "issues": issues,
        "inputs_unchanged": unchanged, "input_sha256": inputs, "cases": cases,
        "total_gradient_vectors": sum(case["gradient_shape"][0] for case in valid),
        "total_gradient_scalars": sum(case["gradient_scalar_count"] for case in valid),
        "maximum_adam_replay_error": max((case["adam_replay_maximum_error"] for case in valid), default=None),
        "maximum_group_norm_error": max((case["maximum_group_norm_error"] for case in valid), default=None),
        "interpretation": ["Gradient replay verifies consistency of recorded gradients, optimizer settings and final weights; it does not independently recompute model gradients.",
            "Nonzero core gradients or tiny parameter movements do not establish a useful learned contribution. Raw gradient ranges are retained for every effective scalar.",
            "Head 0 output-layer tensors are unchanged, but shared hidden/content/core updates can change head 0 function outputs.",
            "The registered source and checkpoint identities are checked locally; this script does not independently query the remote registration commit."],
        "numpy_version": np.__version__, "wall_seconds": time.perf_counter()-started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=HERE / "evidence/full_joint_v1",
                        help="Completed training evidence directory; no evaluation artifacts are read.")
    parser.add_argument("--output", type=Path,
                        help="Exclusive new report path; defaults to EVIDENCE/training_artifact_audit.json.")
    args = parser.parse_args()
    output = args.output or args.evidence / "training_artifact_audit.json"
    if output.exists():
        parser.error("output already exists; choose a new --output path")
    result = audit(args.evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("passed", "total_gradient_vectors", "total_gradient_scalars", "maximum_adam_replay_error", "inputs_unchanged")}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
