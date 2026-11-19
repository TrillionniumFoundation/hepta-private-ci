"""One scalar T=.61 diagnostic with independent 80-digit matrix/reference math."""

from fractions import Fraction as F
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

import mpmath as mp
import numpy as np
import scipy
from scipy.linalg import expm
import torch


HERE = Path(__file__).resolve().parent
torch.set_num_threads(1)
mp.mp.dps = 80
spec = importlib.util.spec_from_file_location("gamma_kernel", HERE / "kernel_snapshot.py")
kernel = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = kernel
spec.loader.exec_module(kernel)


def precise(value):
    fraction = F.from_float(float(value))
    return mp.mpf(fraction.numerator) / fraction.denominator


def main(output):
    start = time.perf_counter()
    frozen = json.loads((HERE / "REQUEST.json").read_text())
    for name, expected in frozen["files"].items():
        if hashlib.sha256((HERE / name).read_bytes()).hexdigest() != expected:
            raise ValueError("frozen source changed")
    arrays, records, cache = {}, [], {}

    class DiagnosticWork(kernel.Work):
        def __init__(self, backend):
            super().__init__(max_dimension=32, max_exponentials=32)
            self.backend = backend

        def exponential(self, matrix):
            if self.exponentials >= 32 or matrix.shape[0] > 32:
                raise RuntimeError("fixed diagnostic action budget exceeded")
            self.exponentials += 1
            self.largest_dimension = max(self.largest_dimension, matrix.shape[0])
            raw = matrix.detach().numpy().copy()
            key = hashlib.sha256(raw.tobytes()).hexdigest()
            if key not in cache:
                if len(cache) >= 32:
                    raise RuntimeError("high-precision matrix budget exceeded")
                index = len(cache)
                p = mp.matrix([[precise(x) for x in row] for row in raw])
                high = mp.expm(p)
                native = torch.matrix_exp(matrix).detach().numpy()
                scipy_value = expm(raw)
                high_fp64 = np.array(high.tolist(), dtype=np.float64)
                err = max(abs(precise(native[i, j]) - high[i, j]) for i in range(len(raw)) for j in range(len(raw)))
                scipy_err = max(abs(precise(scipy_value[i, j]) - high[i, j]) for i in range(len(raw)) for j in range(len(raw)))
                for label, value in (("input", raw), ("torch", native), ("mp80_rounded", high_fp64), ("scipy", scipy_value)):
                    arrays[f"matrix_{index}_{label}"] = value
                records.append({"index": index, "sha256": key, "shape": list(raw.shape),
                    "norm_one": float(np.linalg.norm(raw, 1)), "torch_mp80_max_abs": str(err),
                    "scipy_mp80_max_abs": str(scipy_err), "mp_precision_digits": 80})
                cache[key] = native.copy(), high_fp64.copy()
            return torch.from_numpy(cache[key][0 if self.backend == "torch" else 1].copy())

    rate = torch.tensor(1.7, dtype=torch.float64)
    alpha = torch.tensor([[1.], [-.4], [.3]], dtype=torch.float64)
    zero = rate.new_zeros(())
    law = kernel.Physics(-rate.reshape(1, 1), rate[None], zero[None], rate.new_ones(1),
                         zero[None], zero, zero, zero, F(1, 5))
    results = {}
    for backend in ("torch", "mp80"):
        work = DiagnosticWork(backend)
        state = kernel.advance(kernel.initial(alpha), law, F(61, 100), work)
        values = torch.cat((state.active[:, 0], state.hits, kernel.refractory(state, work))).numpy()
        arrays[backend + "_values"] = values
        results[backend] = {"values": values.tolist(), "kernel_exponential_requests": work.exponentials,
                            "largest_matrix_dimension": work.largest_dimension}
    rate_mp = precise(float(rate))

    def hits(time):
        total = mp.mpf(0)
        for order in range(1, 5):
            remaining = time - F(order - 1, 5)
            if remaining > 0:
                x = rate_mp * remaining.numerator / remaining.denominator
                total += 1 - mp.exp(-x) * sum(x**j / mp.factorial(j) for j in range(order))
        return total

    count = hits(F(61, 100))
    waiting = count - hits(F(41, 100))
    gamma = [precise(float(a)) * value for value in (1-waiting, count, waiting) for a in alpha[:, 0]]
    arrays["gamma80_rounded"] = np.array(gamma, dtype=np.float64)
    for backend, row in results.items():
        row["gamma80_max_abs_error"] = str(max(abs(precise(value) - exact) for value, exact in zip(row["values"], gamma)))
    with (output / "MATRICES.npz").open("xb") as stream:
        np.savez(stream, **arrays)
    report = {"identity": frozen["identity"], "source_sha256": frozen["files"],
              "status": "DIAGNOSTIC_COMPLETE", "backends": results, "matrix_comparisons": records,
              "unique_mp80_matrix_exponentials": len(cache), "unique_torch_matrix_exponentials": len(cache),
              "unique_scipy_matrix_exponentials": len(cache), "gamma80_values": list(map(str, gamma)),
              "torch_version": torch.__version__, "numpy_version": np.__version__, "scipy_version": scipy.__version__,
              "mpmath_version": mp.__version__, "optimizer_calls": 0, "gradient_calls": 0,
              "whole_grids_rerun": 0, "body_wall_seconds": time.perf_counter()-start,
              "scope": "One scalar T=.61 forward diagnosis; the high-precision-backend run is a diagnostic, not a trainable implementation or performance benchmark."}
    (output / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
