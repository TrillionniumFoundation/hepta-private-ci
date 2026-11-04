#!/usr/bin/env python3
"""Verify a diagnostics-only evaluator patch against the original module.

Uses synthetic snapshots and optional aggregate observed failure metadata. It
does not instantiate the live evaluator, call a broker, or edit original data.
The import root must be the authorized, verified source release under review.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def structural_guard(base, candidate):
    left = ast.parse(base.read_text())
    right = ast.parse(candidate.read_text())
    new_helpers = [n for n in right.body if isinstance(n, ast.FunctionDef) and n.name == "current_ledger_replay_issue"]
    assert len(new_helpers) == 1
    right.body.remove(new_helpers[0])
    for tree in (left, right):
        evaluator = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Evaluator")
        snapshot = next(n for n in evaluator.body if isinstance(n, ast.FunctionDef) and n.name == "snapshot")
        # All module logic except snapshot and the one new pure helper is equal.
        evaluator.body.remove(snapshot)
    assert ast.dump(left, include_attributes=False) == ast.dump(right, include_attributes=False), "NON_DIAGNOSTIC_CODE_CHANGED"


def snapshot_arguments(module, report, initial_issues, final=False, strict=True):
    evaluator = object.__new__(module.Evaluator)
    evaluator.plan = {"reward_config_path": "synthetic-config", "reward_config_sha256": "pinned", "training_dataset_path": "synthetic-data", "training_dataset_sha256": "pinned", "producer_registration": {}, "period_sha256": "pinned", "outcome_end_ms": 100}
    evaluator.config = {}
    evaluator.strict_review = strict
    evaluator.preopen = None
    evaluator.evaluate_snapshot = lambda *args: args
    with patch.object(module.W, "sha", return_value="pinned"), patch.object(module.W, "clock_ms", return_value=142 if final else 42), patch("laya_cell.financial_forward_source.ingress", return_value=({}, {}, [], copy.deepcopy(initial_issues))), patch("laya_cell.resident_rewards.current", return_value=copy.deepcopy(report)), patch("laya_cell.financial_forward_evaluate.execution_index", return_value=({}, {}, {})):
        return evaluator.snapshot()


def normalized(arguments):
    out = list(arguments)
    out[-1] = [{k: v for k, v in issue.items() if k != "native_replay_reason"} for issue in out[-1]]
    return out


def fail_closed_branch(module, report, issues):
    evaluator = object.__new__(module.Evaluator)
    evaluator.plan = {}
    evaluator.strict_review = True
    evaluator.preopen = None
    class EmptyStore:
        def remember_commands(self, bindings, state_root):
            assert bindings == []
            return {}
    evaluator.store = EmptyStore()
    with tempfile.TemporaryDirectory(prefix="hepta-replay-diagnostics-") as directory:
        evaluator.root = Path(directory)
        with patch.object(module, "strict_source_unavailable", return_value={"route": "STRICT_SOURCE_UNAVAILABLE"}) as failed:
            result = evaluator.evaluate_snapshot({}, [], copy.deepcopy(report), {}, {}, {}, 42, copy.deepcopy(issues))
            assert result == {"route": "STRICT_SOURCE_UNAVAILABLE"}
            assert failed.call_count == 1
            assert str(failed.call_args.args[2]) == "STRICT_SOURCE_REPLAY_INCOMPLETE"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-root", type=Path, required=True)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--aggregate-observed-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    structural_guard(args.base, args.candidate)
    sys.path[:0] = [str(args.import_root / "research/neuron_learning"), str(args.import_root / "research"), str(args.import_root / "scripts")]
    base = load_module(args.base, "laya_cell._audit_eval_base")
    candidate = load_module(args.candidate, "laya_cell._audit_eval_candidate")
    reports = [
        {"components": {"EUR.USD": {"ledger_complete": True}}},
        {"components": {"EUR.USD": {"ledger_complete": False, "reason": "SUBMITTED_COMMAND_WITHOUT_FILL_OR_ZERO_FILL_PROOF"}}},
        {"components": {}, "reason": "INCOMPLETE_OMS_TAIL"},
        {"components": {}},
        {"components": {"EUR.USD": {"ledger_complete": False, "reason": "sensitive/path/and-identifier"}}},
        {"components": {"EUR.USD": {"ledger_complete": False, "reason": "DU123456"}}},
        {"components": {"EUR.USD": {"ledger_complete": False, "reason": "X" * 129}}},
    ]
    if args.aggregate_observed_report:
        observed = json.loads(args.aggregate_observed_report.read_text())
        reports.append({"components": observed.get("components", {}), "reason": observed.get("global_reason")})
    cases = []
    for index, report in enumerate(reports):
        prior = [{"reason": "EXISTING_INGRESS_ISSUE"}]
        old = snapshot_arguments(base, report, prior)
        new = snapshot_arguments(candidate, report, prior)
        assert normalized(old) == normalized(new), "SNAPSHOT_SEMANTICS_CHANGED"
        issue = candidate.current_ledger_replay_issue(report)
        if issue is not None:
            assert issue["reason"] == "CURRENT_LEDGER_REPLAY_UNAVAILABLE"
            assert all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_" for c in issue["native_replay_reason"])
            fail_closed_branch(base, report, old[-1])
            fail_closed_branch(candidate, report, new[-1])
            for module in (base, candidate):
                try:
                    snapshot_arguments(module, report, [], final=True, strict=False)
                except module.W.EvidenceError as exc:
                    assert str(exc).startswith("FINAL_SOURCE_UNAVAILABLE:")
                else:
                    raise AssertionError("FINAL_SOURCE_FAILURE_WAS_ACCEPTED")
        cases.append({"case": index, "replay_complete": issue is None, "native_replay_reason": issue.get("native_replay_reason") if issue else None, "snapshot_and_failure_route_unchanged": True})
    result = {"schema": "hepta.wsp.native-replay-diagnostics-verification.v1", "cases": cases, "base_sha256": hashlib.sha256(args.base.read_bytes()).hexdigest(), "candidate_sha256": hashlib.sha256(args.candidate.read_bytes()).hexdigest(), "all_other_module_ast_identical": True, "private_identifiers_disclosed": False, "live_evaluator_instantiated": False, "broker_orders_sent": 0, "deployed": False}
    with args.output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
