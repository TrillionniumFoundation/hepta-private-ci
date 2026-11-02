"""CPU-deadline full-distribution supervised learning with real policy feedback.

Complete model mass and every matrix exponential remain in autograd. Teacher
states/Q are targets only. Final complete update is selected, with no validation
selection. The external budget launcher owns whole-process admission.
"""
import argparse
import copy
import gzip
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import torch
import torch.nn.functional as F

from . import joint_task as task
from .joint_budget import BudgetCheckpoint
from .joint_law import IndependentLaw
from .joint_model import FAMILIES, Policy

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    with path.open("xb") as stream:
        stream.write(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)
    return dict(path=str(path), sha256=sha(path), bytes=path.stat().st_size)


def source_identity():
    root = HERE.parent.parent.parent
    names = [HERE/name for name in ("joint_train.py", "joint_model.py", "joint_deploy.py", "joint_kernel.py", "joint_task.py", "joint_law.py", "joint_data.py", "joint_budget.py", "joint_campaign.py", "joint_launch.py", "joint_compiled_dp.py", "joint_deadline_reference.py", "joint_protocol.json")]
    owner = HERE.parent/"task_value_factorial_20261030"
    names += [owner/"task.py", owner/"UPSTREAM_FILES.json", HERE.parent/"digital_read_before_20261031/task.py"]
    manifest = json.loads((owner/"UPSTREAM_FILES.json").read_text())
    names += [root/item["path"] for item in manifest["files"]]
    return {str(p.relative_to(root)): sha(p) for p in names}


def objective(model, rows, protocol, details=False):
    """Actual training loss, shared by finite-difference audit and optimizer."""
    output = model.forward_rows(rows)
    mask = torch.tensor([r["legal"] for r in rows], dtype=torch.float64)
    target = torch.tensor([r["q"] for r in rows], dtype=torch.float64)
    posterior = torch.tensor([r["posterior"] for r in rows], dtype=torch.float64)
    mass = torch.tensor([r["teacher_mass"] for r in rows], dtype=torch.float64)
    bank = torch.tensor([r["teacher_bank"] for r in rows], dtype=torch.float64)
    qloss = (((output["q"]-target).square()*mask).sum(-1)/mask.sum(-1)).mean()
    belief = F.binary_cross_entropy_with_logits(output["logit"], posterior)
    kl = (mass*(torch.log(mass.clamp_min(1e-300))-torch.log(output["mass"].clamp_min(1e-300)))).sum(-1).mean()
    bankloss = (output["bank"]-bank).square().mean()
    loss = qloss+protocol["belief_loss_weight"]*belief+protocol["mass_kl_weight"]*kl+protocol["bank_mse_weight"]*bankloss
    if not bool(torch.isfinite(loss)):
        raise FloatingPointError("nonfinite complete distribution loss")
    if not details:
        return loss
    with torch.no_grad():
        selected = output["q"].masked_fill(~mask.bool(), -torch.inf).argmax(-1)
        regret = target.masked_fill(~mask.bool(), -torch.inf).max(-1).values-target.gather(1, selected[:, None]).flatten()
        metrics = dict(loss=float(loss), q_mse=float(qloss), belief_bce=float(belief), mass_kl=float(kl), bank_mse=float(bankloss),
                       teacher_belief_brier=float((output["belief"]-posterior).square().mean()), teacher_behavior_regret=float(regret.mean()),
                       max_mass_defect=float((output["mass"].sum(-1)-1).abs().max()))
    return loss, metrics


