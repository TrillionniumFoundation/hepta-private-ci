"""Shared train-only teacher and resumable, equally capped policy searches."""

import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.batched_flow import FlowConfig
from qualification.hcsn_adaptive.budget import Budget, BudgetExhausted, CostLedger, summarize_journal
from qualification.hcsn_adaptive.campaign import digest, save_tensor_file, write_json
from qualification.hcsn_adaptive.checkpoint import load_checkpoint, save_checkpoint
from qualification.hcsn_adaptive.datasets import file_digest, load_split
from .model import TaskBoundaryModel, evaluate_policy, gradient_diagnostic


def model_for(manifest, seed):
    random.seed(seed)
    np.random.seed(seed % 2**32)
    torch.manual_seed(seed)
    return TaskBoundaryModel(FlowConfig(**manifest["flow"]), manifest["length"],
                             manifest["config"]["horizon"]).to(manifest["config"]["device"])


def tensors(data, device):
    return (torch.as_tensor(data["x"], dtype=torch.float64, device=device),
            torch.as_tensor(data["y"], dtype=torch.float64, device=device))


def readout_digest(model):
    h = hashlib.sha256()
    for tensor in (model.readout.weight, model.readout.bias, model.readout_mean, model.readout_scale):
        h.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def paths_for(manifest, trial, output):
    identity = digest({"manifest": manifest["sha256"], "trial": trial})
    return identity, Path(output) / "trials" / trial["id"]


