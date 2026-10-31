"""Pure descriptive reducers for already admitted, complete B/C deployment paths.

This module does not admit a directory, decode a checkpoint, import a numerical
runtime, fit a head, execute a model or calculate a counterfactual action value.
Its caller must first verify the separately registered source and complete-study
artifact gate. Hash equality is interpreted only within the original hash recipe.
"""

from collections import Counter
from itertools import product
import math
import re

B_SEEDS = (17, 29, 43)
B_METHODS = ("ordinary", "field12", "full_current_state", "history6", "fixed_taper")
BASELINES = {17: 2, 29: 3, 43: 3}
C_MODES = ("ordinary", "dual")
COMPONENTS = ("parameters", "optimizer")
MULTIPLIERS = (0.0, 0.25, 1.0, 2.0)
B_SECTIONS = set(COMPONENTS) | {
    "buffers",
    "gradients",
    "rng",
    "immutable",
    "remaining_schedule",
    "cursor",
}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value):
    need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
        "Invalid state identity",
    )
    return value


def identities(value):
    need(
        type(value) is dict and set(value) == set(COMPONENTS),
        "Component identity population differs",
    )
    return {key: sha(value[key]) for key in COMPONENTS}


def population(paths, fields, expected):
    need(
        type(paths) is list and len(paths) == len(expected),
        "Incomplete fixed path population",
    )
    result = {}
    for path in paths:
        key = tuple(path[field] for field in fields)
        types = tuple(type(value) for value in next(iter(expected)))
        need(
            tuple(type(value) for value in key) == types
            and key in expected
            and key not in result,
            "Duplicate or unregistered path",
        )
        need(
            type(path["trace"]) is list and len(path["trace"]) == 6,
            "Incomplete six-decision trace",
        )
        result[key] = path
    need(set(result) == expected, "Fixed path population differs")
    return result


def transaction(row, index, baseline, stage, schedule):
    choice, receipt = row["choice"], row["transaction"]
    action = receipt["action_index" if stage == "B" else "action"]
    grain = 48 if stage == "B" else 16
    need(
        type(row["decision"]) is int and row["decision"] == index,
        "Decision order differs",
    )
    need(type(action) is int and action in range(4), "Invalid action")
    need(
        type(choice["chosen_action"]) is int
        and choice["chosen_action"] == action
        and type(choice["override"]) is bool
        and choice["override"] == (action != baseline),
        "Requested action and override label differ",
    )
    need(
        receipt["start"] == grain * index
        and receipt["end"] == grain * (index + 1)
        and receipt["schedule_id" if stage == "B" else "schedule"] == schedule
        and receipt["multiplier"] == MULTIPLIERS[action],
        "Registered clock, tape or multiplier differs",
    )
    need(
        type(receipt["accepted"]) is bool
        and type(receipt["guard_delta"]) in (int, float)
        and math.isfinite(receipt["guard_delta"])
        and receipt["accepted"] == (receipt["guard_delta"] >= 0),
        "Original guard receipt differs",
    )
    need(
        receipt["clock_advances_on_rejection" if stage == "B" else "clock_advances"]
        is True,
        "Registered clock advancement is missing",
    )
    if stage == "B":
        need(
            receipt["logical_clock"] == receipt["end"]
            and receipt["remaining_steps"] == 288 - receipt["end"],
            "B continuation clock differs",
        )
    convert = identities if stage == "B" else sha
    before, candidate, after = (
        convert(receipt[key]) for key in ("before", "candidate", "after")
    )
    need(
        after == (candidate if receipt["accepted"] else before),
        "Committed state or rollback differs",
    )
    need(
        action != 0 or before == after, "Zero action changed registered committed state"
    )
    fallback = choice.get("fallback_reason")
    need(fallback is None or type(fallback) is str, "Malformed fallback reason")
    if "predicted_advantages" in choice:
        scores = choice["predicted_advantages"]
        need(
            type(scores) is list
            and len(scores) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in scores)
            and scores[baseline] == 0,
            "Nonfinite scores or mislabeled head baseline",
        )
    return {
        "clock": receipt["end"],
        "action": action,
        "requested_override": choice["override"],
        "accepted_override": choice["override"] and receipt["accepted"],
        "guard_rejected": not receipt["accepted"],
        "fallback_reason": fallback,
        "before": before,
        "candidate": candidate,
        "after": after,
    }


