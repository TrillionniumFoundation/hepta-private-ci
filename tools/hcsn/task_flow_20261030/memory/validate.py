"""Mechanism probes and independent local derivative checks before training."""
import json
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from task_flow_20261030.memory import models, reference
from task_flow_20261030.memory.freeze import verify, sha
from third.memory.execution import atomic_json


def probes():
    unit = np.eye(16, dtype=np.float64)
    memory = np.zeros((1, 16, 1), np.float64)
    memory = reference.delta_update(memory, unit[None, 0], np.array([[1.]]), np.ones((1, 1)))
    before = float(memory[0, 0, 0])
    for _ in range(4096):
        memory = reference.delta_update(memory, unit[None, 1], np.array([[-1.]]), np.ones((1, 1)))
    after = float(memory[0, 0, 0])
    fixed = 1. / (1. + .01 * (1 + 4097))
    mass = 1. / 1.01
    previous = memory.copy()
    no_write = reference.delta_update(memory, unit[None, 0], np.array([[-1.]]), np.zeros((1, 1)))
    replaced = reference.delta_update(memory, unit[None, 0], np.array([[-1.]]), np.ones((1, 1)))
    interference = []
    for correlation in (0., .25, .5, .9, 1.):
        key = correlation * unit[0] + np.sqrt(1 - correlation ** 2) * unit[1]
        changed = reference.delta_update(previous, key[None], np.array([[-1.]]), np.ones((1, 1)))
        interference.append(dict(correlation=correlation, target_after=float(changed[0, 0, 0]),
                                 target_change=float(changed[0, 0, 0] - before)))
    rng = np.random.default_rng(23419)
    capacity = []
    for count in (4, 8, 16, 24, 32):
        keys = unit[:count].copy() if count <= 16 else rng.normal(size=(count, 16))
        keys /= np.linalg.norm(keys, axis=1, keepdims=True)
        values = rng.uniform(-1, 1, (count, 4))
        m = np.zeros((1, 16, 4))
        for key, value in zip(keys, values):
            m = reference.delta_update(m, key[None], value[None], np.ones((1, 1)))
        error = keys @ m[0] - values
        capacity.append(dict(items=count, key_mode="orthogonal" if count <= 16 else "random_overcomplete",
                             rmse=float(np.sqrt(np.mean(error ** 2))), max_error=float(np.abs(error).max())))
    bounded = np.zeros((1, 16, 4))
    maximum_norm = 0.
    for _ in range(1000):
        key = rng.normal(size=(1, 16)) * .005
        value = rng.uniform(-1, 1, (1, 4))
        bounded = reference.delta_update(bounded, key, value, np.ones((1, 1)))
        maximum_norm = max(maximum_norm, float(np.linalg.norm(bounded, axis=1).max()))
    return dict(orthogonal_before=before, orthogonal_after=after,
                normalized_fixed_read_after=fixed, normalized_mass_read_after=mass,
                zero_write_exact=bool(np.array_equal(no_write, previous)),
                overwrite_error=float(abs(replaced[0, 0, 0] + 1)),
                maximum_column_norm=maximum_norm, interference=interference, capacity=capacity,
                passed=abs(after - before) < 1e-12 and np.array_equal(no_write, previous)
                and abs(replaced[0, 0, 0] + 1) < .0003 and maximum_norm <= 8 + 1e-12)


def derivative_checks(protocol):
    rng = np.random.default_rng(78291)
    x = rng.normal(0, .3, (2, 5, 16))
    dt = rng.uniform(.1, 2., (2, 5))
    checks = []
    for dtype in (np.float64, np.float32):
        for variant in models.VARIANTS:
            p = models.init_model(variant, jax.random.PRNGKey(302), 16, 4, 4)
            p = {k: jnp.asarray(v, dtype) for k, v in p.items()}
            directions = {k: jnp.asarray(rng.normal(size=v.shape), dtype) for k, v in p.items()}
            norm = np.sqrt(sum(np.sum(np.asarray(v) ** 2) for v in directions.values()))
            directions = {k: v / norm for k, v in directions.items()}
            xx, tt = x.astype(dtype), dt.astype(dtype)
            scalar = lambda par: jnp.sum(models.apply_model(par, xx, tt, variant) ** 2)
            grad = jax.grad(scalar)(p)
            analytic = sum(float(jnp.sum(grad[k] * directions[k])) for k in p)
            step = 3e-5 if dtype == np.float64 else .003
            plus = {k: p[k] + step * directions[k] for k in p}
            minus = {k: p[k] - step * directions[k] for k in p}
            finite = (float(scalar(plus)) - float(scalar(minus))) / (2 * step)
            error = abs(analytic - finite) / max(1., abs(analytic), abs(finite))
            logits = np.asarray(models.apply_model(p, xx, tt, variant))
            independent = reference.forward({k: np.asarray(v) for k, v in p.items()}, xx, tt, variant)
            replay = float(np.max(np.abs(logits - independent)))
            tolerance = protocol["validation"]["float64_directional_error" if dtype == np.float64
                                                else "float32_directional_error"]
            checks.append(dict(dtype=np.dtype(dtype).name, variant=variant,
                               directional_error=error, numpy_logit_error=replay,
                               passed=error <= tolerance and replay <= protocol["validation"]["numpy_logit_max_error"]))
            jax.clear_caches()
    # Projection interior and active branch are checked separately; seam is nonsmooth.
    for scale in (.1, 10.):
        m = jnp.asarray(rng.normal(size=(1, 16, 3)) * scale)
        key = jnp.asarray(rng.normal(size=(1, 16)) * .1)
        value = jnp.asarray(rng.uniform(-1, 1, (1, 3)))
        write = jnp.array([[.7]])
        direction = jnp.asarray(rng.normal(size=m.shape))
        loss = lambda state: jnp.sum(models.delta_update(state, key, value, write) ** 2)
        exact = float(jnp.sum(jax.grad(loss)(m) * direction))
        finite = float((loss(m + 1e-5 * direction) - loss(m - 1e-5 * direction)) / 2e-5)
        error = abs(exact - finite) / max(1., abs(exact), abs(finite))
        checks.append(dict(projection_scale=scale, directional_error=error, passed=error < 2e-5))
    return checks


def main():
    jax.config.update("jax_enable_x64", True)
    verify()
    if (HERE / "validation.json").exists():
        raise RuntimeError("Validation already recorded; retain it and use an explicit new audit")
    start = time.perf_counter()
    protocol = json.loads((HERE / "protocol.json").read_text())
    deterministic = probes()
    checks = derivative_checks(protocol)
    slopes = {}
    for name in ("full", "sigmoid", "c1"):
        slopes[name] = [float(jax.grad(lambda z: models.baseline.gates(z, name)[i])(jnp.array(0.))) for i in (0, 1)]
    result = dict(freeze_sha256=sha(HERE / "freeze.json"), deterministic=deterministic,
                  checks=checks, boundary_q_and_call_slopes=slopes,
                  passed=deterministic["passed"] and all(c["passed"] for c in checks),
                  wall_seconds=time.perf_counter() - start,
                  limits="Local derivatives away from gate/projection seams; no global C1 or long-time gradient theorem")
    atomic_json(HERE / "validation.json", result)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
