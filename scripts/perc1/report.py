"""Offline evaluation: sealed labels enter only after actor traces are complete."""

import base64
import random
from collections import defaultdict
from statistics import mean

from .experiment import actor_context, capture_identity, validate_trace
from .schema import (
    ARMS,
    FAMILIES,
    Cost,
    canonical,
    digest,
    exact,
    integer,
    manifest,
    require,
    sha,
    string,
)

CONTRASTS = {
    "dense": (-0.5, 0.5, -0.5, 0.5),
    "active": (-0.5, -0.5, 0.5, 0.5),
    "interaction": (1, -1, -1, 1),
    "joint": (-1, 0, 0, 1),
}


def evaluation(value, frozen, dataset):
    exact(
        value,
        "schema identity_sha256 rubric_sha256 targets canaries receipt_sha256 cost",
    )
    require(value["schema"] == "perc1.evaluator.v1", "evaluator schema mismatch")
    for key in ("identity_sha256", "rubric_sha256"):
        require(
            digest(value[key]) == frozen["evaluator"][key], "evaluator identity changed"
        )
    for key in ("targets", "canaries"):
        require(
            sha(value[key]) == frozen["evaluator"][key + "_sha256"],
            "sealed evaluator data changed",
        )
    digest(value["receipt_sha256"])
    require(Cost.parse(value["cost"]).evaluation > 0, "missing evaluator cost receipt")
    require(
        type(value["canaries"]) is list
        and all(type(c) is str and len(c) >= 8 for c in value["canaries"]),
        "invalid canaries",
    )
    require(type(value["targets"]) is list, "targets array required")
    result = {}
    for target in value["targets"]:
        exact(target, "episode_id answer fields required_evidence")
        episode = dataset.episodes.get(target["episode_id"])
        require(
            episode is not None and target["episode_id"] not in result,
            "unknown or duplicate evaluator target",
        )
        string(target["answer"])
        require(
            type(target["fields"]) is dict and len(target["fields"]) > 0,
            "critical fields are required",
        )
        for key, val in target["fields"].items():
            string(key)
            string(val)
        ids = target["required_evidence"]
        require(
            type(ids) is list
            and len(ids) == len(set(ids)) > 0
            and set(ids) <= set(episode["source_ids"]),
            "invalid necessary evidence",
        )
        result[target["episode_id"]] = target
    return result


def interval(values):
    ordered = sorted(values)
    return [
        ordered[int(0.025 * (len(ordered) - 1))],
        ordered[int(0.975 * (len(ordered) - 1))],
    ]


