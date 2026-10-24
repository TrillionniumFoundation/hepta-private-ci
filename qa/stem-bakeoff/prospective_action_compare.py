"""Paired fixed-seed contrasts with whole-bug and whole-project resampling.

Each condition supplies name, source_ids, group_ids, labels,
probabilities_by_seed and rankings_by_seed. Seed keys are exactly7/17/29;
probabilities are[N,2] in the declared source order. A ranking-only control uses
empty labelled arrays and probabilities_by_seed=None, never invented probabilities.
Ranking reports are the unchanged outputs of prospective_action_ranking.
"""

import hashlib

import numpy as np

from cell_learning_models import canonical
from prospective_action_ranking import SCHEMA as RANKING_SCHEMA, _validate_registry


SEEDS, REPLICATES, BOOTSTRAP_SEED = (7, 17, 29), 2000, 104729
METRICS = ("balanced_accuracy", "nll", "known_positive_top1")
CONDITION_KEYS = {"name", "source_ids", "group_ids", "labels", "probabilities_by_seed", "rankings_by_seed"}


def _condition(value, groups, registry_sha, truth):
    if set(value) != CONDITION_KEYS or type(value["name"]) is not str or not 1 <= len(value["name"].encode()) <= 512:
        raise ValueError("explicit bounded comparison condition required")
    ids, group_ids, labels = list(value["source_ids"]), list(value["group_ids"]), np.asarray(value["labels"])
    if (len(ids) != len(set(ids)) or len(ids) > 16384 or len(group_ids) != len(ids) or labels.shape != (len(ids),)
            or (len(ids) and labels.dtype.kind not in "iu") or np.any((labels != 0) & (labels != 1))):
        raise ValueError("unique valid-labelled source rows required")
    for source, group, label in zip(ids, group_ids, labels):
        if source not in truth or truth[source] != (group, int(label)):
            raise ValueError("probability source/group/label differs from the frozen proposal registry")
    probabilities = value["probabilities_by_seed"]
    if probabilities is None:
        if ids:
            raise ValueError("ranking-only controls cannot supply invented labelled probability rows")
        arrays = None
    else:
        if not isinstance(probabilities, dict) or set(probabilities) != set(SEEDS):
            raise ValueError("exact fixed prediction seeds7/17/29 required")
        arrays = {}
        for seed in SEEDS:
            p = np.asarray(probabilities[seed], dtype=np.float64)
            if (p.shape != (len(ids), 2) or not np.isfinite(p).all() or np.any((p < 0) | (p > 1))
                    or not np.allclose(p.sum(axis=1), 1, atol=1e-12, rtol=0)):
                raise ValueError("finite binary probabilities in declared source order required")
            arrays[seed] = p.copy()
    rankings = value["rankings_by_seed"]
    if not isinstance(rankings, dict) or set(rankings) != set(SEEDS):
        raise ValueError("exact fixed-seed all-proposal rankings required")
    expected = {g["group_id"]: g for g in groups}
    top1, recommending, unknown = [], [], []
    for seed in SEEDS:
        report = rankings[seed]
        if (report["schema"] != RANKING_SCHEMA or report["proposal_registry_sha256"] != registry_sha
                or report["proposed_groups"] != len(groups) or report["group_ids"] != list(expected)
                or len(report["group_records"]) != len(groups)):
            raise ValueError("paired ranking must retain exactly the same complete proposal registry")
        hits, accepted, uncertain = [], [], []
        for record, group in zip(report["group_records"], groups, strict=True):
            if (record["group_id"] != group["group_id"] or record["project"] != group["project"]
                    or record["proposed_actions"] != group["actions"]):
                raise ValueError("ranking group/action outcomes differ from frozen proposals")
            decision = record["top_k"]["1"]
            actions = {a["key"]: a for a in group["actions"]}
            selected = decision["recommended_action_keys"]
            if len(selected) > 1 or any(key not in actions for key in selected):
                raise ValueError("invalid first proposed recommendation")
            hit = bool(selected and actions[selected[0]]["label"] == 1)
            unclear = bool(selected and actions[selected[0]]["label"] is None)
            if (decision["known_positive_hit"] != hit or decision["abstained"] != (not selected)
                    or decision["unknown_selections"] != int(unclear)):
                raise ValueError("ranking outcome metrics do not reproduce first recommendation")
            hits.append(hit); accepted.append(bool(selected)); uncertain.append(unclear)
        top1.append(hits); recommending.append(accepted); unknown.append(uncertain)
    fingerprint = hashlib.sha256(canonical([value["name"], ids, group_ids, labels.tolist(), rankings]))
    if arrays is not None:
        for seed in SEEDS:
            fingerprint.update(canonical([seed, arrays[seed].dtype.str, arrays[seed].shape]))
            fingerprint.update(arrays[seed].tobytes())
    return {"name": value["name"], "source_ids": ids, "group_ids": group_ids, "labels": labels,
        "probabilities": arrays, "top1": np.mean(top1, axis=0), "recommending": np.mean(recommending, axis=0),
        "unknown_selected": np.mean(unknown, axis=0), "sha256": fingerprint.hexdigest()}


