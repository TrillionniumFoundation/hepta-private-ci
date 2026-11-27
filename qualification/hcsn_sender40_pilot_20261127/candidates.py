"""Two frozen proposal rules and two declared controls, using training data only."""
from pathlib import Path
import time

import numpy as np
import torch

from model_adapter import take
from static_support import exact_norm2, flat_from_matrix, realized, role_ids, sha, trust_region, write_bytes, write_json

NAMES = ("ANALYTIC_ROLE_025", "ANALYTIC_ROLE_100", "BP_TASK_4", "BP_TASK_16", "WRONG_ROLE", "RANDOM")


def analytic(trace, train, correct, wrong, ledger):
    ledger.check_time()
    ledger.charge("analytic_solves")
    ledger.event("supervised_analytic_fit_started", wrong_role=wrong)
    good = np.repeat(correct, 2)
    roles = role_ids(train["y"])
    actors = np.repeat(train["groups"], 2)
    for role in (0, 1):
        if len(set(actors[good & (roles == role)].tolist())) < 2:
            raise ValueError("frozen prototype actor-coverage minimum failed")
    drift = trace["sender_drift"]
    if drift.shape != (3, 160, 4) or trace["sender_keys"].shape != (3, 160, 10):
        raise ValueError("complete source-bound training trace shape")
    prototypes = np.stack([[drift[t, good & (roles == role)].mean(axis=0) for role in (0, 1)] for t in range(3)])
    assignment = 1 - roles if wrong else roles
    targets = np.stack([prototypes[t, assignment] for t in range(3)])
    interior = (targets + .2) / .15
    if not np.isfinite(interior).all() or (np.abs(interior) >= 1).any():
        raise ValueError("target drift has no finite declared inverse; no clamp permitted")
    residual = np.arctanh(interior) - trace["sender_z"].astype(np.float64)
    keys = trace["sender_keys"].reshape(-1, 10).astype(np.float64)
    good_rows = np.tile(good, 3)
    solution, evidence = trust_region(keys[~good_rows], residual.reshape(-1, 4)[~good_rows], keys[good_rows])
    ledger.check_time()
    ledger.event("supervised_analytic_fit_completed", wrong_role=wrong, **evidence)
    return flat_from_matrix(solution), dict(prototypes=prototypes.tolist(), role_order=["decoy", "match"],
           correct_training_queries=int(correct.sum()), target_source="parent-correct train labels and actual sender drift",
           supervised_fit=True, parameter_gradient_used=False, frozen_old_recurrence_only=True,
           target_is_ndu_truth=False, **evidence)


def save_candidate(name, theta, adapter, output, budget, evidence):
    adapter.set_theta(theta)
    prefix = Path(output) / name
    raw = np.asarray(theta, dtype="<f4").tobytes()
    write_bytes(prefix.with_suffix(".f32le"), raw)
    checkpoint = prefix.with_suffix(".pt")
    with checkpoint.open("xb") as stream:
        torch.save(adapter.model.state_dict(), stream)
    record = dict(name=name, parameter_sha256=sha(raw), checkpoint_sha256=sha(checkpoint.read_bytes()),
                  norm=budget["norm"], actual_nonzero=int(budget["norm2_numerator"]) != 0,
                  actual_parameter_bits_changed=theta.tobytes() != adapter.parent.tobytes(),
                  exact_budget=budget, evidence=evidence,
                  inference_only=True, optimizer_state_migrated=False, owner_published=False)
    write_json(prefix.with_suffix(".json"), record)
    return record