def prepare_shared(manifest, seed, output, *, resume=False):
    started = time.perf_counter()
    cfg = manifest["config"]
    identity = digest({"manifest": manifest["sha256"], "seed": seed, "role": "shared-teacher"})
    directory = Path(output) / "shared" / str(seed)
    receipt_path, payload_path = directory / "shared.json", directory / "shared.pt"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["identity"] != identity or receipt["sha256"] != file_digest(payload_path):
            raise ValueError("shared teacher checkpoint identity or bytes changed")
        payload = torch.load(payload_path, map_location=cfg["device"], weights_only=True)
        if payload["identity"] != identity:
            raise ValueError("shared teacher payload identity changed")
        model = model_for(manifest, seed)
        model.load_state_dict(payload["model"])
        if readout_digest(model) != receipt["readout_sha256"]:
            raise ValueError("shared frozen readout changed")
        return model, receipt, payload
    existed = (directory / "cost.jsonl").exists()
    if existed and not resume:
        raise FileExistsError("incomplete shared training requires --resume")
    ledger = CostLedger(directory / "cost.jsonl", Budget(**cfg["shared_budget"]), identity, started_at=started)
    checkpoint = directory / "checkpoint.pt"
    with ledger.operation("initialize-shared"):
        train = load_split(cfg["data_dir"], "train", manifest["data"])
        dev = load_split(cfg["data_dir"], "dev", manifest["data"])
        model = model_for(manifest, seed)
        tx, ty = tensors(train, cfg["device"])
        dx, dy = tensors(dev, cfg["device"])
        model.validate_data(tx, train["dt"])
        model.validate_data(dx, dev["dt"])
        optimizer = torch.optim.SGD(model.parameters(), lr=1.0)
        generator = torch.Generator().manual_seed(seed)
        controller = {"phase": 0, "seed": seed}
    if checkpoint.exists():
        controller = load_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                                     generator=generator, ledger=ledger)
    elif existed:
        raise ValueError("shared cost exists without a recoverable checkpoint")
    readout_idx, teacher_idx = manifest["readout_indices"], manifest["teacher_indices"]

    def save():
        save_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                        controller=controller, generator=generator, ledger=ledger)

    save()
    if controller["phase"] == 0:
        with ledger.operation("train-only-readout-ridge", training_examples=len(readout_idx),
                              encoder_events=len(readout_idx)*model.length, forward_examples=len(readout_idx)):
            model.fit_readout(tx[readout_idx], train["dt"][readout_idx], ty[readout_idx], cfg["readout_ridge"])
            with torch.no_grad():
                observed = tx[readout_idx, model.decision_step, 0]
                model.input_mean.copy_(observed.mean())
                model.input_scale.copy_(observed.std(unbiased=False).clamp_min(1e-8))
            controller["phase"] = 1
        save()
    if controller["phase"] == 1:
        with ledger.operation("paired-training-task-teacher-and-critic", training_examples=len(teacher_idx),
                              encoder_events=len(teacher_idx)*(model.length+model.horizon),
                              forward_examples=3*len(teacher_idx)):
            teacher = model.teacher(tx[teacher_idx], train["dt"][teacher_idx], ty[teacher_idx],
                                    split="train", event_cost=cfg["event_cost"])
            model.fit_critic(teacher, cfg["critic_ridge"])
            advantage = teacher["advantage"]
            with torch.no_grad():
                fit = model.critic((teacher["causal_features"]-model.critic_mean)/model.critic_scale)
            controller["teacher"] = {
                "examples": len(teacher_idx), "decision_clock_micros": teacher["decision_clock_micros"],
                "low_task_mse": float(teacher["low"]["loss"].mean()),
                "high_task_mse": float(teacher["high"]["loss"].mean()),
                "low_events": float(teacher["low"]["events"].mean()),
                "high_events": float(teacher["high"]["events"].mean()),
                "advantage_mean": float(advantage.mean()), "advantage_std": float(advantage.std(unbiased=False)),
                "advantage_min": float(advantage.min()), "advantage_max": float(advantage.max()),
                "critic_training_mse": float((fit-advantage).square().mean()),
                "final_clock_micros": teacher["low"]["final_clock_micros"]}
            controller["phase"] = 2
        save()
    if controller["phase"] == 2:
        with ledger.operation("shared-zero-development-reference", development_queries=1,
                              forward_examples=len(dx), encoder_events=len(dx)*model.length):
            controller["baseline"] = evaluate_policy(model, dx, dev["dt"], dy, {"kind": "zero"}, cfg["event_cost"])
            controller["phase"] = 3
        save()
    if controller["phase"] == 3:
        with ledger.operation("boundary-FD-AD-diagnostic", encoder_events=model.decision_step,
                              forward_examples=5, backward_examples=1):
            controller["gradient_diagnostic"] = gradient_diagnostic(model, tx[teacher_idx[:1]])
            controller["phase"] = 4
        save()
    payload = {"identity": identity, "model": model.state_dict(), "contract": model.contract(),
               "baseline": controller["baseline"], "teacher": controller["teacher"],
               "gradient_diagnostic": controller["gradient_diagnostic"],
               "readout_sha256": readout_digest(model)}
    with ledger.operation("checkpoint", mandatory=True):
        save_tensor_file(payload_path, payload)
    receipt = {"identity": identity, "sha256": file_digest(payload_path), "seed": seed,
               "readout_sha256": payload["readout_sha256"], "cost": ledger.snapshot(),
               "cost_attribution": {"train-only-readout-ridge": "common to all arms",
                                    "paired-training-task-teacher-and-critic": "required only by task_advantage",
                                    "boundary-FD-AD-diagnostic": "qualification overhead for task_advantage",
                                    "shared-zero-development-reference": "shared NoUpdate reference"},
               "teacher": controller["teacher"], "gradient_diagnostic": controller["gradient_diagnostic"],
               "contract": model.contract(), "baseline": controller["baseline"]}
    write_json(receipt_path, receipt, exclusive=True)
    return model, receipt, payload


