#!/usr/bin/env python3
"""Bounded research primitives. Local hashes/seals never confer authority."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat

BASE_COMMIT = "6f7e3e1040fd26ddef6600d6440572c58de1de6e"
COMPUTE_ARMS = ("no_change_serial", "joint_encoder_batch", "shared_features_heads")
NDU_ARMS = ("fixed_budget", "confidence", "deterministic_ndu", "recursive_risk_ndu", "generic_nested_risk")
TASKS = ("new_composition", "temporal_order", "missing_evidence", "wrong_hint", "counterfactual")
MAX_BYTES = 64 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, name, low=-math.inf, high=math.inf):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high, "invalid " + name)
    return float(value)


def integer(value, name, low=0, high=1_000_000):
    require(type(value) is int and low <= value <= high, "invalid " + name)
    return value


def identity(value):
    require(isinstance(value, str) and 0 < len(value) <= 256 and all(ord(c) >= 32 for c in value), "invalid identity")
    return value


def sha(value, length=64):
    require(isinstance(value, str) and len(value) == length and set(value) <= set("0123456789abcdef")
            and set(value) != {"0"}, "invalid nonzero SHA")
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def strict_loads(raw):
    def reject(_):
        raise ValueError("nonfinite JSON constant")
    try:
        result = json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)
        canonical(result)  # Includes overflowing JSON exponents.
        return result
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("malformed JSON") from exc


def read_bytes(path):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink evidence denied")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BYTES, "empty/nonregular/oversized evidence")
        raw = stream.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, "oversized evidence")
    return raw


def read_json(path):
    return strict_loads(read_bytes(path))


def read_jsonl(path):
    lines = read_bytes(path).splitlines()
    require(lines and len(lines) <= 1_000_000 and all(x.strip() for x in lines), "blank/oversized JSONL")
    rows = [strict_loads(line) for line in lines]
    require(all(type(r) is dict for r in rows), "JSONL object rows required")
    return rows


def write_once(path, value):
    raw = canonical(value) + b"\n"
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink destination denied")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    # Does not claim directory fsync, multi-file transaction, or hostile-writer safety.


def write_jsonl_once(path, rows):
    raw = b"".join(canonical(row) + b"\n" for row in rows)
    require(raw and len(raw) <= MAX_BYTES, "empty/oversized output")
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink destination denied")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


class PredictionJournal:
    """Local test-then-learn barrier, NOT an independent clock/observer signature."""
    FORBIDDEN = {"label", "answer", "outcome", "reward", "utility", "correct"}

    def __init__(self, path):
        path = Path(path)
        require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink journal denied")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = path.open("xb")
        self.previous, self.sequence = "0" * 64, 0
        self.pending, self.seen = {}, set()

    @classmethod
    def check_prediction(cls, value):
        if isinstance(value, dict):
            require(not cls.FORBIDDEN.intersection(value), "outcome leaked into prediction")
            for v in value.values():
                cls.check_prediction(v)
        elif isinstance(value, list):
            for v in value:
                cls.check_prediction(v)

    def seal(self, prediction):
        self.check_prediction(prediction)
        key = identity(prediction.get("case_id"))
        require(key not in self.seen, "duplicate prediction")
        body = {"sequence": self.sequence, "previous": self.previous, "prediction": prediction,
                "local_time": datetime.now(timezone.utc).isoformat(), "trusted_clock": False}
        token = digest(body)
        self.stream.write(canonical(dict(body, record_digest=token)) + b"\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.seen.add(key)
        self.pending[key] = token
        self.previous, self.sequence = token, self.sequence + 1
        return token

    def before_label_reveal(self, case_id, token):
        require(case_id in self.pending and isinstance(token, str) and self.pending[case_id] == token,
                "unsealed or already revealed label")
        del self.pending[case_id]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()


def verify_journal(rows):
    previous, seen = "0" * 64, set()
    require(rows, "empty journal")
    for sequence, row in enumerate(rows):
        body = dict(row)
        token = body.pop("record_digest", None)
        require(body.get("sequence") == sequence and body.get("previous") == previous and digest(body) == token,
                "broken journal digest/sequence/parent")
        prediction = body.get("prediction")
        require(type(prediction) is dict, "invalid journal prediction")
        PredictionJournal.check_prediction(prediction)
        key = identity(prediction.get("case_id"))
        require(key not in seen, "duplicate journal case")
        seen.add(key)
        previous = token
    return len(rows)


def probabilities(values):
    require(type(values) is list and 2 <= len(values) <= 4096, "invalid class count")
    p = [number(v, "probability", 0, 1) for v in values]
    require(abs(math.fsum(p) - 1) <= 1e-6, "invalid probability sum")
    return p


def metrics(predictions, labels):
    require(predictions and len(predictions) == len(labels), "prediction coverage missing")
    accuracy, brier, bins = [], [], [[] for _ in range(15)]
    width = len(predictions[0])
    for values, y in zip(predictions, labels):
        p = probabilities(values)
        require(len(p) == width, "class width changed")
        integer(y, "label", 0, width - 1)
        winner = max(range(width), key=p.__getitem__)
        correct = float(winner == y)
        accuracy.append(correct)
        brier.append(sum((v - float(i == y)) ** 2 for i, v in enumerate(p)) / width)
        bins[min(14, int(15 * p[winner]))].append(p[winner] - correct)
    return {"n": len(labels), "accuracy": sum(accuracy) / len(labels),
            "normalized_brier": sum(brier) / len(labels),
            "ece15": sum(abs(sum(group)) for group in bins) / len(labels)}


def quantile(values, p):
    require(values, "empty observations")
    number(p, "quantile", 0, 1)
    x = sorted(number(v, "observation") for v in values)
    t = (len(x) - 1) * p
    i = int(t)
    return x[i] + (t - i) * (x[min(i + 1, len(x) - 1)] - x[i])


def latency(values):
    for x in values:
        number(x, "latency", 0)
    return {"n": len(values), **{f"p{int(q * 100)}_ms": quantile(values, q) for q in (.5, .95, .99)}}


def causal_depth(events):
    require(type(events) is list and 0 < len(events) <= 100000, "missing/oversized trace")
    depths, activations, retries = {}, set(), 0
    for event in events:
        key = identity(event.get("event_id"))
        require(key not in depths, "duplicate event")
        parents = event.get("parents")
        require(type(parents) is list and len(set(parents)) == len(parents), "invalid parents")
        require(all(p in depths for p in parents), "missing/future/cyclic causal parent")
        kind = event.get("kind")
        require(kind in ("cell", "guard", "wait", "retry"), "unknown event kind")
        base = max((depths[p] for p in parents), default=0)
        if kind == "cell":
            activation = identity(event.get("activation_id"))
            require(activation not in activations, "duplicate physical activation")
            activations.add(activation)
        retries += kind == "retry"
        depths[key] = base + (kind == "cell")
    return {"sequential_cell_depth": max(depths.values()), "actual_activations": len(activations),
            "retries": retries, "autograd_depth_inferred": False}


def components(rows):
    """Transitive root-source overlap, not caller-assigned pseudo-independent IDs."""
    parents, owner = list(range(len(rows))), {}
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    for i, row in enumerate(rows):
        sources = row.get("root_source_ids")
        require(type(sources) is list and sources and len(sources) == len(set(sources)), "missing/duplicate root lineage")
        for source in sources:
            identity(source)
            if source in owner:
                parents[root(i)] = root(owner[source])
            else:
                owner[source] = i
    groups = defaultdict(list)
    for i in range(len(rows)):
        groups[root(i)].append(i)
    return list(groups.values())


def paired_interval(rows, candidate, control, *, comparisons=64, draws=40000, seed=20261011, min_groups=30):
    require(rows and len({identity(r.get("case_id")) for r in rows}) == len(rows), "empty/duplicate paired cases")
    integer(comparisons, "multiplicity", 1, 10000)
    integer(draws, "bootstrap draws", 1000, 100000)
    integer(min_groups, "source group floor", 2)
    delta = []
    for row in rows:
        scores = row.get("external_scores", {})
        require(candidate in scores and control in scores, "unpaired external outcomes")
        delta.append(number(scores[candidate], "score", -1, 1) - number(scores[control], "score", -1, 1))
    groups = components(rows)
    means = [sum(delta[i] for i in group) / len(group) for group in groups]
    rng = random.Random(seed)
    boot = [sum(rng.choices(means, k=len(means))) / len(means) for _ in range(draws)]
    tail = .05 / (2 * comparisons)
    lower, upper = quantile(boot, tail), quantile(boot, 1 - tail)
    return {"n_cases": len(rows), "source_components": len(groups), "largest_component": max(map(len, groups)),
            "estimand": "equal_root_source_component_weighted_paired_mean",
            "difference": sum(means) / len(means), "lcb": lower, "ucb": upper,
            "comparisons": comparisons, "bootstrap_draws": draws,
            "tail_resolution_warning": draws * tail < 10,
            "positive_diagnostic": len(groups) >= min_groups and lower > 0,
            "independent_outcome_authenticated": False}


def work_totals(entries):
    """Deduplicate exact shared physical jobs; changed costs under one ID are invalid."""
    require(type(entries) is list, "missing work ledger")
    jobs = {}
    for row in entries:
        key = identity(row.get("physical_work_id"))
        require(row.get("phase") in ("training", "search", "inference", "evaluation", "migration"), "unknown work phase")
        for metric in ("wall_seconds", "cpu_seconds"):
            number(row.get(metric), metric, 0)
        require(key not in jobs or jobs[key] == row, "physical job identity/cost conflict")
        jobs[key] = row
    phases = {p: {"wall_seconds": 0., "cpu_seconds": 0., "jobs": 0}
              for p in ("training", "search", "inference", "evaluation", "migration")}
    for row in jobs.values():
        item = phases[row["phase"]]
        item["jobs"] += 1
        for metric in ("wall_seconds", "cpu_seconds"):
            item[metric] += row[metric]
    return {"phases": phases, "unique_jobs": len(jobs),
            "total_cpu_seconds": sum(x["cpu_seconds"] for x in phases.values()),
            "total_wall_work_seconds": sum(x["wall_seconds"] for x in phases.values()),
            "wall_work_is_not_request_latency": True}


def risk_ce(values, probs, risk):
    require(values and len(values) == len(probs), "invalid finite-scenario law")
    values = [number(x, "value", -1e6, 1e6) for x in values]
    probs = [number(p, "scenario probability", 0, 1) for p in probs]
    require(abs(math.fsum(probs) - 1) < 1e-10, "scenario probabilities do not sum to one")
    risk = number(risk, "risk aversion", 0, 100)
    if risk < 1e-10:
        return math.fsum(p * x for p, x in zip(probs, values))
    terms = [math.log(p) - risk * x for p, x in zip(probs, values) if p > 0]
    anchor = max(terms)
    return -(anchor + math.log(math.fsum(math.exp(x - anchor) for x in terms))) / risk


def recursive_value(tree, root, *, risk, discount=1.):
    """Registered finite acyclic recursive-utility profile; NOT a general FBSDE."""
    number(risk, "risk", 0, 100)
    number(discount, "discount", 0, 1)
    require(type(tree) is dict and 0 < len(tree) <= 256, "invalid bounded control tree")
    values, policy, active = {}, {}, set()
    def solve(key):
        require(key in tree and key not in active, "missing successor or cyclic control tree")
        if key in values:
            return values[key]
        active.add(key)
        node = tree[key]
        if "terminal" in node:
            require("actions" not in node, "terminal has actions")
            value = number(node["terminal"], "terminal", -1e6, 1e6)
        else:
            actions = node.get("actions")
            require(type(actions) is list and 0 < len(actions) <= 256, "missing admissible action set")
            scores = {}
            for action in actions:
                name = identity(action.get("id"))
                require(name not in scores, "duplicate action")
                duration = number(action.get("duration"), "duration", 0, 1e6)
                cost = number(action.get("cost"), "cost", 0, 1e6)
                law = action.get("successors")
                require(type(law) is list and 0 < len(law) <= 256, "missing successor law")
                scores[name] = -cost + discount ** duration * risk_ce(
                    [solve(s["node"]) for s in law], [s["probability"] for s in law], risk)
            policy[key] = min(scores, key=lambda name: (-scores[name], name))
            value = scores[policy[key]]
        active.remove(key)
        values[key] = value
        return value
    return solve(root), policy


def generic_nested_risk(tree, root, *, risk, discount=1.):
    """Independent equivalent recursion: forbid NDU-exclusive branding claims."""
    recursive_value(tree, root, risk=risk, discount=discount)
    budget = [100000]
    def visit(key):
        budget[0] -= 1
        require(budget[0] >= 0, "generic evaluator work bound exceeded")
        node = tree[key]
        if "terminal" in node:
            return float(node["terminal"])
        scores = []
        for a in node["actions"]:
            law = [(s["probability"], visit(s["node"])) for s in a["successors"]]
            if risk < 1e-10:
                result = sum(p * x for p, x in law)
            else:
                anchor = min(x for p, x in law if p > 0)
                result = anchor - math.log(sum(p * math.exp(-risk * (x - anchor)) for p, x in law)) / risk
            scores.append(-a["cost"] + discount ** a["duration"] * result)
        return max(scores)
    return visit(root)


def default_plan():
    return {"schema": "hepta.neuron-four-gate-plan.v1", "source_base": BASE_COMMIT,
            "scope": "research_only", "production_promotion_permitted": False,
            "scales": [64, 256, 1024, 4096], "active_fractions": [.05, .25, 1.],
            "input_repeat_fractions": [0., .5, .9], "task_similarity": ["low", "medium", "high"],
            "compute_repetitions": 3, "compute_arms": list(COMPUTE_ARMS),
            "cell_controls": ["no_change", "same_init_frozen", "learned"],
            "task_families": list(TASKS), "depths": [1, 2, 4, 8, 16], "ndu_arms": list(NDU_ARMS),
            "future_windows": ["future_1", "future_2"], "min_source_groups": 30,
            "planned_comparisons": 64, "bootstrap_draws": 40000, "seed": 20261011,
            "runtime_resource_budget": None, "physical_model_manifests": [],
            "independent_observer_trust": None, "general_fbsde_claimed": False}


def validate_plan(plan):
    reference = default_plan()
    require(type(plan) is dict and set(plan) == set(reference), "unknown/missing critical plan field")
    for key in reference:
        if key not in ("runtime_resource_budget", "physical_model_manifests", "independent_observer_trust"):
            require(type(plan[key]) is type(reference[key]) and canonical(plan[key]) == canonical(reference[key]), "changed preregistered " + key)
    budget = plan["runtime_resource_budget"]
    if budget is not None:
        require(type(budget) is dict and set(budget) == {"max_peak_rss_bytes", "max_request_p99_ms", "min_throughput_rps", "max_cpu_ratio"},
                "invalid resource budget")
        for key, value in budget.items():
            number(value, key, 1e-12)
    require(type(plan["physical_model_manifests"]) is list, "model manifests must be a list")
    return digest(plan)
