"""Fixed-opportunity training with every candidate and update log retained."""
import csv
from pathlib import Path
import time

import jax
import jax.numpy as jnp
from jax.example_libraries import optimizers
import numpy as np

from next.common import evaluate_model, strong_parameters, signature
from third.memory.execution import atomic_checkpoint


def train(params, apply_fn, training, validation, seed, directory, protocol):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu_started = time.perf_counter(), time.process_time()
    params = strong_parameters(params)
    init, update, get = optimizers.adam(protocol["learning_rate"])
    state = init(params)
    initial_signature = signature(state)
    def loss_fn(p, x, dt, y):
        logits = apply_fn(p, x, dt)
        return -jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(len(y)), y])
    @jax.jit
    def step(index, opt_state, x, dt, y):
        loss, gradient = jax.value_and_grad(loss_fn)(get(opt_state), x, dt, y)
        norm = jnp.sqrt(sum(jnp.sum(g * g) for g in jax.tree_util.tree_leaves(gradient)))
        gradient = jax.tree_util.tree_map(lambda g: g * jnp.minimum(1., 1. / (norm + 1e-8)), gradient)
        return update(index, gradient, opt_state), loss, norm
    compiled = {}
    stamp = time.perf_counter()
    batch_size = protocol["batch_size"]
    for dataset in training:
        batch = tuple(jnp.asarray(dataset[k][:batch_size]) for k in ("x", "dt", "y"))
        compiled[dataset["x"].shape[1]] = step.lower(jnp.asarray(0, jnp.int32), state, *batch).compile()
    compilation = time.perf_counter() - stamp
    rng = np.random.default_rng(50000 + seed)
    best_loss, best, best_step = float("inf"), params, 0
    history, execution, validation_seconds = [], [], 0.
    steps = protocol["training_updates"]
    with (directory / "updates.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("update", "training_length", "loss", "unclipped_gradient_norm", "optimizer_wall_seconds"))
        for index in range(steps):
            dataset = training[index % len(training)]
            ids = rng.integers(0, len(dataset["y"]), batch_size)
            batch = tuple(jnp.asarray(dataset[k][ids]) for k in ("x", "dt", "y"))
            stamp = time.perf_counter()
            state, loss, norm = compiled[dataset["x"].shape[1]](jnp.asarray(index, jnp.int32), state, *batch)
            jax.block_until_ready((state, loss, norm))
            elapsed = time.perf_counter() - stamp
            execution.append(elapsed)
            if not np.isfinite(float(loss)) or not np.isfinite(float(norm)):
                raise FloatingPointError(f"Nonfinite update {index}")
            if index in (0, 1, steps - 1) and signature(state) != initial_signature:
                raise RuntimeError("Optimizer signature changed")
            writer.writerow((index + 1, dataset["x"].shape[1], float(loss), float(norm), elapsed))
            if (index + 1) % 50 == 0:
                stamp = time.perf_counter()
                candidate = get(state)
                metrics = evaluate_model(apply_fn, candidate, validation)
                validation_seconds += time.perf_counter() - stamp
                path = directory / f"candidate_{index + 1:04d}.npz"
                atomic_checkpoint(path, candidate)
                history.append(dict(step=index + 1, validation=metrics, checkpoint=path.name))
                if metrics["loss"] < best_loss:
                    best_loss, best, best_step = metrics["loss"], candidate, index + 1
                handle.flush()
    return best, history, dict(steps=steps, batch_size=batch_size, best_step=best_step,
                              learning_rate=protocol["learning_rate"], compilation_seconds=compilation,
                              optimizer_seconds=sum(execution), validation_seconds=validation_seconds,
                              train_call_wall_seconds=time.perf_counter() - started,
                              train_call_cpu_seconds=time.process_time() - cpu_started,
                              candidates_retained=len(history), warmup_updates=0,
                              parameters_actually_updated=any(not np.array_equal(np.asarray(params[k]), np.asarray(best[k])) for k in params))
