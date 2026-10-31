"""Counterfactual teacher coverage and genuine residual-policy fitting.

Only the training process calls Bellman. Deployed inference uses the explicitly
bounded OneRead prior plus the frozen residual network; it never calls teacher.
"""
import hashlib
import time

import numpy as np

from ..task_value_factorial_20261030.task import Bellman, feasible, likelihood, metadata, outcomes
from .planner import OneRead


def teacher_data(seed, count, protocol, confusion):
    wall, cpu = time.perf_counter(), time.process_time()
    confusion = np.asarray(confusion, float)
    rng = np.random.default_rng(seed)
    rows, environments = [], []
    for env in range(count):
        meta = metadata(rng, f"counterfactual_{seed}_{env}", protocol)
        environments.append(meta)
        teacher = Bellman(meta, confusion, protocol["multiplier"], protocol["latency_price"])
        planner = OneRead(meta, confusion, protocol["multiplier"], protocol["latency_price"])
        states = {}
        # Counterfactual trajectories cover teacher, bounded-planner and
        # exploratory actions. Observation branches use the fitted public law,
        # not hidden packet values or evaluator truth.
        for trajectory in range(18):
            state = (0, 0, meta["budget"], .5)
            origin = ("teacher", "bounded", "explore")[trajectory % 3]
            while state[0] < 2 and state[1] < meta["deadline"]:
                job, tick, budget, belief = state
                states.setdefault((job, tick, budget, round(belief, 12)), (state, origin))
                legal = feasible(meta, job, tick, budget)
                q = np.asarray(teacher.q(*state)) if origin == "teacher" else planner.q(*state)
                action = int(np.argmax(q)) if origin != "explore" else int(rng.choice(np.flatnonzero(legal)))
                if action == 0:
                    break
                if action == 1:
                    state = job, tick+1, budget, belief
                elif action == 2:
                    prob, beliefs = outcomes(belief, likelihood(confusion, meta["reliability"][job][tick]))
                    obs = int(rng.choice(2, p=prob))
                    state = job, tick+1, budget-1, float(beliefs[obs])
                else:
                    state = job+1, tick+2, budget, .5
        for index in range(24):
            state = (int(rng.integers(2)), int(rng.integers(meta["deadline"])),
                     int(rng.integers(meta["budget"]+1)), float(rng.choice([.5, .6, .7, .8, .9, .98])))
            states.setdefault((state[0], state[1], state[2], round(state[3], 12)), (state, "belief_grid"))
        for state, origin in states.values():
            target, prior = np.asarray(teacher.q(*state)), planner.q(*state)
            mask = np.isfinite(target)
            if np.min(target[mask]-prior[mask]) < -2e-12:
                raise ArithmeticError("Bounded-plan lower-value contract violated")
            rows.append(dict(environment=env, state=list(state), origin=origin,
                features=planner.features(*state, prior).tolist(), feasible=mask.tolist(),
                teacher=np.where(mask, target, 0.).tolist(), prior=np.where(mask, prior, 0.).tolist(),
                prior_regret=float(target.max()-target[int(np.argmax(prior))])))
    return dict(seed=seed, environments=environments, rows=rows,
        source="Fitted-model counterfactual supervision; no packet/evaluator labels",
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)


def parameter_hash(weights):
    return hashlib.sha256(b"".join(np.asarray(weights[k], dtype="<f8").tobytes() for k in ("w", "b", "v", "c"))).hexdigest()


def loss_gradient(weights, x, target, mask, row_weights, mode, l2):
    hidden = np.tanh(x@weights["w"]+weights["b"])
    delta = hidden@weights["v"]+weights["c"]
    delta[:, 0] = 0.
    error = (delta-target)*mask
    if mode == "advantage":
        error -= (error.sum(axis=1)/mask.sum(axis=1))[:, None]*mask
    elif mode != "q_mse":
        raise ValueError("Unknown residual loss")
    weighted = row_weights[:, None]*mask
    denominator = float(weighted.sum())
    loss = float(np.sum(error*error*weighted)/denominator+l2*sum(np.square(v).sum() for v in weights.values()))
    output_gradient = 2*error*weighted/denominator
    output_gradient[:, 0] = 0.
    # Row centering is an orthogonal projection over the same legal mask;
    # its centered derivative therefore has the same expression above.
    d_hidden = (output_gradient@weights["v"].T)*(1-hidden*hidden)
    gradients = dict(w=x.T@d_hidden, b=d_hidden.sum(0), v=hidden.T@output_gradient, c=output_gradient.sum(0))
    return loss, {k:g+2*l2*weights[k] for k,g in gradients.items()}


