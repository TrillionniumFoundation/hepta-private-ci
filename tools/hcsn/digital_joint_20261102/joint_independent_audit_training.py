"""Actual supervised-loss gradient, cache and export audit; engineering only.

Legal completion histories are constructed directly through successor. No file
is opened as a READ, no cohort is generated, and no engineering update is an
admitted efficacy fit. Boundary rates use feasible one-sided differences.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from . import joint_deploy, joint_kernel, joint_law, joint_model, joint_task, joint_train

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    return {Path(module.__file__).name: digest(module.__file__) for module in
            (joint_deploy, joint_kernel, joint_law, joint_model, joint_task, joint_train)} | {Path(__file__).name: digest(__file__)}


def engineering_rows(protocol):
    public = dict(schema=joint_task.SCHEMA, id="independent-training-gradient-fixture", deadline=6,
                  initial_budget=3, target_tick=6, duration=[.25, .5, 1., 1.5, .5, .25],
                  drive=[-1, 1, 0, -1, 1, 0], reliability=[.65, .85, .95, .55, .85, .65],
                  read_price=[.03, .12, .01, .18, .03, .12], read_delay=[2, 1, 1, 2, 1, 1],
                  latency_price=.025, repair_price=.03, failure_probability=.08, prior_distance=.375,
                  packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0"*64]*6)
    confusion = [[.94, .06], [.09, .91]]
    law = joint_law.IndependentLaw(protocol["truth_raw"])
    rows = []
    for failed_branch in (False, True):
        p = deepcopy(public)
        if failed_branch:
            p["read_delay"] = [1]*6
        oracle = joint_task.Oracle(p, law, confusion)
        state = joint_task.initial(p)
        actions = [(2, None), (1, 1), (2, 0), (2, None), (1, 1), (1, None)]
        if failed_branch:
            actions = [(2, "failure"), (3, None), (2, 1), (1, None), (2, 0), (1, None)]
        for action, observed in actions + [(None, None)]:
            mask = joint_task.legal(p, state)
            rows.append(dict(public=deepcopy(p), state=deepcopy(state), legal=mask,
                             q=np.where(mask, oracle.q(state), 0.).tolist(), posterior=oracle.posterior(state),
                             teacher_mass=oracle.belief(state).tolist(), teacher_bank=oracle.bank(state).tolist()))
            if action is None:
                break
            due = joint_task.due_request(p, state, action)
            assert (due is None) == (observed is None)
            completion = None if due is None else dict(observation_tick=due,
                         **(dict(failure=True) if observed == "failure" else dict(observation=observed)))
            state = joint_task.successor(p, state, action, completion)
    changed = deepcopy(rows[2])
    changed["public"]["read_price"][5] += .04
    rows.append(changed)
    # Two lawful paths with the same completed information and final tick,
    # differing only in an additional failed read/repair and its resource use.
    p = deepcopy(public)
    p["read_delay"] = [1]*6
    oracle = joint_task.Oracle(p, law, confusion)
    for extra_failure in (False, True):
        state = joint_task.successor(p, joint_task.initial(p), 2, dict(observation=1, observation_tick=1))
        if extra_failure:
            state = joint_task.successor(p, state, 2, dict(failure=True, observation_tick=2))
            state = joint_task.successor(p, state, 3)
        while state["tick"] < 6:
            state = joint_task.successor(p, state, 1)
        mask = joint_task.legal(p, state)
        rows.append(dict(public=deepcopy(p), state=state, legal=mask,
                         q=np.where(mask, oracle.q(state), 0.).tolist(), posterior=oracle.posterior(state),
                         teacher_mass=oracle.belief(state).tolist(), teacher_bank=oracle.bank(state).tolist()))
    assert rows[-1]["state"]["history"] == rows[-2]["state"]["history"]
    assert rows[-1]["state"]["budget"] != rows[-2]["state"]["budget"]
    return rows, confusion


def numpy_objective(model, rows, protocol):
    policy = joint_deploy.NumpyPolicy(model.export([.25, .5, .75, 1., 1.5]))
    outputs = [policy.predict(row["public"], row["state"]) for row in rows]
    q, mass, bank, logit = [np.asarray([row[key] for row in outputs]) for key in ("q", "mass", "bank", "logit")]
    mask, target, posterior, teacher_mass, teacher_bank = [np.asarray([row[key] for row in rows]) for key in
                                                        ("legal", "q", "posterior", "teacher_mass", "teacher_bank")]
    qloss = np.mean(np.sum((q-target)**2*mask, -1)/mask.sum(-1))
    bce = np.mean(np.logaddexp(0., logit)-posterior*logit)
    kl = np.mean(np.sum(teacher_mass*(np.log(np.maximum(teacher_mass, 1e-300))-np.log(np.maximum(mass, 1e-300))), -1))
    return qloss+protocol["belief_loss_weight"]*bce+protocol["mass_kl_weight"]*kl+protocol["bank_mse_weight"]*np.mean((bank-teacher_bank)**2)


def audit_family(family, rows, confusion, protocol):
    model = joint_model.Policy(family, 37, confusion)
    loss = joint_train.objective(model, rows, protocol)
    numeric_loss = numpy_objective(model, rows, protocol)
    assert abs(float(loss.detach())-numeric_loss) < 1e-10
    named = dict(model.named_parameters())
    gradients = torch.autograd.grad(loss, tuple(named.values()), allow_unused=True)
    gradients = {name: torch.zeros_like(named[name]) if gradient is None else gradient.detach()
                 for name, gradient in zip(named, gradients)}
    assert all(bool(torch.isfinite(gradient).all()) for gradient in gradients.values())
    checks, plane_norms = [], []
    random = np.random.default_rng(981003)
    def value():
        with torch.no_grad():
            return float(joint_train.objective(model, rows, protocol))
    base = value()
    for name, parameter in named.items():
        gradient = gradients[name].numpy().reshape(-1)
        selection = {}
        if name == "core.raw":
            selection = {i: "central" for i in range(8)}
        elif name == "core.rates":
            rates = parameter.detach().numpy()
            stride = rates.shape[1]
            for plane in range(rates.shape[0]):
                grad = gradients[name][plane].numpy()
                plane_norms.append(float(np.linalg.norm(grad)))
                for candidates, method in ((np.flatnonzero(rates[plane] > .001), "central"),
                                           (np.flatnonzero(rates[plane] == 0), "feasible_forward_3point")):
                    assert len(candidates) > 0
                    indices = [candidates[np.argmax(abs(grad[candidates]))], candidates[random.integers(len(candidates))]]
                    selection.update({plane*stride+int(i): method for i in indices})
            assert min(plane_norms) > 1e-9
        else:
            selection = {int(np.argmax(abs(gradient))): "central", int(random.integers(parameter.numel())): "central"}
        for coordinate, method in selection.items():
            flat = parameter.reshape(-1)
            original, step = float(flat[coordinate].detach()), 1e-5
            with torch.no_grad():
                flat[coordinate] = original+step
            plus = value()
            with torch.no_grad():
                flat[coordinate] = original+(2*step if method.startswith("feasible") else -step)
            other = value()
            with torch.no_grad():
                flat[coordinate] = original
            numerical = (-3*base+4*plus-other)/(2*step) if method.startswith("feasible") else (plus-other)/(2*step)
            analytic = float(gradient[coordinate])
            error = abs(numerical-analytic)
            allowed = 2e-6+1e-4*abs(analytic)
            checks.append(dict(parameter=name, coordinate=coordinate, method=method, analytic=analytic,
                               finite_difference=numerical, absolute_error=error, tolerance=allowed))
    assert all(check["absolute_error"] <= check["tolerance"] for check in checks)
    with torch.no_grad():
        batch = model.forward_rows(rows)
        fresh = [model.forward_row(row["public"], row["state"]) for row in rows]
        cache_error = max(float((batch[key]-torch.stack([row[key] for row in fresh])).abs().max()) for key in batch)
    assert cache_error < 1e-11
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-4)
    engineering_losses = []
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        updated = joint_train.objective(model, rows, protocol)
        updated.backward()
        assert all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in model.parameters())
        optimizer.step()
        model.project()
        engineering_losses.append(float(updated.detach()))
    after = float(joint_train.objective(model, rows, protocol).detach())
    after_numpy = numpy_objective(model, rows, protocol)
    assert abs(after-after_numpy) < 1e-10
    return dict(family=family, passed=True, checks=checks, rate_plane_gradient_norms=plane_norms,
                nominal_parameter_count=sum(p.numel() for p in model.parameters()),
                maximum_gradient_error=max(check["absolute_error"] for check in checks),
                cache_batch_vs_fresh_error=cache_error, initial_numpy_loss_error=abs(base-numeric_loss),
                after_two_engineering_updates_numpy_loss_error=abs(after-after_numpy),
                engineering_optimizer_steps=2, engineering_losses=engineering_losses)


def main():
    torch.set_num_threads(1)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    before = source_identity()
    protocol = json.loads((HERE/"joint_protocol.json").read_text())
    rows, confusion = engineering_rows(protocol)
    results = [audit_family(family, rows, confusion, protocol) for family in joint_model.FAMILIES]
    assert before == source_identity()
    result = dict(schema="joint-actual-training-loss-independent-audit-v1", passed=True, families=results,
                  source_sha256=before, legal_engineering_decision_rows=len(rows),
                  maximum_completed_observations=max(len(row["state"]["history"]) for row in rows),
                  repaired_failure_histories_included=True, actual_file_reads=0, formal_fits=0,
                  loss_weights={key: protocol[key] for key in ("belief_loss_weight", "mass_kl_weight", "bank_mse_weight")},
                  scope="Actual model/full-history conditioning/scheduled bank/formal objective; coordinate FD and two engineering update/cache/export checks, no efficacy or continuum-gradient qualification")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(dict(passed=True, rows=len(rows), families=[dict(family=r["family"], checks=len(r["checks"]), max_error=r["maximum_gradient_error"]) for r in results]), sort_keys=True))


if __name__ == "__main__":
    main()
