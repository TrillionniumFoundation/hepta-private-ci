"""Independent convex-reference audit of old calibration fits, calibration only."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_calibrated_curve import inventory, sha_file, verify_prepared, write_json
from cell_calibration_v2 import apply_calibrator_logits, group_weights, weighted_nll
from cell_learning_baselines import FrozenBaselines
from cell_learning_models import NumpyCellHead


def objective_derivatives(theta, x, labels, weights):
    alpha, bias = theta
    score = alpha*x+bias
    e = np.exp(-np.abs(score))
    p = np.where(score >= 0, 1/(1+e), e/(1+e))
    p0 = 1/(1+np.exp(-bias))
    loss = float(weights @ (np.logaddexp(0, score)-labels*score)
        + np.logaddexp(0, bias)+np.logaddexp(0, -bias)+.0005*alpha**2)
    error, variance = weights*(p-labels), weights*p*(1-p)
    gradient = np.array([error@x+.001*alpha, error.sum()+2*p0-1])
    hessian = np.array([[variance@(x*x)+.001, variance@x],
                        [variance@x, variance.sum()+2*p0*(1-p0)]])
    return loss, gradient, hessian


def reference_minimum(x, labels, weights):
    """Profile the intercept by bisection, then bisect the convex scale profile.

    This uses no Newton step, Hessian solve, line search or old fitting function.
    """
    def profile(alpha):
        lo, hi = -12.0, 12.0
        if objective_derivatives([alpha, lo], x, labels, weights)[1][1] >= 0:
            return lo
        if objective_derivatives([alpha, hi], x, labels, weights)[1][1] <= 0:
            return hi
        for _ in range(56):
            middle = (lo+hi)/2
            if objective_derivatives([alpha, middle], x, labels, weights)[1][1] > 0:
                hi = middle
            else:
                lo = middle
        return (lo+hi)/2
    low_bias = profile(0)
    if objective_derivatives([0, low_bias], x, labels, weights)[1][0] >= 0:
        return np.array([0., low_bias])
    high_bias = profile(32)
    if objective_derivatives([32, high_bias], x, labels, weights)[1][0] <= 0:
        return np.array([32., high_bias])
    lo, hi = 0., 32.
    for _ in range(56):
        middle = (lo+hi)/2
        bias = profile(middle)
        if objective_derivatives([middle, bias], x, labels, weights)[1][0] > 0:
            hi = middle
        else:
            lo = middle
    alpha = (lo+hi)/2
    return np.array([alpha, profile(alpha)])


def audit_fit(logits, labels, weights, fitted):
    raw = logits[:, 1]-logits[:, 0]
    center = float(np.average(raw, weights=weights))
    scale = max(float(np.sqrt(np.average((raw-center)**2, weights=weights))), 1e-8)
    if not np.allclose([center, scale], [fitted["center"], fitted["scale"]], atol=1e-14, rtol=1e-13):
        raise ValueError("reconstructed calibration scores differ from fitted standardization")
    x = (raw-center)/scale
    theta = np.array([fitted["alpha"], fitted["bias"]])
    value, gradient, hessian = objective_derivatives(theta, x, labels, weights)
    projected = gradient.copy()
    projected[((theta <= [0, -12]) & (gradient > 0)) | ((theta >= [32, 12]) & (gradient < 0))] = 0
    reference = reference_minimum(x, labels, weights)
    reference_value = objective_derivatives(reference, x, labels, weights)[0]
    recorded_nll = weighted_nll(apply_calibrator_logits(logits, fitted), labels, weights)
    return {"objective_gap_above_independent_reference": value-reference_value,
        "reference_alpha": float(reference[0]), "reference_bias": float(reference[1]),
        "projected_gradient_per_group": float(np.abs(projected).max()/(weights.sum()+2)),
        "hessian_min_eigenvalue": float(np.linalg.eigvalsh(hessian).min()),
        "recorded_calibration_nll_absolute_error": abs(recorded_nll-fitted["weighted_nll"]),
        "recorded_penalized_objective_absolute_error": abs(value-fitted["penalized_objective_final"]),
        "alpha": fitted["alpha"], "bias": fitted["bias"], "scale": scale,
        "raw_inverse_temperature": fitted["alpha"]/scale, "declared_converged": fitted["converged"],
        "group_mass": float(weights.sum()), "calibration_rows": len(labels)}


def audit_study(dataset, features, study, output):
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    dataset, features, study, output = map(Path, (dataset, features, study, output))
    if output.exists():
        raise ValueError("new calibration-only audit directory required")
    files = [dataset, features/"report.json", features/"features.npz", study/"study-plan.json"]
    pins = {str(path): sha_file(path) for path in files}
    data = json.loads(dataset.read_bytes())
    feature_report = json.loads((features/"report.json").read_bytes())
    study_plan = json.loads((study/"study-plan.json").read_bytes())
    if (feature_report["plan"]["dataset_sha256"] != pins[str(dataset)]
            or study_plan["dataset_sha256"] != pins[str(dataset)]
            or feature_report["plan"]["source_ids"] != [r["source_id"] for r in data["rows"]]
            or feature_report["feature_archive_sha256"] != pins[str(features/"features.npz")]):
        raise ValueError("frozen source/feature bindings differ")
    with np.load(features/"features.npz", allow_pickle=False) as archive:
        matrix = archive["features"]
    if hashlib.sha256(matrix.tobytes()).hexdigest() != feature_report["feature_tensor_sha256"]:
        raise ValueError("feature tensor differs")
    by_id = {row["source_id"]: (index, row) for index, row in enumerate(data["rows"])}
    records, prepared_roots = [], []
    for task in study_plan["tasks"]:
        prepared = study/task/"prepared"
        frozen = verify_prepared(prepared)
        prepared_roots.append(prepared)
        pins[str(prepared/"seal.json")] = sha_file(prepared/"seal.json")
        selected = [by_id[source] for source in frozen["plan"]["calibration_source_ids"]]
        if any(row["split"] != "calibration" for _, row in selected):
            raise ValueError("audit accepts only the original calibration half")
        if set(frozen["plan"]["calibration_source_ids"]) & set(frozen["plan"]["tuning_source_ids"]):
            raise ValueError("old tuning and calibration sources overlap")
        cx = matrix[[index for index, _ in selected]]
        cy = np.array([row["labels"][task] for _, row in selected], dtype=np.int64)
        cr = [{k: row[k] for k in ("source_id", "group_id", "text")} for _, row in selected]
        weights = group_weights(cr)
        for run in frozen["runs"]:
            bank = prepared/run["directory"]
            with np.load(bank/"baseline.npz", allow_pickle=False) as archive:
                baseline = FrozenBaselines(archive["features"], archive["labels"],
                    json.loads((bank/"baseline_rows.json").read_bytes()), 2)
            for arm, spec in run["arms"].items():
                if "calibration" not in spec:
                    continue
                if spec["kind"] == "head":
                    head = NumpyCellHead.load(prepared/spec["artifact"], feature_report["feature_identity"])
                    logits = head.predict_logits(cx)
                else:
                    logits = baseline.predict(arm, cx, cr)["logits"]
                records.append({"task": task, "seed": run["seed"], "budget": run["budget"],
                    "arm": arm, **audit_fit(logits, cy, weights, spec["calibration"])})
    for prepared in prepared_roots:
        verify_prepared(prepared)
    if any(sha_file(path) != value for path, value in pins.items()):
        raise ValueError("audit sources changed")
    result = {"schema": "hepta.old-calibration-independent-audit.v1", "study": str(study),
        "fit_count": len(records), "records": records, "input_sha256": pins,
        "all_converged": all(r["declared_converged"] for r in records),
        "maximum_objective_gap": max(r["objective_gap_above_independent_reference"] for r in records),
        "maximum_projected_gradient_per_group": max(r["projected_gradient_per_group"] for r in records),
        "maximum_nll_reconstruction_error": max(r["recorded_calibration_nll_absolute_error"] for r in records),
        "maximum_raw_inverse_temperature": max(r["raw_inverse_temperature"] for r in records),
        "scope": "training artifacts and calibration-half predictions only; no heldout files or statistics",
        "reference_solver": "nested monotone bisection,56iterations each; no old optimizer calls",
        "source_sha256": sha_file(__file__), "new_encoder_forwards": 0, "new_head_updates": 0,
        "new_evaluated_condition": False, "wall_ns": time.perf_counter_ns()-began,
        "cpu_ns": time.process_time_ns()-cpu, "quality_promotion": False}
    output.mkdir(parents=True)
    write_json(output/"report.json", result)
    write_json(output/"seal.json", {"schema": "hepta.calibration-audit-seal.v1", "files": inventory(output)})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "features", "study", "output"):
        parser.add_argument("--"+name, required=True)
    result = audit_study(**vars(parser.parse_args()))
    print(json.dumps({k: v for k, v in result.items() if k not in ("records", "input_sha256")}))