def collect(record, model, adapter, oracle, round_index, rng, protocol, cache):
    public = json.loads((Path(record["folder"])/"public.json").read_text())
    owner, rows, decisions = task.Owner(public, record["folder"], adapter), [], []
    while not owner.state["terminal"]:
        state = copy.deepcopy(owner.state); mask = task.legal(public, state)
        with torch.no_grad():
            scores = model.forward_row(public, state, cache)
        q, belief = scores["q"].tolist(), float(scores["belief"])
        fixed = (round_index+int(record["id"].rsplit("_", 1)[1]))%2 == 0
        action = task.fixed_action(state, mask, belief) if fixed else int(np.argmax(np.where(mask, q, -np.inf)))
        if rng.random() < protocol["exploration_probability"]:
            weights = np.asarray(protocol["behavior_action_weights"])*mask
            action = int(rng.choice(6, p=weights/weights.sum()))
        target = oracle.q(state)
        rows.append(dict(world=record["id"], public=public, state=state, legal=mask,
                         q=np.where(mask, target, 0.).tolist(), posterior=oracle.posterior(state),
                         teacher_mass=oracle.belief(state).tolist(), teacher_bank=oracle.bank(state).tolist()))
        receipt = owner.step(action)
        decisions.append(dict(q=q, belief=belief, action=action, receipt=receipt))
    label = json.loads((Path(record["folder"])/"evaluator.json").read_text())["label"]
    return rows, dict(world=record["id"], decisions=decisions, outcome=task.evaluate_terminal(owner.state, label))


