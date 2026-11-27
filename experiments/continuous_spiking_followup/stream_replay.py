"""Fresh-process model/state restoration and deterministic stream continuation."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


MODULE_CPU, MODULE_WALL = time.process_time(), time.perf_counter()


def state_digest(snapshot):
    """Hash numeric state plus metadata without pickle or object serialization."""
    metadata = {k: v for k, v in snapshot.items() if k not in {"elapsed", "layers"}}
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode())
    tensors = [("elapsed", snapshot["elapsed"])] + [
        (f"{index}/{name}", value)
        for index, layer in enumerate(snapshot["layers"])
        for name, value in sorted(layer.items())
    ]
    for name, tensor in tensors:
        array = tensor.detach().cpu().contiguous().numpy()
        digest.update(json.dumps([name, array.dtype.str, list(array.shape)]).encode())
        digest.update(array.tobytes())
    return digest.hexdigest()


def run_child(request_path, output, request_sha256):
    import numpy as np
    import torch

    from experiments.continuous_spiking_network.models import SequenceClassifier
    from experiments.continuous_spiking_network.records import (
        checkpoint_load,
        digest_bytes,
        write_json,
    )
    from .budget_io import load_arrays, write_arrays
    from .streaming import StreamingClassifier

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    import_cost = {
        "cpu": time.process_time() - MODULE_CPU,
        "wall": time.perf_counter() - MODULE_WALL,
    }
    raw = Path(request_path).read_bytes()
    if digest_bytes(raw) != request_sha256:
        raise ValueError("cross-process request hash mismatch")
    request = json.loads(raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    costs = {"module_import_setup": import_cost}
    cpu, wall = time.process_time(), time.perf_counter()
    checkpoint = Path(request["checkpoint"])
    manifest_raw = (checkpoint / "manifest.json").read_bytes()
    if digest_bytes(manifest_raw) != request["checkpoint_manifest_sha256"]:
        raise ValueError("cross-process checkpoint identity changed")
    model = SequenceClassifier(**json.loads(manifest_raw)["config"])
    checkpoint_load(model, checkpoint)
    model.eval()
    costs["model_initialization_reload"] = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    cpu, wall = time.process_time(), time.perf_counter()
    state_path = Path(request["state"])
    if (
        digest_bytes((state_path / "manifest.json").read_bytes())
        != request["state_manifest_sha256"]
    ):
        raise ValueError("cross-process snapshot identity changed")
    stream = StreamingClassifier(model).load_state(state_path)
    costs["stream_construction_restore"] = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    if stream.model_sha256 != request["model_sha256"]:
        raise ValueError("cross-process model state differs from parent")
    cpu, wall = time.process_time(), time.perf_counter()
    inputs = Path(request["inputs"])
    if (
        digest_bytes((inputs / "manifest.json").read_bytes())
        != request["inputs_manifest_sha256"]
    ):
        raise ValueError("cross-process remainder inputs changed")
    arrays = load_arrays(inputs)
    if set(arrays) != {"x", "dt"}:
        raise ValueError(
            "cross-process request must contain only remainder observations/time"
        )
    x, dt = torch.from_numpy(arrays["x"]), torch.from_numpy(arrays["dt"])
    costs["input_restore"] = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    cpu, wall = time.process_time(), time.perf_counter()
    logits = torch.stack(
        [stream.step(x[:, t], dt[:, t])[0] for t in range(x.shape[1])], dim=1
    )
    costs["continuation"] = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    cpu, wall = time.process_time(), time.perf_counter()
    arrays_sha = write_arrays(output / "arrays", {"logits": logits.numpy()})
    final_state_sha = state_digest(stream.snapshot())
    costs["result_serialization_and_state_hash"] = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    result = {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "request_sha256": request_sha256,
        "model_sha256": stream.model_sha256,
        "arrays_manifest_sha256": arrays_sha,
        "final_state_sha256": final_state_sha,
        "steps": stream.steps,
        "processed_rows": stream.processed_rows,
        "state_bytes": stream.state_bytes,
        "costs_seconds": costs,
        "module_total_cpu_seconds": time.process_time() - MODULE_CPU,
        "module_total_wall_seconds": time.perf_counter() - MODULE_WALL,
        "scope": "module timer includes imports through result construction; parent external timer also includes interpreter startup, final write and shutdown; nested costs are not additive to totals",
        "numpy_version": np.__version__,
        "torch_version": torch.__version__,
    }
    write_json(output / "RESULT.json", result)


def replay_in_subprocess(model, checkpoint, x, dt, output):
    """Verify the remaining stream in a distinct interpreter and record all cost."""
    import numpy as np
    import torch

    from experiments.continuous_spiking_network.records import digest_bytes, write_json
    from .budget_io import load_arrays, write_arrays
    from .streaming import StreamingClassifier

    output, checkpoint = Path(output).resolve(), Path(checkpoint).resolve()
    output.mkdir(parents=True, exist_ok=False)
    total_cpu, total_wall = time.process_time(), time.perf_counter()
    split = max(1, x.shape[1] // 2)
    if split >= x.shape[1]:
        raise ValueError("cross-process replay needs at least two time steps")
    cpu, wall = time.process_time(), time.perf_counter()
    stream = StreamingClassifier(model).reset(x.shape[0])
    for t in range(split):
        stream.step(x[:, t], dt[:, t])
    state_receipt = stream.save_state(output / "state")
    inputs_sha = write_arrays(
        output / "inputs",
        {
            "x": x[:, split:].numpy(),
            "dt": dt[:, split:].numpy(),
        },
    )
    preparation = {"cpu": time.process_time() - cpu, "wall": time.perf_counter() - wall}
    cpu, wall = time.process_time(), time.perf_counter()
    expected = torch.stack(
        [stream.step(x[:, t], dt[:, t])[0] for t in range(split, x.shape[1])], dim=1
    ).numpy()
    expected_state = state_digest(stream.snapshot())
    expected_sha = write_arrays(output / "parent_expected", {"logits": expected})
    reference_work = {
        "cpu": time.process_time() - cpu,
        "wall": time.perf_counter() - wall,
    }
    request = {
        "checkpoint": str(checkpoint),
        "checkpoint_manifest_sha256": digest_bytes(
            (checkpoint / "manifest.json").read_bytes()
        ),
        "state": str(output / "state"),
        "state_manifest_sha256": state_receipt["manifest_sha256"],
        "inputs": str(output / "inputs"),
        "inputs_manifest_sha256": inputs_sha,
        "model_sha256": stream.model_sha256,
    }
    write_json(output / "REQUEST.json", request)
    request_sha = digest_bytes((output / "REQUEST.json").read_bytes())
    command = [
        sys.executable,
        "-m",
        "experiments.continuous_spiking_followup.stream_replay",
        "--request",
        str(output / "REQUEST.json"),
        "--output",
        str(output / "child"),
        "--request-sha256",
        request_sha,
    ]
    env = dict(
        os.environ,
        PYTHONDONTWRITEBYTECODE="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
    )
    try:
        import resource

        usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    except ImportError:
        resource, usage_before = None, None
    cpu, wall = time.process_time(), time.perf_counter()
    with (
        (output / "stdout.log").open("w") as stdout,
        (output / "stderr.log").open("w") as stderr,
    ):
        process = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            stdout=stdout,
            stderr=stderr,
            timeout=300,
        )
    external = {
        "wall": time.perf_counter() - wall,
        "parent_cpu": time.process_time() - cpu,
    }
    if resource is not None:
        usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        external["child_cpu"] = (
            usage_after.ru_utime
            + usage_after.ru_stime
            - usage_before.ru_utime
            - usage_before.ru_stime
        )
    else:
        external["child_cpu"] = None
    result = {
        "status": "child_failed" if process.returncode else "completed",
        "returncode": process.returncode,
        "parent_pid": os.getpid(),
        "command": command,
        "request_sha256": request_sha,
        "split_step": split,
        "preparation_cost_seconds": preparation,
        "reference_cost_seconds": reference_work,
        "external_process_cost_seconds": external,
        "parent_expected_manifest_sha256": expected_sha,
        "parent_expected_final_state_sha256": expected_state,
        "state_receipt": state_receipt,
    }
    if process.returncode == 0:
        child = json.loads((output / "child/RESULT.json").read_text())
        if (
            digest_bytes((output / "child/arrays/manifest.json").read_bytes())
            != child["arrays_manifest_sha256"]
        ):
            raise ValueError("cross-process child result identity changed")
        actual = load_arrays(output / "child/arrays")["logits"]
        exact = bool(np.array_equal(actual, expected))
        same_state = child["final_state_sha256"] == expected_state
        separate = child["pid"] != os.getpid() and child["parent_pid"] == os.getpid()
        result.update(
            {
                "child": child,
                "exact_logits": exact,
                "max_abs_logit_error": float(np.max(np.abs(actual - expected))),
                "exact_final_state": same_state,
                "distinct_process": separate,
                "passed": exact and same_state and separate,
            }
        )
    else:
        result["passed"] = False
    result.update(
        {
            "total_parent_cpu_seconds": time.process_time() - total_cpu,
            "total_wall_seconds": time.perf_counter() - total_wall,
            "accounting": "parent total excludes child CPU; wall includes child lifetime; phase costs are nested, not additional totals",
        }
    )
    write_json(output / "EXECUTION.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--request-sha256", required=True)
    arguments = parser.parse_args()
    run_child(arguments.request, arguments.output, arguments.request_sha256)
