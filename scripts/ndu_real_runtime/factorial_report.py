"""Prospective descriptive output-portfolio panels; never an adoption gate.

Freeze this module in a new PILOT_PLAN before running episodes. Historical
analysis policies and results keep their original source bindings.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from ndu_real_materials.common import strict_json
from .causal_analysis import paired_contrast
from .causal_protocol import b_contrasts, digest
from .metering import atomic_json, file_sha


FAMILIES = (
    "text_sufficient",
    "text_image_complementary",
    "selective_refinement",
    "preparation_required",
    "continuation_not_worthwhile",
)
PRIMARY = {
    "B-A": "ndu_in_ordinary",
    "D-C": "ndu_in_hepta",
    "C-A": "hepta_under_light",
    "D-B": "hepta_under_ndu",
    "(D-C)-(B-A)": "kernel_controller_interaction",
}
REQUIRED_SOURCES = frozenset(
    {
        "scripts/ndu_real_runtime/" + name + ".py"
        for name in (
            "__init__",
            "factorial_report",
            "causal_analysis",
            "causal_protocol",
            "metering",
            "span_meter",
        )
    }
    | {"scripts/ndu_real_materials/__init__.py", "scripts/ndu_real_materials/common.py"}
)


def build_report(plan, selected, rows, *, draws=2000):
    """Keep the whole planned panel even when a favorable subgroup is complete."""
    design = plan["design"]
    roster = plan["independent_fit_roster"]
    fits = {row["fit_id"]: row["training_seed"] for row in roster}
    if (
        not fits
        or len(fits) != len(roster)
        or any(not isinstance(identity, str) or not identity for identity in fits)
        or any(type(seed) is not int or not 0 <= seed < 2**32 for seed in fits.values())
        or len(set(fits.values())) != len(fits)
        or list(fits.values()) != design["training_seeds"]
    ):
        raise ValueError("Distinct planned training repeats are required")
    modes = design.get(
        "memory_modes", [design["controller"].get("memory_mode", "reset")]
    )
    regimes = design["regimes"]
    if (
        not modes
        or len(set(modes)) != len(modes)
        or not set(modes) <= {"reset", "persistent"}
        or not regimes
        or len(set(regimes)) != len(regimes)
        or not set(regimes) <= {"frozen", "joint"}
    ):
        raise ValueError("Explicit nonduplicated regimes and memory modes required")
    mapping = {}
    for arm, spec in design["arms"].items():
        if len(spec) not in (2, 3):
            raise ValueError("An arm must bind core, controller and state mode")
        mode = (
            spec[2]
            if len(spec) == 3
            else design["controller"].get("memory_mode", "reset")
        )
        if mode not in modes:
            raise ValueError("Arm state mode differs from frozen design")
        mapping[arm] = "/".join([*spec[:2], mode])
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Different arm names cannot alias the same condition")
    all_groups = [group for values in selected["groups"].values() for group in values]
    if len(all_groups) != len(set(all_groups)):
        raise ValueError("A source group crosses frozen acquisition roles")
    cases, by_split, coverage = {}, {}, {}
    for category, split, required in (
        ("pilot_new", "development", FAMILIES),
        ("pilot_retention", "retention_validation", ("retention",)),
    ):
        chosen = []
        for case in selected["cases"][category]:
            if (
                case["id"] in cases
                or case["role"] != split
                or case["source_id"] not in selected["groups"][category]
                or case["task_family"] not in required
            ):
                raise ValueError(
                    "Case differs from frozen source, split or required family"
                )
            mapped = {
                "case_id": case["id"],
                "source_group_id": case["source_id"],
                "split": split,
                "task_family": case["task_family"],
            }
            cases[case["id"]] = mapped
            chosen.append(mapped)
        by_split[split] = chosen
        missing = {
            group: sorted(
                set(required)
                - {
                    case["task_family"]
                    for case in chosen
                    if case["source_group_id"] == group
                }
            )
            for group in selected["groups"][category]
        }
        coverage[split] = {
            "planned_cases": len(chosen),
            "planned_source_groups": len(missing),
            "planned_cases_by_family": dict(
                Counter(case["task_family"] for case in chosen)
            ),
            "missing_families_by_source": missing,
            "required_roster_coverage": bool(missing)
            and all(not value for value in missing.values()),
        }
    mapped_rows, operations = [], set()
    for row in rows:
        if (
            row.get("fit_id") not in fits
            or row.get("arm") not in mapping
            or row.get("case_id") not in cases
            or row.get("regime") not in regimes
            or row.get("training_seed") != fits[row["fit_id"]]
            or row.get("estimand") != design.get("estimand", "legacy_pilot")
        ):
            raise ValueError("Result crosses the frozen fit, arm, case or estimand")
        condition = mapping[row["arm"]]
        if (
            any(row.get(k) != v for k, v in cases[row["case_id"]].items())
            or "/".join(row[k] for k in ("core", "controller", "memory_mode"))
            != condition
        ):
            raise ValueError("Result changed its planned family or trained condition")
        identity = row.get("original_operation_id")
        if identity is not None:
            if not isinstance(identity, str) or not identity or identity in operations:
                raise ValueError("Duplicate or invalid original operation")
            operations.add(identity)
        if row.get("terminal_status") in {"Completed", "Failed"} and identity is None:
            raise ValueError("A resolved outcome needs its original operation")
        mapped_rows.append({**row, "condition_id": condition})
    contrasts, comparisons = b_contrasts(), []
    for regime in regimes:
        for mode in modes:
            weights = {
                name: contrasts[f"{key}/{mode}"] for name, key in PRIMARY.items()
            }
            weights.update(
                {
                    name: value
                    for name, value in contrasts.items()
                    if name.startswith("ndu_vs_") and name.endswith("/" + mode)
                }
            )
            for split, chosen in by_split.items():
                panels = {"overall": chosen}
                if split == "development":
                    panels.update(
                        {
                            family: [
                                case for case in chosen if case["task_family"] == family
                            ]
                            for family in FAMILIES
                        }
                    )
                for panel, selected_cases in panels.items():
                    selected_ids = {case["case_id"] for case in selected_cases}
                    partition = [
                        row
                        for row in mapped_rows
                        if row["regime"] == regime and row["case_id"] in selected_ids
                    ]
                    for name, coefficients in weights.items():
                        result = (
                            paired_contrast(
                                partition,
                                coefficients,
                                list(fits),
                                selected_cases,
                                draws=draws,
                            )
                            if selected_cases
                            else {
                                "status": "NO_PLANNED_CASES",
                                "planned_rows": 0,
                                "observed_rows": 0,
                                "mean": None,
                                "interval": None,
                                "scientific_acceptance": "HOLD",
                                "confirmatory_use": False,
                            }
                        )
                        comparisons.append(
                            {
                                "regime": regime,
                                "memory_mode": mode,
                                "split": split,
                                "panel": panel,
                                "contrast": name,
                                "coefficients": coefficients,
                                "descriptive": result,
                            }
                        )
    return {
        "schema": "ndu.real.factorial-panels.v1",
        "independent_training_repeats": len(fits),
        "arm_mapping": mapping,
        "coverage": coverage,
        "comparisons": comparisons,
        "overall_panel_is_primary": True,
        "family_panels_replace_overall": False,
        "family_panel_scope": "descriptive localization only; no subgroup acceptance or multiplicity-adjusted claim",
        "retention_scope": "planned retention tasks only; equal zero scores do not establish retained capability",
        "utility_scope": "caller-supplied frozen analysis_utility; not total improvement efficiency",
        "budget_stop_policy": "unadapted BudgetStop remains unknown; never silently dropped",
        "energy_joules": None,
        "provider_charges": None,
        "full_cost_adjusted": False,
        "provider_authenticity_verified": False,
        "prospective_registration_authenticated": False,
        "confirmatory_use": False,
        "scientific_acceptance": "HOLD",
        "adoption_authorized": False,
    }


def generate(root, expected_plan_sha256, expected_rows_sha256, *, draws=2000):
    """Require this analysis and its dependencies in the original source freeze."""
    root = Path(root)
    paths = {
        name: root / name
        for name in (
            "PILOT_PLAN.json",
            "selected-sources.json",
            "selection-lock.json",
            "paired-rows.jsonl",
        )
    }
    if not digest(expected_plan_sha256) or not digest(expected_rows_sha256):
        raise ValueError("Expected plan and original paired-row digests required")
    raw = {}
    for name, path in paths.items():
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size > 256 * 1024 * 1024
        ):
            raise ValueError("Bounded regular evidence files required")
        raw[name] = path.read_bytes()
    pins = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    if (
        pins["PILOT_PLAN.json"] != expected_plan_sha256
        or pins["paired-rows.jsonl"] != expected_rows_sha256
    ):
        raise ValueError("Plan or paired rows differ from expected bytes")
    plan = strict_json(raw["PILOT_PLAN.json"])
    selected = strict_json(raw["selected-sources.json"])
    lock = strict_json(raw["selection-lock.json"])
    if (
        plan["selected_sources_sha256"] != pins["selected-sources.json"]
        or lock["pilot_plan_sha256"] != expected_plan_sha256
    ):
        raise ValueError("Selected sources or comparison lock differ from frozen plan")
    repository = Path(__file__).resolve().parents[2]
    original_root = Path(plan["execution"]["repository_root"])
    verified = {}
    for pin in plan["source_pins"]:
        named = Path(pin["path"])
        relative = named.relative_to(original_root) if named.is_absolute() else named
        target = repository / relative
        if (
            ".." in relative.parts
            or relative.as_posix() in verified
            or not target.resolve().is_relative_to(repository)
        ):
            raise ValueError("Invalid or duplicate frozen source path")
        if target.stat().st_size != pin["bytes"] or file_sha(target) != pin["sha256"]:
            raise ValueError(
                "Current analysis or execution source differs from frozen plan"
            )
        verified[relative.as_posix()] = pin["sha256"]
    if not REQUIRED_SOURCES <= set(verified):
        raise ValueError(
            "This analysis was not prospectively frozen; historical reports stay unchanged"
        )
    lines = raw["paired-rows.jsonl"].splitlines()
    if len(lines) > 100000 or any(
        not line or len(line) > 2 * 1024 * 1024 for line in lines
    ):
        raise ValueError("Bounded original paired rows required")
    rows = [strict_json(line) for line in lines]
    profiles = {
        choice["profile"]["profile_id"]: choice["profile"]
        for choice in lock["selected"]
    }
    if len(profiles) != len(lock["selected"]) or any(
        not digest(profile.get(key))
        for profile in profiles.values()
        for key in ("model_sha256", "policy_sha256")
    ):
        raise ValueError(
            "Unique selected profiles with model and policy digests required"
        )
    for row in rows:
        if row.get("profile_id") is None and row.get("terminal_status") not in {
            "Completed",
            "Failed",
            "BudgetStop",
        }:
            continue
        profile = profiles.get(row.get("profile_id"))
        if (
            profile is None
            or row.get("selection_lock_sha256") != pins["selection-lock.json"]
            or any(
                row.get(key) != profile.get(key)
                for key in ("fit_id", "regime", "arm", "model_sha256", "policy_sha256")
            )
        ):
            raise ValueError("Original row does not bind the frozen selected profile")
    report = build_report(plan, selected, rows, draws=draws)
    if any(
        file_sha(paths[name]) != digest_value for name, digest_value in pins.items()
    ) or any(
        file_sha(repository / relative) != value for relative, value in verified.items()
    ):
        raise ValueError("Frozen evidence or source changed during analysis")
    return {**report, "input_sha256": pins, "verified_source_sha256": verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--expected-rows-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--draws", default=2000, type=int)
    args = parser.parse_args()
    report = generate(
        args.root,
        args.expected_plan_sha256,
        args.expected_rows_sha256,
        draws=args.draws,
    )
    pin = atomic_json(args.output, report)
    print(json.dumps({"report_sha256": pin, "scientific_acceptance": "HOLD"}))


if __name__ == "__main__":
    main()