def train_trial(manifest, trial, output, *, resume=False, stop_after=None):
    if (Path(output) / "finalization-seal.json").exists():
        raise ValueError("selection set is sealed; policy search cannot resume")
    started = time.perf_counter()
    cfg = manifest["config"]
    identity, directory = paths_for(manifest, trial, output)
    record_path = directory / "training.json"
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if previous["identity"] != identity or previous["trial"] != trial:
            raise ValueError("policy search record identity mismatch")
        if previous["status"] != "paused":
            if previous.get("selected_sha256") and file_digest(directory / "selected.pt") != previous["selected_sha256"]:
                raise ValueError("selected policy bytes changed")
            return previous
        if not resume:
            raise FileExistsError("paused policy search requires --resume")
    model, shared, payload = prepare_shared(manifest, trial["seed"], output, resume=resume)
    # Shared wall is accounted once in its own journal, not repeatedly per arm.
    started_arm = time.perf_counter()
    existed = (directory / "cost.jsonl").exists()
    if existed and not resume:
        raise FileExistsError("incomplete policy search requires --resume")
    ledger = CostLedger(directory / "cost.jsonl", Budget(**cfg["budget"]), identity, started_at=started_arm)
    checkpoint = directory / "checkpoint.pt"
    with ledger.operation("initialize-policy-search"):
        dev = load_split(cfg["data_dir"], "dev", manifest["data"])
        dx, dy = tensors(dev, cfg["device"])
        optimizer = torch.optim.SGD(model.parameters(), lr=1.0)
        generator = torch.Generator().manual_seed(trial["seed"])
        controller = {"seed": trial["seed"], "next": 0, "shared_sha256": shared["sha256"],
                      "best_policy": {"kind": "zero"}, "best": payload["baseline"], "history": []}
    if checkpoint.exists():
        controller = load_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                                     generator=generator, ledger=ledger)
        if controller["seed"] != trial["seed"] or controller["shared_sha256"] != shared["sha256"]:
            raise ValueError("policy controller seed/shared model changed")
    elif existed:
        raise ValueError("policy cost exists without a recoverable checkpoint")

    def save():
        save_checkpoint(checkpoint, identity=identity, model=model, optimizer=optimizer,
                        controller=controller, generator=generator, ledger=ledger)

    save()
    status, iterations = "completed", 0
    for index in range(controller["next"], len(manifest["policies"][trial["arm"]])):
        if stop_after is not None and iterations >= stop_after:
            status = "paused"
            break
        policy = manifest["policies"][trial["arm"]][index]
        try:
            with ledger.operation("development-policy-candidate", development_queries=1, proposals=1,
                                  forward_examples=len(dx)*(2 if policy["kind"] == "task" else 1),
                                  encoder_events=len(dx)*model.length):
                result = evaluate_policy(model, dx, dev["dt"], dy, policy, cfg["event_cost"])
                controller["history"].append({"policy": policy, "result": result})
                if result["objective"] < controller["best"]["objective"]:
                    controller["best"], controller["best_policy"] = result, policy
        except BudgetExhausted:
            status = "budget_exhausted"
            break
        except (FloatingPointError, RuntimeError, ValueError) as exc:
            controller["history"].append({"policy": policy, "failure": type(exc).__name__ + ": " + str(exc)})
        controller["next"] = index + 1
        iterations += 1
        save()
    record = {"identity": identity, "manifest": manifest["sha256"], "trial": trial, "status": status,
              "outcome": "NoUpdate" if controller["best_policy"]["kind"] == "zero" else "SelectedPulse",
              "policy": controller["best_policy"], "dev": controller["best"], "history": controller["history"],
              "shared_identity": shared["identity"], "shared_sha256": shared["sha256"],
              "readout_sha256": shared["readout_sha256"], "scope": "one predeclared continuous boundary pulse",
              "outer_wall_seconds": time.perf_counter()-started}
    if status != "paused":
        with ledger.operation("checkpoint", mandatory=True):
            selected = {"identity": identity, "trial": trial, "shared_sha256": shared["sha256"],
                        "policy": controller["best_policy"], "dev": controller["best"],
                        "readout_sha256": shared["readout_sha256"]}
            save_tensor_file(directory / "selected.pt", selected)
        record["selected_sha256"] = file_digest(directory / "selected.pt")
    record["cost"] = ledger.snapshot()
    write_json(record_path, record)
    return record


def failure_receipt(manifest, trial, output, error, attempt_wall_seconds=None):
    identity, directory = paths_for(manifest, trial, output)
    record = {"identity": identity, "manifest": manifest["sha256"], "trial": trial,
              "status": "failed", "reason": type(error).__name__ + ": " + str(error),
              "attempt_wall_seconds": attempt_wall_seconds,
              "cost": summarize_journal(directory / "cost.jsonl"),
              "shared_cost": summarize_journal(Path(output) / "shared" / str(trial["seed"]) / "cost.jsonl")}
    path = directory / "training.json"
    if path.exists() or isinstance(error, FileExistsError):
        path = directory / ("attempt-failure-" + str(time.time_ns()) + ".json")
    write_json(path, record, exclusive=True)
    return record
