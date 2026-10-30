"""Fresh named streams and extraction through the unmodified native forward."""

import contextlib
import gzip
import importlib.metadata
import io
import os
import platform
import time

import numpy as np

from .artifacts import canonical, entry, sha, write_bytes, write_json


def runtime_identity(config, *, encoder):
    import scipy

    expected = config["runtime"]
    versions = {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__}
    for name, value in versions.items():
        if value != expected[name]:
            raise ValueError(f"Runtime mismatch: {name}={value}, expected {expected[name]}")
    for name in expected["thread_environment"]:
        if os.environ.get(name) != "1":
            raise ValueError(name + " must equal 1 before importing numerical libraries")
    libraries = ["numpy", "scipy"]
    if encoder:
        import torch

        if torch.__version__ != expected["torch"]:
            raise ValueError("The registered CPU Torch version is required")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        if torch.get_num_threads() != 1 or torch.get_num_interop_threads() != 1:
            raise ValueError("Torch thread configuration mismatch")
        versions.update(torch=torch.__version__, torch_threads=1, torch_interop_threads=1,
                        torch_deterministic=True, torch_build=torch.__config__.show())
        libraries.append("torch")
    versions["installed_distribution_metadata"] = {}
    for name in libraries:
        distribution = importlib.metadata.distribution(name)
        records = {field: distribution.read_text(field) for field in ("METADATA", "RECORD")}
        if not all(records.values()):
            raise ValueError("Installed distribution lacks wheel identity records: " + name)
        versions["installed_distribution_metadata"][name] = {
            field + "_sha256": sha(value.encode()) for field, value in records.items()}
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        np.show_config()
    versions.update(numpy_build=captured.getvalue(), platform=platform.platform(),
                    thread_environment={name: os.environ[name] for name in expected["thread_environment"]})
    return versions


def stream(config, role, encoder_seed, example, rollout):
    key = f"{config['namespace']}|{role}|{encoder_seed}|{example}|{rollout}"
    digest = sha(key.encode("utf-8"))
    return {"key": key, "sha256": digest, "seed_decimal": str(int.from_bytes(bytes.fromhex(digest), "little"))}


def bootstrap_stream(config):
    key = config["namespace"] + "|bootstrap"
    digest = sha(key.encode("utf-8"))
    return {"key": key, "sha256": digest, "seed_decimal": str(int.from_bytes(bytes.fromhex(digest), "little"))}


def order_example(identity):
    # Same order-task distribution as frozen tasks.py, with a new per-example stream.
    rng = np.random.Generator(np.random.PCG64(int(identity["seed_decimal"])))
    label = rng.integers(0, 2, size=1).astype(np.float64)[0]
    inputs = rng.normal(0, 0.12, size=(1, 8, 2))[0]
    early, late = int(rng.integers(1, 3)), int(rng.integers(5, 7))
    inputs[early, int(label)] += 2.5
    inputs[late, 1 - int(label)] += 2.5
    return inputs, label


def restore_encoder(checkpoint, seed):
    import torch
    from ..first_passage_operator.network import RenewalNetwork

    net = RenewalNetwork(kind="first_passage", seed=seed, dtype=torch.float64)
    net.load_state_dict({name: torch.tensor(value, dtype=torch.float64) for name, value in checkpoint.items()}, strict=True)
    net.requires_grad_(False)
    net.eval()
    if sum(value.numel() for value in net.parameters()) != 55 or encoded(net) != canonical(checkpoint):
        raise ValueError("Frozen parameter restoration mismatch")
    return net


def encoded(net):
    return canonical({name: value.detach().numpy().tolist() for name, value in net.state_dict().items()})


def native_feature(net, inputs, identity):
    import torch

    with torch.no_grad():
        logits, logs = net(torch.as_tensor(inputs[None], dtype=torch.float64),
                           noise_seed=int(identity["seed_decimal"]), capture=True)
        decay = torch.exp(-0.25 / net.physical()["decay"])
        trace = torch.zeros((1, 3), dtype=torch.float64)
        counts = np.zeros((2, 3), dtype=np.int64)
        if [(row["step"], row["layer"]) for row in logs] != [(step, layer) for step in range(8) for layer in range(2)]:
            raise ArithmeticError("The native one-segment log contract changed")
        for row in logs:
            count = row["count"]
            if not np.isfinite(count).all() or np.any(count != np.floor(count)) or np.any(count < 0):
                raise ArithmeticError("Invalid native count")
            if len(row["events"]) != int(count.sum()):
                raise ArithmeticError("Native event log disagrees with count")
            counts[row["layer"]] += count[0].astype(np.int64)
            if row["layer"] == 1:
                trace = trace * decay[1] + torch.as_tensor(count) * (1 - decay[1]) / 0.25
        affine = trace @ net.readout + net.output_bias
        if not torch.allclose(affine, logits, rtol=1e-12, atol=1e-12):
            raise ArithmeticError("Captured features do not reproduce the native affine score")
        feature, logit = trace[0].numpy().copy(), float(logits[0])
        if not np.isfinite(feature).all() or not np.isfinite(logit):
            raise ArithmeticError("Non-finite native feature or score")
        return feature, logit, counts, float(torch.abs(affine - logits).max())


