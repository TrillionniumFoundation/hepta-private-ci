"""Fixed all-proposal action ranking and recorded-work replay; no fitting.

Scores map source IDs to {score: finite float, eligible: bool}. Learned scores
are positive probabilities; raw Jaccard and command hash are ranking controls.
Unknown outcomes never become negatives. Expected groups include proposals
with no available features or observations.
"""

import hashlib
import math
from numbers import Real

from cell_learning_models import canonical


SCHEMA = "hepta.prospective-action-ranking.v1"
METHODS = ("calibrated_probability", "identifier_jaccard", "command_hash")
TOP_K, POSITIVE_THRESHOLD = (1, 2, 3), .7


def _identifier(value):
    if type(value) is not str or not 1 <= len(value.encode()) <= 512:
        raise ValueError("bounded explicit proposal identities required")
    return value


def _validate_registry(registry, expected_group_ids):
    expected = [_identifier(g) for g in expected_group_ids]
    if not 1 <= len(expected) <= 512 or len(set(expected)) != len(expected):
        raise ValueError("unique complete expected bug-group denominator required")
    by_group, sources, action_count = {}, set(), 0
    for group in registry:
        key, project = _identifier(group["group_id"]), _identifier(group["repo"])
        if key in by_group or group.get("split") != "holdout" or not isinstance(group["actions"], list):
            raise ValueError("unique HOLDOUT proposal groups required")
        if not 0 <= len(group["actions"]) <= 256:
            raise ValueError("bounded action proposals required")
        actions, keys = [], set()
        for proposed in group["actions"]:
            action, source, label = _identifier(proposed["key"]), proposed["source_id"], proposed["label"]
            if action in keys or (label is not None and (type(label) is not int or label not in (0, 1))):
                raise ValueError("unique action keys and binary-or-unknown outcomes required")
            keys.add(action)
            if source is not None:
                _identifier(source)
                if source in sources:
                    raise ValueError("proposal source ID reused across actions")
                sources.add(source)
            wall, commands = proposed["recorded_pair_wall_ns"], proposed["physical_command_executions"]
            observations = proposed.get("complete_command_observations")
            if ((wall is not None and (type(wall) is not int or wall < 0))
                    or (commands is not None and (type(commands) is not int or not 0 <= commands <= 2))
                    or (observations is not None and (type(observations) is not int or not 0 <= observations <= 2))
                    or (commands is not None and observations is not None and observations > commands)):
                raise ValueError("recorded pair work/count must remain measured nonnegative values or unknown")
            actions.append({"key": action, "source_id": source, "label": label,
                "recorded_pair_wall_ns": wall, "observed_commands": commands,
                "physical_command_executions": commands, "complete_command_observations": observations,
                "pair_cost_complete": wall is not None and commands == 2 and observations == 2})
        action_count += len(actions)
        by_group[key] = {"group_id": key, "project": project, "actions": actions}
    if set(by_group) != set(expected) or action_count > 16384:
        raise ValueError("complete expected group set and bounded proposal denominator required")
    return [by_group[key] for key in sorted(expected)], sources


def _decision(ordered, count):
    selected = ordered[:count]
    unknown = [a["key"] for a in selected if a["label"] is None]
    return {"requested_actions": count, "recommended_action_keys": [a["key"] for a in selected],
        "selected_count": len(selected), "known_positive_hit": any(a["label"] == 1 for a in selected),
        "known_positive_selections": sum(a["label"] == 1 for a in selected),
        "known_negative_selections": sum(a["label"] == 0 for a in selected),
        "unknown_selected_keys": unknown, "unknown_selections": len(unknown),
        "abstained": not selected, "recommendation_shortfall": max(0, count-len(selected))}


def _replay(ordered):
    visited, unknown, incomplete, work, commands, observations, hit = [], [], [], 0, 0, 0, False
    for action in ordered:
        visited.append(action["key"])
        if action["label"] is None:
            unknown.append(action["key"])
        if not action["pair_cost_complete"]:
            incomplete.append(action["key"])
        if action["recorded_pair_wall_ns"] is not None:
            work += action["recorded_pair_wall_ns"]
        if action["observed_commands"] is not None:
            commands += action["observed_commands"]
        if action["complete_command_observations"] is not None:
            observations += action["complete_command_observations"]
        if action["label"] == 1:
            hit = True
            break
    return {"full_order": [a["key"] for a in ordered], "replayed_action_keys": visited,
        "known_positive_found": hit, "actions_to_first_known_positive": len(visited) if hit else None,
        "recorded_pair_work_ns": work, "observed_commands_replayed": commands,
        "physical_command_executions_replayed": commands, "complete_command_observations_replayed": observations,
        "unknown_outcome_keys": unknown, "incomplete_pair_cost_keys": incomplete,
        "cost_complete_over_replayed_pairs": not incomplete,
        "recorded_work_is_lower_bound_when_incomplete": bool(incomplete),
        "claim": "counterfactual replay of recorded pair work; not live sequential latency or new execution"}


