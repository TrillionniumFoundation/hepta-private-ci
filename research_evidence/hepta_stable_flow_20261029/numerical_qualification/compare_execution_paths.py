"""Compare the retained pre-optimization kernel to the CPU execution fast path."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
import torch


def load_source(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    source = args.output / "source"
    source.mkdir()
    snapshots = []
    for path, name in [(args.previous, "previous_numerics.py"),
                       (args.current, "current_numerics.py"),
                       (Path(__file__), "compare_execution_paths.py")]:
        shutil.copyfile(path, source / name)
        snapshots.append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    protocol = {"identity": "cpu-callput-execution-equivalence-20261029-v1", "sources": snapshots,
                "value_gate": "bitwise equal", "gradient_relative_l2_gate": {"float32": 2e-6, "float64": 1e-12},
                "cases": ["all_far", "all_stopped", "mixed_near_and_far", "shared_scalar_kappa", "per_head_kappa"],
                "comparisons": "all x and kappa derivatives of weighted Call-Put objective",
                "formula_degree_thresholds_unchanged": True, "torch_version": torch.__version__}
    (args.output / "PROTOCOL.json").write_text(json.dumps(protocol, indent=2) + "\n")
    previous = load_source(source / "previous_numerics.py", "previous_numerics")
    current = load_source(source / "current_numerics.py", "current_numerics")
    cases = {
        "all_far": ([[0.5, 2., 4.], [0.7, 3., 5.]], [0.25, 1., 4.]),
        "all_stopped": ([[-20., -1., 0.], [-2., -0.1, -1e-8]], [0.25, 1., 4.]),
        "mixed_near_and_far": ([[-2., 0., 1e-8], [0.04, 0.5, 3.]], [[0.25, 1., 4.], [0.25, 1., 4.]]),
        "shared_scalar_kappa": ([[-2., 0., 1e-8], [0.04, 0.5, 3.]], 1.),
        "per_head_kappa": ([[-2., 0., 1e-8], [0.04, 0.5, 3.]], [0.25, 1., 4.]),
    }
    arrays, rows = {}, []
    for dtype in [torch.float32, torch.float64]:
        for label, (input_x, input_k) in cases.items():
            records = []
            for name, module in [("previous", previous), ("current", current)]:
                x = torch.tensor(input_x, dtype=dtype, requires_grad=True)
                kappa = torch.tensor(input_k, dtype=dtype, requires_grad=True)
                call, put = module.call_put(x, kappa)
                objective = ((0.31 * call - 0.73 * put) * torch.arange(1, 7, dtype=dtype).view(2, 3)).sum()
                gradients = torch.autograd.grad(objective, (x, kappa))
                values = torch.stack((call, put)).detach()
                vector = torch.cat([g.flatten() for g in gradients]).detach()
                records.append((values, vector))
                prefix = f"{str(dtype)}__{label}__{name}"
                arrays[f"{prefix}__values"] = values.double().numpy()
                arrays[f"{prefix}__gradient"] = vector.double().numpy()
            same = torch.equal(records[0][0], records[1][0])
            error = (torch.linalg.vector_norm(records[0][1].double() - records[1][1].double())
                     / torch.linalg.vector_norm(records[0][1].double())).item()
            gate = 2e-6 if dtype == torch.float32 else 1e-12
            assert same and error <= gate
            rows.append({"dtype": str(dtype), "case": label, "values_bitwise_equal": same,
                         "full_gradient_relative_l2_difference": error, "passed": True})
    np.savez_compressed(args.output / "RAW_ARRAYS.npz", **arrays)
    result = {"passed": True, "rows": rows, "sources": snapshots,
              "raw_arrays_sha256": hashlib.sha256((args.output / "RAW_ARRAYS.npz").read_bytes()).hexdigest()}
    (args.output / "RESULTS.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
