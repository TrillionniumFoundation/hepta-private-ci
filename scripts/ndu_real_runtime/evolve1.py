"""EVOLVE-1 four-cell transfer accounting on the frozen causal-improver protocol.

``summarize_transfer`` accepts independent outer-lineage blocks. Each block has
lineage_id, plan, registry, attempts, solver_rows, historical_costs, source_groups,
and retention_data_digest. ``solver_rows`` maps the two complete starting-bundle
SHA256 pins to S0/S1. The plan registers exactly four runs (two paired rows), using
the existing parent/child roles as I0/I1. All four runs share task, seed, budget,
and evaluator context; only their solver and improver components differ.

Source groups are nonempty lists for training/development/acceptance/holdout/
retention. They are declarations, not verified provenance. Historical costs are
a flat COST_UNITS dictionary of nonnegative measurements or None (unknown).
retention_data_digest pins the actual frozen retention data, not group-ID text.
Authenticated heldout_final evaluator records add retention_baseline,
retention_candidate (higher is better), and matching retention_data_digest.
The frozen holdout profile must cover both utility and retention evaluation.

Output cells S0-I0/S0-I1/S1-I0/S1-I1 report registered/qualified/unresolved run
counts, missing-evidence probability bounds (NOT confidence intervals), all-run
costs, and cost per effective improvement. Lineages retain the base comparison,
observed runs, paired row contrasts, and S1-minus-S0 interaction. History is
reported separately, never silently amortized. This is descriptive pilot
accounting: no scientific, production, adoption, or successor-use authority.
Observed effect/retention rates remain separate from complete qualification;
missing energy or other costs never erase an authenticated observed effect.
"""

from copy import deepcopy

from ._causal_checks import COST_UNITS, _fields, _number, _pin, _require, _text
from .causal_improver import _improver_runs, compare_improvers


_SPLITS = ("training", "development", "acceptance", "holdout", "retention")
_CELLS = ("S0-I0", "S0-I1", "S1-I0", "S1-I1")