def counts(decisions):
    keys = set.intersection(*(set(row) for row in decisions))
    result = {
        key: sum(row[key] for row in decisions)
        for key in sorted(keys)
        if all(type(row[key]) is bool for row in decisions)
    }
    result["fallback_reasons"] = dict(
        sorted(
            Counter(
                row["fallback_reason"]
                for row in decisions
                if row["fallback_reason"] is not None
            ).items()
        )
    )
    result["decisions"] = len(decisions)
    return result


def phase_result(stage, rows, group_key, scope):
    groups = {}
    for group in sorted({row[group_key] for row in rows}):
        selected = [row for row in rows if row[group_key] == group]
        groups[group] = {
            "paths": len(selected),
            **counts([decision for row in selected for decision in row["decisions"]]),
        }
    return {
        "stage": stage,
        "paths": rows,
        "counts_by_" + group_key: groups,
        "path_population": len(rows),
        "decision_population": 6 * len(rows),
        "scientific_admission_performed_here": False,
        "activity_scope": scope,
        "deployment_action_regret": "not_identifiable_from_selected_actions",
        "guard_delta_is_counterfactual_advantage": False,
        "benefit_or_adoption": "not_assessed",
        "paired_difference_is_causal_credit_for_current_decision": False,
        "new_training_scoring_refitting": False,
        "new_bootstrap_or_threshold": False,
        "new_independent_samples": 0,
    }


def audit_b(paths):
    """Validate all 240 paths and distinguish actual commits from paired divergence."""
    indexed = population(
        paths,
        ("seed", "schedule_id", "method"),
        set(product(B_SEEDS, range(106000, 106016), B_METHODS)),
    )
    parsed, result = {}, []
    for key, path in indexed.items():
        seed, schedule, method = key
        need(
            path["id"] == f"seed-{seed}-schedule-{schedule}-{method}",
            "B path identity differs",
        )
        rows = []
        for index, row in enumerate(path["trace"]):
            value = transaction(row, index, BASELINES[seed], "B", schedule)
            sha(row["before"])
            if method in ("ordinary", "fixed_taper"):
                action = (
                    BASELINES[seed]
                    if method == "ordinary"
                    else [BASELINES[seed], BASELINES[seed], 2, 1, 1, 0][index]
                )
                need(value["action"] == action, "B fixed control policy differs")
            if rows:
                need(
                    value["before"] == rows[-1]["after"],
                    "B transaction entry chain differs",
                )
            state = row["state"]
            need(
                set(state["components"]) == B_SECTIONS,
                "B physical state component population differs",
            )
            for digest in state["components"].values():
                sha(digest)
            sha(state["dynamics"])
            sha(state["controller_history"])
            rows.append(value)
        parsed[key] = rows
    for key, path in indexed.items():
        seed, schedule, method = key
        baseline_key = (seed, schedule, "ordinary")
        original, baseline = parsed[key], parsed[baseline_key]
        need(
            original[0]["before"] == baseline[0]["before"],
            "B paired initial parameters/optimizer differ",
        )
        decisions = []
        for i, (value, ref) in enumerate(zip(original, baseline, strict=True)):
            state, reference = (
                path["trace"][i]["state"],
                indexed[baseline_key]["trace"][i]["state"],
            )
            observed = {
                k: v
                for k, v in value.items()
                if k not in ("before", "candidate", "after")
            }
            for component in COMPONENTS:
                paired = value["after"][component] != ref["after"][component]
                # Compare equality relations within each recipe, never raw hashes across recipes.
                need(
                    paired
                    == (
                        state["components"][component]
                        != reference["components"][component]
                    ),
                    "B two recorded component identity recipes disagree on paired equality",
                )
                observed["candidate_" + component + "_change"] = (
                    value["candidate"][component] != value["before"][component]
                )
                observed["committed_" + component + "_change"] = (
                    value["after"][component] != value["before"][component]
                )
                observed["paired_" + component + "_difference"] = paired
            observed["paired_physical_state_difference"] = (
                state["dynamics"] != reference["dynamics"]
            )
            need(
                observed["paired_physical_state_difference"]
                == (state["components"] != reference["components"]),
                "B dynamics digest and component equality disagree",
            )
            observed["paired_controller_history_difference"] = (
                state["controller_history"] != reference["controller_history"]
            )
            decisions.append(observed)
        first = next(
            (
                i
                for i, row in enumerate(decisions)
                if row["paired_physical_state_difference"]
            ),
            None,
        )
        need(
            path["first_legal_divergence_decision"] == first
            and path["first_legal_divergence_clock"]
            == (None if first is None else 48 * (first + 1))
            and type(path["terminal_reference_tail_state_equal"]) is bool
            and path["terminal_reference_tail_state_equal"]
            == (not decisions[-1]["paired_physical_state_difference"]),
            "B original physical divergence summary differs",
        )
        total = counts(decisions)
        need(
            path["overrides"] == total["requested_override"]
            and path["accepted_overrides"] == total["accepted_override"],
            "B override totals differ",
        )
        result.append(
            {
                "id": path["id"],
                "seed": seed,
                "schedule_id": schedule,
                "method": method,
                "decisions": decisions,
                "counts": total,
                "first_parameter_optimizer_divergence_clock": next(
                    (
                        row["clock"]
                        for row in decisions
                        if any(row["paired_" + k + "_difference"] for k in COMPONENTS)
                    ),
                    None,
                ),
            }
        )
    result.sort(
        key=lambda row: (
            row["seed"],
            row["schedule_id"],
            B_METHODS.index(row["method"]),
        )
    )
    report = phase_result(
        "B",
        result,
        "method",
        "Mutable adapter parameters and SGD state at all six paired decision boundaries; physical dynamics exclude controller history and path_kind.",
    )
    target = report["counts_by_method"]["field12"]
    report["field_activity_status"] = (
        "parameter_optimizer_change_observed"
        if any(target["paired_" + k + "_difference"] for k in COMPONENTS)
        else "whole_state_change_only"
        if target["paired_physical_state_difference"]
        else "registered_inactive"
    )
    report["inactive_scope"] = (
        "No paired parameter/optimizer or physical divergence at the six recorded boundaries; controller-history differences remain separately reported. No claim about attempted candidates."
    )
    return report


