"""Constructed branch and joint-gradient checks; not formal fit quality evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import torch

from experiments.hcsn_v13_followup_20261102.joint_core import model


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    source = Path(model.__file__)
    protocol = {"schema": "hcsn-v13-sampled-model-contract-audit.v1", "model_sha256": sha(source),
        "auditor_sha256": sha(__file__), "torch": torch.__version__, "seed": 131701,
        "mandatory_first_modality": "audio", "admitted_balanced_sequences": 10,
        "scope": "Constructed deterministic source-tick crossing/cooldown/restore and real loss-gradient checks. Not trained-model quality, continuous first-hit or financial-parameter training."}
    (out / "PLAN.json").write_text(json.dumps(protocol, indent=2) + "\n")
    checks, failures = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok):
            failures.append(label)

    torch.manual_seed(protocol["seed"])
    full = model.Model("hx_full", 6)
    torch.manual_seed(protocol["seed"])
    margin = model.Model("hx_margin", 6)
    torch.manual_seed(protocol["seed"])
    ordinary = model.Model("ordinary_gate", 6)
    for key, value in full.state_dict().items():
        check(torch.equal(value, margin.state_dict()[key]), "full and independently constructed margin initialize identically: " + key)
        check(torch.equal(value, ordinary.state_dict()[key]), "same-shape ordinary starts identically: " + key)

    row = torch.zeros((2, model.ROW), dtype=torch.float64)
    row[:, 34] = .25
    with torch.no_grad():
        full.asset_drive.weight.zero_()
        full.asset_drive.bias.fill_(-3.)
        full.reset_content.copy_(torch.linspace(-.2, .2, model.HIDDEN))
    initial = full.initial(row)
    crossed, first = full.step(row, initial)
    check(first["reset"].all(), "actual observed crossing resets all constructed cells")
    check(torch.equal(crossed[0], full.reset_content.expand_as(crossed[0])), "crossing installs explicit neural reset content")
    check(torch.equal(crossed[1], crossed[1].new_full(crossed[1].shape, .5)), "crossing installs reset membrane")
    check(torch.equal(crossed[2], crossed[2].new_full(crossed[2].shape, .5)), "crossing starts declared source-clock refractory")
    held, second = full.step(row, crossed)
    check(not second["reset"].any() and not second["restored"].any(), "cooldown prevents another constructed reset")
    check(torch.equal(held[0], crossed[0]) and torch.equal(held[1], crossed[1]), "inactive content and membrane remain exact")
    check(torch.equal(held[2], held[2].new_full(held[2].shape, .25)), "inactive source clock consumes only elapsed duration")
    released, third = full.step(row, held)
    check(third["restored"].all() and not third["reset"].any(), "source-tick restoration is actually exercised")
    check(not torch.equal(released[0], held[0]), "restored state consumes new source-point observation")

    # Independent remaining-time witness: .75 elapsed, .5 refractory => .25 active.
    with torch.no_grad():
        full.asset_drive.bias.zero_()
        full.gate.weight.zero_(); full.gate.bias.zero_()
        full.candidate.weight.zero_(); full.candidate.bias.zero_()
        full.rate.zero_()
    row[:, 34] = .75
    witness = (row.new_ones((2, model.HIDDEN)), row.new_ones((2, model.CELLS)),
               row.new_full((2, model.CELLS), .5))
    actual, event = full.step(row, witness)
    drift = full.financial.p.rate-full.financial.p.payout-.5*full.financial.p.volatility**2
    expected_h = .5*math.exp(-math.log(2)*.25)
    expected_membrane = 1+drift*.25
    check(torch.allclose(actual[0], actual[0].new_full(actual[0].shape, expected_h), atol=1e-14, rtol=0), "decay uses active remainder, not full elapsed interval")
    check(torch.allclose(actual[1], actual[1].new_full(actual[1].shape, expected_membrane), atol=1e-14, rtol=0), "membrane drift uses active remainder")
    check(event["restored"].all() and not event["reset"].any(), "remaining-time witness restores without crossing")

    # A boundary intervention keeps the actual absolute asset anchor unchanged.
    torch.manual_seed(protocol["seed"])
    boundary_model = model.Model("hx_full", 6)
    with torch.no_grad():
        boundary_model.asset_drive.weight.zero_(); boundary_model.asset_drive.bias.zero_()
        boundary_model.gate.weight.zero_(); boundary_model.gate.bias.zero_()
        boundary_model.gate.weight[:, model.ROW+model.HIDDEN+2] = 3.
        boundary_model.candidate.weight.zero_(); boundary_model.candidate.bias.fill_(.7)
    row[:, 34] = 0
    state = boundary_model.initial(row)
    state = (state[0], state[1].new_full(state[1].shape, .2), state[2])
    before, _ = boundary_model.step(row, state)
    anchor_before = boundary_model.asset_log_anchor.clone()
    with torch.no_grad():
        boundary_model.financial.boundary.mul_(1.03)
    after, _ = boundary_model.step(row, state)
    effect = float((after[0]-before[0]).abs().max().detach())
    check(torch.equal(anchor_before, boundary_model.asset_log_anchor), "absolute asset anchor does not co-move with boundary")
    check(effect > 1e-7, "actual content step responds to fixed-asset boundary intervention")

    # A real content objective backpropagates through the asset map on a no-reset path.
    torch.manual_seed(protocol["seed"])
    trainable = model.Model("hx_full", 6)
    with torch.no_grad():
        trainable.asset_drive.weight.zero_(); trainable.asset_drive.bias.fill_(.1)
    x = torch.randn((4, model.STEPS, model.ROW), dtype=torch.float64)*.1
    x[:, :, 34] = .25
    target = (torch.arange(4) % 6)[:, None].expand(-1, model.STEPS)
    parameters_before = {key: value.detach().clone() for key, value in trainable.named_parameters()}
    logits, events = trainable(x, return_events=True)
    check(not any(event["reset"].any() for event in events), "joint-gradient witness remains on differentiable continuation branch")
    loss = torch.nn.functional.cross_entropy(logits.reshape(-1, 6), target.reshape(-1))
    loss.backward()
    gradients = {key: 0. if value.grad is None else float(value.grad.norm()) for key, value in trainable.named_parameters()}
    optimizer = torch.optim.SGD(trainable.parameters(), lr=.01)
    optimizer.step()
    deltas = {key: float((value.detach()-parameters_before[key]).abs().max()) for key, value in trainable.named_parameters()}
    for group in ("asset_drive", "gate", "candidate", "reader"):
        check(any(value > 1e-12 for key, value in gradients.items() if key.startswith(group)), "content loss has nonzero " + group + " gradient")
        check(any(value > 1e-14 for key, value in deltas.items() if key.startswith(group)), "actual optimizer updates " + group)

    def financial_forward_forbidden(*args, **kwargs):
        raise AssertionError("Ordinary bank executed financial forward")

    ordinary.financial.forward = financial_forward_forbidden
    ordinary_logits = ordinary(x)
    check(torch.isfinite(ordinary_logits).all(), "ordinary bank executes without financial forward")
    check(sha(source) == protocol["model_sha256"], "model source unchanged through collection")
    result = {"schema": protocol["schema"], "checks": checks, "passed": not failures, "failures": failures,
        "actual_constructed_reset_count": int(first["reset"].sum()), "actual_constructed_restore_count": int(third["restored"].sum()),
        "remaining_time_witness": {"elapsed": .75, "initial_cooldown": .5, "active": .25,
            "expected_h": expected_h, "actual_h": float(actual[0][0, 0].detach()),
            "expected_membrane": expected_membrane, "actual_membrane": float(actual[1][0, 0].detach())},
        "boundary_content_step_max_effect": effect, "content_loss": float(loss.detach()),
        "gradient_norms": gradients, "parameter_max_changes": deltas,
        "scope": protocol["scope"], "formal_fit_or_quality_pass": False}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"checks": checks, "passed": result["passed"], "failures": failures,
                      "resets": result["actual_constructed_reset_count"], "restores": result["actual_constructed_restore_count"]}))
    return result["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if main(args.out) else 1)
