"""Verify the restored exact CPU runtime without loading study inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import resource
import sys
import time

SOURCE = Path(__file__).resolve().parents[2]
EXPECTED_RUNTIME = "9d6ac19baf5234ed0d7d4ce98e63d550a1fea951126ea4dba0a591e04f65d52c"


def main():
    start, cpu = time.monotonic(), time.process_time()
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).absolute()
    if output.exists() or output.is_relative_to(SOURCE):
        raise ValueError("Runtime probe output must be a fresh external artifact")
    sys.path.insert(0, str(SOURCE))
    import numpy as np
    import torch
    from PIL import Image
    from experiments.parameter_field_fullstudy_20261029.branching import codec, strict
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    runtime = strict.runtime_descriptor()
    actual = codec.digest(runtime)
    expected_versions = json.loads((SOURCE.parent / "runtime_recovery_20261030/RUNTIME_IMPORT_RECEIPT.json").read_bytes())["package_versions"]
    versions = {key: importlib.metadata.version(key) for key in expected_versions}
    if versions != expected_versions or actual != EXPECTED_RUNTIME:
        raise ValueError("Restored runtime differs: " + json.dumps({"versions": versions, "runtime": runtime, "digest": actual}))
    tensor = torch.arange(6, dtype=torch.float64).reshape(2, 3)
    result = tensor @ tensor.T
    if result.tolist() != [[5.0, 14.0], [14.0, 50.0]]:
        raise ValueError("CPU tensor probe differs")
    if Image.new("RGB", (2, 2), (1, 2, 3)).getpixel((0, 0)) != (1, 2, 3):
        raise ValueError("Pillow probe differs")
    receipt = {"schema": "hepta.execution05.restored-runtime-probe.1",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "EXACT_RUNTIME_AND_SMALL_CPU_PROBES_VERIFIED",
        "python_executable": sys.executable, "source_root": str(SOURCE),
        "runtime": runtime, "runtime_sha256": actual, "versions": versions,
        "original_runtime_receipt_sha256": hashlib.sha256((SOURCE.parent / "runtime_recovery_20261030/RUNTIME_IMPORT_RECEIPT.json").read_bytes()).hexdigest(),
        "numpy_small_probe": np.arange(3).tolist(), "tensor_probe": result.tolist(),
        "model_tensors_loaded": False, "scientific_data_opened": False,
        "endpoint_scoring_performed": False, "backward_calls": 0,
        "science_started": False, "wall_seconds": time.monotonic() - start,
        "own_cpu_seconds": time.process_time() - cpu,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": receipt["status"], "runtime_sha256": actual, "output": str(output)}))


if __name__ == "__main__":
    main()
