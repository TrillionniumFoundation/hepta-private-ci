"""Small-state real-graph gradients, independent NumPy replay and solve adjoints."""
import json
from pathlib import Path
import sys

import jax
import jax.numpy as jnp
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from third.memory.freeze import verify, sha
from third.memory.models import init_model, apply_model, read_statistics
from third.memory.reference import forward, readout


def solve_checks():
    rows = []
    key = np.ones(16)/4
    value = np.linspace(-.8, .8, 4)
    for dtype in (jnp.float64, jnp.float32):
        for mass in (1., 1/129, 1/513, 1/4097):
            g = jnp.asarray((.8*np.outer(key, key))[None], dtype)
            h = jnp.asarray((.8*np.outer(key, value))[None], dtype)
            r = jnp.asarray([[mass]], dtype)
            q = jnp.asarray(key[None], dtype)
            for mode in ("fixed", "mass"):
                def loss(gg, hh, rr):
                    read, _, _ = read_statistics(gg, hh, rr, q, mode)
                    return jnp.sum(read**2)
                gradient = jax.grad(loss, argnums=(0, 1, 2))(g, h, r)
                gn, hn, rn = (np.asarray(a, np.float64) for a in (g, h, r))
                matrix = gn[0]+.01*(rn[0, 0] if mode == "mass" else 1.)*np.eye(16)
                fitted = np.linalg.solve(matrix, hn[0])
                read = key @ fitted
                dh = 2*np.outer(np.linalg.solve(matrix.T, key), read)
                dg = -dh @ fitted.T
                dg = .5*(dg+dg.T)
                dr = .01*np.trace(dg) if mode == "mass" else 0.
                refs = (dg[None], dh[None], np.array([[dr]]))
                errors = [float(np.max(np.abs(np.asarray(a)-b))/max(1., np.max(np.abs(b))))
                          for a, b in zip(gradient, refs)]
                answer, jm, jf = read_statistics(g, h, r, q, mode)
                residual = float(jnp.linalg.norm(jm @ jf-h)/jnp.maximum(jnp.linalg.norm(h), 1e-12))
                rows.append(dict(dtype=str(dtype), mode=mode, inverse_mass=mass,
                    condition=float(np.linalg.cond(matrix)), adjoint_errors=errors,
                    relative_residual=residual, finite=bool(np.isfinite(np.asarray(answer)).all()),
                    passed=max(errors) < (1e-8 if dtype == jnp.float64 else .005) and residual < 5e-5))
    return rows


def main():
    frozen = verify()
    p = json.loads((HERE/"protocol.json").read_text())
    standard = p["numerical_standards"]
    jax.config.update("jax_enable_x64", True)
    rng = np.random.default_rng(2026103017)
    x0, dt0 = rng.normal(size=(2, 7, 3)), rng.uniform(.1, 2., (2, 7))
    rows = []
    for variant in p["variants"]:
        name, mode = variant.split("_")
        for precision, dtype in (("float64", jnp.float64), ("float32", jnp.float32)):
            params = jax.tree_util.tree_map(lambda v: jnp.asarray(v, dtype),
                init_model(variant, jax.random.PRNGKey(417), 3, 4, 4))
            x, dt = jnp.asarray(x0, dtype), jnp.asarray(dt0, dtype)
            direction = {k: jnp.asarray(rng.normal(size=v.shape), dtype) for k, v in params.items()}
            norm = jnp.sqrt(sum(jnp.sum(v*v) for v in direction.values()))
            direction = {k: v/norm for k, v in direction.items()}
            def loss(pp):
                return jnp.sum(jnp.tanh(apply_model(pp, x, dt, variant))**2)
            gradient = jax.grad(loss)(params)
            analytic = float(sum(jnp.sum(gradient[k]*direction[k]) for k in params))
            errors = []
            for eps in standard[precision+"_difference_steps"]:
                plus = {k: v+eps*direction[k] for k, v in params.items()}
                minus = {k: v-eps*direction[k] for k, v in params.items()}
                finite = float((loss(plus)-loss(minus))/(2*eps))
                errors.append(abs(finite-analytic)/max(1., abs(analytic)))
            params_np = {k: np.asarray(v) for k, v in params.items()}
            state = forward(params_np, np.asarray(x), np.asarray(dt), name)
            expected, detail = readout(params_np, state, mode)
            actual = np.asarray(apply_model(params, x, dt, variant))
            replay = float(np.max(np.abs(actual-expected)))
            rows.append(dict(variant=variant, dtype=precision, directional_errors=errors,
                numpy_jax_logit_error=replay, solve=detail,
                passed=max(errors) < standard[precision+"_directional_error"]
                and replay < standard["numpy_jax_logit_error"]))
        jax.clear_caches()
        print(variant, rows[-2:][0]["passed"], rows[-1]["passed"], flush=True)
    solves = solve_checks()
    result = dict(passed=all(r["passed"] for r in rows+solves),
                  freeze_sha256=sha(HERE/"freeze.json"), source_sha256=frozen["source_sha256"],
                  graph_checks=rows, solve_checks=solves,
                  scope="Small real recurrent graphs and declared rank-one solve stress only; not a uniform long-time BPTT guarantee")
    (HERE/"numerical_validation.json").write_text(json.dumps(result, indent=2)+"\n")
    print("NUMERICAL_VALIDATION", result["passed"], flush=True)
    if not result["passed"]:
        raise RuntimeError("Numerical validation failed; development training remains closed")


if __name__ == "__main__":
    main()