def _sufficient(condition, common, groups, truth):
    lookup, group_index = {s: i for i, s in enumerate(condition["source_ids"])}, {g["group_id"]: i for i, g in enumerate(groups)}
    source_groups = np.asarray([group_index[truth[s][0]] for s in common], dtype=int)
    labels = np.asarray([truth[s][1] for s in common], dtype=int)
    counts = np.bincount(source_groups, minlength=len(groups))
    support, correct, nll = np.zeros((len(groups), 2)), np.zeros((len(groups), 2)), np.zeros(len(groups))
    if common:
        weights = 1/counts[source_groups]
        np.add.at(support, (source_groups, labels), weights)
        indices = [lookup[s] for s in common]
        for seed in SEEDS:
            p = condition["probabilities"][seed][indices]
            np.add.at(correct, (source_groups, labels), weights*(p.argmax(axis=1) == labels)/len(SEEDS))
            np.add.at(nll, source_groups, -weights*np.log(np.clip(p[np.arange(len(labels)), labels], 1e-15, 1))/len(SEEDS))
    return {"support": support, "correct": correct, "nll": nll, "valid_groups": (counts > 0).astype(float),
            "top1": condition["top1"], "row_counts": counts}


def _statistics(stats, multiplicities):
    support, correct = multiplicities @ stats["support"], multiplicities @ stats["correct"]
    recalls = np.full(support.shape, np.nan)
    np.divide(correct, support, out=recalls, where=support > 0)
    denominator = multiplicities @ stats["valid_groups"]
    nll = np.full(len(multiplicities), np.nan)
    np.divide(multiplicities @ stats["nll"], denominator, out=nll, where=denominator > 0)
    return {"balanced_accuracy": recalls.mean(axis=1), "nll": nll,
            "known_positive_top1": (multiplicities @ stats["top1"])/multiplicities.sum(axis=1)}


def _interval(left, right):
    differences = left-right
    valid = np.isfinite(differences)
    return {"ci95": np.quantile(differences[valid], [.025, .975]).tolist() if valid.any() else None,
        "valid_replicates": int(valid.sum()), "unavailable_replicates": int((~valid).sum()),
        "unavailable_policy": "missing effective class or no common valid group stays unavailable; never zero-filled"}


