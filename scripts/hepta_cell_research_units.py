"""Source, task-family and initialization units for descriptive evidence review.

These declarations prevent repeated observations from changing the registered
denominator. They do not authenticate source independence, exposure or meters.
Units V2 additionally reads each declared complete task artifact and refuses
identical bytes assigned to different source, family or split declarations.
Byte integrity does not establish task semantic completeness or source custody.
"""

from collections import Counter, defaultdict
from statistics import fmean
import re
import unicodedata

import hepta_cell_joint_config as joint


FIELDS = "cases initializations fits planned_attempts cost_coverage"
SCHEMAS = {"hepta.cell-research-units.v1", "hepta.cell-research-units.v2"}
SPLITS = {"development", "confirmation", "retention_validation", "retention_test"}


def shape(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise ValueError("unknown or missing statistical-unit fields")


def identity(value):
    if not isinstance(value, str) or re.fullmatch(r"[\w./:@-]{1,128}", value) is None:
        raise ValueError("invalid statistical-unit identity")
    return value


def records(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 4096:
        raise ValueError("statistical-unit inventory is empty or exceeds 4096")
    return value


def sampling_plan(spec, evidence):
    """Check each experiment's frozen scale and actual threshold-basis bytes."""
    shape(
        spec,
        "minimum_source_groups minimum_task_families minimum_model_initializations threshold_basis",
    )
    for key in (
        "minimum_source_groups",
        "minimum_task_families",
        "minimum_model_initializations",
    ):
        if type(spec[key]) is not int or not 1 <= spec[key] <= 4096:
            raise ValueError("sampling minima must be positive bounded integers")
    if spec["minimum_model_initializations"] < 2:
        raise ValueError("at least two model initializations must be registered")
    evidence.read(spec["threshold_basis"], document=False)


def review(document, rows, evidence, sampling_spec, cost_categories):
    """Reconcile all planned opportunities; none are dropped after observation.

    The enclosing gate verifies the header and validates raw attempt rows.
    Reusing a source, fit, initialization or checkpoint never multiplies n.
    Cost coverage concerns the entire category, including child processes and
    recovery; a partial measurement must remain unknown. This is a declaration,
    not independent meter authentication or a release of sealed material.
    """
    schema = document.get("schema") if isinstance(document, dict) else None
    if schema not in SCHEMAS:
        raise ValueError("unsupported research units schema")
    task_bound = schema == "hepta.cell-research-units.v2"
    cases, source_splits, task_units = {}, {}, {}
    source_aliases = {}
    for case in records(document["cases"]):
        shape(
            case,
            "case_id source_group_id task_family split"
            + (" task_artifact" if task_bound else ""),
        )
        case_id, source, _ = [
            identity(case[k]) for k in ("case_id", "source_group_id", "task_family")
        ]
        if case_id in cases or case["split"] not in SPLITS:
            raise ValueError("duplicate case or unknown registered split")
        # A case-folded or compatibility-normalized alias cannot create an
        # apparent second natural source group in a descriptive sample count.
        # This is an identity-consistency check, not source authentication.
        normalized_source = unicodedata.normalize("NFKC", source).casefold()
        if source_aliases.setdefault(normalized_source, source) != source:
            raise ValueError("aliased natural source-group identity")
        if source_splits.setdefault(source, case["split"]) != case["split"]:
            raise ValueError("one natural source crosses registered splits")
        if task_bound:
            task_sha = evidence.read(case["task_artifact"], document=False)["sha256"]
            unit = (source, case["task_family"], case["split"])
            if task_units.setdefault(task_sha, unit) != unit:
                raise ValueError(
                    "identical task bytes have conflicting statistical units"
                )
        cases[case_id] = case
    initializations = document["initializations"]
    if not isinstance(initializations, dict) or not 1 <= len(initializations) <= 4096:
        raise ValueError("invalid model initialization inventory")
    for sha, binding in initializations.items():
        if not isinstance(sha, str) or joint.SHA256.fullmatch(sha) is None:
            raise ValueError("initialization requires complete SHA256")
        if evidence.read(binding, document=False)["sha256"] != sha:
            raise ValueError("initialization key differs from its original bytes")
    fits, operations = {}, set()
    for fit in records(document["fits"]):
        shape(fit, "fit_id initialization_sha256 training_operation_id")
        fit_id = identity(fit["fit_id"])
        operation = identity(fit["training_operation_id"])
        if fit_id in fits or fit["initialization_sha256"] not in initializations:
            raise ValueError("duplicate fit or missing model initialization")
        fits[fit_id] = fit
        operations.add(operation)
    planned, pairs = {}, set()
    for attempt in records(document["planned_attempts"]):
        shape(attempt, "attempt_id arm fit_id case_id")
        attempt_id, arm, fit, case = [
            identity(attempt[k]) for k in ("attempt_id", "arm", "fit_id", "case_id")
        ]
        key = (arm, fit, case)
        if (
            attempt_id in planned
            or key in pairs
            or fit not in fits
            or case not in cases
        ):
            raise ValueError("duplicate or unregistered planned opportunity")
        planned[attempt_id] = attempt
        pairs.add(key)
    arms = {item["arm"] for item in planned.values()}
    if "candidate" not in arms or len(arms) < 2:
        raise ValueError("candidate and matched controls must be registered")
    blockers = set()
    if len(set(source_splits.values())) != 1:
        blockers.add("MIXED_EVALUATION_SPLITS")
    if len(pairs) != len(arms) * len(fits) * len(cases):
        blockers.add("INCOMPLETE_MATCHED_ROSTER")
    if len(operations) != len(fits):
        blockers.add("ALIASED_TRAINING_OPERATIONS")
    coverage = document["cost_coverage"]
    if not isinstance(coverage, dict) or set(coverage) - set(planned):
        raise ValueError("cost coverage contains unregistered attempts")
    observed, counts, incomplete_cost_arms = set(), Counter(), set()
    for row in rows:
        attempt_id = row["attempt_id"]
        if attempt_id in observed or attempt_id not in planned:
            raise ValueError("duplicate or unplanned observed attempt")
        if any(
            row[key] != planned[attempt_id][key] for key in ("arm", "fit_id", "case_id")
        ):
            raise ValueError("observed attempt changed its statistical unit")
        observed.add(attempt_id)
        counts[row["status"]] += 1
        scopes = coverage.get(attempt_id, {})
        if not isinstance(scopes, dict) or set(scopes) - set(cost_categories):
            raise ValueError("unknown cost coverage category")
        for category in cost_categories:
            status = scopes.get(category, "unknown")
            value = row["costs"].get(category)
            if status not in {"measured", "not_applicable", "unknown"}:
                raise ValueError("unknown cost coverage status")
            if status == "not_applicable" and value != 0:
                raise ValueError("inapplicable cost must be explicitly zero")
            if status == "unknown" or value is None:
                incomplete_cost_arms.add(row["arm"])
    missing = sorted(set(planned) - observed)
    counts["not_observed"] = len(missing)
    if missing:
        blockers.add("MISSING_PLANNED_ATTEMPTS")
        incomplete_cost_arms.update(planned[attempt]["arm"] for attempt in missing)
    if incomplete_cost_arms:
        blockers.add("INCOMPLETE_COST_COVERAGE")
    used_initializations = {fit["initialization_sha256"] for fit in fits.values()}
    groups = len(source_splits)
    families = len({case["task_family"] for case in cases.values()})
    if sampling_spec is None:
        blockers.add("MISSING_SAMPLING_PLAN")
    else:
        for count, key in (
            (groups, "minimum_source_groups"),
            (families, "minimum_task_families"),
            (len(used_initializations), "minimum_model_initializations"),
        ):
            if count < sampling_spec[key]:
                blockers.add("INSUFFICIENT_" + key.removeprefix("minimum_").upper())
    result = {
        "planned_attempts": len(planned),
        "observed_attempts": len(observed),
        "attempt_counts": dict(counts),
        "unobserved_attempt_ids": missing,
        "natural_source_groups": groups,
        "task_families": families,
        "model_initializations": len(used_initializations),
        "training_operations": len(operations),
        "fit_ids": len(fits),
        "sample_count_is_product": False,
        "independence_verified": False,
        "source_exposure_verified": False,
        "full_cost_recorded": not incomplete_cost_arms,
        "incomplete_cost_arms": sorted(incomplete_cost_arms),
        "cost_authenticity_verified": False,
        "blockers": sorted(blockers),
    }
    if task_bound:
        result.update(
            task_artifact_bytes_verified=True,
            distinct_task_artifacts=len(task_units),
            task_semantics_verified=False,
        )
    return result


def balanced_fit_means(units, cases, baseline):
    """Weight sources, families and bound tasks equally within each fit.

    V2 repetitions refine their original task's mean, without increasing that
    task's weight relative to other tasks in the same source and family. V1 has
    no task-byte binding and retains its existing per-case weighting. Raw
    attempts, statuses and costs are accounted for separately and are not removed.
    """
    case_map = {case["case_id"]: case for case in cases}
    values = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    )
    for (fit, case_id), unit in units.items():
        case = case_map[case_id]
        task = case["task_artifact"]["sha256"] if "task_artifact" in case else case_id
        candidate, control = unit["candidate"], unit[baseline]
        values[fit][case["source_group_id"]][case["task_family"]][task].append(
            tuple(candidate[key] - control[key] for key in ("net_utility", "retention"))
        )
    return [
        tuple(
            fmean(
                fmean(
                    fmean(fmean(row[index] for row in rows) for rows in tasks.values())
                    for tasks in families.values()
                )
                for families in sources.values()
            )
            for index in range(2)
        )
        for sources in values.values()
    ]