def terminal_components(record, path, digest):
    """Reduce a byte-verified C checkpoint using the pinned original state.digest.

    The caller owns safe decoding and literal-file verification. This function
    accepts an already decoded record and does not instantiate a model. Parameters
    are selected by the actual named-parameter inventory, excluding model buffers.
    """
    state = record["state"]
    need(
        state["schema"] == "hepta.fullstudy.C.training-state.1"
        and record["metadata"] == path["metadata"]
        and state["model_config"] == path["metadata"]["config"],
        "C checkpoint metadata/state binding differs",
    )
    names = state["parameter_names"]
    need(
        type(names) is list
        and names
        and len(names) == len(set(names))
        and all(type(name) is str and name in state["model"] for name in names)
        and type(state["requires_grad"]) is list
        and len(state["requires_grad"]) == len(names)
        and all(flag is True for flag in state["requires_grad"]),
        "C all-parameter inventory differs",
    )
    full = sha(digest(state))
    need(
        full == record["state_sha256"] == path["state_sha256"],
        "C terminal literal state digest differs",
    )
    return {
        "checkpoint": dict(path["checkpoint"]),
        "metadata": dict(record["metadata"]),
        "state_sha256": full,
        "parameter_names": list(names),
        "parameters": sha(digest({name: state["model"][name] for name in names})),
        "optimizer": sha(digest(state["optimizer"])),
    }


