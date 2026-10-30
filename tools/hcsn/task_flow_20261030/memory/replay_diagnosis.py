"""Post-audit numerical diagnosis of one exposed failing case; no gate repair."""
import json
import os
from pathlib import Path
import resource
import sys
import time
from decimal import Decimal, localcontext

STARTED, CPU_STARTED = time.perf_counter(), time.process_time()
if 6 not in os.sched_getaffinity(0):
    raise RuntimeError("Declared diagnostic CPU 6 is unavailable")
os.sched_setaffinity(0, {6})

import numpy as np
import jax
import jax.numpy as jnp

jax.config.update("jax_enable_x64", True)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.data import make_data, fingerprint
from third.memory import models as model
from third.memory import reference
from task_flow_20261030.memory.freeze import verify, sha


def maximum(value):
    return float(np.max(np.abs(value)))


def matrix(state, index):
    gram = np.asarray(state["gram"][index], np.float64)
    mass = float(np.asarray(state["inverse_mass"][index]).ravel()[0])
    return .5 * (gram + gram.T) + .01 * mass * np.eye(16)


def solve_receipt(a, h, fitted):
    residual = a @ fitted - h
    denominator = np.linalg.norm(a, 2) * np.linalg.norm(fitted) + np.linalg.norm(h)
    return dict(condition_2=float(np.linalg.cond(a)),
                eigenvalue_minimum=float(np.linalg.eigvalsh(a).min()),
                relative_rhs_residual=float(np.linalg.norm(residual) / np.linalg.norm(h)),
                relative_backward_error=float(np.linalg.norm(residual) / denominator))


def decimal_solve(a, h):
    """Independent 80-digit partial-pivot elimination on exact binary64 inputs."""
    n, columns = h.shape
    with localcontext() as context:
        context.prec = 80
        augmented = [[Decimal.from_float(float(v)) for v in row]
                     for row in np.concatenate([a, h], axis=1)]
        for pivot in range(n):
            best = max(range(pivot, n), key=lambda i: abs(augmented[i][pivot]))
            augmented[pivot], augmented[best] = augmented[best], augmented[pivot]
            divisor = augmented[pivot][pivot]
            if divisor == 0:
                raise ArithmeticError("Singular matrix in independent solve")
            augmented[pivot] = [v / divisor for v in augmented[pivot]]
            for row in range(n):
                if row == pivot:
                    continue
                factor = augmented[row][pivot]
                augmented[row] = [v - factor * w for v, w in
                                  zip(augmented[row], augmented[pivot])]
        return np.array([[float(v) for v in row[n:n + columns]] for row in augmented])