def predictions(weights, x, prior, mask):
    delta = np.maximum(0., np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"])
    q = prior+delta
    q[:, 0] = 0.
    return np.where(mask, q, -np.inf)


def fit(train, validation, seed, mode, width=64, updates=3000, batch=256):
    wall, cpu = time.perf_counter(), time.process_time()
    raw = np.asarray([r["features"] for r in train["rows"]])
    mean, scale = raw.mean(0), raw.std(0)
    scale[scale < 1e-9] = 1.
    x = np.clip((raw-mean)/scale, -8., 8.)
    vx = np.clip((np.asarray([r["features"] for r in validation["rows"]])-mean)/scale, -8., 8.)
    target = np.asarray([r["teacher"] for r in train["rows"]])-np.asarray([r["prior"] for r in train["rows"]])
    mask = np.asarray([r["feasible"] for r in train["rows"]], bool)
    vp = np.asarray([r["prior"] for r in validation["rows"]])
    vt = np.asarray([r["teacher"] for r in validation["rows"]])
    vm = np.asarray([r["feasible"] for r in validation["rows"]], bool)
    sampling_weight = 1+4*(np.asarray([r["prior_regret"] for r in train["rows"]]) > 1e-8)
    rng = np.random.default_rng(seed)
    weights = dict(w=rng.normal(0., 1/np.sqrt(x.shape[1]), (x.shape[1], width)), b=np.zeros(width),
                   v=np.zeros((width, 4)), c=np.zeros(4))
    initial_sha = parameter_hash(weights)
    first, second = ({k:np.zeros_like(v) for k,v in weights.items()} for _ in range(2))
    losses, candidates, minibatches = [], [], bytearray()
    chosen, best = None, float("inf")
    checkpoints = sorted(set([0, min(updates, 100), min(updates, 300), min(updates, 1000), updates]))
    for update in range(updates+1):
        if update in checkpoints:
            q = predictions(weights, vx, vp, vm)
            action = np.argmax(q, axis=1)
            regret = float(np.mean(np.max(np.where(vm, vt, -np.inf), axis=1)-vt[np.arange(len(vt)), action]))
            candidate = dict(update=update, validation_regret=regret,
                parameter_sha256=parameter_hash(weights), weights={k:v.tolist() for k,v in weights.items()})
            candidates.append(candidate)
            if regret < best:
                chosen, best = candidate, regret
        if update == updates:
            break
        index = rng.integers(0, len(x), batch)
        minibatches.extend(index.astype("<i8").tobytes())
        loss, gradients = loss_gradient(weights, x[index], target[index], mask[index], sampling_weight[index], mode, 1e-7)
        losses.append(loss)
        if not np.isfinite(loss):
            raise FloatingPointError("Residual fitting failed")
        norm = np.sqrt(sum(float(np.square(g).sum()) for g in gradients.values()))
        for k in weights:
            g = gradients[k]*min(1., 2/max(norm, 1e-15))
            first[k] = .9*first[k]+.1*g
            second[k] = .999*second[k]+.001*g*g
            step = update+1
            weights[k] -= .001*(first[k]/(1-.9**step))/(np.sqrt(second[k]/(1-.999**step))+1e-8)
    checkpoint = dict(schema="hcsn.task.policy.residual.v2", feature_schema="one_read_relative_65_v1",
        norm=dict(mean=mean.tolist(), scale=scale.tolist()), weights=chosen["weights"],
        inference="q=OneReadPrior+max(tanh(clip((raw-mean)/scale,-8,8)@w+b)@v+c,0); q[STOP]=0; legal mask",
        source_scope="Learned residual over bounded one-read planner; no full teacher call at deployment",
        selected_update=chosen["update"], parameter_count=sum(v.size for v in weights.values()))
    selected_weights = {k:np.asarray(v, float) for k,v in chosen["weights"].items()}
    full_loss, full_gradient = loss_gradient(selected_weights, x, target, mask, sampling_weight, mode, 1e-7)
    gradient_norm = float(np.sqrt(sum(float(np.square(g).sum()) for g in full_gradient.values())))
    receipt = dict(mode=mode, seed=seed, updates=updates, batch_size=batch,
        train_states=len(x), validation_states=len(vx), initial_sha256=initial_sha,
        minibatch_sha256=hashlib.sha256(minibatches).hexdigest(), candidates=candidates, losses=losses,
        selected_update=chosen["update"], selected_validation_regret=best,
        selected_full_train_loss=full_loss, selected_full_train_gradient_norm=gradient_norm,
        stationary_at_declared_gradient_tolerance=gradient_norm <= 1e-5,
        gradient_tolerance=1e-5,
        termination="Declared fixed update budget; no convergence claim",
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall)
    return checkpoint, receipt
