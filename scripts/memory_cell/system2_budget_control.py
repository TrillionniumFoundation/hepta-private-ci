"""Budget-conditioned continuation over two FROZEN search policies.

Labels are observed proof success and measured successors, not oracle reachability.
A cheap mandatory probe precedes the one learned continuation decision. The tail
restarts from the root; repeated work is charged. This finite expected-utility
profile is not general NDU, an optimal stopping theorem, or calibrated probability.
"""

from copy import deepcopy
from fractions import Fraction
import time

import torch
from torch import nn

from system2_ablation import model_digest
from system2_verified_search import features, search, validate_task, verify

LIMITS = (256, 1024)
SOLVERS = ("heuristic_search", "value_search")
ARMS = (
    "direct_heuristic",
    "direct_value",
    "probe_stop",
    "probe_heuristic",
    "probe_value",
    "learned",
    "shuffled",
    "cost_blind",
)
UNIT_COST = 0.0001
COUNTERS = (
    "popped_states",
    "generated_successors",
    "critic_examples",
    "verifier_calls",
)


def state_features(numbers, total, spent):
    validate_task(numbers, 24)
    if (
        type(total) is not int
        or total not in LIMITS
        or type(spent) is not int
        or not 0 <= spent < total
    ):
        raise ValueError("registered budget and observed spent successors required")
    return features(tuple(map(Fraction, numbers)), 24) + [
        total / 1024,
        spent / total,
        (total - spent) / 1024,
    ]


def make_head():
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(719)
        return nn.Sequential(nn.Linear(15, 16), nn.Tanh(), nn.Linear(16, 4))


def invoke(numbers, solver, limit, critic, ledger, *, event_sink=None):
    """Journal before execution. An exception is a failure, never a negative label."""
    if (
        solver not in SOLVERS
        or type(limit) is not int
        or not 1 <= limit <= 1024
        or (event_sink is not None and not callable(event_sink))
    ):
        raise ValueError("invalid child policy or budget")
    item = dict(solver=solver, successor_limit=limit, status="started")
    ledger.append(item)
    started = time.perf_counter()
    try:
        if event_sink is not None:
            event_sink(
                dict(
                    phase="child_started",
                    attempt=len(ledger) - 1,
                    execution=deepcopy(item),
                )
            )
        result = search(
            numbers,
            24,
            solver,
            8192,
            critic,
            terminal_policy="eager",
            successor_limit=limit,
        )
        item["result"] = result
        costs = result["costs"]
        if (
            type(result["found"]) is not bool
            or any(type(costs[k]) is not int or costs[k] < 0 for k in COUNTERS)
            or costs["generated_successors"] > limit
            or (result["found"] and not verify(numbers, 24, result["proof"]))
            or (not result["found"] and result["proof"] is not None)
        ):
            raise ValueError("invalid proof or child work receipt")
        item["status"] = "completed"
        return result
    except BaseException as exc:
        item.update(
            status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
        )
        raise
    finally:
        item["invocation_seconds"] = time.perf_counter() - started
        if event_sink is not None:
            event_sink(
                dict(
                    phase="child_" + item["status"],
                    attempt=len(ledger) - 1,
                    execution=deepcopy(item),
                )
            )


