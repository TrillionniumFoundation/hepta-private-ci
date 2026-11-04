#!/usr/bin/env python3
"""Independently check recorded convex fits; do not solve or update a candidate.

Uses scalar math.fsum for the original objective/gradient/Gram reconstruction.
NumPy reads the previously frozen H/head fixture and checks matrix eigenvalues;
no experiment module, policy, RNG, gradient-update routine or direct solver is run.
"""
from pathlib import Path
from fractions import Fraction
import argparse
import gzip
import hashlib
import json
import math

import numpy as np

ROOT = Path(__file__).resolve().parent
FITS = [11, 23, 37, 53, 71]
LAMBDA = 1e-4
FW_TOL = 1e-8
GEOMETRY_SHA = "2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5"
OLD_RESULTS_RAW_SHA = "a55a8136842d366f3d3663b05028bae8fa7eedad63bfa731662fb692104eedb4"
ANALYTIC_RESULTS_SHA = "fe5cf45508635bfc4bd96154a073fba3c292d6a82fd452c54b17ac27e3850dfb"


def require(ok, label):
    if not ok:
        raise ValueError(label)


def raw(path):
    path = Path(path)
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def read(path):
    return json.loads(raw(path))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def close(a, b, label, atol=2e-12):
    require(math.isfinite(a) and math.isfinite(b), label + ": finite")
    require(abs(a-b) <= atol, f"{label}: {a!r} != {b!r}")


