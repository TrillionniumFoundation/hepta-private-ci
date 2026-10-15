"""Learn stop/resume value for the SAME retained heuristic frontier.

One decision after a fixed quarter-budget probe. No policy switching, root
restart, reachability oracle or parameter update at evaluation. The 32-number
observation is a lossy frontier summary, not a sufficient-state theorem.
"""

from copy import deepcopy
import math
import time

import torch
from torch import nn

from system2_ablation import model_digest
from system2_budget_control import COUNTERS, LIMITS, UNIT_COST, state_features
from system2_resumable_search import SearchSession
from system2_verified_search import digest, features, state_key, verify

ARMS = (
    "direct",
    "resume",
    "probe_stop",
    "frontier",
    "root_only",
    "shuffled",
    "cost_blind",
)
TRAINING_MODES = ("frontier", "root_only", "shuffled")
DIMENSION = 32


def observe(session, total):
    """Read only: never advance the pending generator or inspect a future outcome."""
    receipt = session.receipt()
    spent = receipt["costs"]["generated_successors"]
    if (
        session.arm != "heuristic_search"
        or session.goal != 24
        or session.failed
        or receipt["found"]
        or not receipt["paused"]
    ):
        raise ValueError("healthy unfinished fixed-policy frontier required")
    root = state_features(session.numbers, total, spent)
    sizes = (
        len(session.queue),
        len(session.seen),
        len(session.children),
        session.cursor,
    )
    summary = [
        sizes[0] / (1 + sizes[0]),
        sizes[1] / (1 + sizes[1]),
        float(session.pending is not None),
        sizes[2] / (1 + sizes[2]),
        sizes[3] / (1 + sizes[3]),
    ]
    best = features(state_key(session.queue[0][2]), 24) if session.queue else [0.0] * 12
    context = root + summary + best
    if len(context) != DIMENSION or not all(math.isfinite(v) for v in context):
        raise ValueError("invalid observable frontier features")
    return context


def make_head():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(719)
        return nn.Sequential(nn.Linear(DIMENSION, 16), nn.Tanh(), nn.Linear(16, 2))


def advance_logged(session, ceiling, sink):
    """Durable sink runs before work. Interrupts and journal errors propagate."""
    before = session.receipt()
    sink(deepcopy(dict(event="advance_start", ceiling=ceiling, receipt=before)))
    try:
        result = session.advance(ceiling)
        costs = result["costs"]
        if (
            result["status"] != "completed"
            or type(result["found"]) is not bool
            or any(
                type(costs[k]) is not int or costs[k] < before["costs"][k]
                for k in COUNTERS
            )
            or costs["generated_successors"] > ceiling
            or (result["found"] and not verify(session.numbers, 24, result["proof"]))
            or (not result["found"] and result["proof"] is not None)
        ):
            raise ValueError("invalid cumulative search receipt or proof")
    except BaseException as exc:
        sink(
            deepcopy(
                dict(
                    event="advance_failed",
                    ceiling=ceiling,
                    receipt=session.receipt(),
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    incomplete_work=True,
                )
            )
        )
        raise
    sink(deepcopy(dict(event="advance_completed", ceiling=ceiling, receipt=result)))
    return result


