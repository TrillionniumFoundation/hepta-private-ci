"""One-observation value learning over actor-only prefixes (research, advisory).

Paired records complement existing PERC-1 traces; they are not another four-arm
format or execution attestation. Costs use the existing microcredits_v1 ledger.
Declared feature provenance cannot authenticate arbitrary caller-supplied floats.
"""

import math
import random
import time
from pathlib import Path

from .schema import Cost, canonical, digest, exact, identifier, integer, load
from .schema import real, require, sha


def features(value):
    exact(
        value,
        "schema prefix_sha256 task_goal coverage source_repeat remaining_budget uncertainty acquired_latent acquired_receipt_sha256s",
    )
    require(value["schema"] == "perc1.acquisition-features.v1", "wrong feature schema")
    digest(value["prefix_sha256"])
    goal, latent, receipts = (
        value["task_goal"],
        value["acquired_latent"],
        value["acquired_receipt_sha256s"],
    )
    require(type(goal) is list and 1 <= len(goal) <= 16, "invalid goal features")
    require(
        type(latent) is list and len(latent) <= 64, "invalid acquired latent summary"
    )
    require(
        type(receipts) is list and len(receipts) <= 128,
        "invalid acquired receipts",
    )
    for receipt in receipts:
        digest(receipt)
    require(len(set(receipts)) == len(receipts), "duplicate acquired receipts")
    require(not latent or receipts, "latent summary lacks an acquired receipt")
    return (
        [real(x, -1e6, 1e6) for x in goal]
        + [
            real(value["coverage"], 0, 1),
            real(value["source_repeat"], 0, 1),
            math.log1p(integer(value["remaining_budget"])),
            real(value["uncertainty"], 0, 1),
        ]
        + [real(x, -1e6, 1e6) for x in latent]
    )


def paired_label(pair):
    """Validate a controlled prefix pair; return gain and full incremental cost."""
    exact(pair, "schema source_group split candidate_id features without with")
    require(pair["schema"] == "perc1.acquisition-pair.v1", "wrong pair schema")
    identifier(pair["source_group"])
    identifier(pair["candidate_id"])
    require(pair["split"] in ("train", "dev", "confirmation"), "unknown split")
    features(pair["features"])
    costs = []
    for branch in (pair["without"], pair["with"]):
        exact(branch, "prefix_sha256 solver_sha256 inference_seed evidence score cost")
        digest(branch["prefix_sha256"])
        digest(branch["solver_sha256"])
        integer(branch["inference_seed"])
        real(branch["score"], 0, 1)
        evidence = branch["evidence"]
        require(
            type(evidence) is list and len(evidence) <= 129, "invalid evidence list"
        )
        for item in evidence:
            exact(item, "source_id receipt_sha256 capture_sha256")
            identifier(item["source_id"])
            digest(item["receipt_sha256"])
            digest(item["capture_sha256"])
        for key in ("source_id", "receipt_sha256", "capture_sha256"):
            require(
                len({x[key] for x in evidence}) == len(evidence),
                "duplicate/aliased evidence",
            )
        costs.append(Cost.parse(branch["cost"]))
        require(
            costs[-1].training == costs[-1].evaluation == 0,
            "offline costs belong in separate receipts",
        )
    before, after = pair["without"], pair["with"]
    require(
        all(
            before[k] == after[k]
            for k in ("prefix_sha256", "solver_sha256", "inference_seed")
        ),
        "controlled continuation changed",
    )
    require(
        before["prefix_sha256"] == pair["features"]["prefix_sha256"],
        "feature prefix mismatch",
    )
    require(
        pair["features"]["acquired_receipt_sha256s"]
        == [x["receipt_sha256"] for x in before["evidence"]],
        "features include unacquired evidence",
    )
    require(
        len(after["evidence"]) == len(before["evidence"]) + 1
        and after["evidence"][:-1] == before["evidence"],
        "requires exactly one appended observation",
    )
    require(
        after["evidence"][-1]["source_id"] == pair["candidate_id"],
        "candidate receipt mismatch",
    )
    increment = costs[1].total - costs[0].total
    require(
        increment > 0 and costs[1].acquisition > costs[0].acquisition,
        "missing incremental acquisition cost",
    )
    return after["score"] - before["score"], increment


