"""Prospective matched-parent kernel; no scientific loader or admission CLI.

The separately registered runtime adapter must admit immutable original evidence,
reconstruct exact visited parents, lock the original choice before new branches,
normalize the unchanged original transactions, and own all physical cost meters.
This module neither grants admission nor supplies that adapter. Synthetic backends
exercise sequencing and interpretation without loading a model or outcome.
"""

from copy import deepcopy
import hashlib
from itertools import product
import json
import math
import re


ORIGINAL_COMMIT = "bc4e757f5c90f6365f383c1127be710d2ded874a"
MULTIPLIERS = (0.0, 0.25, 1.0, 2.0)
OBSERVERS = ("reward", "audit")
PREDICTORS = ("field12", "full_current_state", "history6")
ROLES = ("probe", "task", "clean")
ROWS = {
    "B": {"probe": 512, "task": 2048, "clean": 812},
    "C": {"probe": 512, "task": 3952, "clean": 988},
}


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(value):
    need(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "Malformed SHA256"
    )
    return value


def finite(value):
    need(
        type(value) in (int, float) and math.isfinite(value),
        "Nonfinite or nonnumeric value",
    )
    return value


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def descriptor(value):
    need(
        type(value) is dict
        and set(value) == {"path", "bytes", "sha256"}
        and type(value["path"]) is str
        and value["path"]
        and type(value["bytes"]) is int
        and value["bytes"] > 0,
        "Missing literal-artifact descriptor",
    )
    sha(value["sha256"])
    return value


def parents():
    """Complete fixed target population, independent of any observed choice/value."""
    result = []
    paths = [
        ("B", "adapter", seed, schedule, 48, 288, 2 if seed == 17 else 3)
        for seed, schedule in product((17, 29, 43), range(106000, 106016))
    ]
    paths += [
        ("C", mode, seed, 8000, 16, 96, 2)
        for mode, seed in product(("ordinary", "dual"), range(801, 809))
    ]
    for stage, mode, seed, schedule, grain, steps, baseline in paths:
        path_id = f"{stage}-{mode}-seed-{seed}-schedule-{schedule}"
        for decision in range(6):
            result.append(
                {
                    "id": f"{path_id}-decision-{decision}",
                    "path_id": path_id,
                    "stage": stage,
                    "architecture": mode,
                    "seed": seed,
                    "schedule": schedule,
                    "decision": decision,
                    "clock": grain * decision,
                    "grain": grain,
                    "steps": steps,
                    "baseline": baseline,
                    "ordinal": len(result),
                }
            )
    return result


PARENTS = {row["id"]: row for row in parents()}


def spec_checked(spec):
    need(
        type(spec) is dict and PARENTS.get(spec.get("id")) == spec,
        "Unregistered parent or changed action/clock population",
    )
    return spec


def work_inventory():
    result = {}
    for stage in ("B", "C"):
        selected = [p for p in PARENTS.values() if p["stage"] == stage]
        tail = sum(4 * (p["steps"] - p["clock"]) for p in selected)
        audit = sum(p["steps"] - p["clock"] for p in selected)
        replay = sum(p["grain"] for p in selected)
        result[stage] = {
            "paths": len({p["path_id"] for p in selected}),
            "parents": len(selected),
            "primary_tails": 4 * len(selected),
            "independent_audit_tails": len(selected),
            "counterfactual_microsteps": tail,
            "audit_microsteps": audit,
            "actual_replay_microsteps": replay,
            "total_microsteps": tail + audit + replay,
        }
    result["total_microsteps"] = sum(result[s]["total_microsteps"] for s in ("B", "C"))
    return result