def collect_training(tasks, ledger, sink):
    """One real probe and retained continuation; targets are not oracle labels."""
    if (
        not tasks
        or len(tasks) > 128
        or len(set(map(tuple, tasks))) != len(tasks)
        or not isinstance(ledger, list)
        or ledger
        or not callable(sink)
    ):
        raise ValueError("unique admitted tasks and empty caller-owned ledger required")
    for numbers in tasks:
        state_features(numbers, LIMITS[0], 0)
    xs, ys = [], []
    for numbers in tasks:
        for budget in LIMITS:
            identity = dict(
                query_id=digest(numbers), numbers=list(numbers), budget=budget
            )
            row = identity | dict(status="started")
            ledger.append(row)
            session = SearchSession(numbers, 24, "heuristic_search")

            def emit(event, identity=identity):
                sink(deepcopy(identity | event))

            try:
                emit(dict(event="context_start"))
                probe = advance_logged(session, budget // 4, emit)
                row["probe"] = probe
                if probe["found"] or not probe["paused"]:
                    row["disposition"] = "no_continuation_decision"
                else:
                    x = observe(session, budget)
                    row["features"] = list(x)
                    row["feature_digest"] = digest(x)
                    # Record state BEFORE the continuation reveals its outcome.
                    emit(
                        dict(
                            event="context_observed",
                            features=x,
                            feature_digest=digest(x),
                        )
                    )
                    tail = advance_logged(session, budget, emit)
                    row["continued"] = tail
                    spent = probe["costs"]["generated_successors"]
                    extra = tail["costs"]["generated_successors"] - spent
                    target = [float(tail["found"]), extra / (budget - spent)]
                    xs.append(x)
                    ys.append(target)
                    row.update(target=target, disposition="actual_resumed_return")
                row["status"] = "completed"
                emit(dict(event="context_completed", row=row))
            except BaseException as exc:
                row.update(
                    status="failed",
                    last_receipt=session.receipt(),
                    error_type=type(exc).__name__,
                    error=str(exc)[:512],
                    incomplete_work=True,
                )
                raise
    if not xs:
        raise ValueError("no unfinished training frontiers; no replacement tasks")
    return torch.tensor(xs, dtype=torch.float32), torch.tensor(ys, dtype=torch.float32)


def fit(x, y, mode, *, steps=200):
    if (
        mode not in TRAINING_MODES
        or x.ndim != 2
        or x.shape[1] != DIMENSION
        or not 1 <= len(x) <= 256
        or y.shape != (len(x), 2)
        or x.dtype != torch.float32
        or y.dtype != x.dtype
        or x.device.type != "cpu"
        or y.device.type != "cpu"
        or x.requires_grad
        or y.requires_grad
        or not torch.isfinite(x).all()
        or not torch.isfinite(y).all()
        or (y < 0).any()
        or (y > 1).any()
        or not ((y[:, 0] == 0) | (y[:, 0] == 1)).all()
        or type(steps) is not int
        or not 1 <= steps <= 200
        or torch.is_inference_mode_enabled()
    ):
        raise ValueError("invalid observed-return training batch")
    started = time.perf_counter()
    inputs = x.clone()
    if mode == "root_only":
        inputs[:, 15:] = 0
    order = (
        torch.randperm(len(y), generator=torch.Generator().manual_seed(827))
        if mode == "shuffled"
        else torch.arange(len(y))
    )
    target = y[order]
    model = make_head()
    before = model_digest(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.01)
    losses = []
    for _ in range(steps):
        logits = model(inputs)
        loss = nn.functional.binary_cross_entropy_with_logits(
            logits[:, 0], target[:, 0]
        ) + nn.functional.mse_loss(torch.sigmoid(logits[:, 1]), target[:, 1])
        if not torch.isfinite(loss):
            raise ValueError("nonfinite resumed-return loss")
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    if not all(torch.isfinite(p).all() for p in model.parameters()):
        raise ValueError("nonfinite fitted head")
    model.eval().requires_grad_(False)
    return model, dict(
        mode=mode,
        before=before,
        after=model_digest(model),
        examples=len(x),
        steps=steps,
        parameters=sum(p.numel() for p in model.parameters()),
        target_permutation=order.tolist(),
        initial_loss=losses[0],
        final_loss=losses[-1],
        input_digest=digest(inputs.tolist()),
        target_digest=digest(target.tolist()),
        seconds=time.perf_counter() - started,
        probability_calibrated=False,
    )


@torch.no_grad()
def choose(model, context, remaining, mode):
    if (
        mode not in (*TRAINING_MODES, "cost_blind")
        or model is None
        or model.training
        or any(p.requires_grad for p in model.parameters())
        or len(context) != DIMENSION
        or type(remaining) is not int
        or not 1 <= remaining <= 1024
        or not all(math.isfinite(v) for v in context)
    ):
        raise ValueError("frozen frontier head and finite observable context required")
    x = torch.tensor([context], dtype=torch.float32)
    if mode == "root_only":
        x[:, 15:] = 0
    logits = model(x)
    if logits.shape != (1, 2) or not torch.isfinite(logits).all():
        raise ValueError("wrong continuation model schema or nonfinite prediction")
    probability, fraction = torch.sigmoid(logits[0]).tolist()
    expected = remaining * fraction
    utility = probability - (0 if mode == "cost_blind" else UNIT_COST * expected)
    return dict(
        action="resume" if utility > 0 else "stop",
        probability=probability,
        expected_additional_successors=expected,
        remaining=remaining,
        continuation_utility=utility,
        stop_utility=0.0,
        mode=mode,
        observed_digest=digest(context),
        model_input_digest=digest(x[0].tolist()),
        probability_calibrated=False,
    )


def episode(numbers, total, arm, head=None, *, event_sink):
    """Single stop/resume decision; success is necessarily a subset of direct search."""
    state_features(numbers, total, 0)
    if arm not in ARMS or not callable(event_sink):
        raise ValueError("registered arm and event sink required")
    started = time.perf_counter()
    session = SearchSession(numbers, 24, "heuristic_search")
    row = dict(
        numbers=list(numbers),
        query_id=digest(numbers),
        budget=total,
        arm=arm,
        status="started",
        controller_calls=0,
        decision=dict(action="none"),
    )
    try:
        first = advance_logged(
            session, total if arm == "direct" else total // 4, event_sink
        )
        row["probe"] = first
        if arm != "direct" and not first["found"] and first["paused"]:
            context = observe(session, total)
            row["context"] = context
            remaining = total - first["costs"]["generated_successors"]
            if arm in ("resume", "probe_stop"):
                decision = dict(
                    action="resume" if arm == "resume" else "stop", remaining=remaining
                )
            else:
                row["controller_calls"] = 1
                decision = choose(head, context, remaining, arm)
            row["decision"] = decision
            event_sink(
                deepcopy(dict(event="decision", decision=decision, context=context))
            )
            if decision["action"] == "resume":
                advance_logged(session, total, event_sink)
        row["status"] = "completed"
    except Exception as exc:
        row.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:512])
    final = session.receipt()
    row.update(
        found=final["found"],
        proof=final["proof"],
        costs=final["costs"],
        final=final,
        seconds=time.perf_counter() - started,
        costs_may_be_incomplete=row["status"] != "completed",
        certified_impossible=False,
        utility=(
            float(final["found"]) - UNIT_COST * final["costs"]["generated_successors"]
            if row["status"] == "completed"
            else None
        ),
    )
    return row
