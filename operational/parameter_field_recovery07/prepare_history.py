"""Create a new cost-only projection; never fabricate or copy a prior completion receipt."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


def identity(path):
    path = Path(path)
    raw = path.read_bytes()
    return {
        "name": path.name,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def build(original_source, a17_complete, failure04, forensics05):
    source = Path(original_source)
    parser_path = source / "operational/parameter_field_recovery04/historical_costs.py"
    contract = json.loads(Path(__file__).with_name("INPUT_CONTRACT.json").read_text())
    if (
        identity(parser_path)["sha256"]
        != contract["source_files"][
            "operational/parameter_field_recovery04/historical_costs.py"
        ]
    ):
        raise ValueError("Original metadata-only parser identity differs")
    spec = importlib.util.spec_from_file_location(
        "original_cost_metadata_parser", parser_path
    )
    parser_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser_module)

    def selected(path, selection):
        before = identity(path)
        text = Path(path).read_text()
        parser = parser_module._MetadataProjection(text)
        value, end = parser.value(0, selection)
        if parser.ws(end) != len(text) or identity(path) != before:
            raise ValueError("Historical cost metadata changed or is malformed")
        return value, before

    study = source / "experiments/parameter_field_fullstudy_20261029/evidence"
    old, old_source = selected(
        study / "REPORT_INPUTS_BLOCKED.json",
        {
            "schema": True,
            "engineering_preflights": True,
            "failed_attempts": True,
            "integrity": True,
        },
    )
    summary, summary_source = selected(
        study / "ENGINEERING_SUMMARY.json",
        {"schema": True, "preflights": [{"source": True, "gradient_microsteps": True}]},
    )
    if (
        old_source["sha256"]
        != "2848a9fc4b3092b79c3bff158b4c966bce5941760c0ea531eb7b4cb45c31c785"
        or not old["integrity"]["historical_exact_regression_gate"].startswith("FAIL")
        or [r["source"] for r in summary["preflights"]] != old["engineering_preflights"]
        or [r["gradient_microsteps"] for r in summary["preflights"]] != [432, 432]
    ):
        raise ValueError("Original historical integrity or summary identity differs")
    rows = [
        {
            "episode": "original_engineering_preflights",
            "gradient_microsteps_lower_bound": 864,
            "evidence_tier": "public summary; original completed receipts unavailable",
            "source": summary_source,
            "source_fields": ["preflights[*].gradient_microsteps"],
            "original_receipt_impersonation": False,
        },
        {
            "episode": "attempt01",
            "gradient_microsteps_lower_bound": sum(
                r["training_microsteps_lower_bound"] for r in old["failed_attempts"]
            ),
            "evidence_tier": "original registered failure lower bound",
            "source": old_source,
            "source_fields": ["failed_attempts[*].training_microsteps_lower_bound"],
            "original_receipt_impersonation": False,
        },
    ]
    for episode, expected in (("EPISODE02", 576), ("EPISODE03", 78336)):
        path = (
            source
            / f"operational/parameter_field_recovery04/evidence/{episode}_COST_FACTS.json"
        )
        value, item = selected(
            path,
            {"scheduled_microsteps_lower_bound": True, "unknown_additional_work": True},
        )
        if (
            value["scheduled_microsteps_lower_bound"] != expected
            or value["unknown_additional_work"] is not True
        ):
            raise ValueError("Prior episode cost fact differs")
        rows.append(
            {
                "episode": episode.lower(),
                "gradient_microsteps_lower_bound": expected,
                "evidence_tier": "previously registered historical observation; incomplete original evidence",
                "source": item,
                "source_fields": ["scheduled_microsteps_lower_bound"],
                "original_receipt_impersonation": False,
            }
        )
    cost_selection = {
        "complete": True,
        "costs": {"scheduled_gradient_microsteps": True},
        "wall_seconds": True,
        "cpu_seconds": True,
        "registered_commit": True,
        "source_freeze_sha256": True,
    }
    for episode, path, expected, complete in (
        ("execution04_completed_A17", a17_complete, 39168, True),
        ("execution04_failed_A29", failure04, 14784, False),
    ):
        value, item = selected(path, cost_selection)
        if (
            value["complete"] is not complete
            or value["costs"]["scheduled_gradient_microsteps"] != expected
        ):
            raise ValueError("Actual previous stage cost metadata differs")
        rows.append(
            {
                "episode": episode,
                "gradient_microsteps_lower_bound": expected,
                "evidence_tier": "new cost-only extraction from surviving original metadata",
                "source": item,
                "source_fields": ["costs.scheduled_gradient_microsteps"],
                "recorded_stage_cpu_seconds": value.get("cpu_seconds"),
                "recorded_stage_wall_seconds": value.get("wall_seconds"),
                "original_receipt_impersonation": False,
            }
        )
    value, item = selected(
        forensics05,
        {
            "schema": True,
            "failure_cost_only_projection": True,
            "outcomes_or_weights_decoded": True,
            "unknown_unwritten_work_retained": True,
        },
    )
    facts = value["failure_cost_only_projection"]
    if (
        value["schema"] != "hepta.execution05.failed-A29-cost-forensics.1"
        or value["outcomes_or_weights_decoded"] is not False
        or facts["costs"]["scheduled_gradient_microsteps"] != 17280
    ):
        raise ValueError("Execution05 cost-only forensic source differs")
    rows.append(
        {
            "episode": "execution05_failed_A29",
            "gradient_microsteps_lower_bound": 17280,
            "evidence_tier": "existing cost-only failure forensics",
            "source": item,
            "source_fields": [
                "failure_cost_only_projection.costs.scheduled_gradient_microsteps"
            ],
            "recorded_stage_cpu_seconds": facts["cpu_seconds"],
            "recorded_stage_wall_seconds": facts["wall_seconds"],
            "original_receipt_impersonation": False,
        }
    )
    total = sum(r["gradient_microsteps_lower_bound"] for r in rows)
    if total != 253328:
        raise ValueError("Nonoverlapping historical gradient subtotal differs")
    return {
        "schema": "hepta.execution07.historical-cost-projection.1",
        "original_integrity": old["integrity"],
        "rows": rows,
        "gradient_microsteps_known_lower_bound": total,
        "original_historical_input": old_source,
        "parser_source": identity(parser_path),
        "original_receipts_bundled": False,
        "current_executor_reverification_scope": "Committed projection bytes only; original sources were checked when this new projection was created.",
        "unknown_additional_work": True,
        "whole_history_cpu_or_wall_total_known": False,
        "execution06_new_work_or_cpu_total": "unknown; do not infer zero from surviving registration/import metadata",
        "completed_A17_counted_once": "Original execution04 A17 was imported into 05/06 without adding its work again; fresh execution07 A17 is a separate actual cost.",
        "scientific_values_decoded": False,
        "new_independent_samples": 0,
        "old_completion_claim_created": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "original-source",
        "a17-complete",
        "failure04",
        "forensics05",
        "output",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    value = build(
        args.original_source, args.a17_complete, args.failure04, args.forensics05
    )
    with Path(args.output).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