def compare_action_conditions(left, right, *, proposal_registry, expected_group_ids):
    """Report left-minus-right contrasts; do not select a model from these scores."""
    groups, _ = _validate_registry(proposal_registry, expected_group_ids)
    registry_sha = hashlib.sha256(canonical(proposal_registry)).hexdigest()
    truth = {a["source_id"]: (g["group_id"], a["label"]) for g in groups for a in g["actions"]
             if a["source_id"] is not None and a["label"] is not None}
    first, second = (_condition(value, groups, registry_sha, truth) for value in (left, right))
    common = sorted(set(first["source_ids"]) & set(second["source_ids"]))
    a, b = (_sufficient(value, common, groups, truth) for value in (first, second))
    point_a, point_b = (_statistics(value, np.ones((1, len(groups)))) for value in (a, b))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    bug_counts = rng.multinomial(len(groups), np.full(len(groups), 1/len(groups)), size=REPLICATES)
    boot_a, boot_b = (_statistics(value, bug_counts) for value in (a, b))
    projects = sorted({g["project"] for g in groups})
    cluster = None
    if len(projects) >= 2:
        project_counts = rng.multinomial(len(projects), np.full(len(projects), 1/len(projects)), size=REPLICATES)
        memberships = [projects.index(g["project"]) for g in groups]
        cluster = [_statistics(value, project_counts[:, memberships]) for value in (a, b)]
    contrasts = {}
    for metric in METRICS:
        pa, pb = point_a[metric][0], point_b[metric][0]
        contrasts[metric] = {"left": float(pa) if np.isfinite(pa) else None, "right": float(pb) if np.isfinite(pb) else None,
            "difference": float(pa-pb) if np.isfinite(pa-pb) else None,
            "whole_bug_bootstrap": _interval(boot_a[metric], boot_b[metric]),
            "project_cluster_bootstrap": _interval(cluster[0][metric], cluster[1][metric]) if cluster else None}
    common_groups = [g["group_id"] for i, g in enumerate(groups) if a["row_counts"][i]]
    return {"schema": "hepta.prospective-action-paired-comparison.v1", "left": first["name"], "right": second["name"],
        "direction": "left minus right; higher BA/top1 and lower NLL favor left", "contrasts": contrasts,
        "proposal_registry_sha256": registry_sha, "left_input_sha256": first["sha256"], "right_input_sha256": second["sha256"],
        "support": {"proposed_groups": len(groups), "proposed_group_ids": [g["group_id"] for g in groups],
            "projects": projects, "project_count": len(projects), "common_valid_rows": len(common),
            "common_valid_source_ids": common, "common_valid_groups": len(common_groups), "common_valid_group_ids": common_groups,
            "left_valid_rows": len(first["source_ids"]), "right_valid_rows": len(second["source_ids"]),
            "left_valid_groups": len(set(first["group_ids"])), "right_valid_groups": len(set(second["group_ids"])),
            "left_rows_outside_common": len(first["source_ids"])-len(common),
            "right_rows_outside_common": len(second["source_ids"])-len(common),
            "common_weighted_class_mass": a["support"].sum(axis=0).tolist(),
            "common_valid_rows_by_project": {p: int(sum(a["row_counts"][i] for i, g in enumerate(groups) if g["project"] == p)) for p in projects},
            "left_mean_recommending_groups": float(first["recommending"].sum()),
            "right_mean_recommending_groups": float(second["recommending"].sum()),
            "left_mean_unknown_selection_groups": float(first["unknown_selected"].sum()),
            "right_mean_unknown_selection_groups": float(second["unknown_selected"].sum()),
            "probability_scope": "common valid source rows; each bug total1 within that common support",
            "top1_scope": "all proposed groups; unavailable or uninformative recommendations remain in denominator"},
        "bootstrap": {"replicates": REPLICATES, "seed": BOOTSTRAP_SEED, "fixed_fit_seeds": list(SEEDS),
            "seed_treatment": "score each fixed fit, then average inside every paired replicate; seeds are not independent units",
            "source_group_unit": "whole bug, retaining all its common action rows and all ranking decisions",
            "project_cluster_unit": "resample whole projects; retain every bug of each sampled project; no within-project independence claim",
            "project_cluster_status": "available" if cluster else "unavailable_fewer_than_two_projects",
            "project_limit": "five external projects in the intended study; cluster intervals remain limited and unstable at that count",
            "percentile_method": "2.5/97.5 percentiles of finite paired differences, no multiple-comparison correction",
            "joint_draws": "identical multiplicities for both conditions and all fixed seeds; bug draws then project draws"},
        "interpretation": "descriptive fixed contrasts; no best model/task/seed selection or qualification from these intervals",
        "quality_qualified": False, "authority": "DENY_ALL"}
