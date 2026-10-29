"""Additional frozen near-boundary regression after the oracle repair."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from .operators import RegenerativeSpec, operator_features
from .validate_operators import reference_features

HERE = Path(__file__).resolve().parent


def run():
    protocol_bytes = (HERE/"NUMERICAL_DOMAIN_EXTENSION.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    arrays, identities, defects = [], [], []
    for path in sorted((HERE/"aborted_operator_quadrature_01").glob("*/*.npz")):
        with np.load(path) as data:
            arrays.extend(data["contexts"])
            defects.extend(data["mass_defects"])
            identities.extend([str(path.relative_to(HERE))+":"+str(i) for i in range(len(data["contexts"]))])
    contexts = np.asarray(arrays)
    if len(contexts) < 16:
        raise ValueError("original training/development oracle records are required")
    selection = protocol["selection"]
    worst = np.argsort(np.abs(defects))[-selection["worst_absolute_old_mass_defect"]:]
    random = np.random.default_rng(selection["random_seed"]).choice(
        len(contexts), selection["random_train_development_rows"], replace=False)
    rows = [(identities[i], contexts[i], float(defects[i])) for i in np.r_[worst, random]]
    corners = itertools.product(selection["corner_mu"], selection["corner_sigma"], selection["corner_reset"],
                                selection["corner_refractory"], selection["corner_horizon"])
    for i, (mu, sigma, reset, refractory, horizon) in enumerate(corners):
        row = np.array([mu, sigma, reset, refractory, 0 if i%2 == 0 else .4, .015, horizon, 0])
        rows.append(("near_boundary_corner:"+str(i), row, None))
    results = []
    for name, row, old_defect in rows:
        mu, sigma, reset, refractory, discount, distance, horizon, pending = row
        spec = RegenerativeSpec(mu, sigma, reset, refractory, discount)
        az, rz = protocol["active_decays"], [0, 1/refractory, 3/refractory]
        actual = operator_features(spec, distance, horizon, active_decays=az,
                                   refractory_decays=rz, pending_refractory=pending)
        if pending > horizon:
            reference = {"features": np.r_[np.zeros(len(az)), np.exp(-np.asarray(rz)*(pending-horizon))],
                         "expected_events": 0, "discounted_events": 0, "discounted_active_time": 0}
        else:
            reference = reference_features(spec, distance if pending == 0 else reset,
                                           horizon-pending, az, rz)
            reference["discounted_events"] *= np.exp(-discount*pending)
            reference["discounted_active_time"] *= np.exp(-discount*pending)
        results.append({"identity": name, "context": row.tolist(), "old_mass_defect": old_defect,
                        "mass_identity_defect": abs(actual["mass_quadrature_defect"]),
                        "feature_error": float(np.max(np.abs(actual["features"]-reference["features"]))),
                        "occupation_error": abs(actual["discounted_active_time"]-reference["discounted_active_time"]),
                        "event_error": max(abs(actual[k]-reference[k]) for k in ["expected_events", "discounted_events"])})
    summary = {"maximum_feature_abs_error": max(r["feature_error"] for r in results),
               "maximum_occupation_abs_error": max(r["occupation_error"] for r in results),
               "maximum_event_abs_error": max(r["event_error"] for r in results),
               "maximum_analytic_mass_defect": max(r["mass_identity_defect"] for r in results),
               "worst_original_mass_defect": float(np.max(np.abs(defects)))}
    gates = {key: bool(summary[key] <= tolerance) for key, tolerance in protocol["gates"].items()}
    report = {"schema": "hepta.regenerative-operator.domain-validation.v1",
              "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
              "source_sha256": {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                                for name in ["operators.py", "validate_operators.py", "validate_operators_domain.py"]},
              "contexts_available": len(contexts), "checked": len(results), "results": results,
              "summary": summary, "gates": gates, "passed": all(gates.values())}
    path = HERE/"NUMERICAL_DOMAIN_VALIDATION.json"
    if path.exists():
        raise FileExistsError("retain existing domain validation")
    path.write_text(json.dumps(report,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(json.dumps({"summary":summary,"gates":gates,"passed":report["passed"]},sort_keys=True))
    return report


if __name__ == "__main__":
    if not run()["passed"]:
        raise SystemExit(1)