def save_arrays(path, arrays):
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    write_bytes(path, buffer.getvalue())
    return {name: {"shape": list(value.shape), "dtype": value.dtype.str,
                   "c_order_sha256": sha(np.ascontiguousarray(value).tobytes())}
            for name, value in arrays.items()}


def generate_cache(net, seed, split, config, directory):
    size, repeats = config["splits"][split]
    prefix = f"cache/{seed}/{split}"
    initial_parameters = encoded(net)
    all_arrays, shards, total_events, max_error = [], [], 0, 0.0
    begin = time.perf_counter()
    for start in range(0, size, 64):
        number = min(64, size - start)
        arrays = {"inputs": np.full((number, 8, 2), np.nan), "labels": np.full(number, np.nan),
                  "features": np.full((number, repeats, 3), np.nan), "native_logits": np.full((number, repeats), np.nan),
                  "event_counts": np.full((number, repeats, 2, 3), -1, dtype=np.int64),
                  "affine_absolute_error": np.full((number, repeats), np.nan),
                  "completed": np.zeros((number, repeats), dtype=bool)}
        streams = []
        try:
            for offset in range(number):
                index = start + offset
                input_identity = stream(config, split + "/input", seed, index, -1)
                row = {"example_index": index, "input": input_identity, "trajectories": []}
                streams.append(row)
                inputs, label = order_example(input_identity)
                arrays["inputs"][offset], arrays["labels"][offset] = inputs, label
                for repetition in range(repeats):
                    identity = stream(config, split + "/trajectory", seed, index, repetition)
                    row["trajectories"].append(identity)
                    feature, logit, counts, error = native_feature(net, inputs, identity)
                    for key, value in (("features", feature), ("native_logits", logit),
                                       ("event_counts", counts), ("affine_absolute_error", error)):
                        arrays[key][offset, repetition] = value
                    arrays["completed"][offset, repetition] = True
                    total_events += int(counts.sum())
                    max_error = max(max_error, error)
        except Exception:
            # Preserve every attempted stream and completed feature in the failing shard.
            save_arrays(directory / f"{prefix}_{start:04d}.partial.npz", arrays)
            raw = b"".join(canonical(row) + b"\n" for row in streams)
            write_bytes(directory / f"{prefix}_{start:04d}.partial.streams.jsonl.gz", gzip.compress(raw, mtime=0))
            raise
        path = directory / f"{prefix}_{start:04d}.npz"
        array_metadata = save_arrays(path, arrays)
        random_path = directory / f"{prefix}_{start:04d}.streams.jsonl.gz"
        raw = b"".join(canonical(row) + b"\n" for row in streams)
        write_bytes(random_path, gzip.compress(raw, mtime=0))
        shards.append({"arrays": entry(path, directory), "streams": entry(random_path, directory),
                       "uncompressed_streams_sha256": sha(raw), "array_metadata": array_metadata,
                       "example_start": start, "examples": number})
        all_arrays.append(arrays)
    if encoded(net) != initial_parameters:
        raise ArithmeticError("Frozen encoder changed during cache generation")
    receipt = {"seed": seed, "split": split, "examples": size, "rollouts": repeats,
               "trajectories": size * repeats, "actual_events": total_events,
               "max_affine_error": max_error, "wall_seconds": time.perf_counter() - begin,
               "encoder_parameters_unchanged": True, "shards": shards}
    write_json(directory / f"{prefix}.json", receipt)
    cache = {key: np.concatenate([part[key] for part in all_arrays]) for key in all_arrays[0]}
    return cache, receipt


def load_cache(directory, seed, split):
    from .artifacts import read_json

    receipt = read_json(directory / f"cache/{seed}/{split}.json")
    parts = []
    for row in receipt["shards"]:
        with np.load(directory / row["arrays"]["path"], allow_pickle=False) as archive:
            parts.append({key: archive[key] for key in archive.files})
    return {key: np.concatenate([part[key] for part in parts]) for key in parts[0]}