def _solve(matrix, targets):
    """Small ridge system with pivoting; both output columns share the factorization."""
    rows = [a[:] + b[:] for a, b in zip(matrix, targets)]
    size = len(rows)
    for column in range(size):
        pivot = max(range(column, size), key=lambda i: abs(rows[i][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        require(abs(rows[column][column]) > 1e-12, "singular ridge system")
        divisor = rows[column][column]
        rows[column] = [x / divisor for x in rows[column]]
        for i in range(size):
            if i != column:
                factor = rows[i][column]
                rows[i] = [a - factor * b for a, b in zip(rows[i], rows[column])]
    return [[real(row[size + output]) for row in rows] for output in range(2)]


def train_head(
    train_pairs,
    dev_pairs,
    split_groups,
    *,
    feature_extractor_sha256,
    seed=0,
    ridge=1.0,
    cost_value=0.0,
    threshold=0.0,
):
    """Fit only train rows; dev calibrates mean residual and observed cost shortfall.

    Closed-form ridge is deterministic. Changing seed is not an independent
    training replicate. Dev maximum cost residual is diagnostic, not a guarantee.
    """
    started, cpu_started = time.perf_counter_ns(), time.process_time_ns()
    digest(feature_extractor_sha256)
    integer(seed)
    real(ridge, 1e-8, 1e6)
    real(cost_value, 0, 1e6)
    real(threshold, 0, 1)
    exact(split_groups, "train dev confirmation")
    groups = set()
    for values in split_groups.values():
        require(type(values) is list and len(values) > 0, "empty split registry")
        for group in values:
            require(identifier(group) not in groups, "source group crosses splits")
            groups.add(group)
    captures, solvers, identities, rows, labels = {}, set(), set(), [], []
    for split, pairs in (("train", train_pairs), ("dev", dev_pairs)):
        require(type(pairs) is list and 0 < len(pairs) <= 10000, "invalid pair count")
        for pair in pairs:
            label = paired_label(pair)
            require(
                pair["split"] == split and pair["source_group"] in split_groups[split],
                "training/calibration split mismatch",
            )
            identity = sha(pair)
            require(identity not in identities, "duplicate pair")
            identities.add(identity)
            solvers.add(pair["without"]["solver_sha256"])
            for item in pair["with"]["evidence"]:
                capture = item["capture_sha256"]
                require(
                    capture not in captures or captures[capture] == split,
                    "captured content crosses splits",
                )
                captures[capture] = split
            rows.append(features(pair["features"]))
            labels.append(label)
    require(len(solvers) == 1, "continuation solver changed across training records")
    layout = [
        len(train_pairs[0]["features"][k]) for k in ("task_goal", "acquired_latent")
    ]
    require(
        all(
            [len(p["features"][k]) for k in ("task_goal", "acquired_latent")] == layout
            for p in train_pairs + dev_pairs
        ),
        "feature layout changed",
    )
    count, width = len(train_pairs), len(rows[0])
    means = [sum(row[j] for row in rows[:count]) / count for j in range(width)]
    scales = [
        max(
            1e-6,
            math.sqrt(sum((row[j] - means[j]) ** 2 for row in rows[:count]) / count),
        )
        for j in range(width)
    ]
    normalized = [[(v - m) / s for v, m, s in zip(row, means, scales)] for row in rows]
    intercepts = [sum(label[k] for label in labels[:count]) / count for k in range(2)]
    matrix = [
        [
            sum(row[j] * row[k] for row in normalized[:count])
            + (ridge if j == k else 0)
            for k in range(width)
        ]
        for j in range(width)
    ]
    targets = [
        [
            sum(
                row[j] * (label[k] - intercepts[k])
                for row, label in zip(normalized[:count], labels[:count])
            )
            for k in range(2)
        ]
        for j in range(width)
    ]
    coefficients = [[b] + w for b, w in zip(intercepts, _solve(matrix, targets))]
    residuals = [
        [
            label[k]
            - (
                coefficients[k][0]
                + sum(a * b for a, b in zip(row, coefficients[k][1:]))
            )
            for k in range(2)
        ]
        for row, label in zip(normalized[count:], labels[count:])
    ]
    bias = [sum(r[k] for r in residuals) / len(residuals) for k in range(2)]
    receipt = dict(
        schema="perc1.acquisition-training.v1",
        algorithm="deterministic_ridge_v1",
        seed=seed,
        independent_training_replicate=False,
        ridge=ridge,
        feature_extractor_sha256=feature_extractor_sha256,
        module_sha256=sha(Path(__file__).read_bytes()),
        solver_sha256=next(iter(solvers)),
        train_pairs_sha256=sha(train_pairs),
        dev_pairs_sha256=sha(dev_pairs),
        split_registry_sha256=sha(split_groups),
        train_groups_sha256=sha(sorted(split_groups["train"])),
        dev_groups_sha256=sha(sorted(split_groups["dev"])),
        train_count=count,
        dev_count=len(dev_pairs),
        elapsed_ns=time.perf_counter_ns() - started,
        cpu_ns=time.process_time_ns() - cpu_started,
    )
    head = dict(
        schema="perc1.acquisition-head.v1",
        status="HOLD",
        scientific_qualified=False,
        layout=layout,
        means=means,
        scales=scales,
        coefficients=coefficients,
        calibration={
            "bias": bias,
            "cost_underprediction": max(0.0, max(r[1] - bias[1] for r in residuals)),
        },
        cost_value=cost_value,
        threshold=threshold,
        training_receipt=receipt,
    )
    _validate_head(head)
    return head


def _validate_head(head):
    exact(
        head,
        "schema status scientific_qualified layout means scales coefficients calibration cost_value threshold training_receipt",
    )
    require(
        head["schema"] == "perc1.acquisition-head.v1"
        and head["status"] == "HOLD"
        and head["scientific_qualified"] is False,
        "invalid head qualification",
    )
    require(type(head["layout"]) is list and len(head["layout"]) == 2, "invalid layout")
    require(
        1 <= integer(head["layout"][0]) <= 16 and integer(head["layout"][1]) <= 64,
        "invalid layout dimension",
    )
    width = sum(head["layout"]) + 4
    for name in ("means", "scales"):
        require(
            type(head[name]) is list and len(head[name]) == width,
            "invalid normalization",
        )
        for value in head[name]:
            real(value, 1e-12 if name == "scales" else -1e100, 1e100)
    require(
        type(head["coefficients"]) is list and len(head["coefficients"]) == 2,
        "invalid output heads",
    )
    for row in head["coefficients"]:
        require(
            type(row) is list and len(row) == width + 1, "invalid coefficient shape"
        )
        for value in row:
            real(value, -1e100, 1e100)
    calibration = exact(head["calibration"], "bias cost_underprediction")
    require(
        type(calibration["bias"]) is list and len(calibration["bias"]) == 2,
        "invalid calibration",
    )
    for value in calibration["bias"]:
        real(value, -1e100, 1e100)
    real(calibration["cost_underprediction"], 0, 1e100)
    real(head["cost_value"], 0, 1e6)
    real(head["threshold"], 0, 1)
    receipt = exact(
        head["training_receipt"],
        "schema algorithm seed independent_training_replicate ridge feature_extractor_sha256 module_sha256 solver_sha256 train_pairs_sha256 dev_pairs_sha256 split_registry_sha256 train_groups_sha256 dev_groups_sha256 train_count dev_count elapsed_ns cpu_ns",
    )
    require(
        receipt["schema"] == "perc1.acquisition-training.v1"
        and receipt["algorithm"] == "deterministic_ridge_v1"
        and receipt["independent_training_replicate"] is False,
        "invalid training receipt",
    )
    for key, value in receipt.items():
        if key.endswith("sha256"):
            digest(value)
    for key in ("seed", "elapsed_ns", "cpu_ns"):
        integer(receipt[key])
    integer(receipt["train_count"], 1)
    integer(receipt["dev_count"], 1)
    real(receipt["ridge"], 1e-8, 1e6)


def predict(head, public_features):
    _validate_head(head)
    vector = features(public_features)
    require(
        [len(public_features[k]) for k in ("task_goal", "acquired_latent")]
        == head["layout"],
        "feature layout mismatch",
    )
    vector = [(v - m) / s for v, m, s in zip(vector, head["means"], head["scales"])]
    raw = [
        real(w[0] + sum(a * b for a, b in zip(vector, w[1:])) + bias)
        for w, bias in zip(head["coefficients"], head["calibration"]["bias"])
    ]
    return {
        "expected_gain": max(-1.0, min(1.0, raw[0])),
        "expected_cost": max(0.0, raw[1]),
    }


def choose(head, candidates, *, mode="active", seed=0):
    """Suggest one read; all comparators enforce the same caller-owned upper quote.

    Quotes are admission inputs, not learned guarantees. The actual source/budget
    owner must recheck authority, reserve, execute and settle independently.
    """
    _validate_head(head)
    require(mode in ("active", "fixed", "random"), "unknown acquisition policy")
    integer(seed)
    require(type(candidates) is list and len(candidates) <= 256, "invalid candidates")
    admissible, ids, prefixes = [], set(), set()
    for candidate in candidates:
        exact(candidate, "id upper_cost features")
        require(identifier(candidate["id"]) not in ids, "duplicate candidate")
        ids.add(candidate["id"])
        f = candidate["features"]
        features(f)
        prediction = predict(head, f) if mode == "active" else None
        prefixes.add(
            sha(
                {
                    k: f[k]
                    for k in (
                        "prefix_sha256",
                        "remaining_budget",
                        "acquired_receipt_sha256s",
                    )
                }
            )
        )
        upper = integer(candidate["upper_cost"], 1)
        net = (
            (
                prediction["expected_gain"]
                - head["cost_value"] * prediction["expected_cost"]
            )
            if prediction
            else None
        )
        if upper <= f["remaining_budget"] and (
            mode != "active" or net > head["threshold"]
        ):
            admissible.append((candidate["id"], prediction, net))
    require(len(prefixes) <= 1, "candidates do not share an actor prefix/budget")
    selected = None
    if admissible:
        selected = (
            max(admissible, key=lambda x: x[2])
            if mode == "active"
            else (
                random.Random(seed).choice(admissible)
                if mode == "random"
                else admissible[0]
            )
        )
    return dict(
        action="ACQUIRE" if selected else "STOP",
        candidate_id=selected[0] if selected else None,
        prediction=selected[1] if selected else None,
        net_value=selected[2] if selected else None,
        advisory=True,
        scientific_qualified=False,
        status="HOLD",
    )


def save_head(path, head):
    _validate_head(head)
    Path(path).write_bytes(canonical(head) + b"\n")
    return sha(head)


def load_head(path, expected_sha256=None):
    head = load(path)
    _validate_head(head)
    if expected_sha256 is not None:
        require(sha(head) == digest(expected_sha256), "head digest mismatch")
    return head