def check_lock(spec, lock):
    spec_checked(spec)
    need(lock["parent_id"] == spec["id"], "Choice lock is for a different parent")
    for key in (
        "parent_state_sha256",
        "actual_successor_sha256",
        "original_transaction_fingerprint",
        "fixed_guard_sha256",
    ):
        sha(lock[key])
    for key in ("source_trace", "frozen_head", "persisted_choice_lock"):
        descriptor(lock[key])
    selected = choice_action(spec, lock["original_choice"])
    if spec["stage"] == "B":
        shadows = lock["frozen_predictors"]
        need(
            type(shadows) is dict and set(shadows) == set(PREDICTORS),
            "All three original frozen B predictors are required",
        )
        for row in shadows.values():
            descriptor(row["head"])
            choice_action(spec, row["choice"])
        need(
            shadows["field12"]["head"] == lock["frozen_head"]
            and shadows["field12"]["choice"] == lock["original_choice"],
            "Shadow field predictor differs from the deployed locked choice",
        )
    else:
        need(
            "frozen_predictors" not in lock,
            "C has no registered full-state/history heads",
        )
    return selected


def choice_action(spec, choice):
    """Preserve each original head's own finite scores and calibration gate."""
    scores, threshold = choice["predicted_advantages"], finite(choice["threshold"])
    need(
        type(scores) is list and len(scores) == 4 and threshold >= 0,
        "Frozen head scores or threshold differ",
    )
    for score in scores:
        finite(score)
    baseline = spec["baseline"]
    need(scores[baseline] == 0, "Original baseline advantage is not zero")
    greedy = max(range(4), key=lambda action: scores[action])
    active = (
        greedy != baseline
        and scores.count(scores[greedy]) == 1
        and scores[greedy] > threshold
    )
    selected = greedy if active else baseline
    need(
        type(choice["chosen_action"]) is int
        and choice["chosen_action"] == selected
        and type(choice["override"]) is bool
        and choice["override"] == active,
        "Locked choice differs from the unchanged original finite-score rule",
    )
    return selected


def native(stage, value):
    if stage == "C":
        return sha(value)
    need(
        type(value) is dict and set(value) == {"parameters", "optimizer"},
        "B native component inventory differs",
    )
    for item in value.values():
        sha(item)
    return value


def snapshot_checked(spec, value, clock):
    need(value["clock"] == clock, "Logical clock differs")
    sha(value["complete_sha256"])
    sha(value["dynamics_sha256"])
    native(spec["stage"], value["native"])
    return value


def stable_transition(receipt):
    """Original semantic fields only; cost and elapsed time are never equality keys."""
    keys = (
        "action",
        "start",
        "end",
        "schedule",
        "multiplier",
        "native_before",
        "native_candidate",
        "native_after",
        "accepted",
        "guard_delta",
        "guard_outputs_sha256",
        "fixed_guard_sha256",
        "tape_sha256",
        "clock_advances",
        "scheduled_gradient_microsteps",
    )
    return {key: receipt[key] for key in keys}


def check_transition(spec, lock, before, receipt, after, action, start):
    snapshot_checked(spec, before, start)
    snapshot_checked(spec, after, start + spec["grain"])
    need(
        type(receipt["action"]) is int
        and receipt["action"] == action
        and receipt["start"] == start
        and receipt["end"] == start + spec["grain"]
        and receipt["schedule"] == spec["schedule"]
        and receipt["multiplier"] == MULTIPLIERS[action]
        and receipt["clock_advances"] is True
        and type(receipt["scheduled_gradient_microsteps"]) is int
        and receipt["scheduled_gradient_microsteps"] == spec["grain"],
        "Transaction changed the fixed action, tape, clock or physical work",
    )
    for key in ("native_before", "native_candidate", "native_after"):
        native(spec["stage"], receipt[key])
    need(
        receipt["native_before"] == before["native"]
        and receipt["native_after"] == after["native"],
        "Native receipt does not bind actual captured state",
    )
    delta = finite(receipt["guard_delta"])
    need(
        type(receipt["accepted"]) is bool and receipt["accepted"] == (delta >= 0),
        "Original fixed-reference guard was changed",
    )
    need(
        receipt["native_after"]
        == (
            receipt["native_candidate"]
            if receipt["accepted"]
            else receipt["native_before"]
        ),
        "Guard rollback or committed native state differs",
    )
    need(
        action != 0 or receipt["native_after"] == receipt["native_before"],
        "Zero action changed native parameters/optimizer state",
    )
    need(
        sha(receipt["fixed_guard_sha256"]) == lock["fixed_guard_sha256"],
        "Guard reference changed between arms",
    )
    sha(receipt["guard_outputs_sha256"])
    sha(receipt["tape_sha256"])


