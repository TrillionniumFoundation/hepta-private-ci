"""Explicit follow-up protocols; old MEM12 plans keep their original endpoint.

MEM14 is a new study after a MEM12 measurement problem was observed. Its public
parser has no expected-label input. It never relabels an existing MEM12 plan.
"""

import copy
import math
import re

LEGACY_SCHEMA = "hepta.mem12.controlled-diagnostic.v1"
FOLLOWUP_SCHEMA = "hepta.mem14.controlled-diagnostic.v1"
SELECTORS = {
    "v1": "mem12-full-output-color-v1; independent of MEM5 OCR public_rule",
    "v2": "mem14-full-output-color-or-courier-sentence-v2; independent of MEM5 OCR public_rule",
}
FIXED_LIMITS = {
    "context_bytes": 2048,
    "output_tokens": 32,
    "input_tokens": 1024,
    "provider_seconds": 60,
}
ANALYSIS = {
    "primary_contrast": "on_bm25 minus off",
    "alpha": 0.05,
    "simultaneous_contrasts": 9,
    "method": "one-sided Hoeffding; Bonferroni for all nine contrasts",
    "difference_range": [-1, 1],
    "population": "independent fresh generated sources under one fixed task template",
    "missing": "use conservative per-source difference bounds; retain planned denominator",
}


def protocol_fields(source_count=8, retrieval_records=2, selector_version="v1"):
    """Only explicit non-default choices create the independent MEM14 schema."""
    if (
        type(source_count) is not int
        or source_count not in (8, 32)
        or type(retrieval_records) is not int
        or retrieval_records not in (1, 2)
        or not isinstance(selector_version, str)
        or selector_version not in SELECTORS
    ):
        raise ValueError("supported source count, record cap and selector required")
    legacy = (source_count, retrieval_records, selector_version) == (8, 2, "v1")
    fields = {
        "schema": LEGACY_SCHEMA if legacy else FOLLOWUP_SCHEMA,
        "selector": SELECTORS[selector_version],
        "limits": {**FIXED_LIMITS, "retrieval_records": retrieval_records},
    }
    if not legacy:
        fields.update(
            source_count=source_count,
            selector_version=selector_version,
            analysis=copy.deepcopy(ANALYSIS),
        )
    return fields


def selector_version(plan):
    """Legacy schemas cannot acquire v2 by adding or relabeling a version field."""
    if plan.get("schema") == LEGACY_SCHEMA:
        if "selector_version" in plan or "source_count" in plan:
            raise ValueError("legacy plans cannot claim follow-up protocol fields")
        version = "v1"
    elif plan.get("schema") == FOLLOWUP_SCHEMA:
        version = plan.get("selector_version")
    else:
        raise ValueError("unknown diagnostic schema")
    if not isinstance(version, str) or version not in SELECTORS:
        raise ValueError("unknown frozen selector version")
    if plan.get("selector") != SELECTORS[version]:
        raise ValueError("selector identity differs from its frozen version")
    return version


def validate_protocol(plan, arms):
    """Reject changed denominators, per-arm rosters and budget interpretations."""
    version = selector_version(plan)
    legacy = plan["schema"] == LEGACY_SCHEMA
    count = 8 if legacy else plan.get("source_count")
    limits = plan.get("limits")
    if not isinstance(limits, dict) or any(
        type(value) is not int for value in limits.values()
    ):
        raise ValueError("typed frozen limits required")
    records = 2 if legacy else limits.get("retrieval_records")
    expected = protocol_fields(count, records, version)
    if (
        plan["schema"] != expected["schema"]
        or limits != expected["limits"]
        or plan.get("analysis") != expected.get("analysis")
        or plan.get("arms") != {name: list(value) for name, value in arms.items()}
        or not isinstance(plan.get("cases"), list)
        or len(plan["cases"]) != count
    ):
        raise ValueError("frozen protocol count, limits or arms changed")
    for index, case in enumerate(plan["cases"], 1):
        case_id = f"source-{index:02d}"
        if (
            not isinstance(case, dict)
            or case.get("case_id") != case_id
            or case.get("source_id") != case_id
            or not isinstance(case.get("arm_order"), list)
            or len(case["arm_order"]) != len(arms)
            or any(not isinstance(name, str) for name in case["arm_order"])
            or set(case["arm_order"]) != set(arms)
        ):
            raise ValueError("source roster or complete arm order changed")


def selected_v2(value):
    """Accept one color, bare UNKNOWN, or exactly the preregistered sentence."""
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    colors = r"red|orange|yellow|green|blue|purple|pink|white"
    word = re.fullmatch(r"(" + colors + r"|unknown)", value)
    if word is not None:
        return word[1]
    sentence = re.fullmatch(r"the courier must use a (" + colors + r") badge\.", value)
    return None if sentence is None else sentence[1]


def hoeffding_lower(lower_mean, source_count, *, family_size=1):
    """Bound independent source-paired D in [-1,1], after conservative missingness."""
    radius = math.sqrt(2 * math.log(family_size / ANALYSIS["alpha"]) / source_count)
    return max(-1.0, lower_mean - radius)