def audit_c(paths, terminal):
    """Validate all 32 C paths; component activity is observable at terminal time."""
    indexed = population(
        paths,
        ("mode", "seed", "policy"),
        set(product(C_MODES, range(801, 809), ("baseline", "field"))),
    )
    need(
        type(terminal) is dict and set(terminal) == set(indexed),
        "Incomplete C terminal component population",
    )
    parsed, result = {}, []
    for key, path in indexed.items():
        mode, seed, policy = key
        metadata, component = path["metadata"], terminal[key]
        need(
            metadata["schema"] == "hepta.fullstudy.C.endpoint.1"
            and metadata["mode"] == mode
            and metadata["seed"] == seed
            and metadata["policy"] == policy
            and metadata["clock"] == 96
            and metadata["schedule"] == 8000,
            "C terminal endpoint identity differs",
        )
        need(
            component["metadata"] == metadata
            and component["checkpoint"] == path["checkpoint"]
            and component["state_sha256"] == path["state_sha256"],
            "C terminal component evidence is unbound",
        )
        for k in (*COMPONENTS, "state_sha256"):
            sha(component[k])
        need(
            type(path["decision_state_sha256"]) is list
            and len(path["decision_state_sha256"]) == 6,
            "Incomplete C decision-state population",
        )
        rows = []
        for i, row in enumerate(path["trace"]):
            value = transaction(row, i, 2, "C", 8000)
            need(
                row["before"] == value["before"]
                and value["after"] == sha(path["decision_state_sha256"][i]),
                "C recorded whole-state chain differs",
            )
            need(
                value["before"]
                == (rows[-1]["after"] if rows else metadata["warmstart_state_sha256"]),
                "C warmstart or continuation identity differs",
            )
            need(
                policy != "baseline" or value["action"] == 2,
                "C baseline policy differs",
            )
            rows.append(value)
        need(
            rows[-1]["after"] == path["state_sha256"],
            "C terminal and final decision state differ",
        )
        parsed[key] = rows
    for key, path in indexed.items():
        mode, seed, policy = key
        ref_key = (mode, seed, "baseline")
        original, baseline = parsed[key], parsed[ref_key]
        need(
            original[0]["before"] == baseline[0]["before"], "C paired warmstarts differ"
        )
        decisions = []
        for value, ref in zip(original, baseline, strict=True):
            observed = {
                k: v
                for k, v in value.items()
                if k not in ("before", "candidate", "after")
            }
            observed.update(
                candidate_whole_state_change=value["candidate"] != value["before"],
                committed_whole_state_change=value["after"] != value["before"],
                paired_whole_state_difference=value["after"] != ref["after"],
            )
            decisions.append(observed)
        first = next(
            (
                i
                for i, row in enumerate(decisions)
                if row["paired_whole_state_difference"]
            ),
            None,
        )
        need(
            path["first_legal_divergence_decision"] == first
            and path["first_legal_divergence_clock"]
            == (None if first is None else 16 * (first + 1)),
            "C original whole-state divergence summary differs",
        )
        total = counts(decisions)
        need(
            path["overrides"] == total["requested_override"]
            and path["accepted_overrides"] == total["accepted_override"],
            "C override totals differ",
        )
        component_difference = {
            k: terminal[key][k] != terminal[ref_key][k] for k in COMPONENTS
        }
        need(
            terminal[key]["parameter_names"] == terminal[ref_key]["parameter_names"],
            "C paired parameter inventories differ",
        )
        need(
            decisions[-1]["paired_whole_state_difference"]
            or not any(component_difference.values()),
            "Equal whole states cannot contain unequal components",
        )
        result.append(
            {
                "mode": mode,
                "seed": seed,
                "policy": policy,
                "decisions": decisions,
                "counts": total,
                "terminal_paired_component_difference": component_difference,
                "intermediate_parameter_optimizer_activity": "not_separately_recorded",
            }
        )
    result.sort(
        key=lambda row: (C_MODES.index(row["mode"]), row["seed"], row["policy"])
    )
    report = phase_result(
        "C",
        result,
        "policy",
        "Original captured training state at six boundaries; exact parameters and SGD state at terminal only, paired within architecture and seed. Logical clock and immutable context are outside the state digest and aligned by the registered receipts.",
    )
    fields = [row for row in result if row["policy"] == "field"]
    report["field_activity_status"] = (
        "parameter_optimizer_change_observed"
        if any(
            any(row["terminal_paired_component_difference"].values()) for row in fields
        )
        else "whole_state_change_only"
        if report["counts_by_policy"]["field"]["paired_whole_state_difference"]
        else "registered_inactive"
    )
    report["component_evidence_scope"] = (
        "Terminal component equality does not exclude intermediate component divergence followed by convergence. Equal complete states at each recorded boundary do establish equality of their components at those boundaries."
    )
    report["first_parameter_optimizer_divergence_clock"] = (
        "unknown_except_no_divergence_at_boundaries_when_all_whole_states_equal"
    )
    return report
