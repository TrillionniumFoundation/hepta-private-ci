"""Independent DOP853/quadrature forward data and closed inverse validation."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import numpy as np

from contract_inverse import Probe, Surface


def forward(solution, contract, scales, margins):
    rows = []
    for s in scales:
        changed = contract.copy()
        changed[6] *= s
        rows.append(solution(changed, np.asarray(margins)))
    return np.array(rows)


def relative_sensitivity(probe, scales, obs, truth):
    """2-norm operator gain between dimensionless observation and parameter errors."""
    rows = obs.ravel()
    columns = []
    for j in range(4):
        step = abs(rows[j])*2e-6
        delta = np.eye(4)[j]*step
        yp = probe.recover(scales, (rows+delta).reshape(2, 2))
        ym = probe.recover(scales, (rows-delta).reshape(2, 2))
        columns.append((yp-ym)/(2*step)*abs(rows[j])/truth)
    return np.linalg.norm(np.stack(columns, axis=1), ord=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path, help="sibling differentiable_law/reference.py")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.reference.resolve().parent))
    from reference import solution
    import hx_reference

    cases = json.loads(args.reference.with_name("reference.json").read_text())["cases"]
    rng = np.random.default_rng(84719)
    contracts = [np.array(row["contract"]) for row in cases]
    scales = [.72, 1.28]
    recover_errors, quote_errors, examples = [], [], []
    for case, p in enumerate(contracts):
        truth = p[[5,6,4,3]]
        surface = Surface(*p[[0,1,2,7,8]])
        for margin in (.015, .16, .4):
            obs = forward(solution, p, scales, [margin])[:,0][:,[0,2]]
            probe = Probe.at(surface, margin)
            recovered = probe.recover(scales, obs)
            scaled_error = np.max(abs(recovered-truth)/truth)
            recover_errors.append(scaled_error)
            recovered_contract = p.copy()
            recovered_contract[[5,6,4,3]] = recovered
            # These scales and all margins differ from the two inverse probes.
            test_scales, test_margins = [.80, 1., 1.18], [.035, .2, .36, .61]
            initial = forward(solution, p, test_scales, test_margins)
            recalc = forward(solution, recovered_contract, test_scales, test_margins)
            quote_errors.append(np.max(abs(initial-recalc), axis=(0,1)).tolist())
            examples.append(dict(case=case, margin=margin, scales=scales,
                                 four_parameters=recovered.tolist(), relative_error=scaled_error,
                                 raw_observations=obs.tolist()))
    p = contracts[0]
    surface = Surface(*p[[0,1,2,7,8]])
    truth = p[[5,6,4,3]]
    sensitivity = []
    for amplitude in (.28, .02, .001):
        s = [1.-amplitude, 1.+amplitude]
        for margin in (.015, .16, .4):
            probe = Probe.at(surface, margin)
            y = forward(solution, p, s, [margin])[:,0][:,[0,2]]
            errors, inadmissible = [], 0
            for _ in range(500):
                noisy = y*(1+rng.normal(0,1e-5,y.shape))
                z = probe.recover(s, noisy)
                errors.append(np.max(abs(z/truth-1)))
                inadmissible += int(z[0] <= 0 or z[1] <= 0 or not (0<=z[2]<=1 and 0<=z[3]<=1))
            sensitivity.append(dict(half_amplitude=amplitude, margin=margin,
                                    dimensionless_inverse_gain=relative_sensitivity(probe,s,y,truth),
                                    median_max_parameter_relative_error=float(np.median(errors)),
                                    p95_max_parameter_relative_error=float(np.quantile(errors,.95)),
                                    inadmissible_500=inadmissible))
    # Gauge at s=1, then perturb only the relative principal. This explicit
    # negative case uses the original forward engine, independent of the inverse.
    b = forward(solution, p, [1.], [.16])[0,0,0]
    h = .45
    shifted = p.copy()
    shifted[5] += h
    q = p[0]+p[8]
    shifted[6] += h/q
    shifted[4] += h/(q*b)
    shifted[3] = 1-(1-p[3])*p[5]/shifted[5]
    grid = [.02,.15,.34,.59]
    baseline_gap = forward(solution, p, [1.], grid)-forward(solution, shifted, [1.], grid)
    stimulated_gap = forward(solution, p, scales, grid)-forward(solution, shifted, scales, grid)
    result = dict(reference_sha256=sha256(args.reference.read_bytes()).hexdigest(),
                  first_passage_reference_sha256=sha256(Path(hx_reference.__file__).read_bytes()).hexdigest(),
                  cases=len(contracts), inversions=len(recover_errors),
                  max_relative_parameter_error=max(recover_errors),
                  independent_law_max_absolute_error_by_channel=np.max(quote_errors,axis=0).tolist(),
                  out_of_probe_scales=test_scales, out_of_probe_margins=test_margins,
                  known_input_order=["r","payout","sigma","maturity","premium"],
                  recovered_order=["C","P","recovery","tax"], channel_order=["B","E","credit_loss","F","G"],
                  noise_law="independent multiplicative N(0,1e-5) per raw quote, 500 trials per cell, seed 84719",
                  noise=sensitivity, one_setting_gauge=dict(
                      base=p.tolist(),shifted=shifted.tolist(),
                      max_base_difference=np.max(abs(baseline_gap),axis=(0,1)).tolist(),
                      max_stimulated_difference=np.max(abs(stimulated_gap),axis=(0,1)).tolist()),
                  runs=examples)
    if max(recover_errors)>1e-7 or np.max(quote_errors)>1e-6:
        raise ArithmeticError("independent inverse or cross-intervention replay failed")
    if np.max(abs(baseline_gap))>1e-7 or np.max(abs(stimulated_gap[:,:,0])) < 1e-4:
        raise ArithmeticError("nominal equality or controlled discrimination failed")
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({k:result[k] for k in ("cases","inversions","max_relative_parameter_error","independent_law_max_absolute_error_by_channel","noise","one_setting_gauge")},indent=2))


if __name__ == "__main__":
    main()
