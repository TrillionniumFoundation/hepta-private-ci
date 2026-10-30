"""Complete public information and equal-capacity masked neural readouts."""
import numpy as np
import jax
import jax.numpy as jnp
from identity import protocol
from oracle import features as old_features, feasible

jax.config.update("jax_enable_x64", True)


def features(meta, job, tick, budget, posterior, confusion, multiplier):
    original = old_features(meta, job, tick, budget, posterior, confusion, multiplier)
    quality, price = np.zeros((2, 10)), np.zeros((2, 10))
    quality[:, :meta["deadline"]] = np.asarray(meta["reliability"])
    price[:, :meta["deadline"]] = multiplier*np.asarray(meta["price"])
    value = np.concatenate([original, quality.ravel(), price.ravel(), np.asarray(confusion).ravel()])
    assert value.shape == (84,)
    return value


def initialize(seed):
    rng = np.random.default_rng(protocol()["initialization_seed_base"]+seed)
    return dict(w1=(rng.normal(size=(84, 32))/np.sqrt(84)).astype(np.float32),
                b1=np.zeros(32, np.float32), w2=(rng.normal(size=(32, 4))/np.sqrt(32)).astype(np.float32),
                b2=np.zeros(4, np.float32))


def forward(parameters, x):
    return jnp.tanh(x @ parameters["w1"]+parameters["b1"]) @ parameters["w2"]+parameters["b2"]


def numpy_forward(parameters, x):
    return np.tanh(x @ parameters["w1"]+parameters["b1"]) @ parameters["w2"]+parameters["b2"]


def loss(parameters, x, target, valid):
    residual = jnp.where(valid, forward(parameters, x)-target, 0.)
    return jnp.mean(jnp.sum(residual*residual, axis=1)/jnp.sum(valid, axis=1))


@jax.jit
def update(parameters, momentum, variance, number, x, target, valid):
    objective, gradient = jax.value_and_grad(loss)(parameters, x, target, valid)
    beta1, beta2 = jnp.asarray(.9, objective.dtype), jnp.asarray(.999, objective.dtype)
    momentum = jax.tree_util.tree_map(lambda m, g: beta1*m+(1-beta1)*g, momentum, gradient)
    variance = jax.tree_util.tree_map(lambda v, g: beta2*v+(1-beta2)*g*g, variance, gradient)
    step = number+1
    parameters = jax.tree_util.tree_map(lambda w, m, v: w-.003*(m/(1-beta1**step))/(jnp.sqrt(v/(1-beta2**step))+1e-8),
                                         parameters, momentum, variance)
    norm = jnp.sqrt(sum(jnp.sum(g*g) for g in gradient.values()))
    return parameters, momentum, variance, objective, norm


def action(parameters, mean, scale, meta, job, tick, budget, posterior, confusion, multiplier):
    x = ((features(meta, job, tick, budget, posterior, confusion, multiplier)-mean)/scale).astype(np.float32)
    scores = numpy_forward(parameters, x)
    return int(np.argmax(np.where(feasible(meta, job, tick, budget), scores, -np.inf)))