def _validated_blocks(blocks):
    _require(isinstance(blocks, list) and blocks, "EVOLVE_BLOCKS_REQUIRED")
    prepared, lineages, children, global_groups, global_data = [], set(), set(), {}, {}
    for block in deepcopy(blocks):
        _fields(
            block,
            (
                "lineage_id",
                "plan",
                "registry",
                "attempts",
                "solver_rows",
                "historical_costs",
                "source_groups",
                "retention_data_digest",
            ),
            "EVOLVE_BLOCK_FIELDS",
        )
        identity = block["lineage_id"]
        _require(_text(identity) and identity not in lineages, "EVOLVE_LINEAGE_ID")
        lineages.add(identity)
        _require(_pin(block["retention_data_digest"]), "EVOLVE_RETENTION_DATA_PIN")
        _fields(block["historical_costs"], COST_UNITS, "EVOLVE_HISTORY_UNITS")
        _require(
            all(
                value is None or _number(value, minimum=0)
                for value in block["historical_costs"].values()
            ),
            "EVOLVE_INVALID_HISTORY_COST",
        )
        _fields(block["source_groups"], _SPLITS, "EVOLVE_SOURCE_GROUP_FIELDS")
        groups = {}
        for split, values in block["source_groups"].items():
            _require(
                isinstance(values, list)
                and values
                and all(_text(value) for value in values)
                and len(set(values)) == len(values),
                "EVOLVE_SOURCE_GROUPS",
            )
            groups[split] = set(values)
            for value in values:
                _require(
                    global_groups.get(value, split) == split,
                    "EVOLVE_SOURCE_GROUP_LEAKAGE",
                )
                global_groups[value] = split
        solver_rows = block["solver_rows"]
        _require(
            isinstance(solver_rows, dict)
            and len(solver_rows) == 2
            and all(_pin(key) and _text(value) for key, value in solver_rows.items())
            and set(solver_rows.values()) == {"S0", "S1"},
            "EVOLVE_SOLVER_ROWS",
        )
        runs, pairs = _improver_runs(block["plan"])
        _require(len(runs) == 4 and len(pairs) == 2, "EVOLVE_FOUR_ARMS_REQUIRED")
        child = block["plan"]["improvers"]["child"]["artifact_digest"]
        _require(child not in children, "EVOLVE_REUSED_DESCENDANT_NOT_INDEPENDENT")
        children.add(child)
        cells, context = {}, None
        for run_id, run in runs.items():
            start = run["common_start"]
            _require(start["initial_bundle"] in solver_rows, "EVOLVE_SOLVER_BINDING")
            row = solver_rows[start["initial_bundle"]]
            cell = row + ("-I0" if run["role"] == "parent" else "-I1")
            _require(cell not in cells.values(), "EVOLVE_DUPLICATE_CELL")
            cells[run_id] = cell
            current = {
                key: value for key, value in start.items() if key != "initial_bundle"
            }
            current.update(
                {
                    key: run[key]
                    for key in (
                        "full_budget_contract",
                        "acceptance_profile",
                        "holdout_profile",
                        "evaluator_owner",
                    )
                }
            )
            _require(
                context is None or context == current,
                "EVOLVE_UNMATCHED_TRANSFER_CONTEXT",
            )
            context = current
        _require(set(cells.values()) == set(_CELLS), "EVOLVE_FOUR_CELLS_REQUIRED")
        _require(
            block["retention_data_digest"]
            not in {
                context[key]
                for key in (
                    "training_data",
                    "development_data",
                    "acceptance_data",
                    "holdout_data",
                )
            },
            "EVOLVE_RETENTION_DATA_OVERLAP",
        )
        for split in _SPLITS:
            digest = (
                block["retention_data_digest"]
                if split == "retention"
                else context[split + "_data"]
            )
            _require(
                global_data.get(digest, split) == split, "EVOLVE_DATA_DIGEST_LEAKAGE"
            )
            global_data[digest] = split
        for previous, _, _, _, old_groups, old_context in prepared:
            for split, keys in (
                ("holdout", ("holdout_data", "holdout_family", "holdout_profile")),
                ("retention", ("holdout_profile",)),
            ):
                same_data = (
                    block["retention_data_digest"] == previous["retention_data_digest"]
                    if split == "retention"
                    else context["holdout_data"] == old_context["holdout_data"]
                )
                if groups[split] & old_groups[split] or same_data:
                    _require(
                        groups[split] == old_groups[split]
                        and all(context[key] == old_context[key] for key in keys)
                        and (
                            split != "retention"
                            or block["retention_data_digest"]
                            == previous["retention_data_digest"]
                        ),
                        "EVOLVE_SHARED_CONFIRMATION_MISMATCH",
                    )
        prepared.append((block, runs, pairs, cells, groups, context))
    return prepared


def _difference(left, right):
    value = right - left if left is not None and right is not None else None
    _require(value is None or _number(value), "EVOLVE_CONTRAST_OVERFLOW")
    return value


def _aggregate(records):
    n = len(records)
    qualified = sum(record["qualified"] is True for record in records)
    unknown = sum(record["qualified"] is None for record in records)
    known = {
        unit: sum(record["cost_known_lower_bounds"][unit] for record in records)
        for unit in COST_UNITS
    }
    _require(
        all(_number(value, minimum=0) for value in known.values()),
        "EVOLVE_COST_SUM_OVERFLOW",
    )
    totals = {
        unit: known[unit]
        if all(record["cost_totals"][unit] is not None for record in records)
        else None
        for unit in COST_UNITS
    }
    result = {
        "registered_runs": n,
        "qualified_runs": qualified,
        "unresolved_runs": unknown,
        "not_qualified_runs": n - qualified - unknown,
        "improvement_probability_bounds": [qualified / n, (qualified + unknown) / n],
        "cost_totals": totals,
        "cost_known_lower_bounds": known,
        "cost_per_effective_improvement": {
            unit: total / qualified
            if total is not None and qualified and not unknown
            else None
            for unit, total in totals.items()
        },
    }
    for metric, prefix, yes_label, no_label, rate_key in (
        (
            "effect_criterion_met",
            "effect_criterion",
            "met",
            "not_met",
            "effect_criterion_probability_bounds",
        ),
        (
            "retention_violated",
            "retention",
            "violated",
            "not_violated",
            "retention_violation_probability_bounds",
        ),
    ):
        yes = sum(record[metric] is True for record in records)
        no = sum(record[metric] is False for record in records)
        unresolved = n - yes - no
        result.update(
            {
                prefix + "_" + yes_label + "_runs": yes,
                prefix + "_" + no_label + "_runs": no,
                prefix + "_unknown_runs": unresolved,
                rate_key: [yes / n, (yes + unresolved) / n],
            }
        )
    return result


