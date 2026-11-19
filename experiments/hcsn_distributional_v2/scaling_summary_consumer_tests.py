"""Narrow real-metadata and negative-contract checks for final scaling closure."""

import argparse
import copy
import json
from pathlib import Path
import sys

from . import archive_closure as base
from . import archive_closure_final as final
from . import final_bundle_plan as planner


PACKAGE = Path(__file__).resolve().parent


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    originals = ("archive_closure.py", "lif_cost_receipts.py", "scaling_admission.py", "scaling_summary_repair.py",
        "SCALING002_PROTOCOL.json", "results/lif_cost_receipts001/RECEIPTS.json",
        "results/lif_cost_normalization001/EXECUTION.json", "results/scaling002/SUITE_EXECUTION.json",
        "results/scaling002_summary_repair001/COMPLETE.json", "results/content_analysis002/ANALYSIS.json")
    before = {name: base.file_hash(PACKAGE / name) for name in originals}
    tests = []
    for name in ("prerequisites", "audit_bundle", "verify_selection", "audit_run_inventory"):
        assert getattr(final.ClosureAudit, name) is getattr(base.ClosureAudit, name)
    tests.append(dict(case="main_lif_archive_checks_are_inherited", status="passed"))
    auditor = final.ClosureAudit(PACKAGE)
    main, lif, _, proofs = auditor.prerequisites()
    assert len(main["jobs"]) == 176 and len(lif["jobs"]) == 18
    assert auditor.main_analysis_admission["original_strict"]["gate_passed"] is False
    assert auditor.main_analysis_admission["supplemental"]["valid"] == 176
    tests.append(dict(case="actual_original_and_supplemental_main_and_lif_metadata", status="passed"))
    scaling = auditor.audit_scaling()
    repair = auditor.scaling_summary_repair
    assert len(scaling["rows"]) == 30 and scaling["successful"] == 30 and scaling["failed"] == 0
    assert repair["original_suite"]["returncode"] == 1 and repair["repair_outer"]["returncode"] == 0
    tests.append(dict(case="actual_30_original_workers_and_independent_repair_verified", status="passed",
                      zero_medians=repair["zero_timing_medians"], undefined_ratios=repair["undefined_ratios"]))

    def reject(name, operation):
        try:
            operation()
        except (ValueError, KeyError) as error:
            tests.append(dict(case=name, status="passed", rejection=str(error)))
        else:
            raise AssertionError("Invalid scaling identity accepted: " + name)

    protocol = base.read_json(PACKAGE / "SCALING002_PROTOCOL.json")
    suite = base.read_json(PACKAGE / "results/scaling002/SUITE_EXECUTION.json")
    forged = dict(suite, returncode=0)
    reject("original_suite_cannot_be_relabelled_success", lambda: final.verify_original_failed_suite(
        forged, base.file_hash(PACKAGE / "SCALING002_PROTOCOL.json"), protocol["source_files_sha256"]))
    forged = dict(suite, complete_receipt_sha256="0"*64)
    reject("original_suite_cannot_claim_new_completion", lambda: final.verify_original_failed_suite(
        forged, base.file_hash(PACKAGE / "SCALING002_PROTOCOL.json"), protocol["source_files_sha256"]))
    summary = base.read_json(PACKAGE / "results/scaling002_summary_repair001/SUMMARY.json")
    nulls = [(index, key) for index, row in enumerate(summary["measured_fixed_width_depth_changes"])
             for key, value in row.items() if key.endswith("_ratio_to_16") and value is None]
    assert nulls
    changed = copy.deepcopy(summary)
    index, key = nulls[0]
    changed["measured_fixed_width_depth_changes"][index][key] = 0.0
    reject("zero_denominator_cannot_receive_a_fabricated_zero_ratio", lambda: final.validate_summary_ratios(changed))
    changed = copy.deepcopy(summary)
    changed["measured_fixed_width_depth_changes"][index]["undefined_ratio_reasons"].pop(key)
    reject("undefined_ratio_requires_a_reason", lambda: final.validate_summary_ratios(changed))
    changed = copy.deepcopy(summary)
    candidates = [(i, key) for i, row in enumerate(changed["measured_fixed_width_depth_changes"])
                  for key, value in row.items() if key.endswith("_ratio_to_16") and key != "length_ratio_to_16"
                  and value is not None]
    i, key = candidates[0]
    changed["measured_fixed_width_depth_changes"][i][key] += 1
    reject("nonzero_ratio_must_equal_original_values", lambda: final.validate_summary_ratios(changed))
    changed = copy.deepcopy(summary)
    changed["measured_fixed_width_depth_changes"].pop()
    reject("summary_ratio_panel_cannot_omit_a_case", lambda: final.validate_summary_ratios(changed))
    assert planner.ClosureAudit is final.ClosureAudit
    for name in ("archive_closure_final.py", "ARCHIVE_CLOSURE_FINAL.md"):
        assert planner.exclusion(name)
    for name in ("results/scaling002_summary_repair001/COMPLETE.json",
                 "results/scaling002_summary_repair001_execution/EXECUTION.json",
                 "results/scaling_summary_consumer005/before/archive_closure.py"):
        assert planner.exclusion(name) is None and planner.group(name) == "v2_auxiliary_evidence"
    tests.append(dict(case="planner_uses_final_consumer_and_preserves_all_repair_evidence", status="passed"))
    assert {name: base.file_hash(PACKAGE / name) for name in originals} == before
    assert "torch" not in sys.modules and "numpy" not in sys.modules
    tests.append(dict(case="all_original_sources_normalization_and_results_unchanged", status="passed"))
    source = output / "source"
    source.mkdir()
    names = ("archive_closure_final.py", "archive_closure.py", "lif_cost_receipts.py", "final_bundle_plan.py",
             "scaling_summary_consumer_tests.py", "ARCHIVE_CLOSURE_FINAL.md")
    for name in names:
        (source / name).write_bytes((PACKAGE / name).read_bytes())
    result = dict(schema="hcsn-final-scaling-consumer-tests.v1", status="passed", tests=len(tests), records=tests,
        source_sha256={name: base.file_hash(source / name) for name in names}, original_sha256=before,
        actual_proofs=dict(proofs, **scaling["proofs"]), original_suite=repair["original_suite"],
        repair_outer=repair["repair_outer"],
        scope="Read-only real completed metadata and pure negative-contract variants. No training, timing, inference, original-file changes or formal archive-closure publication.")
    base.write_new(output / "RESULTS.json", result)
    print(json.dumps(dict(status="passed", tests=len(tests), zero_medians=repair["zero_timing_medians"],
                         undefined_ratios=repair["undefined_ratios"])))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