def sealed_state(backend, kind, action, captured):
    item = backend.seal_state(kind, action)
    descriptor(item["artifact"])
    need(
        item["state_sha256"] == captured["complete_sha256"],
        "Literal checkpoint does not bind the captured complete state",
    )
    return item


def enumerate_parent(spec, lock, backend):
    """All four tails, a predetermined audit, then the locked actual continuation.

    Backend methods are restore_parent(), snapshot(), transition(action, clock),
    scheduled_microsteps(), seal_state(kind, action), and advance_original(lock).
    advance_original applies the already verified original policy and history
    update; it may not consume these branch labels or fit a head. No endpoint
    scorer is called here. Every call and failed attempt needs an outer real wait4
    in the future runtime adapter; this function does not claim that measurement.
    """
    selected = check_lock(spec, lock)
    before_work = backend.scheduled_microsteps()
    need(type(before_work) is int and before_work >= 0, "Missing physical work count")
    tapes, branches = {}, []

    def restore():
        backend.restore_parent()
        state = snapshot_checked(spec, backend.snapshot(), spec["clock"])
        need(
            state["complete_sha256"] == lock["parent_state_sha256"],
            "Counterfactual did not restore the exact visited parent",
        )
        return state

    parent = restore()
    parent_item = sealed_state(backend, "parent", None, parent)

    def arm(action, persist):
        current, trace, first, first_item = restore(), [], None, None
        for clock in range(spec["clock"], spec["steps"], spec["grain"]):
            chosen = action if clock == spec["clock"] else spec["baseline"]
            receipt = backend.transition(chosen, clock)
            after = backend.snapshot()
            check_transition(spec, lock, current, receipt, after, chosen, clock)
            tape = receipt["tape_sha256"]
            need(tapes.setdefault(clock, tape) == tape, "Arms consumed different tapes")
            trace.append(deepcopy(stable_transition(receipt)))
            if first is None:
                first = deepcopy(after)
                if persist:
                    first_item = sealed_state(backend, "first", action, after)
            current = after
        result = {
            "action": action,
            "first": first,
            "terminal": deepcopy(current),
            "transactions": trace,
        }
        if persist:
            result.update(
                first_checkpoint=first_item,
                terminal_checkpoint=sealed_state(backend, "terminal", action, current),
            )
        return result

    for action in range(4):
        branches.append(arm(action, True))
    audit_action = spec["ordinal"] % 4
    audit = arm(audit_action, False)
    need(
        all(
            audit[key] == branches[audit_action][key]
            for key in ("first", "terminal", "transactions")
        ),
        "Predetermined independent tail replay was not exact",
    )
    before = restore()
    receipt = backend.advance_original(deepcopy(lock))
    after = backend.snapshot()
    check_transition(spec, lock, before, receipt, after, selected, spec["clock"])
    fingerprint = digest(stable_transition(receipt))
    need(
        fingerprint == lock["original_transaction_fingerprint"]
        and stable_transition(receipt) == branches[selected]["transactions"][0]
        and after["dynamics_sha256"] == branches[selected]["first"]["dynamics_sha256"]
        and after["complete_sha256"] == lock["actual_successor_sha256"],
        "Original selected action or visited successor failed exact reconstruction",
    )
    expected_work = 5 * (spec["steps"] - spec["clock"]) + spec["grain"]
    actual_work = backend.scheduled_microsteps() - before_work
    need(actual_work == expected_work, "Physical microstep ledger differs")
    return {
        "schema": "hepta.visited-counterfactual.parent-candidate.1",
        "parent": spec,
        "choice_lock": deepcopy(lock),
        "parent_checkpoint": parent_item,
        "branches": branches,
        "audit_action": audit_action,
        "independent_replay_equal": True,
        "actual_successor": after,
        "physical_microsteps": actual_work,
        "scientific_admission_performed_here": False,
        "endpoint_values_opened_here": False,
        "real_external_wait4_required": True,
        "new_independent_samples": 0,
    }


