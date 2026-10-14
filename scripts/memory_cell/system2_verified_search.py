"""Controlled arithmetic search: legal operations, frozen critics, exact proof check.

No language model or pretrained Encoder is used. Reachability labels come ONLY
from training number-multisets; evaluation solvability is checked after every
prediction is sealed. A reachability critic is NOT an on-policy success estimate
or calibrated NDU continuation. Discounted NDU here is an explicit special case.
"""

import argparse
from fractions import Fraction
from functools import lru_cache
import hashlib
import heapq
import itertools
import json
from pathlib import Path
import time

import torch
from torch import nn

from system2_ablation import model_digest
from finite_tree_bsde import recursive_utility

ARMS = (
    "greedy",
    "breadth_first",
    "heuristic_search",
    "value_search",
    "ndu_value",
    "shuffled_value",
    "flat_ndu",
)
PROTOCOL = dict(
    schema="hepta.system2.verified-arithmetic.v1",
    train_tasks=12,
    evaluation_tasks=24,
    budgets=[64, 256],
    arms=ARMS,
    target=24,
    train_states_per_task=128,
    optimizer_steps=200,
    critic_hidden=16,
    discount=0.98,
    per_step_cost=0.001,
    training_target="existence of a legal completion; not budget-conditioned policy value",
    inputs="explicit rational arithmetic state, not pretrained Encoder representations",
    synthetic_controlled_tasks=True,
    independent_natural_task_evidence=False,
    exact_compute_matched=False,
    production_accepted=False,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate_task(numbers, goal):
    if (
        len(numbers) != 4
        or any(type(n) is not int or not 1 <= n <= 9 for n in numbers)
        or type(goal) is not int
        or not 1 <= goal <= 100
    ):
        raise ValueError("bounded four-integer task required")


def state_key(terms):
    return tuple(sorted((v for v, _ in terms)))


def successors(terms):
    """Combine two disjoint expression trees; postfix leaves name original inputs."""
    for i, j in itertools.combinations(range(len(terms)), 2):
        a, ap = terms[i]
        b, bp = terms[j]
        rest = tuple(term for k, term in enumerate(terms) if k not in (i, j))
        options = [
            (a + b, ap + bp + ("+",)),
            (a * b, ap + bp + ("*",)),
            (a - b, ap + bp + ("-",)),
            (b - a, bp + ap + ("-",)),
        ]
        if b:
            options.append((a / b, ap + bp + ("/",)))
        if a:
            options.append((b / a, bp + ap + ("/",)))
        for value, proof in options:
            yield rest + ((value, proof),)


def verify(numbers, goal, proof):
    """Independent stack evaluator: no eval(), no acceptance from search scores."""
    validate_task(numbers, goal)
    if not isinstance(proof, (tuple, list)) or len(proof) != 7:
        return False
    stack = []
    try:
        for token in proof:
            if token in ("n0", "n1", "n2", "n3"):
                index = int(token[1])
                stack.append((Fraction(numbers[index]), 1 << index))
            elif token in ("+", "-", "*", "/"):
                right, rmask = stack.pop()
                left, lmask = stack.pop()
                if rmask & lmask:
                    return False
                if token == "+":
                    value = left + right
                elif token == "-":
                    value = left - right
                elif token == "*":
                    value = left * right
                else:
                    value = left / right
                stack.append((value, rmask | lmask))
            else:
                return False
        return len(stack) == 1 and stack[0] == (Fraction(goal), 15)
    except (IndexError, ZeroDivisionError, TypeError):
        return False


def features(values, goal):
    vals = sorted(float(v) for v in values)
    gap = min(abs(v - goal) for v in vals)
    total, absolute = sum(vals), sum(abs(v) for v in vals)
    small = min(abs(v) for v in vals)
    return (
        [v / (1 + abs(v)) for v in vals]
        + [0.0] * (4 - len(vals))
        + [
            len(vals) / 4,
            goal / (1 + abs(goal)),
            gap / (1 + gap),
            total / (1 + abs(total)),
            absolute / (1 + absolute),
            small / (1 + small),
            sum(v.denominator == 1 for v in values) / 4,
            sum(v == 0 for v in values) / 4,
        ]
    )


class ExactLabels:
    """Bounded exhaustive reachability, used for training or post-seal diagnostics."""

    def __init__(self):
        self.calls = 0
        self.solve = lru_cache(maxsize=200000)(self._solve)

    def _solve(self, values, goal):
        self.calls += 1
        if self.calls > 200000:
            raise ValueError("exact-label work budget exceeded")
        if len(values) == 1:
            return values[0] == goal
        terms = tuple((v, ()) for v in values)
        return any(self.solve(state_key(child), goal) for child in successors(terms))


def train_critic(tasks, *, shuffled=False, steps=200):
    if not tasks or not 1 <= steps <= 200:
        raise ValueError("bounded nonempty training cohort required")
    started = time.perf_counter()
    labeler = ExactLabels()
    rows = []
    for numbers in tasks:
        validate_task(numbers, 24)
        root = tuple((Fraction(n), ("n" + str(i),)) for i, n in enumerate(numbers))
        pending = [root]
        seen = set()
        while pending and len(seen) < 128:
            terms = pending.pop(0)
            key = state_key(terms)
            if key in seen:
                continue
            seen.add(key)
            rows.append((key, float(labeler.solve(key, 24))))
            if len(terms) > 1:
                pending.extend(successors(terms))
    x = torch.tensor([features(key, 24) for key, _ in rows], dtype=torch.float32)
    y = torch.tensor([label for _, label in rows], dtype=torch.float32)
    if shuffled:
        y = y[torch.randperm(len(y), generator=torch.Generator().manual_seed(827))]
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(719)
        model = nn.Sequential(nn.Linear(12, 16), nn.Tanh(), nn.Linear(16, 1))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01, weight_decay=0.01)
    before = model_digest(model)
    losses = []
    for _ in range(steps):
        logits = model(x).flatten()
        loss = nn.functional.binary_cross_entropy_with_logits(logits, y)
        if not torch.isfinite(loss):
            raise ValueError("nonfinite training loss")
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        losses.append(float(loss.detach()))
    model.eval().requires_grad_(False)
    return model, dict(
        before=before,
        after=model_digest(model),
        steps=steps,
        examples=len(rows),
        positives=float(y.sum()),
        initial_loss=losses[0],
        final_loss=losses[-1],
        label_solver_states=labeler.calls,
        shuffled=shuffled,
        seconds=time.perf_counter() - started,
        state_keys=[[(v.numerator, v.denominator) for v in key] for key, _ in rows],
        trainable_parameter_count=sum(p.numel() for p in model.parameters()),
    )


