"""Unified descriptive review behind the unchanged original complete-review gate.

Register this additive source closure before real use. The original scientific
freeze, populations, analyses and thresholds remain unchanged. Source identities
reported here identify the observed files; they do not replace preregistration.
"""

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from operational.parameter_field_five_questions_20261031 import postseal_analysis_coverage as coverage
from supplements.parameter_field_execution_20261031 import p0_actions, p1_interpretation


SCHEMA = "hepta.parameter-field.unified-postseal-review.1"


@contextmanager
def measured(timings, name):
    wall, cpu = time.monotonic(), time.process_time()
    try:
        yield
    finally:
        timings[name] = {"wall_seconds": time.monotonic()-wall, "cpu_seconds": time.process_time()-cpu}


def implementation_sources():
    root = Path(__file__).resolve().parents[2]
    paths = [Path(module.__file__).resolve() for module in (coverage, p0_actions, p1_interpretation)]
    paths += [Path(__file__).resolve(), root / "operational/parameter_field_five_questions_20261031/finite_head_guard.py"]
    return [{"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for path in sorted(paths) for raw in (path.read_bytes(),)]


def assemble(aggregate, review, audit, p0):
    """Combine admitted original results; do not derive unmeasured activity."""
    coverage.need(p0.get("status") in ("DESCRIPTIVE_COMPLETE", "ORIGINAL_INTEGRITY_ISSUES"),
                  "P0 diagnostics have not completed")
    issues = review.get("integrity_issues")
    integrity = "unknown"
    if issues is not None:
        count = issues.get("issue_count")
        coverage.need(type(count) is int and count >= 0, "Original integrity issue count is invalid")
        integrity = "failed" if count else "passed"
        coverage.need((p0["status"] == "ORIGINAL_INTEGRITY_ISSUES") is (count > 0),
                      "P0 and original review integrity dispositions differ")
    deficits = audit.get("cost_coverage_deficiencies")
    complete = audit.get("declared_cost_rows_complete")
    cost = "unknown"
    cost_scope = audit.get("coverage_scope", "Current cost coverage has not been supplied")
    if deficits is not None and complete is not None:
        coverage.need(type(deficits) is list and all(type(x) is str for x in deficits)
                      and type(complete) is bool and complete == (not deficits), "Cost coverage disposition differs")
        cost = "complete" if complete else "partial"
    analyses = aggregate["formal_analyses"]
    coverage.need(set(analyses) == {"B", "C"}, "Both original formal analyses are required")
    gates = {stage: deepcopy(analyses[stage]["statistical_thresholds"]) for stage in ("B", "C")}
    interpretations = {}
    for stage in ("B", "C"):
        evidence = {
            "integrity": {"status": integrity,
                "scope": "Original review issue count and additive structural checks only; no efficacy certification."},
            "activity": {"status": "unknown",
                "scope": stage + " deployment activity is not inferred from A/C calibration choices or effect intervals."},
            "cost_coverage": {"status": cost, "scope": cost_scope,
                "deficiencies": deepcopy(deficits), "historical_total_remains_unknown": True},
        }
        interpretations[stage] = p1_interpretation.interpret(stage, analyses[stage], evidence_context=evidence)
        coverage.need(interpretations[stage]["registered_statistical_thresholds"] == gates[stage]
                      and analyses[stage]["statistical_thresholds"] == gates[stage], "An original statistical gate changed")
    status = ("ORIGINAL_INTEGRITY_ISSUES" if integrity == "failed" else
              "EVIDENCE_CONTEXT_INCOMPLETE" if integrity == "unknown" or cost == "unknown" else
              "COST_COVERAGE_INCOMPLETE" if cost == "partial" else "DESCRIPTIVE_COMPLETE")
    return {"schema": SCHEMA, "status": status, "P0": p0, "interpretations": interpretations,
            "coverage_audit": audit, "original_statistical_gates": gates,
            "original_review_integrity": deepcopy(issues), "consumed_inputs": deepcopy(p0["consumed_inputs"]),
            "original_full_source_seal_gate_reentered": True, "source_registration_required_before_real_use": True,
            "scientific_inputs_modified": False, "scientific_efficacy_conclusion_assigned": False,
            "new_training_scoring_refitting": False, "new_bootstrap_or_threshold": False,
            "adoption": "not_assessed", "unconditional_net_benefit": "not_assessed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-complete")
    parser.add_argument("--expected-review-complete-sha256")
    args = parser.parse_args(argv)
    timings, admitted, gate_called = {}, False, False
    wall, cpu = time.monotonic(), time.process_time()
    if not args.review_complete or not re.fullmatch(r"[0-9a-f]{64}", args.expected_review_complete_sha256 or ""):
        print(json.dumps({"schema": SCHEMA, "status": "NOT_EVALUATED", "scientific_payloads_decoded": False,
            "reason": "Actual original review completion and externally held SHA256 are required."}))
        return 2
    try:
        with measured(timings, "implementation_identity"):
            sources = implementation_sources()
        with measured(timings, "original_gate_and_bound_review_read"):
            gate_called = True
            aggregate, review, provenance, context = coverage.read_after_review_complete(
                args.review_complete, args.expected_review_complete_sha256)
            admitted = True
        with measured(timings, "original_analysis_and_cost_coverage"):
            audit = coverage.aggregate_checks(aggregate)
        with measured(timings, "P0_sealed_calibration_and_successor_diagnostics"):
            p0 = p0_actions.analyze(context)
        with measured(timings, "B_C_descriptive_interpretation"):
            result = assemble(aggregate, review, audit, p0)
        with measured(timings, "final_input_and_source_stability"):
            context["inputs"].unchanged()
            for descriptor in provenance.values():
                coverage.checked_bytes(descriptor)
            coverage.need(implementation_sources() == sources, "Additive implementation bytes changed during review")
        result.update(gate_input_descriptors=provenance, implementation_sources=sources)
        code = 0 if result["status"] == "DESCRIPTIVE_COMPLETE" else 3
    except (ValueError, KeyError, TypeError, OSError, ImportError, OverflowError, FloatingPointError) as error:
        result = {"schema": SCHEMA, "status": "INTEGRITY_FAILURE" if admitted else "NOT_EVALUATED",
                  "reason": str(error), "original_gate_call_returned_successfully": admitted,
                  "scientific_payload_access": "admitted_by_original_gate" if admitted else
                  "not_established_after_original_gate_call_failure" if gate_called else "not_attempted",
                  "scientific_inputs_modified": False, "new_training_scoring_refitting": False}
        code = 2
    result["timing"] = {"components": timings,
        "enclosing_total_before_output_serialization": {"wall_seconds": time.monotonic()-wall,
                                                       "cpu_seconds": time.process_time()-cpu},
        "components_are_disjoint": True, "enclosing_total_is_not_additive_to_components": True,
        "enclosing_total_scope": "After module imports and CLI parsing; excludes startup, output serialization and receipt writes. External wait4 is authoritative for inclusive process cost.",
        "cpu_scope": "This process; an external wait4 wrapper owns inclusive child/campaign accounting.",
        "diagnostic_cost_is_not_added_to_original_scientific_outcomes": True}
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False), file=sys.stderr if code == 2 else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
