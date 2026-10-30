"""Independent recurrence equivalence and directional-gradient checks before heads."""
import json
from pathlib import Path
import sys

import jax
jax.config.update("jax_enable_x64", True)
import jax.numpy as jnp
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from next.ablation.models import apply_model as previous_apply
from next.full_kernel import as_jax_table
from third.encoder.models import apply_dynamic, gates, init_model


def main():
    rng = np.random.default_rng(981732)
    table = as_jax_table(dict(np.load(ROOT/"next/full_kernel/baseline_table.npz")), jnp.float64)
    p = init_model("full_hx", jax.random.PRNGKey(9123), 5, 3, 2)
    p = jax.tree_util.tree_map(lambda a: jnp.asarray(a, jnp.float64), p)
    x = jnp.asarray(rng.normal(size=(2, 7, 5)))
    dt = jnp.asarray(rng.uniform(.05, 2, size=(2, 7)))
    previous = previous_apply(p, x, dt, "full", table)
    actual = apply_dynamic(p, x, dt, "full_hx", table)
    equivalence_error = float(jnp.max(jnp.abs(previous-actual)))
    assert equivalence_error < 1e-12
    direction = jax.tree_util.tree_map(lambda a: jnp.asarray(rng.normal(size=a.shape)), p)
    norm = np.sqrt(sum(float(jnp.sum(v*v)) for v in jax.tree_util.tree_leaves(direction)))
    direction = jax.tree_util.tree_map(lambda a: a/norm, direction)
    gradients = []
    for kind in ("full_hx", "same_call_sigmoid", "ordinary_c1"):
        def loss(params):
            return jnp.sum(jnp.tanh(apply_dynamic(params, x, dt, kind, table)))
        grad = jax.grad(loss)(p)
        analytic = sum(float(jnp.sum(a*b)) for a, b in zip(jax.tree_util.tree_leaves(grad),
                                                         jax.tree_util.tree_leaves(direction)))
        epsilon = 1e-5
        plus = jax.tree_util.tree_map(lambda a, b: a+epsilon*b, p, direction)
        minus = jax.tree_util.tree_map(lambda a, b: a-epsilon*b, p, direction)
        finite = float((loss(plus)-loss(minus))/(2*epsilon))
        error = abs(analytic-finite)/(1+abs(finite))
        assert error < 1e-7, (kind, error)
        gradients.append(dict(kind=kind, autodiff=analytic, central_difference=finite, scaled_error=error))
    z = jnp.asarray([-1e-6, 0., 1e-6])
    q, a = gates(z, "ordinary_c1", table)
    dq = jax.vmap(jax.grad(lambda t: gates(t, "ordinary_c1", table)[0]))(z)
    da = jax.vmap(jax.grad(lambda t: gates(t, "ordinary_c1", table)[1]))(z)
    assert abs(float(dq[1])) == 0 and abs(float(da[1])) == 0
    extreme = gates(jnp.asarray([-1e30, 1e30], jnp.float32), "ordinary_c1", table)
    assert all(np.isfinite(np.asarray(value)).all() for value in extreme)
    result = dict(passed=True, full_hx_old_recurrence_max_error=equivalence_error,
                  directional_gradients=gradients,
                  ordinary_c1_join=dict(z=np.asarray(z).tolist(), q=np.asarray(q).tolist(),
                                        a=np.asarray(a).tolist(), dq=np.asarray(dq).tolist(), da=np.asarray(da).tolist()),
                  scope="Numerical local directions and exact recurrence comparison; not a long-time stability proof")
    (HERE/"validation.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