@torch.no_grad()
def search(
    numbers,
    goal,
    arm,
    budget,
    critic=None,
    *,
    terminal_policy="deferred",
    successor_limit=None,
):
    """No reachability oracle. Eager mode verifies exact terminals upon generation.

    Default deferred behavior preserves the original experiment. An optional
    common successor ceiling counts every yielded child, including duplicates;
    it is not a FLOP budget. Successor generation may compute several rational
    options before yielding: that overhead and exact verification are timed.
    Eager mode never calls the critic on a terminal state. Failed leaves are
    discarded; a proof is accepted only by the independent runtime verifier.
    """
    validate_task(numbers, goal)
    if (
        arm not in ARMS
        or type(budget) is not int
        or not 1 <= budget <= 8192
        or terminal_policy not in ("deferred", "eager")
        or (
            successor_limit is not None
            and (type(successor_limit) is not int or not 1 <= successor_limit <= 65536)
        )
    ):
        raise ValueError("unregistered search or budget")
    if arm in ("value_search", "ndu_value", "shuffled_value") and critic is None:
        raise ValueError("frozen critic required")
    started = time.perf_counter()
    counters = dict(
        popped_states=0, generated_successors=0, critic_examples=0, verifier_calls=0
    )
    generation_exhausted = False
    root = tuple((Fraction(n), ("n" + str(i),)) for i, n in enumerate(numbers))
    queue = [(0.0, 0, root)]
    seen = {state_key(root)}
    serial = 1
    while queue and counters["popped_states"] < budget:
        _, _, terms = heapq.heappop(queue)
        counters["popped_states"] += 1
        if len(terms) == 1:
            counters["verifier_calls"] += 1
            if verify(numbers, goal, terms[0][1]):
                return dict(
                    found=True,
                    proof=terms[0][1],
                    budget_exhausted=False,
                    costs=counters,
                    seconds=time.perf_counter() - started,
                )
            continue
        children = []
        remaining = (
            None
            if successor_limit is None
            else max(0, successor_limit - counters["generated_successors"])
        )
        stream = (
            successors(terms)
            if remaining is None
            else itertools.islice(successors(terms), remaining)
        )
        for child in stream:
            counters["generated_successors"] += 1
            key = state_key(child)
            if key in seen:
                continue
            seen.add(key)
            if terminal_policy == "eager" and len(child) == 1:
                counters["verifier_calls"] += 1
                if verify(numbers, goal, child[0][1]):
                    return dict(
                        found=True,
                        proof=child[0][1],
                        budget_exhausted=False,
                        costs=counters,
                        seconds=time.perf_counter() - started,
                    )
                continue
            children.append(child)
        if (
            successor_limit is not None
            and counters["generated_successors"] >= successor_limit
        ):
            generation_exhausted = True
        if not children:
            continue
        depth = 4 - len(children[0])
        if arm in ("value_search", "ndu_value", "shuffled_value"):
            batch = torch.tensor(
                [features(state_key(c), goal) for c in children], dtype=torch.float32
            )
            scores = torch.sigmoid(critic(batch).flatten())
            if scores.shape != (len(children),) or not torch.isfinite(scores).all():
                raise ValueError("invalid critic output")
            counters["critic_examples"] += len(children)
            values = scores.tolist()
        elif arm == "breadth_first":
            values = [-depth] * len(children)
        elif arm == "flat_ndu":
            values = [0.5] * len(children)
        else:
            values = [
                1 / (1 + min(abs(float(v) - goal) for v, _ in c)) for c in children
            ]
        if arm in ("ndu_value", "flat_ndu"):
            values = [
                recursive_utility([-0.001] * depth, [0.98] * depth, v)[0]
                for v in values
            ]
        if arm == "greedy":
            best = max(range(len(children)), key=lambda i: values[i])
            children, values = [children[best]], [values[best]]
        for child, value in zip(children, values, strict=True):
            heapq.heappush(queue, (-value, serial, child))
            serial += 1
    return dict(
        found=False,
        proof=None,
        budget_exhausted=bool(queue) or generation_exhausted,
        costs=counters,
        seconds=time.perf_counter() - started,
    )


