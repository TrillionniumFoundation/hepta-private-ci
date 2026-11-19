"""Standalone fixed-fixture 80-digit log F/G Hessian measurement; no training."""
from pathlib import Path
import hashlib
import json
import sys
import time
import mpmath as mp
import torch
from qualification.hcsn_differentiable.operator import _first_hit_logprob
from qualification.hcsn_differentiable.tests.test_logrisk import reference

CASES = (
    (0.15, 0.1, -0.12, 0.35, 0.3),
    (0.15, 0.1, 0.0, 0.35, 0.3),
    (0.15, 0.1, 0.12, 0.35, 0.3),
    (1.0, 1e-4, 0.2, 0.1, 0.3),
    (1e-4, 0.01, 0.2, 0.1, 0.3),
    (0.15, 0.1, -0.12, 0.35, None),
    (0.15, 0.1, 0.0, 0.35, None),
    (1.0, 1e-4, 0.2, 0.1, None),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    start = time.perf_counter()
    records = []
    with mp.workdps(80):
        for data in CASES:
            variables = tuple(torch.tensor(v, dtype=torch.float64, requires_grad=True)
                              for v in data if v is not None)
            actual = _first_hit_logprob(*variables)
            grad = torch.autograd.grad(actual, variables, create_graph=True)
            hss = torch.autograd.grad(grad[3], variables[3], retain_graph=True)[0]
            mixed = torch.autograd.grad(grad[2], variables[3], retain_graph=True)[0]
            originals = tuple(mp.mpf(v) if v is not None else None for v in data)
            ref = reference(*originals[:4], originals[4])
            rr = mp.diff(lambda s: reference(*originals[:3], s, originals[4]), originals[3], 2)
            rm = mp.diff(lambda m, s: reference(originals[0], originals[1], m, s, originals[4]),
                         (originals[2], originals[3]), (1, 1))
            def comparison(a, b):
                return {"ad": float(a.detach()), "reference": float(b),
                        "scaled_absolute_error": abs(float(a.detach())-float(b))/max(1.,abs(float(b)))}
            records.append({"arguments": list(data), "log_probability": comparison(actual, ref),
                            "d2_dsigma2": comparison(hss, rr),
                            "d2_dmu_dsigma": comparison(mixed, rm)})
    file_root = Path('qualification/hcsn_differentiable')
    report = {
        "schema": "hcsn-p1-logrisk-hessian-fixture-v1",
        "status": "HOLD_NO_GO",
        "scientific_scope": "8 sampled scalar 80-digit reference F/G log-probability Hessians only; not training posterior/whole network/general numerical certification",
        "tested_device": "cpu", "dtype": "torch.float64", "reference_digits": 80,
        "python": sys.version.split()[0], "torch": torch.__version__, "mpmath": mp.__version__,
        "model": None, "dataset": "8 literal scalar fixtures in code", "optimizer_steps": 0,
        "source_sha256": sha(file_root / 'operator.py'),
        "test_sha256": sha(file_root / 'tests/test_logrisk_hessian.py'),
        "reference_test_sha256": sha(file_root / 'tests/test_logrisk.py'),
        "comparison_count": len(records)*2,
        "maximum_scaled_second_derivative_error": max(max(x['d2_dsigma2']['scaled_absolute_error'],
                                                          x['d2_dmu_dsigma']['scaled_absolute_error']) for x in records),
        "elapsed_wall_seconds": time.perf_counter()-start,
        "records": records}
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