def checked_score(spec, role, row):
    descriptor(row["artifact"])
    sha(row["panel_sha256"])
    sha(row["emissions_sha256"])
    need(
        type(row["rows"]) is int
        and row["rows"] == ROWS[spec["stage"]][role]
        and set(row["means"]) == set(OBSERVERS),
        "Wrong panel or observer population",
    )
    for value in row["means"].values():
        finite(value)


def reduce_parent(record, scores, clean_reference):
    """Finite-panel paired contrasts after a separate complete extension seal.

    Caller must verify literal emissions, aligned source/condition identities and
    all population/source/transport/cost gates before constructing score records.
    Scalar summaries here cannot themselves establish those gates.
    """
    spec, lock = record["parent"], record["choice_lock"]
    selected = check_lock(spec, lock)
    need(
        type(scores) is list
        and len(scores) == 4
        and len(record["branches"]) == 4
        and [row["action"] for row in record["branches"]] == list(range(4)),
        "All four fixed action arms are required",
    )
    baseline = spec["baseline"]
    for arm in scores:
        need(set(arm) == set(ROLES), "Probe, task and clean scores are all required")
        for role in ROLES:
            checked_score(spec, role, arm[role])
            need(
                arm[role]["panel_sha256"] == scores[baseline][role]["panel_sha256"],
                "Counterfactual arms were not scored on the same paired panel",
            )
    checked_score(spec, "clean", clean_reference)
    need(
        clean_reference["panel_sha256"] == scores[baseline]["clean"]["panel_sha256"],
        "Clean reference panel is not paired",
    )
    for action, branch in enumerate(record["branches"]):
        reference = record["branches"][baseline]
        if branch["first"]["dynamics_sha256"] == reference["first"]["dynamics_sha256"]:
            need(
                branch["terminal"]["dynamics_sha256"]
                == reference["terminal"]["dynamics_sha256"],
                "Equal first physical states produced different fixed tails",
            )
        if (
            branch["terminal"]["dynamics_sha256"]
            == reference["terminal"]["dynamics_sha256"]
        ):
            need(
                all(
                    scores[action][role]["means"] == scores[baseline][role]["means"]
                    and scores[action][role]["emissions_sha256"]
                    == scores[baseline][role]["emissions_sha256"]
                    for role in ROLES
                ),
                "Equal terminal states received unequal outputs or scores",
            )
    effects = {}
    for role in ROLES:
        effects[role] = {}
        for observer in OBSERVERS:
            values = [row[role]["means"][observer] for row in scores]
            advantages = [value - values[baseline] for value in values]
            attainable = max(advantages)
            effects[role][observer] = {
                "action_advantages": advantages,
                "chosen_advantage": advantages[selected],
                "attainable_gain": attainable,
                "finite_panel_regret": attainable - advantages[selected],
            }
    predicted = lock["original_choice"]["predicted_advantages"]
    actual = effects["probe"]["reward"]["action_advantages"]
    residuals = [predicted[action] - actual[action] for action in range(4)]
    nonbaseline = [action for action in range(4) if action != baseline]
    threshold = lock["original_choice"]["threshold"]
    predictors = None
    if spec["stage"] == "B":
        predictor_values = {}
        for name in PREDICTORS:
            choice = lock["frozen_predictors"][name]["choice"]
            chosen = choice_action(spec, choice)
            predictor_values[name] = {
                "chosen_action": chosen,
                "frozen_choice": deepcopy(choice),
                "roles": {
                    role: {
                        observer: {
                            "chosen_advantage": effects[role][observer][
                                "action_advantages"
                            ][chosen],
                            "finite_panel_regret": effects[role][observer][
                                "attainable_gain"
                            ]
                            - effects[role][observer]["action_advantages"][chosen],
                        }
                        for observer in OBSERVERS
                    }
                    for role in ROLES
                },
            }
        increments = {
            name + "-minus-field12": {
                role: {
                    observer: predictor_values[name]["roles"][role][observer][
                        "chosen_advantage"
                    ]
                    - predictor_values["field12"]["roles"][role][observer][
                        "chosen_advantage"
                    ]
                    for observer in OBSERVERS
                }
                for role in ROLES
            }
            for name in ("full_current_state", "history6")
        }
        predictors = {
            "fixed_predictors": predictor_values,
            "chosen_gain_increments": increments,
            "occupancy": "same original field12 visited-parent population",
            "same_all_action_values_reused": True,
            "own_closed_loop_policy_value_is_estimated": False,
            "information_oracle_or_irreducible_information_bound": False,
            "original_W_reflection_reachability_established": False,
            "new_counterfactual_gradient_microsteps": 0,
        }
    return {
        "parent": spec,
        "selected_action": selected,
        "baseline_action": baseline,
        "effects": effects,
        "frozen_predictor_comparison": predictors,
        "guard_accepted": [
            r["transactions"][0]["accepted"] for r in record["branches"]
        ],
        "frozen_threshold_diagnostic": {
            "probe_reward_overprediction": residuals,
            "nonbaseline_exceeds_threshold": [
                residuals[a] > threshold for a in nonbaseline
            ],
            "chosen_exceeds_threshold": residuals[selected] > threshold,
            "nonbaseline_squared_errors": [residuals[a] ** 2 for a in nonbaseline],
            "threshold_refitted": False,
            "certificate": False,
        },
        "chosen_clean_minus_original_frozen_or_warmstart": {
            o: scores[selected]["clean"]["means"][o] - clean_reference["means"][o]
            for o in OBSERVERS
        },
        "guard_delta_is_advantage": False,
        "advantage_scope": "one guarded action then the registered baseline tail at this exact visited parent",
        "complete_deployed_policy_value_is_estimated": False,
        "scientific_admission_performed_here": False,
        "new_independent_samples": 0,
    }


