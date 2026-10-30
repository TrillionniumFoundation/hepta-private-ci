"""Fifteen paired controller trainings with one validation-regret selection rule."""
import csv
import hashlib
import time
import numpy as np
import jax
import jax.numpy as jnp
from identity import HERE, protocol, save, sha, verify
from cohorts import make_states
from network import initialize, forward, numpy_forward, update

PREDICT = jax.jit(forward)


def metrics(logits, data):
    predictions = np.argmax(np.where(data["valid"], logits, -np.inf), axis=1)
    best = np.max(np.where(data["valid"], data["full"], -np.inf), axis=1)
    selected = data["full"][np.arange(len(predictions)), predictions]
    return dict(regret=float(np.mean(best-selected)),
                disagreement=float(np.mean(predictions != data["action"])),
                maximum_regret=float(np.max(best-selected)))


def raw_hash(values):
    h = hashlib.sha256()
    for name in sorted(values):
        h.update(name.encode())
        h.update(np.asarray(values[name]).tobytes())
    return h.hexdigest()


def train_one(seed, family, train, validation, mean, scale):
    verify()
    p = protocol()
    wall, cpu = time.perf_counter(), time.process_time()
    folder = HERE / "runs" / f"{family}_seed{seed}"
    assert not (folder / "run.json").exists(), "Do not replace a completed run"
    folder.mkdir(parents=True, exist_ok=True)
    initial = initialize(seed)
    assert sum(v.size for v in initial.values()) == p["parameter_count"]
    parameters = jax.tree_util.tree_map(jnp.asarray, initial)
    zero = jax.tree_util.tree_map(jnp.zeros_like, parameters)
    target = np.eye(4)[train["action"]] if family == "ordinary_boundary" else train["full" if family == "full_value" else "first"]
    target = jnp.asarray(target/2., jnp.float32)
    x = jnp.asarray(((train["x"]-mean)/scale).astype(np.float32))
    vx = jnp.asarray(((validation["x"]-mean)/scale).astype(np.float32))
    valid = jnp.asarray(train["valid"])
    start, start_cpu = time.perf_counter(), time.process_time()
    compiled = update.lower(parameters, zero, zero, jnp.int32(0), x[:64], target[:64], valid[:64]).compile()
    compile_wall, compile_cpu = time.perf_counter()-start, time.process_time()-start_cpu
    momentum, variance = zero, zero
    rng = np.random.default_rng(p["optimizer_seed_base"]+seed)
    batch_digest = hashlib.sha256()
    best, history, rows = None, [], []
    update_wall = update_cpu = validation_wall = validation_cpu = serialization_wall = 0.
    for step in range(1, p["training_updates"]+1):
        ids = rng.integers(0, len(train["x"]), p["batch_size"], dtype=np.int32)
        batch_digest.update(ids.tobytes())
        start, start_cpu = time.perf_counter(), time.process_time()
        parameters, momentum, variance, objective, norm = compiled(parameters, momentum, variance,
            jnp.int32(step-1), x[ids], target[ids], valid[ids])
        objective.block_until_ready()
        elapsed, elapsed_cpu = time.perf_counter()-start, time.process_time()-start_cpu
        update_wall += elapsed
        update_cpu += elapsed_cpu
        loss_value, gradient_norm = float(objective), float(norm)
        assert np.isfinite(loss_value) and np.isfinite(gradient_norm)
        rows.append([step, loss_value, gradient_norm, elapsed, elapsed_cpu])
        if step % p["checkpoint_interval"] == 0:
            start, start_cpu = time.perf_counter(), time.process_time()
            logits = np.asarray(PREDICT(parameters, vx))
            score = metrics(logits, validation)
            validation_wall += time.perf_counter()-start
            validation_cpu += time.process_time()-start_cpu
            start = time.perf_counter()
            checkpoint = folder / f"candidate_{step:04d}.npz"
            arrays = {name: np.asarray(value) for name, value in parameters.items()}
            np.savez_compressed(checkpoint, **arrays, feature_mean=mean, feature_scale=scale)
            entry = dict(step=step, **score, checkpoint=str(checkpoint.relative_to(HERE)), sha256=sha(checkpoint))
            history.append(entry)
            if best is None or score["regret"] < best["regret"]:
                best = entry.copy()
            serialization_wall += time.perf_counter()-start
    with (folder / "updates.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["update", "masked_loss", "gradient_norm", "wall_seconds", "cpu_seconds"])
        writer.writerows(rows)
    selected_arrays = dict(np.load(HERE / best["checkpoint"]))
    selected = {name: selected_arrays[name] for name in initial}
    independent_logits = numpy_forward(selected, np.asarray(vx))
    main_logits = np.asarray(PREDICT(jax.tree_util.tree_map(jnp.asarray, selected), vx))
    error = float(np.max(np.abs(independent_logits-main_logits)))
    assert error < 1e-5
    independent_metrics = metrics(independent_logits, validation)
    assert abs(independent_metrics["regret"]-best["regret"]) < 1e-10
    np.savez_compressed(folder / "selected_validation.npz", logits=independent_logits,
                        valid=validation["valid"], full_q=validation["full"])
    updated = {name: float(np.max(np.abs(selected[name]-initial[name]))) for name in initial}
    result = dict(seed=seed, family=family, complete=True, updates=p["training_updates"],
        trainable_parameters=sum(v.size for v in initial.values()), initialization_sha256=raw_hash(initial),
        batch_stream_sha256=batch_digest.hexdigest(), selected=best, candidates=history,
        independently_replayed_validation=independent_metrics, numpy_jax_max_logit_error=error,
        parameter_updates=updated, all_parameter_groups_updated=all(v > 0. for v in updated.values()),
        compile_wall_seconds=compile_wall, compile_cpu_seconds=compile_cpu,
        optimizer_wall_seconds=update_wall, optimizer_cpu_seconds=update_cpu,
        validation_wall_seconds=validation_wall, validation_cpu_seconds=validation_cpu,
        checkpoint_serialization_wall_seconds=serialization_wall,
        total_wall_seconds=time.perf_counter()-wall, total_cpu_seconds=time.process_time()-cpu,
        updates_sha256=sha(folder / "updates.csv"),
        selected_validation_sha256=sha(folder / "selected_validation.npz"),
        scientific_freeze_sha256=sha(HERE / "freeze.json"))
    save(folder / "run.json", result)
    print(dict(seed=seed, family=family, selected_update=best["step"], validation_regret=best["regret"]), flush=True)
    return result


def seed_data(seed, manifest, confusion):
    start, cpu = time.perf_counter(), time.process_time()
    train = make_states(seed, "train", manifest, confusion)
    val = make_states(seed, "validation", manifest, confusion)
    folder = HERE / "states" / f"seed{seed}"
    folder.mkdir(parents=True, exist_ok=True)
    for split, data in (("train", train), ("validation", val)):
        np.savez_compressed(folder / f"{split}.npz", **{name: value for name, value in data.items() if name != "provenance"})
        save(folder / f"{split}_provenance.json", data["provenance"])
    mean, scale = train["x"].mean(axis=0), train["x"].std(axis=0)
    mean[0], scale[0] = 0., 1.
    scale[scale < 1e-8] = 1.
    return train, val, mean, scale, dict(seed=seed, oracle_state_and_serialization_wall_seconds=time.perf_counter()-start,
        oracle_state_and_serialization_cpu_seconds=time.process_time()-cpu,
        train_sha256=sha(folder / "train.npz"), validation_sha256=sha(folder / "validation.npz"),
        training_states=len(train["x"]), validation_states=len(val["x"]))
