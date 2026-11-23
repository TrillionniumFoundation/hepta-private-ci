"""Program written after the disclosed RAVDESS TRAIN diagnostic.

The weakly separated STOP/READ scores motivate edits to action *contrasts*.
Probe each registered physical bias on TRAIN, conditionally refit the same
readout, then write joint finite-radius patches that change those contrasts.
The probes are finite displacements, not model backward passes. The linear
superposition is only a candidate model; actual policies must be evaluated.
"""

import math

import torch


def _inverse_patch(responses, desired, weight, radius):
    """Exact trust-radius solution of the regularized empirical response table."""
    z = (weight / weight.sum()).sqrt()
    design, target = responses * z[:, None], desired * z
    u, s, vh = torch.linalg.svd(design, full_matrices=False)
    if not len(s) or s[0] < 1e-10:
        return None, 0, 0.0
    rank = int((s > 1e-6 * s[0]).sum())
    floor = (0.02 * s[0]) ** 2
    coef = s * (u.T @ target)

    def solve(penalty):
        return vh.T @ (coef / (s.square() + floor + penalty))

    trial = solve(0)
    if trial.norm() > radius:
        lo, hi = 0., max(float(coef.norm()) / radius, 1e-16)
        for _ in range(44):
            mid = (lo + hi) / 2
            if solve(mid).norm() > radius:
                lo = mid
            else:
                hi = mid
        trial = solve(hi)
    gain = float(target.square().sum() - (target - design @ trial).square().sum())
    return trial, rank, gain


def propose(origin, diagnostics, edit_names, train_probe):
    """Build up to four observable-rank corrections using no evaluation labels."""
    names = tuple(edit_names)
    allowed = {("drive_bias", "mark_bias"), ("drive_bias", "mark_bias", "boundary_logit")}
    if names not in allowed or diagnostics["split"] != "TRAIN" or torch.is_grad_enabled():
        raise ValueError("expected the registered physical coordinates and gradient-free TRAIN context")
    rows = diagnostics["rows"]
    base, y, legal, w = (rows[k] for k in ("scores", "targets", "legal", "weights"))
    if base.shape[1] != 3 or not legal[:, :2].all():
        raise ValueError("expected legal STOP/READ endpoints and optional WAIT")
    response = []
    # Half the allowed radius is an actual, noticeable parameter perturbation.
    # Each measured column includes readout refitting, matrix-exponential
    # dynamics and, for QVI, its induced boundary shift.
    step = .175
    for j in range(len(names)):
        candidate = origin.clone()
        candidate[j] += step
        response.append((train_probe(candidate)["scores"] - base) / step)
    response = torch.stack(response, dim=-1)
    actual, fitted, a, b = [], [], [], []
    for left, right in ((0, 1), (0, 2), (1, 2)):
        a.append(left)
        b.append(right)
        actual.append(y[:, left] - y[:, right])
        fitted.append(base[:, left] - base[:, right])
    truth, gap = torch.stack(actual, 1), torch.stack(fitted, 1)
    effect = response[:, a, :] - response[:, b, :]
    mask = legal[:, a] & legal[:, b] & (truth.abs() > 1e-9)
    opposite = truth.sign() * gap < 0
    # Margin targets cap the leverage of impossible-to-fit full hindsight Q
    # gaps. Already separated rows request no move and act as anchors.
    wanted = truth.sign() * torch.relu(torch.minimum(truth.abs(), truth.new_tensor(.15)) -
                                       truth.sign() * gap)
    proposals = []
    schemes = (
        ("balanced_read", .35, "balance both sides of the sign reversal in STOP minus READ"),
        ("rank_protection", .35, "repair all legal action gaps and anchor already-correct gaps"),
        ("paid_read_recovery", .35, "prioritize missed affordable READs where READ beats both alternatives"),
        ("conservative_read", .15, "apply a tighter-radius STOP versus READ repair"),
    )
    for name, radius, explanation in schemes:
        active = mask.clone()
        mass = w[:, None].expand_as(gap).clone()
        if name in ("balanced_read", "conservative_read"):
            active[:, 1:] = False
            for value in (-1, 1):
                side = active[:, 0] & (truth[:, 0].sign() == value)
                if side.any():
                    mass[side, 0] /= mass[side, 0].sum()
        elif name == "paid_read_recovery":
            oracle = y.masked_fill(~legal, -torch.inf).argmax(1)
            missed = (oracle == 1) & (base.masked_fill(~legal, -torch.inf).argmax(1) != 1)
            if not missed.any():
                continue
            # Upweight the small set of mislabeled paid acquisition choices;
            # retain every other legitimate margin as a counterterm.
            mass[missed] *= min(10.0, 1.0 / max(float(w[missed].sum()), 1e-8))
        if not active.any():
            continue
        mass = mass * torch.where(opposite, 2., 1.)
        delta, rank, gain = _inverse_patch(effect[active], wanted[active], mass[active], radius)
        if delta is None or not math.isfinite(gain) or gain <= 1e-12 or delta.norm() < 1e-8:
            continue
        patched = origin + delta
        if any(torch.allclose(patched, p["theta"], rtol=0, atol=1e-9) for p in proposals):
            continue
        proposals.append({"name": name, "theta": patched,
                          "rationale": f"{explanation}; measured response rank {rank}/{len(names)}, "
                                       f"{int(active.sum())} TRAIN inequalities, predicted residual reduction {gain:.8g}"})
    return proposals