def train(datafile, family, protocol_path, out, published_source_commit):
    if len(published_source_commit) != 40 or set(published_source_commit)-set("0123456789abcdef"):
        raise ValueError("published formal source identity required")
    torch.set_num_threads(1); budget = BudgetCheckpoint.from_env()
    protocol = json.loads(Path(protocol_path).read_text())
    if protocol["status"] != "frozen" or protocol["families"] != list(FAMILIES):
        raise ValueError("publish final protocol and full registered family set before fitting")
    data = json.loads(Path(datafile).read_text()); fit = int(data["fit"])
    if (fit not in protocol["fits"] or data["environment_law"]["raw"] != protocol["truth_raw"]
            or any(data[s+"_cohort"]["published_source_commit"] != published_source_commit for s in ("train", "validation"))
            or any(len(data[s+"_cohort"]["records"]) != protocol[s+"_worlds"] for s in ("train", "validation"))):
        raise ValueError("formal data identity, fit, physics or cohort dimensions mismatch")
    out.mkdir(parents=True, exist_ok=False); sources = source_identity()
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    model = Policy(family, fit, data["confusion"]); initial_head = model.head_identity()
    optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["learning_rate"], weight_decay=protocol["weight_decay"])
    rows = list(data["train"]["rows"]); rng = np.random.default_rng(918000+fit)
    adapter = task.ContentAdapter(); law = IndependentLaw(protocol["truth_raw"])
    records = data["train_cohort"]["records"]
    oracles = {r["id"]: task.Oracle(json.loads((Path(r["folder"])/"public.json").read_text()), law, data["confusion"]) for r in records}
    write(out/"STARTED.json", dict(schema="joint-fit-start-v1", family=family, fit=fit, sources=sources,
            published_source_commit=published_source_commit, data_sha256=sha(datafile), protocol_sha256=sha(protocol_path), initial_head_sha256=initial_head,
            budget_nominal=budget.spec.nominal_cpu_seconds, shared_charge=budget.shared_cpu_seconds,
            versions=dict(python=platform.python_version(), numpy=np.__version__, torch=torch.__version__),
            objective="complete conditional mass supervised loss, no teacher features; final CPU-deadline update"))
    updates, rounds, step_estimate = [], [], .25
    work_start, work_end = budget.used_cpu_seconds, budget.spec.nominal_cpu_seconds-budget.spec.export_reserve_seconds
    for round_index in range(protocol["policy_feedback_rounds"]):
        target_cpu = work_start+(work_end-work_start)*(round_index+1)/protocol["policy_feedback_rounds"]
        round_rows, episodes, cache = [], [], {}
        for record in records:
            if not budget.can_continue(.30):
                break
            new_rows, episode = collect(record, model, adapter, oracles[record["id"]], round_index, rng, protocol, cache)
            round_rows += new_rows; episodes.append(episode)
        rows += round_rows
        completed = len(episodes) == len(records)
        before_steps = len(updates)
        while completed and budget.can_continue(step_estimate) and budget.used_cpu_seconds+step_estimate < target_cpu:
            indices = rng.integers(len(rows), size=protocol["batch_states"])
            batch = [rows[int(i)] for i in indices]
            before = time.process_time(); optimizer.zero_grad(set_to_none=True)
            loss, metrics = objective(model, batch, protocol, details=True); loss.backward()
            if any(p.grad is not None and not bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
                raise FloatingPointError("nonfinite model gradient")
            raw_gradient = model.core.raw.grad.detach().tolist() if family == "renewal" else []
            norm = float(torch.nn.utils.clip_grad_norm_(model.parameters(), protocol["gradient_clip"]))
            optimizer.step(); model.project()
            elapsed = time.process_time()-before; step_estimate = max(.01, .75*step_estimate, 1.5*elapsed)
            updates.append(dict(step=len(updates)+1, round=round_index, **metrics, gradient_norm_before_clip=norm,
                                raw_gradient=raw_gradient, cpu_seconds=elapsed, minibatch_indices=indices.tolist()))
        rounds.append(dict(round=round_index, complete=completed, episodes=episodes, added_rows=len(round_rows),
                           total_rows=len(rows), updates=len(updates)-before_steps, cpu_at_end=budget.used_cpu_seconds))
        if not completed:
            break
    export_start = time.process_time()
    with torch.no_grad():
        _, validation = objective(model, data["validation"]["rows"], protocol, details=True)
    durations = sorted(set(protocol["train_domain"]["durations"]+protocol["ood_domain"]["durations"]))
    artifact = model.export(durations); model_info = write(out/"model.json", artifact)
    if source_identity() != sources:
        raise RuntimeError("source changed during complete fit; reject scientific comparison")
    result = dict(schema="joint-fit-complete-v1", family=family, fit=fit, model=model_info,
                  source_sha256=sources, data_sha256=sha(datafile), protocol_sha256=sha(protocol_path), published_source_commit=published_source_commit,
                  initial_head_sha256=initial_head, final_head_sha256=model.head_identity(),
                  raw_initial=artifact["nominal_raw"], raw_final=None if family != "renewal" else artifact["core"]["raw"],
                  actual_updates=len(updates), actual_collection_episodes=sum(len(r["episodes"]) for r in rounds),
                  actual_collection_visits=sum(r["added_rows"] for r in rounds),
                  all_rounds_complete=len(rounds) == protocol["policy_feedback_rounds"] and all(r["complete"] for r in rounds),
                  validation_diagnostic=validation, validation_used_for_selection=False, convergence_claim=False,
                  parameter_count=artifact["parameter_count"], export_and_validation_cpu_seconds=time.process_time()-export_start,
                  wall_seconds=time.perf_counter()-start_wall, internal_cpu_seconds=time.process_time()-start_cpu,
                  cpu_before_final_receipt=budget.used_cpu_seconds, final_selection="last complete optimizer update, no validation selection")
    write(out/"TRAINING.json.gz", dict(updates=updates, rounds=rounds, initial_behavior_rows=len(data["train"]["rows"])))
    write(out/"COMPLETE.json", result)
    print(json.dumps(dict(stage="fit_complete", fit=fit, family=family, updates=len(updates), rounds_complete=result["all_rounds_complete"], cpu=budget.used_cpu_seconds)), flush=True)


def main():
    p = argparse.ArgumentParser(); p.add_argument("--data", type=Path, required=True)
    p.add_argument("--family", choices=FAMILIES, required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--protocol", type=Path, default=HERE/"joint_protocol.json"); p.add_argument("--source-commit", required=True)
    a = p.parse_args(); train(a.data, a.family, a.protocol, a.out, a.source_commit)


if __name__ == "__main__":
    main()