def run(output):
    output.mkdir(exist_ok=False, parents=True)
    catalogue = sorted(
        itertools.combinations_with_replacement(range(1, 10), 4),
        key=lambda n: digest(("verified-search-v1", n)),
    )
    training, evaluation = catalogue[:12], catalogue[12:36]
    plan = PROTOCOL | dict(
        training=training,
        evaluation=evaluation,
        task_multisets_disjoint=True,
        intermediate_states_may_overlap=True,
        new_encoder_reader_calls=0,
    )
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    models, receipts = {}, {}
    for key, shuffled in (("value", False), ("shuffled", True)):
        models[key], receipts[key] = train_critic(training, shuffled=shuffled)
    from safetensors.torch import save_file

    for key, model in models.items():
        save_file(model.state_dict(), str(output / (key + ".safetensors")))
    (output / "training.json").write_text(json.dumps(receipts, indent=2) + "\n")
    seals = {k: model_digest(m) for k, m in models.items()}
    records = []
    for numbers in evaluation:
        for budget in plan["budgets"]:
            for arm in ARMS:
                row = dict(
                    numbers=numbers, query_id=digest(numbers), arm=arm, budget=budget
                )
                started = time.perf_counter()
                try:
                    result = search(
                        numbers,
                        24,
                        arm,
                        budget,
                        models["shuffled" if arm == "shuffled_value" else "value"],
                    )
                    row.update(result, status="completed")
                except Exception as exc:
                    row.update(
                        status="failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:512],
                        seconds=time.perf_counter() - started,
                    )
                records.append(row)
                with (output / "predictions.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, allow_nan=False) + "\n")
                    stream.flush()
    raw = (output / "predictions.jsonl").read_bytes()
    answer_sha = hashlib.sha256(raw).hexdigest()
    (output / "prediction-seal.json").write_text(
        json.dumps(dict(sha256=answer_sha, scoring_started=False)) + "\n"
    )
    if seals != {k: model_digest(m) for k, m in models.items()}:
        raise ValueError("evaluation mutated frozen critic")
    labeler = ExactLabels()
    possible = {
        digest(n): labeler.solve(tuple(Fraction(v) for v in n), 24) for n in evaluation
    }
    for row in records:
        valid = row.get("found", False) and verify(row["numbers"], 24, row["proof"])
        if row.get("found", False) and not valid:
            raise ValueError("search exported an invalid arithmetic proof")
        row.update(verified_solution=bool(valid), solvable=possible[row["query_id"]])
    summaries = {}
    for budget in plan["budgets"]:
        summaries[str(budget)] = {}
        for arm in ARMS:
            group = [r for r in records if r["arm"] == arm and r["budget"] == budget]
            summaries[str(budget)][arm] = dict(
                planned=len(group),
                failed=sum(r["status"] == "failed" for r in group),
                valid_solutions=sum(r["verified_solution"] for r in group),
                solvable_tasks=sum(r["solvable"] for r in group),
                seconds=sum(r["seconds"] for r in group),
                measured_costs={
                    name: sum(r.get("costs", {}).get(name, 0) for r in group)
                    for name in (
                        "popped_states",
                        "generated_successors",
                        "critic_examples",
                        "verifier_calls",
                    )
                },
                failed_costs_may_be_incomplete=any(
                    r["status"] == "failed" for r in group
                ),
            )
    summary = plan | dict(
        recorded=len(records),
        planned=24 * 2 * len(ARMS),
        results=summaries,
        prediction_sha256=answer_sha,
        evaluation_oracle_states=labeler.calls,
        reasoning_emergence_established=False,
        ndu_utility_calibrated=False,
    )
    (output / "scored.json").write_text(
        json.dumps(records, indent=2, allow_nan=False) + "\n"
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    if (
        hashlib.sha256((output / "predictions.jsonl").read_bytes()).hexdigest()
        != answer_sha
    ):
        raise ValueError("scoring modified original proofs")
    if any(r["status"] == "failed" for r in records):
        raise RuntimeError("failed searches retained in full census")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print(json.dumps(run(parser.parse_args().output)))