def generate(adapter, train, trace, parent_scores, output, ledger):
    parent = adapter.parent.copy()
    correct = parent_scores.argmax(axis=1) == train["y"]
    write_json(Path(output) / "supervised_training_selection.json", dict(
        correct_mask=correct.tolist(), fit_queries=80, fitted_actor_groups=sorted(set(train["groups"].tolist())),
        selection_is_supervised=True, dev_or_retain_used_for_fitting=False))
    records, vectors = {}, {}
    start, cpu_start = time.monotonic(), time.process_time()
    delta, evidence = analytic(trace, train, correct, False, ledger)
    for name, factor in ((NAMES[0], .25), (NAMES[1], 1.)):
        theta, budget = realized(parent, delta * factor)
        vectors[name] = theta.copy()
        records[name] = save_candidate(name, theta, adapter, output, budget, dict(evidence, fixed_scale=factor))
    adapter.set_theta(parent)
    write_json(Path(output) / "analytic_cost.json", dict(wall_seconds=time.monotonic() - start,
               cpu_seconds=time.process_time() - cpu_start,
               qualification_and_parent_trace_shared=True, fit_and_two_compiles_included=True))
    start, cpu_start = time.monotonic(), time.process_time()
    try:
        optimizer = torch.optim.Adam([adapter.model.body.input_drive.weight, adapter.model.body.input_drive.bias],
                                     lr=.008, betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)
        generator = np.random.default_rng(20261127)
        batches = np.concatenate((generator.permutation(80), generator.permutation(80)[:48])).reshape(16, 8)
        write_json(Path(output) / "bp_batches.json", dict(seed=20261127, generator="numpy.PCG64", batches=batches.tolist()))
        parent_margin = (parent_scores[:, 1] - parent_scores[:, 0]).astype("float32")
        losses = []
        for step, ids in enumerate(batches, 1):
            optimizer.zero_grad(set_to_none=True)
            scores, _, _ = adapter.run(take(train, ids), "BP_TRAIN_" + str(step), gradient=True)
            loss = torch.nn.functional.cross_entropy(scores.to(torch.float64), torch.from_numpy(train["y"][ids]))
            selected = correct[ids]
            if selected.any():
                margin = (scores[:, 1] - scores[:, 0])[torch.from_numpy(selected)].to(torch.float64)
                loss = loss + .25 * (margin - torch.from_numpy(parent_margin[ids][selected]).to(torch.float64)).square().mean()
            ledger.backward(loss)
            parameters = [adapter.model.body.input_drive.weight, adapter.model.body.input_drive.bias]
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in parameters):
                raise ValueError("nonfinite/missing same-coordinate BP gradient")
            torch.nn.utils.clip_grad_norm_(parameters, 1.)
            ledger.charge("optimizer_steps")
            ledger.event("optimizer_step_started", step=step)
            optimizer.step()
            theta, budget = realized(parent, adapter.theta().astype(np.float64) - parent.astype(np.float64))
            adapter.set_theta(theta)
            ledger.event("optimizer_step_completed", step=step, exact_norm2=budget)
            losses.append(dict(step=step, loss_f64=float(loss.detach()), batch_parent_correct=int(selected.sum())))
            if step in (4, 16):
                name = "BP_TASK_" + str(step)
                vectors[name] = theta.copy()
                records[name] = save_candidate(name, theta, adapter, output, budget, dict(
                    optimizer_steps=step, loss="F64 CE of actual F32 scores plus within-batch protected margin MSE",
                    objective_differs_from_physical_surrogate=True, losses=losses.copy()))
    finally:
        adapter.set_theta(parent)
    write_json(Path(output) / "bp_cost.json", dict(wall_seconds=time.monotonic() - start,
               cpu_seconds=time.process_time() - cpu_start, updates=16, snapshot_steps=[4, 16],
               qualification_and_parent_trace_shared=True, candidate_evaluation_not_yet_included=True))
    start, cpu_start = time.monotonic(), time.process_time()
    wrong, evidence = analytic(trace, train, correct, True, ledger)
    theta, budget = realized(parent, wrong)
    vectors["WRONG_ROLE"] = theta.copy()
    records["WRONG_ROLE"] = save_candidate("WRONG_ROLE", theta, adapter, output, budget, evidence)
    random = np.random.default_rng(20261128).choice(np.array([-1., 1.]), 40)
    cap2 = exact_norm2(vectors["ANALYTIC_ROLE_100"], parent)
    theta, budget = realized(parent, random, cap2)
    vectors["RANDOM"] = theta.copy()
    records["RANDOM"] = save_candidate("RANDOM", theta, adapter, output, budget,
        dict(seed=20261128, norm_cap_from="ANALYTIC_ROLE_100", selected_using_quality=False,
             cap2_numerator=str(cap2.numerator), cap2_denominator=str(cap2.denominator),
             actual2_numerator=budget["norm2_numerator"], actual2_denominator=budget["norm2_denominator"],
             absolute_norm_gap=records["ANALYTIC_ROLE_100"]["norm"] - budget["norm"],
             exact_equal_norm_not_claimed=True))
    adapter.set_theta(parent)
    write_json(Path(output) / "controls_cost.json", dict(wall_seconds=time.monotonic() - start,
               cpu_seconds=time.process_time() - cpu_start, wrong_role_solves=1,
               random_is_inward_same_cap_not_exact_norm_match=True))
    if tuple(sorted(records)) != tuple(sorted(NAMES)):
        raise ValueError("the fixed six-candidate declaration was not completed")
    write_json(Path(output) / "CANDIDATES_SEALED.json", dict(
        schema="hepta.sender40-six-candidate-seal.v1", candidate_order=list(NAMES), records=records,
        before_any_candidate_dev_retain=True, parent_restored_in_memory=True,
        test_used=False, immutable_after_seal=True, counts=dict(ledger.counts)))
    return records, vectors, correct