def summarize_transfer(
    blocks,
    *,
    minimum_gain,
    maximum_retention_loss,
    read_evaluation=None,
    verify_evaluation=None,
):
    """Summarize registered four-arm pilots; never grant scientific/owner authority.

    Callbacks use the compare_improvers signatures: read(kind, reference) and
    verify(kind, record, evaluator_owner) -> exactly True. A missing callback or
    missing record leaves evidence unresolved. An authenticated malformed or
    misbound record is rejected. NoUpdate, failed/cancelled selections, and
    retained baseline bundles never qualify, regardless of reported utility.
    """
    _require(
        _number(minimum_gain, minimum=0) and minimum_gain > 0, "EVOLVE_MINIMUM_GAIN"
    )
    _require(_number(maximum_retention_loss, minimum=0), "EVOLVE_RETENTION_LIMIT")
    prepared = _validated_blocks(blocks)
    cell_records = {cell: [] for cell in _CELLS}
    lineages, history = {}, {}
    complete = True
    for block, runs, pairs, cells, _, _ in prepared:
        verified_finals = {}

        def read(kind, reference):
            return deepcopy(read_evaluation(kind, reference))

        def verify(kind, record, owner):
            authenticated = verify_evaluation(kind, record, owner) is True
            if authenticated and kind == "heldout_final":
                _require(
                    _text(record.get("run_id"))
                    and record.get("retention_data_digest")
                    == block["retention_data_digest"]
                    and all(
                        _number(record.get(key))
                        for key in ("retention_baseline", "retention_candidate")
                    ),
                    "EVOLVE_RETENTION_BINDING",
                )
                verified_finals[record.get("run_id")] = deepcopy(record)
            return authenticated

        has_ports = callable(read_evaluation) and callable(verify_evaluation)
        comparison = compare_improvers(
            block["plan"],
            block["registry"],
            block["attempts"],
            read_evaluation=read if has_ports else None,
            verify_evaluation=verify if has_ports else None,
        )
        complete = complete and comparison["status"] == "DESCRIPTIVE_COMPLETE"
        results, rows_by_id = {}, {row["attempt_id"]: row for row in block["attempts"]}
        for run_id, run in runs.items():
            report = comparison["runs"][run_id]
            final = block["registry"]["finals"].get(run_id)
            record = (
                verified_finals.get(run_id)
                if report["heldout_delta"] is not None
                else None
            )
            chosen = rows_by_id.get(final["attempt_id"]) if final is not None else None
            retention_loss, effect, violated, reason = (
                None,
                None,
                None,
                "UNRESOLVED_EVIDENCE",
            )
            if record is not None:
                delta = _difference(
                    record["retention_baseline"], record["retention_candidate"]
                )
                retention_loss = max(0.0, -delta)
                violated = retention_loss > maximum_retention_loss
            if final is not None and (
                final["attempt_id"] is None
                or final["candidate_bundle"] == run["common_start"]["initial_bundle"]
            ):
                effect, reason = False, "NO_UPDATE"
            elif chosen is not None and chosen["terminal_status"] in {
                "FAILED",
                "CANCELLED",
            }:
                effect, reason = False, "UNSUCCESSFUL_SELECTION"
            elif record is not None and (
                report["heldout_delta"] < minimum_gain or violated
            ):
                effect, reason = False, "IMPROVEMENT_OR_RETENTION_GATE_FAILED"
            elif (
                record is not None
                and chosen is not None
                and (
                    chosen["terminal_status"] == "SUCCEEDED"
                    and chosen["rolled_back"] is False
                )
            ):
                effect, reason = True, "EFFECT_OBSERVED_FULL_QUALIFICATION_UNRESOLVED"
            qualified = False if effect is False else None
            if effect is True and (
                comparison["registry_closed"]
                and report["reported_cost_coverage_complete"]
                and not any(
                    report[key]
                    for key in (
                        "unknown_validity",
                        "unresolved_evaluation",
                        "unknown_rollback",
                    )
                )
                and not report["terminal_counts"]["UNKNOWN"]
            ):
                qualified, reason = True, "QUALIFIED_DESCRIPTIVE_OBSERVATION"
            result = {
                "cell": cells[run_id],
                "qualified": qualified,
                "reason": reason,
                "effect_criterion_met": effect,
                "retention_violated": violated,
                "heldout_delta": report["heldout_delta"],
                "retention_loss": retention_loss,
                "net_improvement": report["net_improvement"],
                "cost_totals": report["cost_totals"],
                "cost_known_lower_bounds": report["cost_known_lower_bounds"],
            }
            results[run_id] = result
            cell_records[cells[run_id]].append(result)
            complete = complete and qualified is not None
        contrasts = {}
        for pair_id, pair in pairs.items():
            left, right = (
                results[pair[role]["run_id"]] for role in ("parent", "child")
            )
            left_record, right_record = (
                verified_finals.get(pair[role]["run_id"])
                for role in ("parent", "child")
            )
            if left_record is not None and right_record is not None:
                _require(
                    left_record["retention_baseline"]
                    == right_record["retention_baseline"],
                    "EVOLVE_UNMATCHED_RETENTION_BASELINE",
                )
            row = left["cell"].split("-")[0]
            contrasts[row] = {"pair_id": pair_id}
            for metric in ("heldout_delta", "net_improvement", "retention_loss"):
                contrasts[row][metric + "_child_minus_parent"] = _difference(
                    left[metric], right[metric]
                )
            for indicator in (
                "qualified",
                "effect_criterion_met",
                "retention_violated",
            ):
                contrasts[row][indicator + "_indicator_child_minus_parent"] = (
                    _difference(
                        int(left[indicator]) if left[indicator] is not None else None,
                        int(right[indicator]) if right[indicator] is not None else None,
                    )
                )
        lineages[block["lineage_id"]] = {
            "comparison": comparison,
            "observed_runs": results,
            "row_contrasts": contrasts,
            "interaction_S1_minus_S0": {
                key: _difference(contrasts["S0"][key], contrasts["S1"][key])
                for key in contrasts["S0"]
                if key != "pair_id"
            },
        }
        history[block["lineage_id"]] = block["historical_costs"]
    history_known = {
        unit: sum(value[unit] for value in history.values() if value[unit] is not None)
        for unit in COST_UNITS
    }
    _require(
        all(_number(value, minimum=0) for value in history_known.values()),
        "EVOLVE_HISTORY_SUM_OVERFLOW",
    )
    return {
        "schema": "ndu.evolve1.transfer-summary.v1",
        "status": "DESCRIPTIVE_PILOT_COMPLETE"
        if complete
        else "HOLD_INCOMPLETE_EVIDENCE",
        "minimum_gain": minimum_gain,
        "maximum_retention_loss": maximum_retention_loss,
        "lineages": lineages,
        "cells": {cell: _aggregate(records) for cell, records in cell_records.items()},
        "online_costs": _aggregate(
            [record for records in cell_records.values() for record in records]
        ),
        "historical_costs": {
            "by_lineage": history,
            "known_lower_bounds": history_known,
            "totals": {
                unit: history_known[unit]
                if all(value[unit] is not None for value in history.values())
                else None
                for unit in COST_UNITS
            },
            "amortized": False,
        },
        "statistics_unit": "outer_improver_lineage_with_paired_solver_rows_not_episode",
        "probability_bounds_are_missing_evidence_bounds": True,
        "confidence_intervals_computed": False,
        "source_group_provenance_verified": False,
        "independent_lineage_provenance_verified": False,
        "cost_provenance_verified": False,
        "scientific_efficacy_qualified": False,
        "production_adoption_qualified": False,
        "successor_consumption_verified": False,
        "authority_granted": False,
    }
