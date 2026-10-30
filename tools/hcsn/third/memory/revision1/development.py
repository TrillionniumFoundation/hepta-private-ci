"""One frozen 48-run development matrix; no confirmation-set construction."""
import gc
import json
import os
from pathlib import Path
import resource
import sys
import time

import jax
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.common import train_model, evaluate_model, measure_latency, predictor
from next.ridge.models import count_parameters
from third.memory.data import make_suite, audit_freshness
from third.memory.freeze import verify, sha
from third.memory.models import init_model, matched_width, apply_model, resources


def solve_diagnostics(params, data, variant):
    fn = jax.jit(lambda x, dt: apply_model(params, x, dt, variant, True))
    result = dict(maximum_condition=0., maximum_relative_residual=0., maximum_read=0.,
                  maximum_write_mass=0., all_finite=True, condition_bound_satisfied=True)
    for offset in range(0, len(data["y"]), 32):
        _, aux = fn(data["x"][offset:offset+32], data["dt"][offset:offset+32])
        a = {k: np.asarray(v) for k, v in aux.items()}
        condition = np.linalg.cond(a["matrix"].astype(np.float64))
        residual = np.linalg.norm(a["matrix"] @ a["fitted"]-a["cross"], axis=(-2, -1))
        residual /= np.maximum(np.linalg.norm(a["cross"], axis=(-2, -1)), 1e-12)
        mass = (1/a["inverse_mass"]-1).ravel()
        bound = 1+mass/.01 if variant.endswith("_mass") else np.full_like(mass, 101.)
        result["maximum_condition"] = max(result["maximum_condition"], float(condition.max()))
        result["maximum_relative_residual"] = max(result["maximum_relative_residual"], float(residual.max()))
        result["maximum_read"] = max(result["maximum_read"], float(np.abs(a["read"]).max()))
        result["maximum_write_mass"] = max(result["maximum_write_mass"], float(mass.max()))
        result["condition_bound_satisfied"] &= bool(np.all(condition <= bound*1.001))
        result["all_finite"] &= all(np.isfinite(v).all() for v in a.values())
    return result


def decision(rows, protocol):
    targets = protocol["development_gate"]
    mass = [r for r in rows if r["variant"] == "full_mass"]
    fixed = [r for r in rows if r["variant"] == "full_fixed"]
    expected = len(protocol["variants"])*len(protocol["tasks"])*len(protocol["seeds"])
    checks = dict(matrix_complete=len(rows) == expected)
    for task, threshold in (("memory", .95), ("retrieval", .90)):
        group = [r for r in mass if r["task"] == task]
        checks[task+"128_every_seed"] = len(group) == len(protocol["seeds"]) and all(
            r["metrics"]["diagnostic128"]["accuracy"] >= threshold for r in group)
    deltas = {}
    for task in protocol["tasks"]:
        a = [r["metrics"]["diagnostic512"]["accuracy"] for r in mass if r["task"] == task]
        b = [r["metrics"]["diagnostic512"]["accuracy"] for r in fixed if r["task"] == task]
        deltas[task] = float(np.mean(a)-np.mean(b)) if a and b else None
        checks[task+"512_delta"] = deltas[task] is not None and deltas[task] >= targets[
            "full_mass_minus_full_fixed_mean_"+task+"512_min"]
    checks["all_numerical"] = all(d["all_finite"] and d["condition_bound_satisfied"] and
        d["maximum_relative_residual"] <= targets["maximum_solve_relative_residual"]
        for r in rows for d in r["solve_diagnostics"].values())
    return dict(passed=all(checks.values()), checks=checks, mean512_deltas=deltas,
        next_action="Separate frozen confirmation only if passed; no backbone authorization",
        financial_shape_superiority_established=False, confirmation_data_constructed=False)