def _aggregate(decisions, denominator):
    hits = sum(d["known_positive_hit"] for d in decisions)
    return {"proposed_group_denominator": denominator, "known_positive_hit_groups": hits,
        "known_positive_hit_rate": hits/denominator,
        "groups_with_recommendation": sum(not d["abstained"] for d in decisions),
        "abstained_groups": sum(d["abstained"] for d in decisions),
        "selected_actions": sum(d["selected_count"] for d in decisions),
        "known_positive_selections": sum(d["known_positive_selections"] for d in decisions),
        "known_negative_selections": sum(d["known_negative_selections"] for d in decisions),
        "unknown_selections": sum(d["unknown_selections"] for d in decisions),
        "groups_selecting_unknown": sum(bool(d["unknown_selections"]) for d in decisions),
        "recommendation_shortfall": sum(d["recommendation_shortfall"] for d in decisions)}


def rank_actions(proposal_registry, scores_by_source_id, *, method_kind, expected_group_ids):
    """Apply the frozen ranking to the full expected bug-group denominator."""
    if method_kind not in METHODS or not isinstance(scores_by_source_id, dict):
        raise ValueError("explicit ranking method and source-keyed scores required")
    groups, sources = _validate_registry(proposal_registry, expected_group_ids)
    if not set(scores_by_source_id).issubset(sources) or (method_kind == "command_hash" and scores_by_source_id):
        raise ValueError("only proposed source scores permitted; hash control consumes no scores")
    scores = {}
    for source, record in scores_by_source_id.items():
        if (set(record) != {"score", "eligible"} or type(record["eligible"]) is not bool
                or isinstance(record["score"], bool) or not isinstance(record["score"], Real)
                or not math.isfinite(record["score"]) or not 0 <= record["score"] <= 1):
            raise ValueError("finite probability/Jaccard score and explicit boolean eligibility required")
        scores[source] = {"score": float(record["score"]), "eligible": record["eligible"]}
    records = []
    for group in groups:
        actions = group["actions"]
        if method_kind == "command_hash":
            ordered = sorted(actions, key=lambda a: a["key"])
        else:
            eligible = [a for a in actions if a["source_id"] in scores and scores[a["source_id"]]["eligible"]]
            ordered = sorted(eligible, key=lambda a: (-scores[a["source_id"]]["score"], a["key"]))
        chosen = {a["key"] for a in ordered}
        remaining = sorted((a for a in actions if a["key"] not in chosen), key=lambda a: a["key"])
        threshold_order = ([a for a in ordered if scores[a["source_id"]]["score"] >= POSITIVE_THRESHOLD]
                           if method_kind == "calibrated_probability" else None)
        oracle_order = sorted(actions, key=lambda a: (a["label"] != 1, a["key"]))
        records.append({"group_id": group["group_id"], "project": group["project"],
            "proposed_actions": actions, "proposed_action_count": len(actions),
            "known_positive_actions": sum(a["label"] == 1 for a in actions),
            "unknown_outcome_actions": sum(a["label"] is None for a in actions),
            "source_available_actions": sum(a["source_id"] is not None for a in actions),
            "supplied_score_actions": sum(a["source_id"] in scores for a in actions),
            "rankable_actions": len(ordered), "ranked_action_keys": [a["key"] for a in ordered],
            "unscored_appended_keys": [a["key"] for a in remaining],
            "top_k": {str(k): _decision(ordered, k) for k in TOP_K},
            "positive_threshold_recommendation": _decision(threshold_order, 1) if threshold_order is not None else None,
            "full_order_replay": _replay(ordered+remaining),
            "known_positive_oracle": {"top1_upper_bound": any(a["label"] == 1 for a in actions),
                "replay": _replay(oracle_order), "uses_outcome_labels": True,
                "scope": "known-positive success upper bound only; hash ties; replay cost is not a minimum-cost bound"}})
    denominator = len(records)
    return {"schema": SCHEMA, "method_kind": method_kind,
        "proposal_registry_sha256": hashlib.sha256(canonical(proposal_registry)).hexdigest(),
        "scores_sha256": hashlib.sha256(canonical(scores)).hexdigest(),
        "group_ids": [r["group_id"] for r in records], "group_records": records,
        "proposed_groups": denominator, "projects": sorted({r["project"] for r in records}),
        "proposed_actions": sum(r["proposed_action_count"] for r in records),
        "top_k": {str(k): _aggregate([r["top_k"][str(k)] for r in records], denominator) for k in TOP_K},
        "positive_threshold": POSITIVE_THRESHOLD if method_kind == "calibrated_probability" else None,
        "positive_threshold_recommendation": (_aggregate([r["positive_threshold_recommendation"] for r in records], denominator)
            if method_kind == "calibrated_probability" else None),
        "oracle_known_positive_top1_rate": sum(r["known_positive_oracle"]["top1_upper_bound"] for r in records)/denominator,
        "oracle_scope": "uses observed known positives; not deployable and makes no assertion about unknown outcomes",
        "ranking_tie_rule": "frozen command hash ascending", "unknowns_relabelled_negative": False,
        "abstention_counts_as_success": False, "raw_ranking_control_is_calibrated_probability": False,
        "seed_is_independent_case": False, "new_execution_or_fit_performed": False,
        "quality_qualified": False, "authority": "DENY_ALL"}
