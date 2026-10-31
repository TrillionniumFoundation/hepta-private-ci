"""Fresh development, equal-budget learning and immutable pre-test freeze."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..task_native_loop_20261031.train import adam_step, numerical_gradient, packed
from ..task_value_factorial_20261030.controller import parameters, parameter_hash
from ..task_value_factorial_20261030.dataset import collect
from ..task_value_factorial_20261030.storage import archive
from ..task_value_factorial_20261030.task import ContentAdapter, calibrate, save, sha
from .model import design, export, identity, loss_gradient, norm67, residual
from .value import anchors, metrics

HERE = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sources():
    paths = [HERE/name for name in ("train.py", "value.py", "model.py", "PROTOCOL.json", "propagation/finite.py")]
    return {str(p.relative_to(HERE)):sha(p) for p in paths}


def train_family(family, seed, train, validation, norm, base, vbase, protocol):
    wall, cpu = time.perf_counter(), time.process_time()
    theta = np.random.default_rng(seed+protocol["cell_init_seed_base"]).normal(0., .15, 11)
    initial = theta.copy()
    rows = [r for r in train if "next_observation" in r]
    labels = np.asarray([r["next_observation"] for r in rows])
    first, second = np.zeros(11), np.zeros(11)
    pretraining = []

    def observation_loss(candidate):
        from .propagation.finite import augmented_features
        p = augmented_features(family, candidate, rows)[:, 4]
        return float(-np.mean(labels*np.log(p)+(1-labels)*np.log1p(-p)))

    for step in range(1, protocol["pretrain_cell_updates"]+1):
        g, _ = numerical_gradient(theta, observation_loss, protocol["finite_difference_epsilon"])
        theta, magnitude = adam_step(theta, g, first, second, step,
                                     protocol["pretrain_learning_rate"], protocol["gradient_clip"])
        pretraining.append(dict(step=step, loss=observation_loss(theta), gradient=g.tolist(), norm=magnitude))
    pretrained = theta.copy()
    weights = parameters(seed+protocol["critic_init_seed_base"], 67, 24)
    initial_hash = parameter_hash(weights)
    hfirst, hsecond = ({k:np.zeros_like(v) for k,v in weights.items()} for _ in range(2))
    first, second = np.zeros(11), np.zeros(11)
    target = np.asarray([r["q"] for r in train])-base
    vtarget = np.asarray([r["q"] for r in validation])-vbase
    valid = np.asarray([r["feasible"] for r in train], bool)
    vvalid = np.asarray([r["feasible"] for r in validation], bool)
    x, vx = design(train, family, theta, norm), design(validation, family, theta, norm)
    rng, crng = (np.random.default_rng(seed+protocol["batch_seed_base"]+i) for i in (0,1))
    batch_bytes, cbatch_bytes = bytearray(), bytearray()
    joint, losses, candidates, best = [], [], [], None
    radius = protocol["residual_radius"]
    for update in range(1, protocol["critic_updates"]+1):
        batch = rng.integers(0, len(train), protocol["batch_size"])
        batch_bytes.extend(batch.astype("<i8").tobytes())
        loss, gradients = loss_gradient(weights, x[batch], target[batch], valid[batch], radius)
        magnitude = np.sqrt(sum(float(np.square(g).sum()) for g in gradients.values()))
        if not np.isfinite(loss+magnitude):
            raise FloatingPointError("Nonfinite residual training")
        for k in weights:
            g = gradients[k]*min(1., protocol["gradient_clip"]/max(magnitude, 1e-15))
            hfirst[k] = .9*hfirst[k]+.1*g
            hsecond[k] = .999*hsecond[k]+.001*g*g
            weights[k] -= protocol["learning_rate"]*(hfirst[k]/(1-.9**update))/(np.sqrt(hsecond[k]/(1-.999**update))+1e-8)
        losses.append(loss)
        if update % protocol["joint_cell_every"] == 0:
            batch = crng.integers(0, len(train), protocol["joint_cell_batch_size"])
            cbatch_bytes.extend(batch.astype("<i8").tobytes())
            records = [train[int(i)] for i in batch]

            def objective(candidate):
                return loss_gradient(weights, design(records, family, candidate, norm),
                                     target[batch], valid[batch], radius)[0]

            g, _ = numerical_gradient(theta, objective, protocol["finite_difference_epsilon"])
            before = theta.copy()
            theta, magnitude = adam_step(theta, g, first, second, len(joint)+1,
                                         protocol["cell_learning_rate"], protocol["gradient_clip"])
            joint.append(dict(update=update, task_gradient=g.tolist(), norm=magnitude,
                              parameter_delta=(theta-before).tolist()))
            x, vx = design(train, family, theta, norm), design(validation, family, theta, norm)
        if update in protocol["checkpoint_updates"]:
            vloss, _ = loss_gradient(weights, vx, vtarget, vvalid, radius)
            delta, _, _ = residual(weights, vx, radius)
            candidate = dict(update=update, validation_loss=vloss, calibration=metrics(vbase+delta, validation),
                parameters=theta.tolist(), weights={k:v.tolist() for k,v in weights.items()})
            candidates.append(candidate)
            if best is None or vloss < best["validation_loss"]:
                best = candidate
    receipt = dict(family=family, seed=seed, initial_parameters=initial.tolist(),
        pretrained_parameters=pretrained.tolist(), pretraining=pretraining, joint=joint,
        losses=losses, candidates=candidates, selected_update=best["update"],
        critic_initial_sha256=initial_hash, minibatch_sha256=hashlib.sha256(batch_bytes).hexdigest(),
        cell_minibatch_sha256=hashlib.sha256(cbatch_bytes).hexdigest(), allocated_parameters=1743,
        active_parameters=1718, inactive_stop_head_parameters=25,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    return np.asarray(best["parameters"]), {k:np.asarray(v) for k,v in best["weights"].items()}, receipt


def prepare(out, protocol):
    out.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    source = sources()
    save(out/"STARTED.json", dict(at=stamp(), sources=source, heldout_generated=False))
    save(out/"PROTOCOL.json", protocol)
    models, costs, grids, artifacts = {}, {}, {}, {}
    for seed in protocol["seeds"]:
        print(json.dumps(dict(stage="development", seed=seed)), flush=True)
        shared_start = time.process_time()
        adapter = ContentAdapter()
        root = out/"_work"/f"development_seed{seed}"
        confusion, calibration = calibrate(adapter, root, seed, protocol["calibration_packets"], protocol)
        train = collect(root, "train", seed, protocol["train_sessions"], protocol, adapter, confusion,
                        protocol["multiplier"], protocol["latency_price"])
        validation = collect(root, "validation", seed, protocol["validation_sessions"], protocol, adapter,
                             confusion, protocol["multiplier"], protocol["latency_price"])
        norm = norm67(train["rows"])
        candidates = []
        nodes = None
        for n in protocol["grid_candidates"]:
            vbase, cost = anchors(validation["rows"], n)
            result = metrics(vbase, validation["rows"])
            candidates.append(dict(nodes=n, metrics=result, cost=cost))
            if result["max_q_error"] <= protocol["grid_max_q_error"] and result["mean_action_regret"] <= protocol["grid_mean_action_regret"]:
                nodes = n
                break
        if nodes is None:
            save(out/f"GRID_FAILURE_{seed}.json", candidates)
            raise ValueError("Ordinary calibration gate failed before heldout")
        base, base_cost = anchors(train["rows"], nodes)
        shared_cpu = time.process_time()-shared_start
        fits = {}
        for family in ("ordinary", "analytic"):
            theta, weights, fit = train_family(family, seed, train["rows"], validation["rows"], norm, base, vbase, protocol)
            fits[family] = fit
            model = export(family, seed, theta, weights, norm, confusion, protocol, nodes)
            path = out/"models"/f"seed{seed}_{family}_value.json"
            save(path, model)
            models[str(path.relative_to(out))] = dict(sha256=sha(path), identity=identity(model))
            if family == "ordinary":
                derived = dict(model, controller="grid")
                path = out/"models"/f"seed{seed}_grid.json"
            else:
                derived = dict(model, intervention="constant")
                path = out/"models"/f"seed{seed}_analytic_constant.json"
            save(path, derived)
            models[str(path.relative_to(out))] = dict(sha256=sha(path), identity=identity(derived))
            print(json.dumps(dict(stage="fit", seed=seed, family=family, nodes=nodes,
                cpu_seconds=fit["cpu_seconds"], selected=fit["selected_update"])), flush=True)
        path = out/"training"/f"seed{seed}.json.gz"
        artifacts[str(path.relative_to(out))] = packed(path, dict(train=train, validation=validation,
            calibration=calibration, fits=fits, grid_selection=candidates, train_grid_cost=base_cost))
        path = out/"data"/f"development_seed{seed}.tar.gz"
        artifacts[str(path.relative_to(out))] = archive(path, root)
        costs[str(seed)] = dict(shared_cpu_seconds=shared_cpu,
            fit_cpu_seconds={family:fits[family]["cpu_seconds"] for family in fits})
        grids[str(seed)] = candidates
    if source != sources():
        raise RuntimeError("Training source changed during training")
    save(out/"FREEZE.json", dict(at=stamp(), source=source, protocol_sha256=sha(out/"PROTOCOL.json"),
        models=models, artifacts=artifacts, costs=costs, grids=grids, heldout_generated=False,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start))
    print(json.dumps(dict(stage="frozen", sha256=sha(out/"FREEZE.json"))), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.out, json.loads((HERE/"PROTOCOL.json").read_text()))
