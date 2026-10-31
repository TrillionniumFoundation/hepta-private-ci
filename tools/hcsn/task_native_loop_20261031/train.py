"""Five independently fitted, equal-budget cells and full-task Q controllers.

TRAIN supplies observations and fitted-law Q labels. Validation chooses a whole
cell/critic checkpoint. No heldout cohort is created in this preparation phase.
Run with OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..task_value_factorial_20261030.cells import recurrent_features
from ..task_value_factorial_20261030.controller import (
    loss_and_gradient, parameter_hash, parameters, validation_regret)
from ..task_value_factorial_20261030.dataset import collect
from ..task_value_factorial_20261030.storage import archive
from ..task_value_factorial_20261030.task import ContentAdapter, calibrate, save, sha
from .model import ARMS, design, export, identity, norm67

HERE = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def announce(stage, **fields):
    print(json.dumps(dict(stage=stage, time=stamp(), **fields)), flush=True)


def packed(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(value, allow_nan=False, sort_keys=True).encode(), mtime=0))
    return sha(path)


def source_identity():
    paths = [HERE / name for name in ("train.py", "model.py", "reference.py", "PROTOCOL.json")]
    previous = HERE.parent / "task_value_factorial_20261030"
    paths += [previous / name for name in ("task.py", "dataset.py", "cells.py", "controller.py",
                                         "execution.py", "propagation.py", "storage.py", "UPSTREAM_FILES.json")]
    return {str(p.relative_to(HERE.parent)): sha(p) for p in paths}


def adam_step(values, gradient, first, second, step, lr, clip):
    magnitude = float(np.linalg.norm(gradient))
    gradient = gradient * min(1., clip / max(magnitude, 1e-15))
    first *= .9
    first += .1 * gradient
    second *= .999
    second += .001 * gradient * gradient
    result = values - lr * (first / (1-.9**step)) / (np.sqrt(second / (1-.999**step)) + 1e-8)
    return np.clip(result, -3., 3.), magnitude


def numerical_gradient(theta, objective, epsilon):
    gradient = np.zeros_like(theta)
    losses = []
    for index in range(len(theta)):
        plus, minus = theta.copy(), theta.copy()
        plus[index], minus[index] = min(3., theta[index]+epsilon), max(-3., theta[index]-epsilon)
        upper, lower = objective(plus), objective(minus)
        if not np.isfinite(upper+lower):
            raise FloatingPointError("Nonfinite cell objective")
        gradient[index] = (upper-lower)/(plus[index]-minus[index])
        losses.append([upper, lower])
    return gradient, losses


def train_family(family, seed, train, validation, norm, protocol):
    wall, cpu = time.perf_counter(), time.process_time()
    rng = np.random.default_rng(seed + protocol["cell_init_seed_base"])
    theta = rng.normal(0., .15, 11)
    original = theta.copy()
    rows = [r for r in train if "next_observation" in r]
    if len(rows) < 4:
        raise ValueError("Insufficient actual TRAIN READ observations")
    labels = np.asarray([r["next_observation"] for r in rows], float)
    first, second, pretraining = np.zeros(11), np.zeros(11), []

    def observation_loss(candidate):
        raw = recurrent_features(family, candidate[:6], rows)
        logit = raw @ candidate[6:10] + candidate[10]
        return float(np.mean(np.logaddexp(0., logit)-labels*logit)
                     + protocol["cell_l2"] * (candidate @ candidate))

    for step in range(1, protocol["pretrain_cell_updates"]+1):
        gradient, losses = numerical_gradient(theta, observation_loss, protocol["finite_difference_epsilon"])
        theta, magnitude = adam_step(theta, gradient, first, second, step,
                                     protocol["pretrain_learning_rate"], protocol["gradient_clip"])
        pretraining.append(dict(update=step, central_losses=losses, gradient=gradient.tolist(),
                                gradient_norm=magnitude, loss=observation_loss(theta), parameters=theta.tolist()))
    pretrained = theta.copy()
    pretraining_cpu, pretraining_wall = time.process_time()-cpu, time.perf_counter()-wall
    weights = parameters(seed+protocol["critic_init_seed_base"], 67, protocol["critic_width"])
    initial_hash = parameter_hash(weights)
    head_first, head_second = ({k: np.zeros_like(v) for k, v in weights.items()} for _ in range(2))
    first, second = np.zeros(11), np.zeros(11)
    target = np.asarray([r["q"] for r in train], float)
    valid = np.asarray([r["feasible"] for r in train], bool)
    vtarget = np.asarray([r["q"] for r in validation], float)
    vvalid = np.asarray([r["feasible"] for r in validation], bool)
    x = design(train, family, theta, norm)
    vx = design(validation, family, theta, norm)
    batches = np.random.default_rng(seed+protocol["batch_seed_base"])
    cell_batches = np.random.default_rng(seed+protocol["batch_seed_base"]+1)
    batch_bytes, cell_batch_bytes = bytearray(), bytearray()
    losses, joint, candidates, best = [], [], [], None
    for update in range(1, protocol["critic_updates"]+1):
        batch = batches.integers(0, len(train), protocol["batch_size"])
        batch_bytes.extend(batch.astype("<i8").tobytes())
        loss, gradients = loss_and_gradient(weights, x[batch], target[batch], valid[batch], protocol["critic_l2"])
        if not np.isfinite(loss) or not all(np.all(np.isfinite(g)) for g in gradients.values()):
            raise FloatingPointError("Nonfinite critic training")
        norm_g = np.sqrt(sum(float(np.square(g).sum()) for g in gradients.values()))
        factor = min(1., protocol["gradient_clip"]/max(norm_g, 1e-15))
        for name in weights:
            gradient = gradients[name]*factor
            head_first[name] = .9*head_first[name]+.1*gradient
            head_second[name] = .999*head_second[name]+.001*gradient*gradient
            weights[name] -= protocol["learning_rate"]*(head_first[name]/(1-.9**update))/(np.sqrt(head_second[name]/(1-.999**update))+1e-8)
        losses.append(loss)
        if update % protocol["joint_cell_every"] == 0:
            subset = cell_batches.integers(0, len(train), protocol["joint_cell_batch_size"])
            cell_batch_bytes.extend(subset.astype("<i8").tobytes())
            selected_rows = [train[int(i)] for i in subset]

            def task_loss(candidate):
                z = design(selected_rows, family, candidate, norm)
                result, _ = loss_and_gradient(weights, z, target[subset], valid[subset], 0.)
                return result + protocol["cell_l2"] * float(candidate @ candidate)

            before = theta.copy()
            gradient, cell_losses = numerical_gradient(theta, task_loss, protocol["finite_difference_epsilon"])
            theta, magnitude = adam_step(theta, gradient, first, second, len(joint)+1,
                                         protocol["cell_learning_rate"], protocol["gradient_clip"])
            joint.append(dict(critic_update=update, central_losses=cell_losses, gradient=gradient.tolist(),
                gradient_norm=magnitude, task_loss_after=task_loss(theta),
                parameter_delta=(theta-before).tolist(), parameters=theta.tolist()))
            x, vx = design(train, family, theta, norm), design(validation, family, theta, norm)
        if update in protocol["checkpoint_updates"]:
            regret = validation_regret(weights, vx, vtarget, vvalid)
            checkpoint = dict(update=update, validation_regret=regret, parameters=theta.tolist(),
                              weights={k: v.tolist() for k, v in weights.items()}, critic_sha256=parameter_hash(weights))
            candidates.append(checkpoint)
            if best is None or regret < best["validation_regret"]:
                best = checkpoint
    if best is None:
        raise ValueError("No frozen checkpoint evaluated")
    selected_theta = np.asarray(best["parameters"])
    receipt = dict(family=family, seed=seed, selected_update=best["update"],
        selected_validation_regret=best["validation_regret"], initial_parameters=original.tolist(),
        pretrained_parameters=pretrained.tolist(), selected_parameters=selected_theta.tolist(),
        selected_task_training_parameter_delta=(selected_theta-pretrained).tolist(),
        critic_initial_sha256=initial_hash, critic_minibatch_sha256=hashlib.sha256(batch_bytes).hexdigest(),
        cell_minibatch_sha256=hashlib.sha256(cell_batch_bytes).hexdigest(), pretraining=pretraining,
        joint=joint, losses=losses, candidates=candidates, parameter_count=1743,
        central_difference_evaluations=22*(len(pretraining)+len(joint)),
        objective_evaluations=23*(len(pretraining)+len(joint)),
        train_states=len(train), validation_states=len(validation), train_read_rows=len(rows),
        pretraining_cpu_seconds=pretraining_cpu, pretraining_wall_seconds=pretraining_wall,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        convergence_claim=False, stopping_reason="Frozen equal optimizer/evaluation budget exhausted")
    return selected_theta, {k: np.asarray(v) for k, v in best["weights"].items()}, receipt


def prepare(out, protocol):
    start, cpu = time.perf_counter(), time.process_time()
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    save(out / "PROTOCOL.json", protocol)
    sources = source_identity()
    save(out / "STARTED.json", dict(created_at=stamp(), source=sources, heldout_generated=False))
    policies, datasets, archives, fits = {}, {}, {}, {}
    for seed in protocol["seeds"]:
        announce("development", seed=seed)
        shared_cpu, shared_wall = time.process_time(), time.perf_counter()
        adapter = ContentAdapter()
        root = out / "_work" / f"development_seed{seed}"
        confusion, calibration = calibrate(adapter, root, seed, protocol["calibration_packets"], protocol)
        train = collect(root, "train", seed, protocol["train_sessions"], protocol, adapter, confusion,
                        protocol["multiplier"], protocol["latency_price"])
        validation = collect(root, "validation", seed, protocol["validation_sessions"], protocol, adapter,
                             confusion, protocol["multiplier"], protocol["latency_price"])
        norm = norm67(train["rows"])
        fit = dict(seed=seed, confusion=confusion.tolist(), adapter=adapter.setup,
                   shared_cpu_seconds=time.process_time()-shared_cpu,
                   shared_wall_seconds=time.perf_counter()-shared_wall, families={})
        for family in ("ordinary", "analytic"):
            announce("joint_training", seed=seed, family=family, states=len(train["rows"]))
            theta, weights, receipt = train_family(family, seed, train["rows"], validation["rows"], norm, protocol)
            fit["families"][family] = receipt
            for mode in ("fixed", "value"):
                policy = export(family, mode, seed, theta, weights, norm, confusion, protocol)
                path = out / "models" / f"seed{seed}_{family}_{mode}.json"
                save(path, policy)
                policies[str(path.relative_to(out))] = dict(sha256=sha(path), model_identity=identity(policy))
            announce("family_complete", seed=seed, family=family, cpu_seconds=receipt["cpu_seconds"],
                     selected_update=receipt["selected_update"], regret=receipt["selected_validation_regret"])
        path = out / "training" / f"seed{seed}.json.gz"
        datasets[str(path.relative_to(out))] = packed(path, dict(train=train, validation=validation,
            calibration=calibration, fit=fit))
        path = out / "data" / f"development_seed{seed}.tar.gz"
        archives[str(path.relative_to(out))] = archive(path, root)
        fits[str(seed)] = dict(shared_cpu_seconds=fit["shared_cpu_seconds"],
            training_cpu_seconds={f: fit["families"][f]["cpu_seconds"] for f in fit["families"]},
            selected_updates={f: fit["families"][f]["selected_update"] for f in fit["families"]},
            selected_task_parameter_delta={f: fit["families"][f]["selected_task_training_parameter_delta"] for f in fit["families"]})
    if source_identity() != sources:
        raise RuntimeError("Training source changed during preparation; preserve this attempt")
    save(out / "FREEZE.json", dict(schema="hcsn.task.native.loop.freeze.v1", frozen_at=stamp(),
        source=sources, protocol_sha256=sha(out / "PROTOCOL.json"), policies=policies, training=datasets,
        development_archives=archives, fits=fits, heldout_generated=False,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
        cost_scope="Outer preparation includes data, calibration, teachers, both cell fits and serialization. Nested fit timers are attributions, not additive campaign costs."))
    announce("freeze_ready", out=str(out), freeze_sha256=sha(out / "FREEZE.json"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.out, json.loads((HERE / "PROTOCOL.json").read_text()))


if __name__ == "__main__":
    main()
