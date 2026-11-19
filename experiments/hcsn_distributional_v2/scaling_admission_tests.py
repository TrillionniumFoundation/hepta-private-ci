"""Narrow metadata admission checks; no model import, training, or benchmark."""

import argparse
import ast
import copy
from pathlib import Path
import sys
from unittest.mock import patch

from . import scaling_admission as admission


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    checks = []
    original = admission.original_contract()
    evidence = admission.main_evidence()
    gates = admission.run_gates()
    assert len(original["cases"]) == original["expected_cases"] == 30
    assert evidence == gates["main_admission"]
    checks.append("real original contract, supplement and completed normalization verified")
    try:
        admission.frozen.gate_bindings()
    except RuntimeError as error:
        assert "results/content_analysis002/ANALYSIS.json" in str(error)
        checks.append("unchanged SCALING001 still refuses the actual strict175/1 audit")
    else:
        raise AssertionError("Original gate must remain failed")

    original_read = admission.read
    bad = []
    bad.append(("results/content_analysis002/ANALYSIS.json", ("valid",), 176, "original strict failure cannot be relabeled"))
    bad.append(("results/content_analysis_supplement001/ANALYSIS.json", ("valid",), 175, "incomplete supplement rejected"))
    bad.append(("results/content_analysis_supplement001/ANALYSIS.json", ("statistical_gates_changed",), True, "changed statistical gates rejected"))
    for key in admission.RECONCILIATION_KEYS:
        bad.append(("results/content_analysis_supplement001/ANALYSIS.json", ("scientific_comparison_reconciliation", key), False, key + " required"))
    bad.append(("results/content_analysis_supplement001_execution/EXECUTION.json", ("returncode",), 1, "failed supplementary process rejected"))
    bad.append(("results/lif_cost_receipts001/RECEIPTS.json", ("main_admission", "scientific_comparisons_preserved"), False, "normalization scientific admission required"))
    bad.append(("results/lif_cost_receipts001/RECEIPTS.json", ("scopes", 0, "cpu_seconds"), 0.0, "normalization must match original CPU pointer"))
    for target, keys, value, description in bad:
        target_path = admission.PACKAGE / target

        def tampered(path):
            data = original_read(path)
            if Path(path).resolve() == target_path:
                data = copy.deepcopy(data)
                parent = data
                for key in keys[:-1]:
                    parent = parent[key]
                parent[keys[-1]] = value
            return data

        with patch.object(admission, "read", side_effect=tampered):
            try:
                admission.run_gates()
            except ValueError:
                checks.append(description)
            else:
                raise AssertionError(description)
    ast.parse(Path(admission.__file__).read_text())
    assert "torch" not in sys.modules and "numpy" not in sys.modules
    assert not any((admission.PACKAGE / "results/scaling001" / name).exists()
                   for name in ("cases", "COMPLETE.json", "SUITE_EXECUTION.json", "RUN_AUTHORIZATION.json"))
    checks.append("stdlib-only source parse and no original formal workers")
    admission.write(output / "RESULTS.json", dict(schema="hcsn-scaling002-admission-tests.v1", status="passed",
        checks=checks, number_of_checks=len(checks), new_training_or_inference=False,
        torch_or_numpy_imported=False, original_protocol_sha256=admission.ORIGINAL_PROTOCOL_SHA,
        source_sha256=admission.sha(admission.__file__), test_source_sha256=admission.sha(__file__),
        original_strict_gate_passed=False, main_admission=evidence))
    print(f"{len(checks)} admission checks passed; zero neural operations")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output.resolve())