def main():
    destination = HERE / "replay_diagnosis.json"
    if destination.exists():
        raise RuntimeError("Preserve existing diagnostic evidence")
    verify()
    protected = {name: sha(HERE / name) for name in ("results.json", "audit.json", "freeze.json")}
    result = json.loads((HERE / "results.json").read_text())
    audit = json.loads((HERE / "audit.json").read_text())
    worst_check = max(audit["checks"], key=lambda row: row["logit_error"])
    if (worst_check["run_id"], worst_check["split"]) != ("memory_full_mass_seed61", "test512"):
        raise RuntimeError("This diagnosis is limited to the recorded worst case")
    row = next(r for r in result["runs"] if r["run_id"] == worst_check["run_id"])
    protocol = result["protocol"]
    data = make_data("memory", protocol["data_seed_base"] + 1000 * row["seed"] + 812,
                     protocol["evaluation_examples"], 512)
    if fingerprint(data) != row["data_sha256"]["test512"]:
        raise RuntimeError("Frozen data identity mismatch")
    params = dict(np.load(HERE / row["checkpoint"], allow_pickle=False))
    saved = dict(np.load(HERE / row["predictions"]["test512"]["path"], allow_pickle=False))
    pieces = []
    for start in range(0, len(data["y"]), 64):
        state = reference.forward(params, data["x"][start:start + 64],
                                  data["dt"][start:start + 64], "full")
        pieces.append(reference.readout(params, state, "mass", np.float64)[0])
    numpy_audit = np.concatenate(pieces)
    difference = np.abs(numpy_audit - saved["logits"])
    example, output = (int(i) for i in np.unravel_index(np.argmax(difference), difference.shape))
    start, local = (example // 32) * 32, example % 32
    x, dt = data["x"][start:start + 32], data["dt"][start:start + 32]
    print(json.dumps(dict(stage="located", example=example, output=output,
                         audit_error=float(difference[example, output]))), flush=True)

    plain = jax.jit(lambda p, x, dt: model.apply_model(p, x, dt, "full_mass"))
    with_aux = jax.jit(lambda p, x, dt: model.apply_model(p, x, dt, "full_mass", True))
    jp = {k: jnp.asarray(v) for k, v in params.items()}
    j_plain = np.asarray(plain(jp, jnp.asarray(x), jnp.asarray(dt)))
    j_logits, j_state = with_aux(jp, jnp.asarray(x), jnp.asarray(dt))
    j_logits = np.asarray(j_logits)
    j_state = {k: np.asarray(v) for k, v in j_state.items()}
    n_state = reference.forward(params, x, dt, "full")
    n_logits, n_diagnostics = reference.readout(params, n_state, "mass", np.float64)

    aj, an = matrix(j_state, local), matrix(n_state, local)
    hj = np.asarray(j_state["cross"][local], np.float64)
    hn = np.asarray(n_state["cross"][local], np.float64)
    qj, qn = (np.asarray(s["query"][local], np.float64) for s in (j_state, n_state))
    fj = np.asarray(j_state["fitted"][local], np.float64)
    fj_numpy, fn_numpy = np.linalg.solve(aj, hj), np.linalg.solve(an, hn)
    high = decimal_solve(aj, hj)
    read_j, read_n = qj @ fj_numpy, qn @ fn_numpy
    # Exact perturbation identity separates input changes from solve error.
    state_effect = np.linalg.solve(an, (hn - hj) - (an - aj) @ fj_numpy)
    predicted_read_difference = qn @ state_effect + (qn - qj) @ fj_numpy
    state_differences = {k: dict(maximum_absolute=maximum(j_state[k][local] - n_state[k][local]),
                                jax_dtype=str(j_state[k].dtype), numpy_dtype=str(n_state[k].dtype))
                         for k in ("gram", "cross", "inverse_mass", "query", "fast", "slow")}
    print(json.dumps(dict(stage="fp32_states", gram=state_differences["gram"],
                         condition=float(np.linalg.cond(aj)))), flush=True)

    params64 = {k: v.astype(np.float64) for k, v in params.items()}
    n_state64 = reference.forward(params64, x.astype(np.float64), dt.astype(np.float64), "full")
    n_logits64, n_diagnostics64 = reference.readout(params64, n_state64, "mass", np.float64)
    j_logits64, j_state64 = with_aux({k: jnp.asarray(v) for k, v in params64.items()},
                                    jnp.asarray(x, jnp.float64), jnp.asarray(dt, jnp.float64))
    j_logits64 = np.asarray(j_logits64)
    j_state64 = {k: np.asarray(v) for k, v in j_state64.items()}
    high_precision = dict(
        scope="Same saved binary32 weights and shared rounded financial table, recurrence arithmetic promoted to binary64; diagnostic only",
        jax_numpy_logit_maximum_batch=maximum(j_logits64 - n_logits64),
        jax_numpy_logit_maximum_worst_example=maximum(j_logits64[local] - n_logits64[local]),
        jax32_vs_jax64_maximum_worst_example=maximum(j_logits[local] - j_logits64[local]),
        numpy32_vs_numpy64_maximum_worst_example=maximum(n_logits[local] - n_logits64[local]),
        state_differences={k: maximum(j_state64[k][local] - n_state64[k][local])
                           for k in ("gram", "cross", "inverse_mass", "query", "fast", "slow")},
        numpy_batch_diagnostics=n_diagnostics64)
    verify()
    unchanged = {name: sha(HERE / name) == digest for name, digest in protected.items()}
    if not all(unchanged.values()):
        raise RuntimeError("Protected source/result changed during diagnosis")
    report = dict(
        exploratory=True, run_id=row["run_id"], split="test512", checkpoint_sha256=sha(HERE / row["checkpoint"]),
        source_sha256=sha(__file__), protected_sha256=protected, protected_unchanged=unchanged,
        original_audit_passed=audit["passed"], original_worst_check=worst_check,
        selection=dict(example=example, output=output, original_jax_batch_start=start,
                       original_jax_batch_size=32, numpy_audit_batch_size=64,
                       reproduced_numpy_audit_error=float(difference[example, output])),
        batch32=dict(jax_plain_saved_logit_error=maximum(j_plain - saved["logits"][start:start + 32]),
                     jax_aux_plain_logit_error=maximum(j_logits - j_plain),
                     numpy_jax_aux_logit_error=maximum(n_logits - j_logits),
                     numpy32_numpy64batch_audit_error=maximum(n_logits - numpy_audit[start:start + 32])),
        worst_example=dict(jax_logits=j_logits[local].tolist(), numpy_logits=n_logits[local].tolist(),
                           saved_logits=saved["logits"][example].tolist(), label=int(data["y"][example]),
                           state_differences=state_differences,
                           ridge_jax=float(.01 * j_state["inverse_mass"][local, 0]),
                           ridge_numpy=float(.01 * n_state["inverse_mass"][local, 0]),
                           relative_matrix_difference=float(np.linalg.norm(aj - an, 2) / np.linalg.norm(aj, 2)),
                           relative_rhs_difference=float(np.linalg.norm(hj - hn) / np.linalg.norm(hj)),
                           jax_solve=solve_receipt(aj, hj, fj),
                           numpy_same_input_solve=solve_receipt(aj, hj, fj_numpy),
                           numpy_own_input_solve=solve_receipt(an, hn, fn_numpy),
                           jax_numpy_same_input_fitted_error=maximum(fj - fj_numpy),
                           jax_decimal80_same_input_fitted_error=maximum(fj - high),
                           numpy_decimal80_same_input_fitted_error=maximum(fj_numpy - high),
                           jax_decimal80_same_input_read_error=maximum(qj @ (fj - high)),
                           read_difference_from_changed_states=maximum(read_n - read_j),
                           exact_perturbation_identity_error=maximum(read_n - read_j - predicted_read_difference)),
        high_precision=high_precision, numpy_batch_diagnostics=n_diagnostics,
        interpretation="One exposed worst case only. Same-input higher-precision solves and promoted recurrence diagnose arithmetic sensitivity; they neither replace saved predictions nor relax the failed frozen logit gate.",
        execution=dict(affinity=sorted(os.sched_getaffinity(0)), jax=jax.__version__, numpy=np.__version__,
                       wall_seconds=time.perf_counter() - STARTED, cpu_seconds=time.process_time() - CPU_STARTED,
                       max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       blas_threads={k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")}))
    destination.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True), flush=True)
    jax.clear_caches()


if __name__ == "__main__":
    main()