def collect_training(tasks, critic, *, ledger=None, event_sink=None):
    """Actual returns, with a caller-owned ledger and optional durable event sink.

    The sink receives detached snapshots before and after every child call. A
    logging error fails closed. The caller owns persistence; this function never
    converts an execution failure to a negative training label. Abrupt process
    termination can leave a started event, not a fabricated completed receipt.
    """
    if (
        not tasks
        or len(tasks) > 128
        or len({tuple(n) for n in tasks}) != len(tasks)
        or (ledger is not None and (not isinstance(ledger, list) or ledger))
        or (event_sink is not None and not callable(event_sink))
    ):
        raise ValueError("bounded unique tasks and empty caller-owned ledger required")
    for numbers in tasks:
        validate_task(numbers, 24)
    rows = [] if ledger is None else ledger
    x, y = [], []
    for numbers in tasks:
        for total in LIMITS:
            row = dict(
                numbers=list(numbers), budget=total, executions=[], status="started"
            )
            rows.append(row)

            def emit(event):
                if event_sink is not None:
                    event_sink(dict(numbers=list(numbers), budget=total, **event))

            try:
                emit(dict(phase="context_started"))
                probe = invoke(
                    numbers,
                    SOLVERS[0],
                    total // 4,
                    critic,
                    row["executions"],
                    event_sink=emit,
                )
                if probe["found"]:
                    row["disposition"] = "probe_succeeded_no_tail_label"
                else:
                    spent = probe["costs"]["generated_successors"]
                    context = state_features(numbers, total, spent)
                    remaining = total - spent
                    tails = [
                        invoke(
                            numbers,
                            a,
                            remaining,
                            critic,
                            row["executions"],
                            event_sink=emit,
                        )
                        for a in SOLVERS
                    ]
                    target = [float(r["found"]) for r in tails] + [
                        r["costs"]["generated_successors"] / remaining for r in tails
                    ]
                    row.update(
                        disposition="observed_fixed_policy_returns",
                        features=context,
                        target=target,
                    )
                    x.append(context)
                    y.append(target)
                row["status"] = "completed"
                emit(dict(phase="context_completed", disposition=row["disposition"]))
            except BaseException as exc:
                row.update(
                    status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
                )
                emit(
                    dict(
                        phase="context_failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:512],
                    )
                )
                raise
    if not x:
        raise ValueError("no observed failed-probe continuation examples")
    return (
        torch.tensor(x, dtype=torch.float32),
        torch.tensor(y, dtype=torch.float32),
        rows,
    )


def training_census(rows, tasks):
    """Known completed child work is a lower bound, not zero for missing work."""
    expected = {(tuple(n), b) for n in tasks for b in LIMITS}
    keys = [(tuple(r["numbers"]), r["budget"]) for r in rows]
    if len(keys) != len(set(keys)) or not set(keys) <= expected:
        raise ValueError("invalid training context census")
    children = [e for r in rows for e in r["executions"]]
    known = [e for e in children if e["status"] == "completed"]
    completed = sum(r["status"] == "completed" for r in rows)
    return dict(
        planned_contexts=len(expected),
        recorded_contexts=len(rows),
        completed_contexts=completed,
        incomplete_contexts=len(rows) - completed,
        not_started_contexts=len(expected) - len(rows),
        usable_targets=sum(
            r.get("status") == "completed" and "target" in r for r in rows
        ),
        attempted_child_calls=len(children),
        completed_child_calls=len(known),
        known_completed_child_costs={
            k: sum(e["result"]["costs"][k] for e in known) for k in COUNTERS
        },
        work_may_be_missing=completed != len(expected) or len(known) != len(children),
        unknown_work_imputed_as_zero=False,
    )


def fit(x, y, *, shuffled=False, steps=200):
    if (
        x.ndim != 2
        or x.shape[1] != 15
        or not 1 <= len(x) <= 256
        or y.shape != (len(x), 4)
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
        or not torch.all((y[:, :2] == 0) | (y[:, :2] == 1))
        or type(steps) is not int
        or not 1 <= steps <= 200
        or type(shuffled) is not bool
        or torch.is_inference_mode_enabled()
    ):
        raise ValueError("invalid observed-return training batch")
    started = time.perf_counter()
    permutation = (
        torch.randperm(len(y), generator=torch.Generator().manual_seed(827))
        if shuffled
        else torch.arange(len(y))
    )
    target = y[permutation]
    model = make_head()
    before = model_digest(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.01)
    losses = []
    for _ in range(steps):
        logits = model(x)
        loss = nn.functional.binary_cross_entropy_with_logits(
            logits[:, :2], target[:, :2]
        ) + nn.functional.mse_loss(torch.sigmoid(logits[:, 2:]), target[:, 2:])
        if not torch.isfinite(loss):
            raise ValueError("nonfinite observed-return objective")
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    if not all(torch.isfinite(p).all() for p in model.parameters()):
        raise ValueError("nonfinite fitted continuation head")
    model.eval().requires_grad_(False)
    return model, dict(
        before=before,
        after=model_digest(model),
        examples=len(x),
        steps=steps,
        parameters=sum(p.numel() for p in model.parameters()),
        shuffled=shuffled,
        target_permutation=permutation.tolist(),
        initial_loss=losses[0],
        final_loss=losses[-1],
        seconds=time.perf_counter() - started,
        calibrated_probability=False,
    )


