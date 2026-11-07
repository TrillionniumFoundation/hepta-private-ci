"""Finite TRAIN-only candidates using the frozen WSP task and affine head owner."""
import time
from types import SimpleNamespace

import numpy as np

from guard import dual_norm_random, digest, model_identity, protected_identity
from artifact_io import read, save
from task_graph import TrainWorld
from run_experiment import model_for, select_path, serialize_model
from vendor import planning as p
from vendor import quadratic as q


def construct(upstream, out, fit, protocol, protocol_sha, full_ctx, budget):
    start = time.process_time()
    ctx = SimpleNamespace(**{name: getattr(full_ctx, name) for name in
        ("checked_mm", "NumpyPolicy", "Oracle", "initial", "legal", "due_request", "successor",
         "predicted", "outcomes", "policy_value", "head", "deploy")})
    model = read(upstream / f"inputs/fit_{fit}_C.json.gz")
    if model_identity(model) != protocol["models"][str(fit)]:
        raise ValueError("checkpoint identity does not match frozen semantic contract")
    C, policy = ctx.head(model), ctx.NumpyPolicy(model)
    publics = read(upstream / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
    if len(publics) != 64:
        raise ValueError("complete original TRAIN required")
    worlds = []
    for public in publics:
        budget()
        worlds.append(TrainWorld(ctx, public, policy, C, len(publics), protocol))
    H, Y, W = [np.concatenate([getattr(world, name) for world in worlds]) for name in ("H", "targets", "W")]
    if len(H) > protocol["state_caps"]["training_rows_per_fit"]:
        raise OverflowError("complete TRAIN exceeds declared row cap")
    problem = q.prepare(H, Y, W, C[:3], ctx.checked_mm)
    shared = time.process_time() - start
    radius = problem["radius"]
    arms, paths, reports, costs = {name: C.copy() for name in ("C", "L", "J", "MYOPIC")}, {}, {}, {}
    endpoints = {}
    for arm in ("E", "G", "A", "EG"):
        arm_start = time.process_time()
        endpoint = C.copy()
        if arm == "E":
            endpoint[:3], reports[arm] = q.direct(problem, ctx.checked_mm, budget)
        elif arm == "G":
            endpoint[:3], reports[arm] = q.pgd(problem, ctx.checked_mm, budget)
        elif arm == "A":
            vectors, values = problem["vectors"], problem["values"]
            retained, masks, projections = [], [], []
            for vector, value, rhs in zip(vectors, values, problem["rhs"]):
                data_values = np.maximum(value - q.LAMBDA, 0.)
                keep = (data_values > 0) & (data_values >= protocol["optimization"]["agent_eigenvalue_fraction"] * data_values.max())
                retained.append(int(keep.sum()))
                masks.append(keep)
                projections.append(ctx.checked_mm(vector.T, rhs))
            def point(mu):
                return np.asarray([ctx.checked_mm(v, np.where(mask, pr / (e + mu), 0.))
                    for v, mask, pr, e in zip(vectors, masks, projections, values)])
            delta, mu = point(0.), 0.
            if np.linalg.norm(delta) > radius:
                low, high = 0., max(1., float(np.linalg.norm(problem["rhs"])) / radius)
                for _ in range(160):
                    middle = .5 * (low + high)
                    if middle in (low, high):
                        break
                    if np.linalg.norm(point(middle)) > radius:
                        low = middle
                    else:
                        high = middle
                mu, delta = high, point(high)
            endpoint[:3], proof, _ = q.stored_point(C[:3], delta, radius)
            diagnostics = q.diagnostics(problem, endpoint[:3], ctx.checked_mm)
            full_gradient = np.asarray(diagnostics["gradient"])
            restricted_gradient = np.asarray([ctx.checked_mm(v, np.where(mask, ctx.checked_mm(v.T, g), 0.))
                for v, mask, g in zip(vectors, masks, full_gradient)])
            restricted_gap = float(np.sum(restricted_gradient * (endpoint[:3] - C[:3])) + radius*np.linalg.norm(restricted_gradient))
            if not -1e-11 <= restricted_gap <= 1e-8:
                raise ArithmeticError("restricted spectral solution has not converged")
            reports[arm] = {"retained_modes_per_action": retained, "gradient_steps": 0,
                            "exact_norm": proof, "hypothesis": protocol["agent_hypothesis"],
                            "restricted_FW_gap": restricted_gap, "multiplier": mu,
                            "full_objective_diagnostics": diagnostics,
                            "discarded_rhs_squared": [float(np.sum(pr[~mask]**2)) for pr, mask in zip(projections, masks)]}
        else:
            delta = arms["E"][:3] - C[:3]
            for _ in range(protocol["optimization"]["short_training_steps"]):
                gradient = 2 * np.array([ctx.checked_mm(a, d) - rhs for a, d, rhs in
                    zip(problem["matrices"], delta, problem["rhs"])])
                delta -= gradient / problem["L"]
                delta *= min(1., radius / max(float(np.linalg.norm(delta)), np.finfo(float).tiny))
            endpoint[:3], proof, _ = q.stored_point(C[:3], delta, radius)
            reports[arm] = {"steps": protocol["optimization"]["short_training_steps"], "exact_norm": proof,
                            "optimizer_state_policy": protocol["optimizer_state"]["EG"]}
        if arm in ("E", "G") and not reports[arm]["converged"]:
            raise ArithmeticError("solver failed its predeclared numerical gate")
        endpoints[arm] = endpoint.copy()
        arms[arm], paths[arm] = select_path(out, fit, arm, model, C, endpoint, radius, worlds,
                                          protocol["optimization"]["alphas"], budget)
        costs[arm] = {"exclusive_cpu_seconds": time.process_time() - arm_start,
                      "inclusive_shared_cpu_seconds": shared + time.process_time() - arm_start}
        if arm == "EG":
            costs[arm]["depends_on_selected_E"] = True
            costs[arm]["inclusive_shared_cpu_seconds"] += costs["E"]["exclusive_cpu_seconds"]
        if costs[arm]["inclusive_shared_cpu_seconds"] > protocol["resources"]["per_fit_per_arm_candidate_cpu_cap"]:
            raise TimeoutError("per-arm candidate resource cap exceeded")
    random_start = time.process_time()
    rng = np.random.Generator(np.random.PCG64(int(digest([protocol_sha, fit, "dual-norm"]), 16)))
    arms["R"] = C.copy()
    arms["R"][:3], random_proof, _ = q.stored_point(C[:3], dual_norm_random(arms["E"][:3] - C[:3], rng), radius)
    random_cpu = time.process_time() - random_start
    serialization_start = time.process_time()
    identities = {}
    for name, theta in arms.items():
        arms[name], identities[name] = serialize_model(out, fit, name, model, theta, ctx)
        if protected_identity(model_for(model, arms[name])) != protected_identity(model):
            raise ValueError("candidate changes protected semantics")
    differences = [arms[name][:3] - C[:3] for name in ("E", "R")]
    norms = {kind: [float(np.linalg.norm(d.ravel(), ord=order)) for d in differences]
             for kind, order in (("L2", 2), ("Linf", np.inf))}
    for values in norms.values():
        if not np.isclose(*values, rtol=1e-10, atol=1e-15):
            raise ArithmeticError("stored random candidate does not match both effective norms")
    costs["R"] = {"exclusive_cpu_seconds": random_cpu,
                  "depends_on_selected_E": True, "dependency_cpu_seconds": costs["E"]["inclusive_shared_cpu_seconds"],
                  "inclusive_shared_cpu_seconds": random_cpu + costs["E"]["inclusive_shared_cpu_seconds"]}
    if costs["R"]["inclusive_shared_cpu_seconds"] > protocol["resources"]["per_fit_per_arm_candidate_cpu_cap"]:
        raise TimeoutError("random control dependency-inclusive resource cap exceeded")
    record = {"fit": fit, "models": identities, "heads": arms, "paths": paths,
              "endpoint_heads": endpoints, "radius": radius,
              "solvers": reports, "random_norms": norms, "random_exact_norm": random_proof,
              "costs": costs, "shared_preparation_cpu_seconds": shared,
              "shared_serialization_and_norm_check_cpu_seconds": time.process_time() - serialization_start,
              "total_physical_cpu_seconds": time.process_time() - start,
              "rows": len(H), "worlds": len(publics),
              "diagnostics": {"hessian_min_eigenvalues": problem["values"].min(axis=1),
                "hessian_max_eigenvalues": problem["values"].max(axis=1),
                "terminal_anchor_range": [min(w.report["terminal_anchor_offset_min"] for w in worlds),
                                          max(w.report["terminal_anchor_offset_max"] for w in worlds)],
                "no_missing_state_proof": True},
              "training_worlds": [w.report for w in worlds],
              "checkpoint_identity": model_identity(model),
              "no_evaluator_truth_targets": True}
    save(out / f"fit_{fit}_CANDIDATES.json.gz", record)
    return {"model": model, "policy": policy, "arms": arms, "record": record}
