"""Cross token length and physical horizon; retain a causal exact-memory control.

The new draws are frozen before evaluation, but this is a diagnostic of reused
checkpoints, not independent architecture confirmation. The delta memory uses
task-known symbol/address encoders and has no learned natural-content claim.
"""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time
import traceback

START_WALL = time.perf_counter()

import numpy as np


SEEDS = (81031, 81032, 81033)
TASKS = ("selective_copy", "mqar")
DATA_SEED = 202610314201
FAMILIES = ("shared", "two_gate_frozen_shared_updates256", "analytic_frozen_shared_updates256")


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def base_content(task, size, seed):
    """Four bindings and their relative physical event times fixed for all cells."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, TASKS.index(task)]))
    x = np.zeros((size, 32, 64), np.float32)
    gold = np.zeros((size, 4), np.int64)
    times = np.cumsum(rng.uniform(.5, 1.5, (size, 32)), axis=1)
    times -= times[:, :1]
    times /= times[:, -1:]
    for row in range(size):
        values = rng.integers(0, 8, 28)
        if task == "selective_copy":
            selected = np.sort(rng.choice(24, 4, replace=False))
            x[row, np.arange(28), values] = 1
            x[row, selected, 8] = 1
            x[row, -4:, 9] = 1
            gold[row] = values[selected]
        else:
            keys = rng.choice(8, 4, replace=False)
            locations = np.sort(rng.choice(16, 4, replace=False))
            x[row, locations, keys] = 1
            x[row, locations, 8 + values[:4]] = 1
            x[row, locations, 16] = 1
            order = rng.permutation(4)
            x[row, np.arange(28, 32), keys[order]] = 1
            x[row, -4:, 17] = 1
            x[row, :28, 18:26] = np.eye(8)[values]
            gold[row] = values[:4][order]
    return x, times, gold


def expand_content(task, base, times, gold, length, horizon, seed):
    """Insert nonsupervised distractors without changing existing event times."""
    size = len(base)
    mapping = np.r_[np.rint(np.linspace(0, length - 5, 28)).astype(int),
                    np.arange(length - 4, length)]
    if len(set(mapping)) != 32:
        raise ValueError("Length must be at least 32")
    rng = np.random.default_rng(np.random.SeedSequence([seed, length, TASKS.index(task), 99]))
    x = np.zeros((size, length, 64), np.float32)
    distractors = rng.integers(0, 8, (size, length - 4))
    offset = 0 if task == "selective_copy" else 18
    for row in range(size):
        x[row, np.arange(length - 4), offset + distractors[row]] = 1
    x[:, mapping] = base
    released = np.stack([np.interp(np.arange(length), mapping, row) for row in times]) * horizon
    dt = np.diff(released, prepend=np.zeros((size, 1)), axis=1).astype(np.float32)
    if task == "selective_copy":
        selected, queried = x[:, :, 8] > 0, x[:, :, 9] > 0
        selected_count, query_count = selected.cumsum(1), queried.cumsum(1)
        x[:, :, 10], x[:, :, 11] = selected_count / 4, query_count / 4
        for address in range(1, 5):
            x[:, :, 11 + address] = ((selected & (selected_count == address)) |
                                     (queried & (query_count == address)))
    if not np.allclose(released[:, mapping], times * horizon, atol=1e-12, rtol=0):
        raise AssertionError("Insertion moved original observations")
    return dict(x=x, dt=dt, gold=gold.copy(), mapping=mapping,
                episode_id=np.arange(size, dtype=np.int64), released=released)


class DeltaMemory:
    """Fixed orthogonal key encoder and causal fast-weight value storage.

    Each write uses M <- M + k (v - k^T M), so writing an existing key replaces
    its previous value. A read uses q^T M. Known one-hot keys are normalized;
    no labels or future inputs enter the state. Unknown reads abstain.
    """

    def __init__(self, addresses):
        self.weights = np.zeros((addresses, 8), np.float32)
        self.present = np.zeros(addresses, bool)

    def step(self, address, value=None):
        address = np.asarray(address, np.float32)
        if address.shape != (len(self.present),) or not np.isin(address, [0, 1]).all() or address.sum() != 1:
            raise ValueError("Exactly one task-known key is required")
        key = int(np.argmax(address))
        if value is not None:
            value = np.asarray(value, np.float32)
            if value.shape != (8,) or not np.isin(value, [0, 1]).all() or value.sum() != 1:
                raise ValueError("Exactly one task-known value is required")
            self.weights += address[:, None] * (value - address @ self.weights)[None, :]
            self.present[key] = True
        return (address @ self.weights).copy() if self.present[key] else None

    @property
    def state_bytes(self):
        return self.weights.nbytes + self.present.nbytes


def exact_recall(task, x):
    probabilities, counters = [], []
    for sequence in x:
        memory = DeltaMemory(4 if task == "selective_copy" else 8)
        selected = queried = writes = reads = 0
        predictions = []
        for token in sequence:
            if task == "selective_copy":
                if token[8] > 0:
                    memory.step(np.eye(4)[selected], token[:8])
                    selected += 1
                    writes += 1
                if token[9] > 0:
                    predictions.append(memory.step(np.eye(4)[queried]))
                    queried += 1
                    reads += 1
            else:
                if token[16] > 0:
                    memory.step(token[:8], token[8:16])
                    writes += 1
                if token[17] > 0:
                    predictions.append(memory.step(token[:8]))
                    reads += 1
        if len(predictions) != 4 or any(item is None for item in predictions):
            raise ValueError("Four defined queries required by this probe")
        probabilities.append(predictions)
        counters.append(dict(inspected_tokens=len(sequence), writes=writes, reads=reads,
                             array_state_bytes=memory.state_bytes,
                             counter_scalars=4, output_buffer_bytes=4 * 8 * 4))
    return np.asarray(probabilities), counters


def protocol(output, checkpoint_root, size):
    output.mkdir(parents=True, exist_ok=False)
    checkpoints = []
    for task in TASKS:
        for seed in SEEDS:
            for family in FAMILIES:
                job = f"{task}_s{seed}_{family}"
                path = checkpoint_root / job / "selected.pt"
                selection = json.loads((path.parent / "selection.json").read_text())
                digest = file_hash(path)
                if digest != selection["selected_checkpoint_sha256"]:
                    raise ValueError(f"Checkpoint selection mismatch: {job}")
                checkpoints.append(dict(job=job, task=task, seed=seed, family=family,
                                        path=str(path), sha256=digest,
                                        selected_step=selection["selected_step"]))
    imports = [Path(__file__), Path(__file__).parent.parent / "hcsn_mechanism_content_v2/content.py",
               Path(__file__).parent.parent / "hcsn_task_value_v1/model.py"]
    plan = dict(schema="hcsn-causal-memory-probe.v3", baseline="c5e159ec6c5ba174b36debacad166da635c57d48",
                prepared_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                data_seed=DATA_SEED, samples=size, fitted_seeds=list(SEEDS),
                lengths=[32, 128], horizons=[3.2, 12.8], reference_lengths=[32, 128, 512],
                checkpoints=checkpoints, sources=[dict(path=str(p), sha256=file_hash(p)) for p in imports],
                frozen_before_new_data=True, checkpoint_selection="Reused v2 validation selections; no refit or reselection",
                endpoint="query accuracy and all-four exact recall; no superiority test",
                matching="Same four bindings, query order, original distractors and normalized event times; insertion adds irrelevant tokens",
                scope="Exploratory counterfactuals of reused models; new synthetic draws, not natural-content or heldout architecture confirmation",
                cost_scope="One-run inference plus complete shared diagnostic process; descriptive only, not isolated-arm economic benchmark",
                structural_reference="Task-known normalized one-hot encoder with causal delta-rule memory; no learned encoder or HCSN benefit")
    write_json(output / "PROTOCOL.json", plan)
    return plan


def infer(model, values, disabled):
    import torch
    probs = []
    wall, cpu = time.perf_counter(), time.process_time()
    with torch.inference_mode():
        for lo in range(0, len(values["x"]), 16):
            x = torch.from_numpy(values["x"][lo:lo + 16])
            dt = torch.from_numpy(values["dt"][lo:lo + 16])
            logits = model(x, dt, disable_adapter=disabled)[:, -4:]
            probs.append(logits.softmax(-1).numpy())
    return np.concatenate(probs), dict(cpu_seconds=time.process_time() - cpu,
                                      wall_seconds=time.perf_counter() - wall)


def summarize(probabilities, gold):
    correct = probabilities.argmax(-1) == gold
    chosen = np.take_along_axis(probabilities, gold[..., None], axis=-1)[..., 0]
    return dict(query_accuracy=float(correct.mean()), exact_recall=float(correct.all(1).mean()),
                nll=float(-np.log(np.maximum(chosen, 1e-12)).mean()), samples=len(gold), queries=gold.size)


def run(output):
    import torch
    from experiments.hcsn_mechanism_content_v2.content import ContentModel
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    plan = json.loads((output / "PROTOCOL.json").read_text())
    for item in plan["sources"] + plan["checkpoints"]:
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Frozen source/checkpoint changed")
    data_dir, prediction_dir = output / "data", output / "predictions"
    data_dir.mkdir()
    prediction_dir.mkdir()
    rows, base = [], {}
    for task in TASKS:
        base[task] = base_content(task, plan["samples"], plan["data_seed"])
        for length in plan["reference_lengths"]:
            for horizon in plan["horizons"]:
                values = expand_content(task, *base[task], length, horizon, plan["data_seed"])
                name = f"{task}_L{length}_H{horizon}"
                np.savez_compressed(data_dir / f"{name}.npz", **values)
                cpu, wall = time.process_time(), time.perf_counter()
                probabilities, counters = exact_recall(task, values["x"])
                cost = dict(cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - wall)
                np.savez_compressed(prediction_dir / f"{name}_delta_memory.npz", probabilities=probabilities,
                                    gold=values["gold"], episode_id=values["episode_id"])
                rows.append(dict(task=task, length=length, horizon=horizon, family="delta_memory", seed=None,
                                 adapter_disabled=False, **summarize(probabilities, values["gold"]), cost=cost,
                                 operation_counts=counters[0], prediction=f"predictions/{name}_delta_memory.npz"))
    for checkpoint in plan["checkpoints"]:
        payload = torch.load(checkpoint["path"], map_location="cpu", weights_only=False)
        model = ContentModel(**payload["config"])
        model.load_state_dict(payload["model_state"], strict=True)
        model.eval()
        for length in plan["lengths"]:
            for horizon in plan["horizons"]:
                values = expand_content(checkpoint["task"], *base[checkpoint["task"]],
                                        length, horizon, plan["data_seed"])
                for disabled in ([False, True] if model.config["family"] != "shared" else [False]):
                    probabilities, cost = infer(model, values, disabled)
                    name = f"{checkpoint['job']}_L{length}_H{horizon}_disabled{int(disabled)}.npz"
                    np.savez_compressed(prediction_dir / name, probabilities=probabilities,
                                        gold=values["gold"], episode_id=values["episode_id"],
                                        checkpoint_sha256=np.asarray(checkpoint["sha256"]))
                    row = dict(task=checkpoint["task"], length=length, horizon=horizon,
                               family=model.config["family"], seed=checkpoint["seed"], adapter_disabled=disabled,
                               **summarize(probabilities, values["gold"]), cost=cost,
                               prediction=f"predictions/{name}")
                    rows.append(row)
                    print(json.dumps({key: row[key] for key in ("task", "length", "horizon", "family", "seed", "adapter_disabled", "exact_recall")}), flush=True)
    write_json(output / "RESULTS.json", dict(rows=rows, protocol_sha256=file_hash(output / "PROTOCOL.json")))
    files = [dict(path=str(p.relative_to(output)), sha256=file_hash(p), bytes=p.stat().st_size)
             for p in sorted(output.rglob("*")) if p.is_file()]
    usage = resource.getrusage(resource.RUSAGE_SELF)
    write_json(output / "RECEIPT.json", dict(schema="hcsn-memory-diagnostic-receipt.v3", files=files,
        process_cpu_seconds=usage.ru_utime + usage.ru_stime, body_wall_seconds=time.perf_counter() - START_WALL,
        process_maxrss_kib=usage.ru_maxrss, import_loading_included_in_cpu=True,
        startup_wall_excluded=True, final_receipt_serialization_excluded=True,
        host_shared=True, energy_joules=None, training_performed=False,
        historical_training_cost="Not recharged or erased; this receipt covers follow-up evaluation only"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-root", type=Path)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        if args.checkpoint_root is None:
            parser.error("--prepare requires --checkpoint-root")
        protocol(args.output, args.checkpoint_root, args.samples)
    if args.run:
        try:
            run(args.output)
        except Exception:
            write_json(args.output / "FAILURE.json", dict(traceback=traceback.format_exc()))
            raise


if __name__ == "__main__":
    main()