@torch.no_grad()
def choose(model, context, remaining, *, cost_aware=True):
    if (
        model is None
        or any(p.requires_grad for p in model.parameters())
        or type(remaining) is not int
        or not 1 <= remaining <= 1024
        or len(context) != 15
        or type(cost_aware) is not bool
    ):
        raise ValueError("frozen head and bounded observable context required")
    batch = torch.tensor([context], dtype=torch.float32)
    logits = model(batch)
    if (
        logits.shape != (1, 4)
        or not torch.isfinite(logits).all()
        or not torch.isfinite(batch).all()
    ):
        raise ValueError("invalid budget-value prediction")
    values = torch.sigmoid(logits[0]).tolist()
    success, cost_fraction = values[:2], values[2:]
    work = [remaining * v for v in cost_fraction]
    utilities = [
        p - (UNIT_COST * c if cost_aware else 0.0) for p, c in zip(success, work)
    ]
    # The stop option is exactly zero; prefer it on a zero tie, then the cheap solver.
    index = max(range(2), key=lambda i: (utilities[i], -i))
    action = SOLVERS[index] if utilities[index] > 0 else "stop"
    return dict(
        action=action,
        probability=success,
        expected_successors=work,
        continuation_utility=utilities,
        stop_utility=0.0,
        cost_aware=cost_aware,
        remaining=remaining,
        observable_features=list(context),
        calibrated_probability=False,
    )


def episode(numbers, total, arm, critic, head=None, *, decision_sink=None):
    """A fixed cheap probe followed by one learned decision; no online updates.

    Sunk probe cost is omitted only from the argmax, never from reported utility.
    Tail restart duplicates are paid again. Stop means no proof, NOT impossibility.
    """
    state_features(numbers, total, 0)
    if arm not in ARMS:
        raise ValueError("unknown budget-controller arm")
    started = time.perf_counter()
    ledger = []
    record = dict(
        arm=arm,
        budget=total,
        numbers=list(numbers),
        executions=ledger,
        found=False,
        proof=None,
        status="started",
        controller_calls=0,
    )
    try:
        direct = arm in ("direct_heuristic", "direct_value")
        first_solver = SOLVERS[1] if arm == "direct_value" else SOLVERS[0]
        result = invoke(
            numbers, first_solver, total if direct else total // 4, critic, ledger
        )
        if not result["found"] and not direct:
            spent = result["costs"]["generated_successors"]
            remaining = total - spent
            if arm in ("learned", "shuffled", "cost_blind"):
                record["controller_calls"] = 1
                decision = choose(
                    head,
                    state_features(numbers, total, spent),
                    remaining,
                    cost_aware=arm != "cost_blind",
                )
            else:
                action = {
                    "probe_stop": "stop",
                    "probe_heuristic": SOLVERS[0],
                    "probe_value": SOLVERS[1],
                }[arm]
                decision = dict(action=action, remaining=remaining)
            record["decision"] = decision
            # Persist the decision before its chosen continuation can reveal an outcome.
            if decision_sink is not None:
                decision_sink(decision)
            if decision["action"] != "stop":
                result = invoke(numbers, decision["action"], remaining, critic, ledger)
        record.update(found=result["found"], proof=result["proof"], status="completed")
    except Exception as exc:
        record.update(
            status="failed", error_type=type(exc).__name__, error=str(exc)[:512]
        )
    costs = {
        k: sum(s.get("result", {}).get("costs", {}).get(k, 0) for s in ledger)
        for k in COUNTERS
    }
    if costs["generated_successors"] > total:
        record.update(status="failed", error="total successor budget exceeded")
    record.update(
        costs=costs,
        seconds=time.perf_counter() - started,
        costs_may_be_incomplete=record["status"] == "failed",
        certified_impossible=False,
        utility=(
            float(record["found"]) - UNIT_COST * costs["generated_successors"]
            if record["status"] == "completed"
            else None
        ),
    )
    return record
