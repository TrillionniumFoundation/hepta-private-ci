"""Check binary forward and the declared approximate backward rule, not hard FD."""

import json
from pathlib import Path
import numpy as np
import jax
import jax.numpy as jnp
try:
    from .snn_models import init_model, apply_model, matched_width, hard_spike
    from .models import parameter_count
except ImportError:
    from snn_models import init_model, apply_model, matched_width, hard_spike
    from models import parameter_count


def validate():
    z = jnp.array([-2., -1e-6, 0., 1e-6, 2.], dtype=jnp.float32)
    forward = hard_spike(z)
    backward = jax.vmap(jax.grad(hard_spike))(z)
    expected = 1. / (1. + 5. * np.abs(np.asarray(z))) ** 2
    assert np.array_equal(np.asarray(forward), [0., 0., 1., 1., 1.])
    assert np.allclose(np.asarray(backward), expected, atol=1e-7)
    width, count = matched_width(16, 4)
    p = init_model(jax.random.PRNGKey(99), 16, width, 4)
    assert parameter_count(p) == count
    assert not any(v.weak_type for v in jax.tree_util.tree_leaves(p))
    x = .3 * jax.random.normal(jax.random.PRNGKey(101), (4, 32, 16))
    dt = jnp.ones((4, 32), dtype=jnp.float32)
    logits, aux = apply_model(p, x, dt, return_aux=True)
    values = np.unique(np.asarray(aux["spikes"]))
    assert set(values.tolist()) == {0., 1.}
    loss = lambda pp: -jnp.mean(jax.nn.log_softmax(apply_model(pp, x, dt))[:, 0])
    gradient = jax.grad(loss)(p)
    norms = {name: float(jnp.linalg.norm(v)) for name, v in gradient.items()}
    assert all(np.isfinite(list(norms.values()))) and norms["inp"] > 0.
    assert norms["tau_membrane"] > 0. and norms["recurrent"] > 0.
    assert np.allclose(np.asarray(aux["tau_membrane"]), 4., atol=1e-6)
    assert np.allclose(np.asarray(aux["tau_readout"]), 16., atol=1e-6)
    assert np.all(np.isfinite(np.asarray(logits)))
    result = dict(passed=True, jax=jax.__version__, dtype="float32",
                  parameter_count=count, width=width, persistent_state_scalars=3*width,
                  tested_threshold_offsets=np.asarray(z).tolist(),
                  hard_forward=np.asarray(forward).tolist(),
                  backward=np.asarray(backward).tolist(), declared_surrogate=expected.tolist(),
                  parameter_gradient_norms=norms, spike_values=values.tolist(),
                  spike_fraction=float(jnp.mean(aux["spikes"])),
                  every_initial_parameter_strong_float32=True,
                  interpretation="Backward matches the declared surrogate; it is not the true derivative of hard forward, so finite-difference equality is not claimed")
    return result


if __name__ == "__main__":
    result = validate()
    (Path(__file__).parent / "snn_validation.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