def main():
    freeze = verify()
    protocol = json.loads((HERE/"protocol.json").read_text())
    numerical = json.loads((HERE/"numerical_validation.json").read_text())
    diagnostic = json.loads((HERE/"diagnostic_results.json").read_text())
    if not numerical["passed"] or numerical["freeze_sha256"] != sha(HERE/"freeze.json"):
        raise RuntimeError("Numerical prerequisite has not passed this freeze")
    if not diagnostic["all_old_accuracies_reproduced"]:
        raise RuntimeError("Old checkpoint reproduction prerequisite failed")
    output = HERE/"development_results.json"
    if output.exists():
        result = json.loads(output.read_text())
        if result["freeze_sha256"] != sha(HERE/"freeze.json") or result["complete"]:
            raise RuntimeError("Completed or mismatching freeze; no silent rerun")
    else:
        freshness = audit_freshness(protocol)
        if not freshness["passed"]:
            (HERE/"freshness_failure.json").write_text(json.dumps(freshness, indent=2)+"\n")
            raise RuntimeError("Fresh input audit failed")
        result = dict(protocol=protocol, freeze_sha256=sha(HERE/"freeze.json"),
            source_sha256=freeze["source_sha256"], freshness=freshness, runs=[], complete=False,
            jax=jax.__version__, numpy=np.__version__,
            cpu_affinity=sorted(os.sched_getaffinity(0)), platform=sys.platform,
            elapsed_seconds=0., no_confirmation_data_constructed=True)
    for row in result["runs"]:
        if sha(HERE/row["checkpoint_file"]) != row["checkpoint_sha256"]:
            raise RuntimeError("Resume checkpoint changed")
    checkpoints = HERE/"checkpoints"
    checkpoints.mkdir(exist_ok=True)
    done = {(r["task"], r["seed"], r["variant"]) for r in result["runs"]}
    start, prior_elapsed = time.perf_counter(), result["elapsed_seconds"]
    for task in protocol["tasks"]:
        for seed in protocol["seeds"]:
            train, suite, hashes = make_suite(task, seed, protocol)
            offset = seed % len(protocol["variants"])
            variants = protocol["variants"][offset:]+protocol["variants"][:offset]
            for variant in variants:
                if (task, seed, variant) in done:
                    continue
                verify()
                width, count = matched_width(variant, 16, 4, protocol["parameter_target"])
                params = init_model(variant, jax.random.PRNGKey(protocol["initialization_seed_base"]+seed), 16, width, 4)
                if count_parameters(params) != count:
                    raise RuntimeError("Parameter budget mismatch")
                initial_hash = __import__("hashlib").sha256(b"".join(
                    k.encode()+np.asarray(params[k]).tobytes() for k in sorted(params))).hexdigest()
                apply = lambda p, x, dt, v=variant: apply_model(p, x, dt, v)
                learned, history, timing = train_model(params, apply, train, suite["validation32"],
                    protocol["optimizer_seed_base"]+seed, steps=protocol["training_updates"],
                    batch_size=protocol["batch_size"], lr=protocol["learning_rate"])
                path = checkpoints/f"{task}_{variant}_seed{seed}.npz"
                np.savez_compressed(path, **{k: np.asarray(v) for k, v in learned.items()})
                metrics = {name: evaluate_model(apply, learned, d) for name, d in suite.items()}
                solves = {name: solve_diagnostics(learned, suite[name], variant)
                          for name in ("diagnostic128", "diagnostic512")}
                row = dict(task=task, seed=seed, variant=variant, width=width, parameters=count,
                    resources=resources(variant, width), initial_parameters_sha256=initial_hash,
                    data_sha256=hashes, metrics=metrics, history=history, timing=timing,
                    solve_diagnostics=solves, checkpoint_file=str(path.relative_to(HERE)),
                    checkpoint_sha256=sha(path), latency_batch32=measure_latency(
                        apply, learned, suite["validation32"], repeats=20),
                    process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
                result["runs"].append(row)
                result["elapsed_seconds"] = prior_elapsed+time.perf_counter()-start
                result["development_gate"] = decision(result["runs"], protocol)
                result["complete"] = result["development_gate"]["checks"]["matrix_complete"]
                output.write_text(json.dumps(result, indent=2)+"\n")
                print(json.dumps(dict(run=len(result["runs"]), task=task, seed=seed, variant=variant,
                    accuracy={k: v["accuracy"] for k, v in metrics.items()},
                    peak_rss_bytes=row["process_peak_rss_bytes"])), flush=True)
                del learned, params
                predictor.cache_clear()
                jax.clear_caches()
                gc.collect()
    print("DEVELOPMENT_GATE", json.dumps(result["development_gate"]), flush=True)


if __name__ == "__main__":
    main()
