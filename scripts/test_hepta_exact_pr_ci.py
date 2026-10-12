#!/usr/bin/env python3
"""Fail-closed regression tests for exact-HEAD PR Actions identity."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "hepta_exact_pr_ci", ROOT / "hepta_exact_pr_ci.py"
)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATE
SPEC.loader.exec_module(GATE)

REPO = "TrillionniumFoundation/hepta-private-ci"
HEAD = "a" * 40
BASE = "b" * 40


def pr(head=HEAD, base=BASE):
    return {
        "number": 1468,
        "state": "open",
        "draft": True,
        "head": {
            "sha": head,
            "ref": "codex/hepta-production-gates-20261010",
            "repo": {"full_name": REPO},
        },
        "base": {"sha": base},
    }


def run(name, *, sha=HEAD, base=BASE, conclusion="success", event="pull_request"):
    return {
        "name": name,
        "event": event,
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "run_number": 123,
        "run_attempt": 1,
        "pull_requests": [
            {
                "number": 1468,
                "head": {
                    "sha": sha,
                    "repo": {"url": f"https://api.github.com/repos/{REPO}"},
                },
                "base": {"sha": base},
            }
        ],
    }


class ExactPrCiTests(unittest.TestCase):
    def test_full_exact_pr_workflow_set_is_required(self):
        all_runs = [run(name) for name in GATE.REQUIRED]
        result = GATE.evaluate(pr(), all_runs, REPO, 1468, HEAD)
        self.assertTrue(result["qualified"])
        self.assertEqual(
            set(result["required_pull_request_runs"]), set(GATE.REQUIRED)
        )

    def test_missing_or_manual_source_lane_cannot_be_green(self):
        cases = [
            [run("Hepta architecture convergence", event="workflow_dispatch")],
            [run("Hepta architecture convergence")],
            [run("blocking-ci"), run("v8-canary")],
            [run(name, sha="c" * 40) for name in GATE.REQUIRED],
            [run(name, base="d" * 40) for name in GATE.REQUIRED],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                self.assertFalse(
                    GATE.evaluate(pr(), rows, REPO, 1468, HEAD)["qualified"]
                )

    def test_current_failure_outweighs_old_success(self):
        old = run("blocking-ci")
        newer = run("blocking-ci", conclusion="failure")
        newer["run_number"] = 124
        rows = [run("Hepta architecture convergence"), old, newer, run("v8-canary")]
        result = GATE.evaluate(pr(), rows, REPO, 1468, HEAD)
        self.assertFalse(result["qualified"])
        self.assertEqual(result["required_pull_request_runs"]["blocking-ci"], "failure")

    def test_updated_pr_base_or_head_cannot_reuse_prior_run(self):
        rows = [run(name) for name in GATE.REQUIRED]
        with self.assertRaisesRegex(ValueError, "differs from pin"):
            GATE.evaluate(pr(head="c" * 40), rows, REPO, 1468, HEAD)
        self.assertFalse(
            GATE.evaluate(pr(base="c" * 40), rows, REPO, 1468, HEAD)["qualified"]
        )

    def test_draft_and_open_pr_are_mandatory(self):
        for key, value in [("draft", False), ("state", "closed")]:
            candidate = pr()
            candidate[key] = value
            with self.assertRaises(ValueError):
                GATE.evaluate(candidate, [], REPO, 1468, HEAD)

    def test_dispatch_only_invokes_existing_manual_workflows(self):
        with mock.patch.object(
            GATE, "current", side_effect=[(pr(), {"qualified": False}), (pr(), {})]
        ) as load:
            with mock.patch.object(GATE, "gh") as dispatch:
                with mock.patch.object(sys, "argv", [
                    "hepta_exact_pr_ci.py", "--pr", "1468", "--expected-sha", HEAD,
                    "--dispatch-source",
                ]):
                    with mock.patch("builtins.print"):
                        self.assertEqual(GATE.main(), 1)
        self.assertEqual(load.call_count, 2)
        self.assertEqual(dispatch.call_count, 2)
        for call, name in zip(dispatch.call_args_list, GATE.MANUAL):
            self.assertEqual(call.args[:3], ("workflow", "run", name))
            self.assertNotIn("blocking-ci.yml", call.args)


if __name__ == "__main__":
    unittest.main()
