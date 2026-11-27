"""Eight scalar 80-digit log-pair/gradient comparisons; no model training.

This recorded repeat expands the earlier console summary into full values.
The reference evaluates the original closed form in mpmath and differentiates
it independently with mp.diff. Float32 inputs are converted exactly to mp.mpf.
"""

import hashlib
import json
import platform
import sys
import time
from pathlib import Path

import mpmath as mp
import torch


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "qualification/hcsn/tensor.py"
SOURCE_SHA = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
sys.path.insert(0, str(ROOT))
from qualification.hcsn import tensor as hx


def reference(point):
    u, z, shifted, scale = point
    phi = lambda w: mp.erfc(-w/mp.sqrt(2))/2

    def integral(lam):
        if lam == 0:
            w = shifted*scale
            return scale*(mp.exp(-w*w/2)/mp.sqrt(2*mp.pi)+w*phi(w))
        return (phi(shifted*scale)-mp.exp((lam*lam/2-lam*shifted)*scale*scale)
                * phi((shifted-lam)*scale))/lam

    return mp.log(integral(u-z)-integral(u+z))


def main():
    output = Path(sys.argv[1])
    with output.open("x") as stream:
        torch.set_num_threads(1)
        mp.mp.dps = 80
        wall, cpu = time.perf_counter(), time.process_time()
        rows = []
        for w in (-1.999, -2.001, -268., -1000.):
            for dtype in (torch.float64, torch.float32):
                theta = torch.tensor([.25, 1.6, w/.045, .045], dtype=dtype, requires_grad=True)
                value = hx._log_normal_tail_pair(*theta)
                gradient = torch.autograd.grad(value, theta)[0]
                point = tuple(mp.mpf(float(v)) for v in theta.detach())
                exact = reference(point)
                derivatives = [mp.diff(lambda v: reference(point[:i]+(v,)+point[i+1:]), point[i])
                               for i in range(4)]
                rows.append({"nominal_w": w, "dtype": str(dtype), "rounded_inputs": theta.detach().tolist(),
                             "actual_value": float(value.detach()), "reference_value_80_digits": str(exact),
                             "ad_gradient": gradient.tolist(), "reference_gradients_80_digits": list(map(str, derivatives)),
                             "value_absolute_error": abs(float(value.detach())-float(exact)),
                             "max_gradient_relative_error": max(abs(float(a)-float(b))/abs(float(b))
                                                                  for a, b in zip(gradient, derivatives))})
        theta = torch.tensor([1e8, 1., -1e10, .2], dtype=torch.float32, requires_grad=True)
        value = hx._log_normal_tail_pair(*theta)
        gradient = torch.autograd.grad(value, theta)[0]
        if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
            raise ValueError("source changed during independent scalar review")
        result = {"method": "80-digit original H(lambda) closed form, independent mp.diff of all four inputs",
                  "source_sha256": SOURCE_SHA, "python": platform.python_version(),
                  "torch": torch.__version__, "mpmath": mp.__version__, "cases": rows,
                  "former_unused_branch_case": {"input": theta.detach().tolist(), "value": float(value.detach()),
                                                 "gradient": gradient.tolist(), "all_finite": bool(torch.isfinite(gradient).all())},
                  "wall_seconds": time.perf_counter()-wall, "cpu_seconds": time.process_time()-cpu,
                  "training_steps": 0, "n256_dynamic_steps": 0,
                  "recorded_repeat_of_prior_console_summary": True}
        json.dump(result, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"output": str(output), "source_sha256": SOURCE_SHA,
                      "cases": len(rows), "cpu_seconds": result["cpu_seconds"]}))


if __name__ == "__main__":
    main()