def complete_summary(rows):
    need(
        type(rows) is list and len(rows) == len(PARENTS), "Incomplete 384-parent result"
    )
    seen = {}
    for row in rows:
        spec = spec_checked(row["parent"])
        need(spec["id"] not in seen, "Duplicate parent result")
        seen[spec["id"]] = row
    need(set(seen) == set(PARENTS), "Fixed parent population differs")
    groups = {}
    for stage, mode, seed in sorted(
        {(p["stage"], p["architecture"], p["seed"]) for p in PARENTS.values()}
    ):
        subset = [
            r
            for r in rows
            if (r["parent"]["stage"], r["parent"]["architecture"], r["parent"]["seed"])
            == (stage, mode, seed)
        ]
        label = f"{stage}/{mode}/seed-{seed}"
        groups[label] = {
            "parents": len(subset),
            "roles": {
                role: {
                    observer: {
                        metric: sum(
                            r["effects"][role][observer][metric] for r in subset
                        )
                        / len(subset)
                        for metric in (
                            "chosen_advantage",
                            "attainable_gain",
                            "finite_panel_regret",
                        )
                    }
                    for observer in OBSERVERS
                }
                for role in ROLES
            },
        }
        if stage == "B":
            groups[label]["frozen_predictor_comparison"] = {
                name: {
                    role: {
                        observer: {
                            metric: sum(
                                r["frozen_predictor_comparison"]["fixed_predictors"][
                                    name
                                ]["roles"][role][observer][metric]
                                for r in subset
                            )
                            / len(subset)
                            for metric in ("chosen_advantage", "finite_panel_regret")
                        }
                        for observer in OBSERVERS
                    }
                    for role in ROLES
                }
                for name in PREDICTORS
            }
            groups[label]["frozen_predictor_chosen_gain_increments"] = {
                contrast: {
                    role: {
                        observer: sum(
                            r["frozen_predictor_comparison"]["chosen_gain_increments"][
                                contrast
                            ][role][observer]
                            for r in subset
                        )
                        / len(subset)
                        for observer in OBSERVERS
                    }
                    for role in ROLES
                }
                for contrast in (
                    "full_current_state-minus-field12",
                    "history6-minus-field12",
                )
            }
    return {
        "schema": "hepta.visited-counterfactual.descriptive-candidate.1",
        "parent_population": len(rows),
        "per_architecture_and_seed": groups,
        "new_independent_samples": 0,
        "certificate": False,
        "statistical_efficacy_or_adoption_claim": False,
        "scientific_admission_performed_here": False,
        "new_confidence_intervals_or_thresholds": False,
        "cost_completeness": "requires separately verified inclusive real wait4 and delivery receipts",
    }