def build_report(frozen, dataset, traces, evaluator, bootstrap=2000):
    manifest(frozen, dataset)
    require(integer(bootstrap, 200) <= 10000, "invalid bootstrap count")
    targets = evaluation(evaluator, frozen, dataset)
    seeds = [run["seed"] for run in frozen["controller"]["training_runs"]]
    require(len(seeds) >= 2, "at least two distinct training seed receipts required")
    episodes = [e for e in dataset.episodes.values() if e["split"] == "confirmation"]
    require(
        {e["family"] for e in episodes} == set(FAMILIES),
        "all four task families required",
    )
    expected = {
        (e["id"], seed, arm) for e in episodes for seed in seeds for arm in ARMS
    }
    rows, costs, by_phase, acquired, pending = {}, [], defaultdict(int), set(), 0
    for source in dataset.sources.values():
        dataset.read(source["id"])
    require(type(traces) is list, "traces must be an array")
    for trace in traces:
        audit = validate_trace(trace, frozen, dataset)
        key = (trace["episode_id"], trace["seed"], trace["arm"])
        require(
            key in expected and key not in rows,
            "unpaired, duplicate, or non-confirmation trace",
        )
        require(key[0] in targets, "missing evaluator target")
        target, result = targets[key[0]], trace["answer"]
        visible = canonical(
            actor_context(dataset, dataset.episodes[key[0]], trace["steps"])
        ) + canonical(result)
        visible += b"".join(
            base64.b64decode(s["observation"]["raw_base64"])
            for s in trace["steps"]
            if s["observation"] is not None
        )
        require(
            not any(c.encode() in visible for c in evaluator["canaries"]),
            "teacher/evaluator canary reached actor",
        )
        fidelity = mean(
            result["fields"].get(k) == v for k, v in target["fields"].items()
        )
        required_captures = {
            capture_identity(dataset.sources[i]) for i in target["required_evidence"]
        }
        rows[key] = {
            "task_success": float(result["text"] == target["answer"] and fidelity == 1),
            "critical_fidelity": fidelity,
            "cost": audit["spent"] + audit["pending_reservation"],
            "evidence_recall": len(
                audit["observed_captures"].intersection(required_captures)
            )
            / len(required_captures),
        }
        pending += audit["pending_reservation"]
        acquired.update(audit["observed"])
        costs.append(audit)
        for step in trace["steps"]:
            for phase, amount in step["cost"].items():
                by_phase[phase] += amount
    require(set(rows) == expected, "incomplete paired four-arm matrix")
    groups = sorted({e["group"] for e in episodes})
    group_episodes = {g: [e["id"] for e in episodes if e["group"] == g] for g in groups}
    metrics = ("task_success", "critical_fidelity", "cost", "evidence_recall")
    cells = {
        (g, s, a, m): mean(rows[(e, s, a)][m] for e in group_episodes[g])
        for g in groups
        for s in seeds
        for a in ARMS
        for m in metrics
    }
    means = {
        a: {m: mean(cells[g, s, a, m] for g in groups for s in seeds) for m in metrics}
        for a in ARMS
    }
    rng = random.Random(20261108)
    draws = [
        (rng.choices(groups, k=len(groups)), rng.choices(seeds, k=len(seeds)))
        for _ in range(bootstrap)
    ]
    effects = {}
    for metric in metrics[:3]:
        effects[metric] = {}
        for name, weights in CONTRASTS.items():
            point = sum(weights[i] * means[a][metric] for i, a in enumerate(ARMS))
            samples = [
                mean(
                    sum(weights[i] * cells[g, s, a, metric] for i, a in enumerate(ARMS))
                    for g in gs
                    for s in ss
                )
                for gs, ss in draws
            ]
            effects[metric][name] = {"estimate": point, "ci95": interval(samples)}
    reasons = [
        "Origin-to-view mapping, source authenticity, training independence and billing receipts need independent attestation.",
        "No controlled continuation branches: per-observation terminal causal gain is unmeasured.",
        "No immutable preregistration timestamp or adjusted confirmatory multiple-comparison audit is established.",
    ]
    if frozen["encoder"]["kind"] == "diagnostic_fixture":
        reasons.insert(
            0,
            "Synthetic protocol fixture: features are deterministic shape diagnostics, not learned latents.",
        )
    if any(
        s["uri"].startswith(("synthetic:", "fixture:"))
        for s in dataset.sources.values()
    ):
        reasons.append("Synthetic sources cannot establish real-task qualification.")
    if not evaluator["canaries"]:
        reasons.append("No sealed teacher/evaluator canaries were registered.")
    limits, thresholds_met = frozen["thresholds"], None
    if limits is None:
        reasons.append("Confirmation thresholds were not preregistered.")
    else:
        thresholds_met = (
            len(seeds) >= limits["minimum_training_seeds"]
            and effects["task_success"]["joint"]["ci95"][0]
            >= limits["minimum_task_gain"]
            and effects["critical_fidelity"]["joint"]["ci95"][0]
            >= -limits["maximum_field_regression"]
        )
    if pending:
        reasons.append(
            "Unknown external effects retain reservations; owner reconciliation is outstanding."
        )
    training = sum(
        Cost.parse(r["cost"]).total for r in frozen["controller"]["training_runs"]
    )
    return {
        "schema": "perc1.report.v1",
        "status": "HOLD",
        "structural_validation": "PASS",
        "scientific_qualified": False,
        "manifest_sha256": sha(frozen),
        "source_provenance": "UNATTESTED",
        "independent_training_verified": False,
        "thresholds_met": thresholds_met,
        "hold_reasons": reasons,
        "episodes": len(episodes),
        "source_groups": len(groups),
        "training_seed_receipts": len(seeds),
        "paired_traces": len(rows),
        "arms": means,
        "effects": effects,
        "confidence_method": "95% percentile bootstrap resampling source groups and training seeds, paired across all arms; unadjusted diagnostic intervals",
        "bootstrap_replicates": bootstrap,
        "per_observation_causal_gain": None,
        "cost_metric": "incurred online charges plus unresolved reservations; final unknown cost is not imputed as zero",
        "costs": {
            "online_by_phase": dict(by_phase),
            "online_total": sum(a["spent"] for a in costs),
            "training_total_once": training,
            "evaluation_total_once": Cost.parse(evaluator["cost"]).total,
            "pending_reservations": pending,
        },
    }
