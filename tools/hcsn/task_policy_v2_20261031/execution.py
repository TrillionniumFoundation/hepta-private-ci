"""Real owner execution for new development or frozen confirmation cohorts."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..native_task_bridge_20261031.reference import NUMERIC_CONTRACT, infer, select_action
from ..task_value_factorial_20261030.task import ACTIONS, Bellman, Owner, score_terminal
from .planner import OneRead

FLOAT64_CONTRACT = "hepta.task.float64-numpy-argmax.v1"


def rollout(session, adapter, confusion, multiplier, latency_price, policy, checkpoint=None,
            numeric_contract=FLOAT64_CONTRACT):
    if numeric_contract not in (FLOAT64_CONTRACT, NUMERIC_CONTRACT):
        raise ValueError("Unregistered numeric deployment contract")
    wall, cpu = time.perf_counter(), time.process_time()
    owner = Owner(session["folder"], adapter, confusion, multiplier, latency_price)
    if policy == "exact_teacher":
        controller = Bellman(owner.meta, confusion, multiplier, latency_price)
    elif policy in ("one_read", "residual"):
        controller = OneRead(owner.meta, confusion, multiplier, latency_price)
    else:
        raise ValueError("Unregistered policy")
    traces, controller_cpu, controller_wall = [], 0., 0.
    weights = {k:np.asarray(v, float) for k,v in checkpoint["weights"].items()} if policy == "residual" else None
    model = dict(checkpoint, weights=weights) if weights is not None else None
    while not owner.terminal:
        begin, begin_cpu = time.perf_counter(), time.process_time()
        state = (owner.job, owner.tick, owner.budget, owner.posterior)
        q = np.asarray(controller.q(*state))
        prior, features, drive = q.copy(), None, None
        legal = np.isfinite(prior)
        if weights is not None:
            features = controller.features(*state, prior=q)
            if numeric_contract == NUMERIC_CONTRACT:
                action, q, drive = infer(model, features, prior, legal)
            else:
                x = np.clip((features-checkpoint["norm"]["mean"])/checkpoint["norm"]["scale"], -8., 8.)
                delta = np.maximum(0., np.tanh(x@weights["w"]+weights["b"])@weights["v"]+weights["c"])
                q = q+delta
                q[0] = 0.
        if numeric_contract == FLOAT64_CONTRACT:
            action = int(np.argmax(q))
        elif weights is None:
            action, drive = select_action(q, legal)
        controller_cpu += time.process_time()-begin_cpu
        controller_wall += time.perf_counter()-begin
        event = owner.act(ACTIONS[action])
        traces.append(dict(state=list(state), q=np.where(legal, q, 0.).tolist(),
            prior=np.where(np.isfinite(prior), prior, 0.).tolist(),
            feasible=legal.tolist(), action=action, drive=None if drive is None else drive.tolist(),
            features=None if features is None else features.tolist(), event=event))
    score = score_terminal(owner)
    return dict(seed=session["seed"], session_id=session["id"], split=session["split"], policy=policy,
        numeric_contract=numeric_contract,
        score=score, counts=owner.counts, task_elapsed=owner.task_elapsed, traces=traces,
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
        controller_cpu_seconds=controller_cpu, controller_wall_seconds=controller_wall,
        public_sha256=owner.public_sha256)


def diagnose(rows, meta_by_id, confusion, multiplier, latency_price):
    """Post-execution fitted-law regret; teacher computation is timed separately."""
    wall, cpu = time.perf_counter(), time.process_time()
    details = []
    for row in rows:
        teacher = Bellman(meta_by_id[row["session_id"]], confusion, multiplier, latency_price)
        losses = []
        for trace in row["traces"]:
            q = np.asarray(teacher.q(*trace["state"]))
            losses.append(float(q.max()-q[trace["action"]]))
        details.append(dict(session_id=row["session_id"], policy=row["policy"],
                            cumulative_regret=sum(losses), decisions=len(losses), regrets=losses))
    return dict(rows=details, cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
                scope="Read-only teacher diagnosis after actual execution; excluded from policy CPU")


def source_hashes():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))}
