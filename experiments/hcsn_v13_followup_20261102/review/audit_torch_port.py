"""Independent scalar-value and finite-difference asset audit of the Torch port."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch

from experiments.hcsn_hx_unified_v3 import hx
from experiments.hcsn_v13_followup_20261102.joint_core.hx_torch import FinancialMap


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    financial = FinancialMap()
    source = Path(__file__).resolve().parents[1] / "joint_core/hx_torch.py"
    protocol = {"schema": "hcsn-v13-independent-torch-financial-audit.v1",
        "port_sha256": sha(source), "auditor_sha256": sha(__file__), "reference_sha256": sha(hx.__file__),
        "fixed_parameters": vars(financial.p), "torch": torch.__version__,
        "value_atol": 1e-10, "value_rtol": 1e-10, "gradient_atol": 3e-7, "gradient_rtol": 3e-6,
        "finite_difference_relative_steps": [1e-4, 5e-5],
        "value_log_margins": [-.5, -.02, 0., .02, .05, .1, .5, 1., 2.],
        "interior_gradient_log_margins": [.02, .1, .5, 1., 2.], "times": [0., .05, .5, 2.],
        "scope": "Fixed financial-law value and asset/log-asset derivatives only. No financial-parameter or neural quality claim."}
    (out / "PLAN.json").write_text(json.dumps(protocol, indent=2) + "\n")
    checks, failures, value_rows, gradient_rows = 0, [], [], []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok):
            failures.append(label)

    def close(actual, expected, atol, rtol):
        return all(math.isfinite(a) and math.isfinite(b) and abs(a-b) <= atol+rtol*abs(b)
                   for a, b in zip(actual, expected))

    p, b = financial.p, float(financial.boundary)

    def scalar(asset, tau):
        return [hx.equity_closed(p, asset, b), hx.default_probability(p, asset, tau, b),
                hx.discounted_default_factor(p, asset, tau, b), hx.bond_value(p, asset, tau, b)]

    def derivative(function, center, step):
        values = [function(center+i*step) for i in (-2, -1, 1, 2)]
        return [(a-8*c+8*d-e)/(12*step) for a, c, d, e in zip(*values)]

    check(abs(b-hx.boundary(p)) < 1e-13, "exact inherited financial boundary")
    for margin in protocol["value_log_margins"]:
        asset = b*math.exp(margin)
        for tau in protocol["times"]:
            actual = financial.channels(torch.tensor([asset], dtype=torch.float64), torch.tensor(tau, dtype=torch.float64))[0]
            expected = scalar(asset, tau)
            check(close(actual.tolist(), expected, protocol["value_atol"], protocol["value_rtol"]), "all four financial values")
            value_rows.append({"log_margin": margin, "tau": tau, "torch": actual.tolist(), "scalar": expected})
    for margin in protocol["interior_gradient_log_margins"]:
        for tau in (.05, .5, 2.):
            asset = b*math.exp(margin)
            v = torch.tensor([asset], dtype=torch.float64, requires_grad=True)
            channels = financial.channels(v, torch.tensor(tau, dtype=torch.float64))
            actual = [float(torch.autograd.grad(channels[0, i], v, retain_graph=True)[0]) for i in range(4)]
            references = [derivative(lambda a: scalar(a, tau), asset, step*asset)
                          for step in protocol["finite_difference_relative_steps"]]
            check(close(references[0], references[1], protocol["gradient_atol"], protocol["gradient_rtol"]), "independent asset FD scale convergence")
            check(close(actual, references[1], protocol["gradient_atol"], protocol["gradient_rtol"]), "autograd asset derivative versus scalar FD")
            gradient_rows.append({"log_margin": margin, "tau": tau, "autograd_dasset": actual,
                                  "scalar_fd_coarse": references[0], "scalar_fd_fine": references[1]})

    def normalized(log_asset):
        asset = math.exp(log_asset)
        e, f, g, bond = scalar(asset, p.maturity)
        return [log_asset-math.log(b), e/asset, f, g,
                (bond-p.per_bond_principal)/p.per_bond_principal]

    normalized_rows = []
    for margin in protocol["interior_gradient_log_margins"]:
        at = math.log(b)+margin
        z = torch.tensor([at], dtype=torch.float64, requires_grad=True)
        result = financial(z)
        actual = [float(torch.autograd.grad(result[0, i], z, retain_graph=True)[0]) for i in range(5)]
        references = [derivative(normalized, at, step) for step in protocol["finite_difference_relative_steps"]]
        check(close(result[0].tolist(), normalized(at), protocol["value_atol"], protocol["value_rtol"]), "normalized neural feature values")
        check(close(references[0], references[1], protocol["gradient_atol"], protocol["gradient_rtol"]), "log-asset FD scale convergence")
        check(close(actual, references[1], protocol["gradient_atol"], protocol["gradient_rtol"]), "actual normalized log-asset gradient")
        normalized_rows.append({"log_margin": margin, "autograd": actual, "scalar_fd_fine": references[1]})

    # Deliberately broken derivative: identical financial forward values, detached asset.
    v = torch.tensor([b*math.exp(.5)], dtype=torch.float64, requires_grad=True)
    detached = financial.channels(v.detach()) + 0*v[:, None]
    broken_gradient = [float(torch.autograd.grad(detached[0, i], v, retain_graph=True)[0]) for i in range(4)]
    reference_gradient = derivative(lambda a: scalar(a, p.maturity), float(v.detach()), 5e-5*float(v.detach()))
    check(not close(broken_gradient, reference_gradient, protocol["gradient_atol"], protocol["gradient_rtol"]), "actual detached-asset negative control rejected")
    negative_control = {"broken_gradient": broken_gradient, "reference_gradient": reference_gradient,
                        "forward_value_difference": float((detached-financial.channels(v)).abs().max()), "rejected": True}
    check(negative_control["forward_value_difference"] == 0, "negative control preserves values while breaking gradients")
    for kwargs in ({"shock_intensity": 0.}, {"sale_fraction": 0.}):
        refused = False
        try:
            FinancialMap(hx.HX(**kwargs))
        except ValueError:
            refused = True
        check(refused, "declared coalescent exclusion is executable")
    for asset in (torch.tensor([0.], dtype=torch.float64), torch.tensor([1.], dtype=torch.float32),
                  torch.tensor([math.nan], dtype=torch.float64)):
        refused = False
        try:
            financial.channels(asset)
        except ValueError:
            refused = True
        check(refused, "invalid asset input is rejected")
    check(sha(source) == protocol["port_sha256"], "port unchanged through collection")
    result = {"schema": protocol["schema"], "checks": checks, "passed": not failures, "failures": failures,
        "values": value_rows, "asset_gradients": gradient_rows, "normalized_logasset_gradients": normalized_rows,
        "detach_negative_control": negative_control, "scope": protocol["scope"],
        "global_parameter_gradient_or_neural_adoption": False}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": checks, "passed": result["passed"], "failures": failures}))
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if main(args.out) else 1)
