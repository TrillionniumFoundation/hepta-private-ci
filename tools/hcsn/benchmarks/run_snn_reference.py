"""Run one fixed conventional SNN on the existing v1 and frozen-text protocols."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time
import numpy as np
import jax
import jax.numpy as jnp
from jax.example_libraries import optimizers
try:
    from .data import INPUT_DIM, OUTPUT_DIM, TASKS, dataset_suite, fingerprint
    from .snn_models import init_model, apply_model, matched_width
    from .models import parameter_count
    from .train import train_model, evaluate_dataset
    from .validate_snn import validate
except ImportError:
    from data import INPUT_DIM, OUTPUT_DIM, TASKS, dataset_suite, fingerprint
    from snn_models import init_model, apply_model, matched_width
    from models import parameter_count
    from train import train_model, evaluate_dataset
    from validate_snn import validate


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_trainer():
    init_opt, update_opt, get_params = optimizers.adam(.003)
    def loss_fn(p, x, dt, y):
        logits = apply_model(p, x, dt)
        return -jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(y.shape[0]), y])
    @jax.jit
    def step(i, state, x, dt, y):
        loss, g = jax.value_and_grad(loss_fn)(get_params(state), x, dt, y)
        norm = jnp.sqrt(sum(jnp.sum(v*v) for v in jax.tree_util.tree_leaves(g)))
        g = jax.tree_util.tree_map(lambda v: v*jnp.minimum(1., 1./(norm+1e-8)), g)
        return update_opt(i, g, state), loss, norm
    @jax.jit
    def evaluate(p, x, dt, y):
        logits = apply_model(p, x, dt)
        prob = jax.nn.softmax(logits)
        return (-jnp.mean(jax.nn.log_softmax(logits)[jnp.arange(y.shape[0]), y]),
                jnp.mean(jnp.argmax(logits, -1) == y),
                jnp.mean(jnp.sum((prob-jax.nn.one_hot(y, logits.shape[-1]))**2, axis=-1)))
    return init_opt, step, get_params, evaluate


def spike_statistics(p, data):
    # Diagnostics on a fixed first batch; not an energy or event-driven cost estimate.
    _, aux = apply_model(p, jnp.asarray(data["x"][:128]),
                         jnp.asarray(data["dt"][:128]), return_aux=True)
    spikes = np.asarray(aux["spikes"])
    assert np.all((spikes == 0.) | (spikes == 1.))
    return dict(examples=min(128, len(data["y"])), binary_forward_verified=True,
                active_fraction=float(spikes.mean()),
                mean_spikes_per_example=float(spikes.sum(axis=(1, 2)).mean()),
                tau_membrane_mean=float(np.mean(aux["tau_membrane"])),
                tau_readout_mean=float(np.mean(aux["tau_readout"])))


def summary(rows):
    result = {}
    for task in sorted(set(r["task"] for r in rows)):
        group = [r for r in rows if r["task"] == task]
        result[task] = dict(parameter_count=group[0]["parameter_count"],
                            persistent_state_scalars=group[0]["persistent_state_scalars"],
                            seeds=[r["seed"] for r in group])
        for split in group[0]["metrics"]:
            values = np.array([r["metrics"][split]["accuracy"] for r in group])
            result[task][split] = dict(mean_accuracy=float(values.mean()),
                                      sample_sd=float(values.std(ddof=1)) if len(values)>1 else None)
        result[task]["mean_train_call_wall_seconds_including_validation_jit"] = float(np.mean([
            r["timing"]["train_call_wall_seconds_including_validation_jit"] for r in group]))
        result[task]["mean_train_call_process_cpu_seconds_including_validation_jit"] = float(np.mean([
            r["timing"]["train_call_process_cpu_seconds_including_validation_jit"] for r in group]))
    return result


def train_one(task, seed, suite, input_dim, output_dim, budget, trainer, folder, frozen=False):
    width, count = matched_width(input_dim, output_dim, budget)
    initial_seed = seed if frozen else 1000 + seed
    params = init_model(jax.random.PRNGKey(initial_seed), input_dim, width, output_dim)
    assert parameter_count(params) == count
    wall_start = time.perf_counter(); cpu_start = time.process_time()
    learned, history, timing = train_model(params, "snn_lif", suite["train"],
        suite["validation"], seed, steps=300, batch_size=32, lr=.003, trainer=trainer)
    timing["train_call_wall_seconds_including_validation_jit"] = time.perf_counter() - wall_start
    timing["train_call_process_cpu_seconds_including_validation_jit"] = time.process_time() - cpu_start
    timing["interpretation"] = "Diagnostic only, shared CPU and cache-order effects; no speed or energy inference. Legacy warm_training_seconds excludes only update 1 and is not asserted pure warm."
    evaluate = trainer[3]
    metrics = {name: evaluate_dataset(evaluate, learned, data) for name, data in suite.items()}
    checkpoint = folder / "snn_reference_checkpoints" / f"{task}_seed{seed}.npz"
    checkpoint.parent.mkdir(exist_ok=True)
    np.savez_compressed(checkpoint, **{k: np.asarray(v) for k, v in learned.items()})
    return dict(task=task, kind="snn_lif", seed=seed, initial_seed=initial_seed,
                width=width, parameter_count=count, persistent_state_scalars=3*width,
                data_sha256={name: fingerprint(data) for name, data in suite.items()},
                history=history, timing=timing, metrics=metrics,
                spike_diagnostics=spike_statistics(learned, suite["test"]),
                checkpoint_file=str(checkpoint.relative_to(folder)), checkpoint_sha256=sha(checkpoint),
                process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("/tmp/hcsn-encoder-assets/frozen_features.npz"))
    args = parser.parse_args()
    folder = Path(__file__).parent
    protocol = json.loads((folder / "snn_protocol.json").read_text())
    validate_result = validate()
    (folder / "snn_validation.json").write_text(json.dumps(validate_result, indent=2))
    names = ("snn_models.py", "run_snn_reference.py", "validate_snn.py", "snn_protocol.json",
             "data.py", "train.py", "models.py")
    metadata = dict(protocol=protocol, source_sha256={name: sha(folder/name) for name in names},
                    python=platform.python_version(), jax=jax.__version__, numpy=np.__version__,
                    cpu_affinity=sorted(os.sched_getaffinity(0)), devices=[str(v) for v in jax.devices()],
                    gradient_validation=validate_result,
                    comparison_status="Additional post-declared baseline on already examined holdouts; exploratory, not a new independent confirmation",
                    timing_caveat="All timing fields are diagnostic; cache and shared CPU effects prevent speed/energy conclusions; old warm_training_seconds may include secondary JIT compilation",
                    scope="Dense CPU reference simulation of hard-spiking neurons; no energy or neuromorphic hardware measurement")
    v1_rows = json.loads((folder/"sequence_results.json").read_text())["runs"]
    original_hashes = {(r["task"], r["seed"]): r["data_sha256"] for r in v1_rows}
    result = dict(metadata=metadata, runs=[], complete=False)
    start = time.perf_counter()
    trainer = make_trainer()
    for task in TASKS:
        for seed in protocol["seeds"]:
            suite = dataset_suite(task, seed)
            hashes = {name: fingerprint(data) for name, data in suite.items()}
            assert hashes == original_hashes[task, seed], (task, seed, "v1 data mismatch")
            row = train_one(task, seed, suite, INPUT_DIM, OUTPUT_DIM, 6200, trainer, folder)
            row["data_exactly_matches_v1"] = True
            result["runs"].append(row)
            result["summary"] = summary(result["runs"])
            result["elapsed_seconds"] = time.perf_counter() - start
            (folder/"snn_reference_results.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(dict(task=task, seed=seed, test=row["metrics"]["test"]["accuracy"],
                long=row["metrics"]["long"]["accuracy"], parameters=row["parameter_count"],
                active_spikes=row["spike_diagnostics"]["active_fraction"])), flush=True)
    result["complete"] = True
    (folder/"snn_reference_results.json").write_text(json.dumps(result, indent=2))

    before = sha(args.features)
    assert before == protocol["frozen_features_sha256"]
    with np.load(args.features) as raw:
        suite = {split: {key: raw[split+"_"+key].copy() for key in ("x", "dt", "y")}
                 for split in ("train", "validation", "test")}
    rng = np.random.default_rng(20261101)
    corrupt = {k: v.copy() for k, v in suite["test"].items()}
    keep = rng.random(corrupt["x"].shape[:2]) > .2; keep[:, -1] = True
    corrupt["x"] = ((corrupt["x"]+rng.normal(0, .15, corrupt["x"].shape))*keep[..., None]).astype(np.float32)
    suite["corrupted_test"] = corrupt
    frozen = dict(metadata=dict(metadata, feature_sha256=before,
        shared_encoder_frozen=True, shared_training_only_pca=True,
        perturbation="Local feature-block dropout and noise, full-sentence global feature preserved; does not test raw missing inputs"),
        runs=[], complete=False)
    frozen_start = time.perf_counter()
    for seed in protocol["seeds"]:
        row = train_one("frozen_text", seed, suite, 64, 2, 6000, trainer, folder, frozen=True)
        frozen["runs"].append(row); frozen["summary"] = summary(frozen["runs"])
        frozen["elapsed_seconds"] = time.perf_counter() - frozen_start
        (folder/"snn_frozen_results.json").write_text(json.dumps(frozen, indent=2))
        print(json.dumps(dict(task="frozen_text", seed=seed, test=row["metrics"]["test"]["accuracy"],
            corrupted_test=row["metrics"]["corrupted_test"]["accuracy"], parameters=row["parameter_count"],
            active_spikes=row["spike_diagnostics"]["active_fraction"])), flush=True)
    frozen["feature_sha_after_training"] = sha(args.features)
    assert frozen["feature_sha_after_training"] == before
    frozen["complete"] = True
    (folder/"snn_frozen_results.json").write_text(json.dumps(frozen, indent=2))
    print(json.dumps(dict(synthetic=result["summary"], frozen=frozen["summary"]), indent=2), flush=True)


if __name__ == "__main__":
    main()