def dot(a, b):
    require(len(a) == len(b), "dot dimensions")
    return math.fsum(x*y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def frac(x):
    return Fraction.from_float(float(x))


def rational(value):
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def vector_close(a, b, label, atol=2e-12):
    require(len(a) == len(b), label + ": dimensions")
    for x, y in zip(a, b):
        close(x, y, label, atol)


def hashed_record(records, filename, digest):
    require(Path(filename).name == filename, "flat record path")
    path = records / filename
    require(sha(path) == digest, filename + ": hash")
    return read(path)


def verify_radius(certificate, b, b0, radius):
    exact = sum(((frac(x)-frac(y))**2 for x, y in zip(b, b0)), Fraction())
    original = sum((frac(x)**2 for x in b0), Fraction()) / 4
    safe = frac(radius)**2
    require(rational(certificate["actual_squared_delta"]) == exact, "actual stored-parameter radius")
    require(rational(certificate["original_radius_squared"]) == original, "exact original radius")
    require(rational(certificate["safe_radius_squared"]) == safe, "exact safe radius")
    require(safe <= original and exact <= safe, "actual candidate in safe/original balls")
    require(certificate["within_safe"] is True and certificate["within_original"] is True, "radius receipt flags")


def reconstruct_problem(problem):
    H, probabilities, targets, b0 = [problem[k] for k in ("H", "own_bank7", "target_logit", "b0")]
    n = len(H)
    require(n > 0 and len(b0) == 49 and len(probabilities) == len(targets) == n, "problem dimensions")
    require(all(len(row) == 49 and all(math.isfinite(v) for v in row) and row[-1] == 1 for row in H), "hidden features plus bias")
    require(all(math.isfinite(v) for v in b0), "finite original weights")
    require(all(math.isfinite(p) and 0 < p < 1 for p in probabilities), "strict own bank probabilities without clipping")
    expected_targets = [math.log(p)-math.log1p(-p) for p in probabilities]
    vector_close(targets, expected_targets, "own probability logit")
    require(problem["regularization"] == LAMBDA and problem["safe_factor"] == 1-1e-8
            and problem["storage_roundoff_inward_guard_factor"] == 1-1e-12, "fixed objective/numerical guard")
    original_radius = .5*norm(b0)
    close(problem["original_radius_float"], original_radius, "half original weight norm")
    close(problem["safe_radius"], problem["original_radius_float"]*(1-1e-8), "declared safe factor", 0.)
    residual_target = [t-dot(row, b0) for row, t in zip(H, targets)]
    columns = list(zip(*H))
    matrix = [[dot(a, b)/n + (LAMBDA if j == k else 0.) for k, b in enumerate(columns)]
              for j, a in enumerate(columns)]
    rhs = [dot(column, residual_target)/n for column in columns]
    require(len(problem["matrix"]) == 49, "Gram rows")
    for expected, recorded in zip(matrix, problem["matrix"]):
        vector_close(recorded, expected, "mean-scaled regularized Gram")
    vector_close(problem["rhs"], rhs, "mean-scaled rhs")
    eigenvalues = np.linalg.eigvalsh(np.asarray(matrix, dtype=float)).tolist()
    require(eigenvalues[0] > 0, "positive regularized Hessian")
    vector_close(problem["eigenvalues"], eigenvalues, "recorded matrix eigenvalues", 2e-10)
    close(problem["L"], 2*eigenvalues[-1], "gradient Lipschitz constant", 4e-10)
    return H, targets, b0, matrix, rhs


def verify_diagnostics(state, problem, H, targets, b0, matrix, rhs):
    b = state["b"]
    require(len(b) == 49 and all(math.isfinite(x) for x in b), "stored Belief weights")
    delta = [x-y for x, y in zip(b, b0)]
    vector_close(state["delta_float"], delta, "recorded rounded delta", 0.)
    residual = [dot(row, b)-t for row, t in zip(H, targets)]
    mse = math.fsum(x*x for x in residual)/len(H)
    penalty = LAMBDA*dot(delta, delta)
    gradient = [2*math.fsum(row[j]*r for row, r in zip(H, residual))/len(H) + 2*LAMBDA*delta[j] for j in range(49)]
    gradient_norm = norm(gradient)
    fw = dot(gradient, delta) + problem["safe_radius"]*gradient_norm
    gram_gradient = [2*(dot(row, delta)-g) for row, g in zip(problem["matrix"], problem["rhs"])]
    for key, expected in [("objective", mse+penalty), ("own_bank_logit_mse", mse),
                          ("regularization_penalty", penalty), ("gradient_norm", gradient_norm),
                          ("numerical_fw_gap", fw), ("delta_l2", norm(delta)),
                          ("gradient_reference_vs_gram_linf", max(abs(x-y) for x, y in zip(gradient, gram_gradient)))]:
        close(state[key], expected, key)
    vector_close(state["gradient"], gradient, "original-H objective gradient")
    verify_radius(state["certificate"], b, b0, problem["safe_radius"])
    require(state["converged_to_declared_FW_tolerance"] == (-1e-12 <= state["numerical_fw_gap"] <= FW_TOL), "own stored-FW convergence flag")
    require(fw >= -3e-12, "numerical FW nonnegativity within diagnostic tolerance")
    return {"delta": delta, "gradient": gradient, "objective": mse+penalty, "fw": fw}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", required=True)
    parser.add_argument("--analytic-root", required=True)
    args = parser.parse_args()
    study, analytic, records = Path(args.study_root), Path(args.analytic_root), ROOT / "records"
    protocol, design = read(ROOT / "PROTOCOL_BEFORE_RESULTS.json"), read(ROOT / "DESIGN_BEFORE_RESULTS.json")
    require(sha(ROOT / "DESIGN_BEFORE_RESULTS.json") == protocol["design_sha256"], "frozen design identity")
    for name, expected in design["local_source_sha256"].items():
        require(sha(ROOT / name) == expected, "frozen local source: " + name)
    for name, expected in design["joint_source_sha256"].items():
        require(sha(study / name) == expected, "frozen joint source: " + name)
    require(sha(analytic / "run_analytic_belief.py") == design["analytic_driver_sha256"], "analytic feature-source identity")
    oldbytes = raw(study / "records/results_strict.json.gz")
    require(hashlib.sha256(oldbytes).hexdigest() == OLD_RESULTS_RAW_SHA, "original fit/input identities")
    oldfits = {f["fit"]: f for f in json.loads(oldbytes)["fits"]}
    geometry_path = study / "fixtures/train_linear_geometry.npz"
    require(sha(geometry_path) == GEOMETRY_SHA, "previous independent TRAIN geometry")
    geometry = np.load(geometry_path, allow_pickle=False)
    require(sha(analytic / "records/RESULTS.json.gz") == ANALYTIC_RESULTS_SHA, "previous own-bank evidence")
    previous = {f["fit"]: f for f in read(analytic / "records/RESULTS.json.gz")["fits"]}
    results = read(records / "RESULTS.json.gz")
    qualification = read(records / "QUALIFICATION.json")
    require(sha(records / "RESULTS.json.gz") == qualification["results_sha256"], "current result hash")
    require(results["status"] == qualification["status"] == "completed", "completed scientific run")
    require(results["protocol"] == protocol and results["protocol_sha256"] == sha(ROOT / "PROTOCOL_BEFORE_RESULTS.json"), "protocol chain")
    require([f["fit"] for f in results["fits"]] == FITS, "complete five fits")
    report = []
    for f in results["fits"]:
        fit = f["fit"]
        problem = hashed_record(records, f["problem_file"], f["problem_file_sha256"])
        solvers = hashed_record(records, f["solver_file"], f["solver_file_sha256"])
        require(solvers == f["solvers"] and solvers["problem_sha256"] == f["problem_file_sha256"], "solver/problem chain")
        require(problem["fit"] == solvers["fit"] == fit, "fit identity")
        require(problem["source_model_sha256"] == f["source_model_sha256"] == oldfits[fit]["source_model_sha256"], "original model identity")
        require(problem["source_data_sha256"] == f["source_data_sha256"] == oldfits[fit]["source_data_sha256"], "original TRAIN data identity")
        H, targets, b0, matrix, rhs = reconstruct_problem(problem)
        old_H, old_theta = geometry[f"fit{fit}_x"], geometry[f"fit{fit}_theta"]
        require(np.asarray(H).shape == old_H.shape, "same full TRAIN feature shape")
        H_error = float(np.max(np.abs(np.asarray(H)-old_H)))
        require(H_error <= 2e-12 and b0 == old_theta[3].tolist(), "existing TRAIN features/base row provenance")
        prior_link = previous[fit]["probes"]["train"]
        prior_probe = hashed_record(analytic / "records", prior_link["file"], prior_link["sha256"])
        vector_close(problem["own_bank7"], prior_probe["model_bank7"], "previous same-model TRAIN bank provenance", 0.)
        require(len(H) == prior_probe["rows"], "same original TRAIN rows")
        direct, pgd = solvers["direct"], solvers["gradient"]
        di = verify_diagnostics(direct, problem, H, targets, b0, matrix, rhs)
        gi = verify_diagnostics(pgd, problem, H, targets, b0, matrix, rhs)
        require(direct["solver"] == "eigh_scalar_lagrange_monotone_root" and direct["converged_to_declared_FW_tolerance"], "direct qualified numerical solution")
        mu = direct["lagrange_mu"]
        require(math.isfinite(mu) and mu >= 0, "nonnegative trust-region multiplier")
        eq = [dot(row, di["delta"])+mu*d-g for row, d, g in zip(problem["matrix"], di["delta"], problem["rhs"])]
        residual_linf = max(abs(x) for x in eq)
        close(direct["linear_equation_residual_linf"], residual_linf, "mu normal equation")
        require(residual_linf <= 1e-9*(1+max(abs(x) for x in problem["rhs"])) + 2e-12, "direct equation gate")
        kkt = max(abs(g+2*mu*d) for g, d in zip(di["gradient"], di["delta"]))
        close(direct["kkt_stationarity_linf"], kkt, "KKT multiplier/gradient scale")
        complementarity = abs(mu*(dot(di["delta"], di["delta"])-problem["safe_radius"]**2))
        close(direct["complementarity_absolute"], complementarity, "KKT complementarity")
        if mu > 0:
            require(abs(norm(di["delta"])-problem["safe_radius"]) <= 1e-9*max(1., problem["safe_radius"]), "active radius for positive mu")
        require(0 <= direct["root_bracket_steps"] <= 64 and 0 <= direct["root_bisections"] <= 160, "bounded direct root")
        require(pgd["solver"] == "projected_gradient_fixed_1_over_L" and pgd["max_steps"] == 20000
                and pgd["FW_tolerance"] == FW_TOL, "fixed PGD policy")
        require(0 <= pgd["steps"] <= 20000, "PGD steps")
        close(pgd["L"], problem["L"], "same L", 0.)
        close(pgd["step_size"], 1/problem["L"], "PGD 1/L", 0.)
        if pgd["converged_to_declared_FW_tolerance"]:
            require(pgd["stop_reason"] == "own_stored_parameter_FW_gap", "independent PGD stopping reason")
        else:
            require(pgd["steps"] == 20000 and pgd["stop_reason"] == "fixed_maximum_steps", "unconverged maximum-step result kept")
        trace = pgd["trace"]
        require(trace[0]["step"] == 0 and trace[0]["delta_l2"] == 0 and trace[-1]["step"] == pgd["steps"], "PGD starts at base and ends at recorded step")
        require([x["step"] for x in trace] == sorted({x["step"] for x in trace}), "ordered PGD trace")
        allowed = direct["converged_to_declared_FW_tolerance"] and pgd["converged_to_declared_FW_tolerance"]
        require(solvers["same_convex_FW_precision_cost_comparison_allowed"] == allowed, "no matched-convex-precision cost claim for unconverged PGD")
        close(solvers["direct_gradient_objective_difference"], di["objective"]-gi["objective"], "common actual objective contrast")
        for name, base, candidate in [("D", "A", direct), ("CD", "C", direct), ("G", "A", pgd), ("CG", "C", pgd)]:
            require(f["heads"][name][:3] == f["heads"][base][:3] and f["heads"][name][3] == candidate["b"], "49-coordinate edit in intended head")
            require(f["new_changed_parameters"][name] == sum(x != y for x, y in zip(candidate["b"], b0)), "actual changed-coordinate count")
        report.append({"fit": fit, "TRAIN_rows": len(H), "H_max_difference_from_frozen_geometry": H_error,
            "own_bank_exactly_matches_prior_TRAIN_probe": True,
            "direct_objective_recomputed": di["objective"], "PGD_objective_recomputed": gi["objective"],
            "direct_FW_gap_recomputed": di["fw"], "PGD_FW_gap_recomputed": gi["fw"],
            "direct_mu": mu, "direct_KKT_stationarity_linf_recomputed": kkt,
            "PGD_steps": pgd["steps"], "PGD_converged": pgd["converged_to_declared_FW_tolerance"],
            "equal_objective_precision_gate_passed": allowed})
    geometry.close()
    print(json.dumps({"status": "passed_recorded_convex_numerics", "verifier_sha256": sha(__file__),
        "results_sha256": qualification["results_sha256"], "fits": report,
        "new_model_forwards": 0, "candidate_solves": 0, "gradient_updates": 0,
        "scope": "Independent scalar reconstruction of recorded objective/gradient/Gram/FW/KKT and exact stored-IEEE radius, with previously frozen TRAIN H and own-bank target provenance. Eigenvalues checked for L only; no new candidate solve or PGD replay. Numerical diagnostics are not rigorous outward-rounded real optimality certificates. Matching this small self-target objective does not establish full-model-training or task-quality equivalence."}, indent=2))


if __name__ == "__main__":
    main()
