"""Read-only audit of the actual R12 model, using independent matrix calculations."""

import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from scipy.linalg import expm
from scipy.stats import norm
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import contract
import data
import models
from audit import uniformized


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    torch.set_num_threads(1)
    torch.manual_seed(20261031)
    paths = [ROOT / name for name in ("contract.py", "data.py", "models.py", "PROTOCOL.json",
                                      "IMPLEMENTATION.json")]
    paths.append(contract.SOURCE)
    hashes = {str(path.relative_to(ROOT.parent)): digest(path) for path in paths}
    actual = contract.true_model()
    clock_fixture = data.EvidenceWorld(20261031, 3, actual, contract.PROTOCOL["train_dt"])
    assert np.all(clock_fixture.dt_indices == clock_fixture.dt_indices[0:1])
    assert clock_fixture.read_calls == 0
    q = actual["Q"]
    n, width = len(actual["grid"]), len(q) // 2
    active = np.r_[np.arange(n), np.arange(width, width+n)]
    off = q - np.diag(np.diag(q))
    assert off.min() >= 0 and abs(q.sum(axis=1)).max() < 1e-12
    assert abs(actual["prior"].sum()-1) < 1e-14
    assert abs(actual["emission"].sum(axis=1)-1).max() < 1e-14
    recovery_rate = 2 / contract.PROTOCOL["recovery_mean"]
    same_probability = contract.PROTOCOL["content_retention"] + (
        1-contract.PROTOCOL["content_retention"]) / 2
    reset_rows = []
    for bit in range(2):
        row = bit*width+n+1
        same = q[row, bit*width:bit*width+n].sum() / recovery_rate
        other = q[row, (1-bit)*width:(1-bit)*width+n].sum() / recovery_rate
        assert abs(same-same_probability) < 1e-14
        assert abs(same+other-1) < 1e-14
        assert abs(q[bit*width+n, row]-recovery_rate) < 1e-14
        reset_rows.append({"bit": bit, "same_bit": float(same), "other_bit": float(other)})
    rows = []
    theta = actual["theta"]
    mu, sigma = theta[0]-theta[1]-theta[2]**2/2, theta[2]
    killed = q[np.ix_(active[:n], active[:n])]
    for dt in contract.PROTOCOL["train_dt"]:
        transition = expm(q*dt)
        independent, tail, terms = uniformized(q, dt)
        torch_transition = torch.matrix_exp(torch.tensor(q)*dt).numpy()
        semi = expm(q*(dt+0.23)) - transition @ expm(q*0.23)
        finite_hit = 1-expm(killed*dt).sum(axis=1)
        x = actual["grid"]
        scale = sigma*np.sqrt(dt)
        continuous_hit = (norm.cdf((-x-mu*dt)/scale)
            + np.exp(-2*mu*x/sigma**2)*norm.cdf((-x+mu*dt)/scale))
        result = {"dt": dt, "min_probability": float(transition.min()),
            "row_mass_error": float(abs(transition.sum(axis=1)-1).max()),
            "semigroup_error": float(abs(semi).max()),
            "uniformization_error": float(abs(transition-independent).max()),
            "uniformization_tail": tail, "uniformization_terms": terms,
            "torch_scipy_error": float(abs(torch_transition-transition).max()),
            "finite_first_hit": finite_hit.tolist(),
            "continuous_unbounded_upper_first_hit": continuous_hit.tolist(),
            "max_continuum_discrepancy": float(abs(finite_hit-continuous_hit).max())}
        assert result["min_probability"] >= -1e-14
        for key in ("row_mass_error", "semigroup_error", "uniformization_error", "torch_scipy_error"):
            assert result[key] < 1e-12
        rows.append(result)
    # Check the actual custom AD bridge through b, reset, Q, exp, debt, and equity.
    raw = contract.initial_raw().requires_grad_(True)
    score = torch.linspace(-0.4, 0.7, len(q), dtype=contract.DTYPE)

    def scalar(parameters):
        terms = contract.model_terms(parameters)
        law = terms["prior"] @ torch.matrix_exp(0.45*terms["Q"])
        return (law @ score + 0.3*(law @ terms["read_cost"])
                + 0.1*(law @ terms["answer_rewards"][:, 0])
                + 0.0001*terms["boundary"])

    loss = scalar(raw)
    analytic = torch.autograd.grad(loss, raw)[0].detach().numpy()
    finite_difference = []
    for j in range(len(raw)):
        direction = torch.zeros_like(raw)
        direction[j] = 1e-5
        plus = float(scalar(raw.detach()+direction).detach())
        minus = float(scalar(raw.detach()-direction).detach())
        finite_difference.append((plus-minus)/(2e-5))
    finite_difference = np.array(finite_difference)
    error = abs(analytic-finite_difference)
    assert np.isfinite(analytic).all() and error.max() < 1e-7
    assert (abs(analytic) > 1e-8).all()
    # Same-model generic filtering, not a true-model privileged-posterior injection.
    model = models.DistributionCell()
    times = torch.tensor([[0.15, 0.45, 1.05], [1.05, 0.15, 0.45]], dtype=contract.DTYPE)
    tokens = torch.tensor([[0, 6, 4], [5, 0, 6]], dtype=torch.long)
    observed = torch.tensor([[True, False, True], [False, True, True]])
    output = model(times, tokens, observed)
    exported = model.export_model()
    generic = np.tile(exported["prior"], (2, 1))
    recorded = []
    for t in range(3):
        for row in range(2):
            generic[row:row+1] = contract.bayes_step(generic[row:row+1],
                expm(exported["Q"]*float(times[row, t])), exported["emission"],
                tokens[row:row+1, t].numpy(), observed[row:row+1, t].numpy())
        recorded.append(generic.copy())
    generic_output = np.stack(recorded, axis=1)
    parity_error = float(abs(output.detach().numpy()-generic_output).max())
    assert parity_error < 1e-12
    changed = tokens.clone()
    changed[~observed] = (changed[~observed]+3) % 7
    masked_error = float((model(times, changed, observed)-output).abs().max().detach())
    assert masked_error == 0
    # Fixed hypothetical supervised prefix: no task dataset or confirmation labels.
    loss_weights = torch.arange(1, len(q)+1, dtype=contract.DTYPE)
    differentiable_loss = -(output*loss_weights).sum()/len(q)
    raw_gradient, likelihood_gradient = torch.autograd.grad(
        differentiable_loss, (model.raw, model.logits))
    assert torch.isfinite(raw_gradient).all() and torch.isfinite(likelihood_gradient).all()
    after = {str(path.relative_to(ROOT.parent)): digest(path) for path in paths}
    if after != hashes:
        raise RuntimeError("Audited sources changed during execution; rerun on a stable snapshot")
    report = {"status": "actual_model_local_checks_passed", "source_sha256": hashes,
        "audit_sha256": digest(Path(__file__)),
        "scope": "Read-only actual-model audit; constructed fixtures, no confirmation data.",
        "states": len(q), "boundary": float(actual["boundary"]),
        "grid": actual["grid"].tolist(), "generator_row_error": float(abs(q.sum(axis=1)).max()),
        "recovery_mean": 2/recovery_rate, "reset_content_probabilities": reset_rows,
        "propagation": rows,
        "shared_gradient_path": {"raw_analytic": analytic.tolist(),
            "raw_finite_difference": finite_difference.tolist(),
            "absolute_error": error.tolist(), "scalar_value": float(loss.detach()),
            "hypothetical_content_loss_raw_gradient": raw_gradient.tolist(),
            "hypothetical_content_loss_emission_gradient_norm": float(likelihood_gradient.norm())},
        "generic_filter_parity_error": parity_error, "masked_token_change_error": masked_error,
        "decision_episode_dt_is_fixed": True, "initial_actual_read_calls": clock_fixture.read_calls,
        "limitations": ["Finite CTMC equality is not continuum first-passage equality.",
            "Cell-centered first-site killing uses the interior down rate, without a half-cell boundary correction.",
            "Upper truncation is reflecting/holding; continuum comparison has no upper boundary.",
            "Recovery and bit reinjection are specified extensions, not the original financial model.",
            "The custom financial bridge provides first derivatives only, on CPU.",
            "Upwind rates have a drift-sign kink; only local smooth-parameter derivatives were checked.",
            "F and G are exported financial diagnostics; Q uses drift, diffusion, and the boundary-driven reset.",
            "Synthetic task rewards use E and debt; no task-optimality theorem for the financial boundary follows."]}
    target = Path(__file__).with_name("actual_model_raw.json")
    target.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "boundary": report["boundary"],
        "gradient_error": float(error.max()), "generic_parity": parity_error,
        "continuum_discrepancy": max(row["max_continuum_discrepancy"] for row in rows)}))


if __name__ == "__main__":
    main()
