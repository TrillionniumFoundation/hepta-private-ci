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
        "created_at": "2026-10-11T02:59:18Z",
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

    def test_exact_prospective_merge_parents_are_required(self):
        merge = "d" * 40
        cases = [
            ([BASE, HEAD], "exact", True),
            ([BASE, "c" * 40], "stale_merge_parents", False),
            (["c" * 40, HEAD], "stale_merge_parents", False),
            ([HEAD, BASE], "stale_merge_parents", False),
            ([BASE], "stale_merge_parents", False),
        ]
        for parents, status, qualified in cases:
            with self.subTest(parents=parents):
                with mock.patch.object(
                    GATE, "gh_json",
                    side_effect=[
                        {
                            "ref": "refs/pull/1468/merge",
                            "object": {"sha": merge},
                        },
                        {
                            "parents": [{"sha": sha} for sha in parents],
                            "committer": {"date": "2026-10-11T02:59:17Z"},
                        },
                    ],
                ) as fetch:
                    result = GATE.prospective_merge_identity(
                        REPO, 1468, HEAD, BASE
                    )
                self.assertEqual(result["status"], status)
                self.assertEqual(result["qualified"], qualified)
                self.assertEqual(fetch.call_count, 2)

    def test_missing_or_unreadable_prospective_merge_is_not_green(self):
        for response in [
            {"ref": "refs/pull/1468/head", "object": {"sha": "d" * 40}},
            {"ref": "refs/pull/1468/merge", "object": {"sha": "invalid"}},
        ]:
            with self.subTest(response=response):
                with mock.patch.object(GATE, "gh_json", return_value=response):
                    result = GATE.prospective_merge_identity(
                        REPO, 1468, HEAD, BASE
                    )
                self.assertFalse(result["qualified"])
                self.assertEqual(
                    result["status"], "missing_or_unreadable_merge_ref"
                )

    def test_current_rejects_old_merge_ref_even_with_three_green_runs(self):
        jobs = [run(name) for name in GATE.REQUIRED]
        stale = "c" * 40
        with mock.patch.object(
            GATE, "gh_json",
            side_effect=[
                pr(),
                {"workflow_runs": jobs},
                {
                    "ref": "refs/pull/1468/merge",
                    "object": {"sha": "d" * 40},
                },
                {"parents": [{"sha": BASE}, {"sha": stale}]},
            ],
        ):
            _, result = GATE.current(REPO, 1468, HEAD)
        self.assertFalse(result["qualified"])
        self.assertEqual(
            result["prospective_merge_ref"]["status"],
            "stale_merge_parents",
        )
        self.assertEqual(
            set(result["required_pull_request_runs"].values()), {"success"}
        )

    def test_replayed_green_run_cannot_qualify_new_base_merge(self):
        merge = "d" * 40
        jobs = [run(name) for name in GATE.REQUIRED]
        merge_ref = {
            "ref": "refs/pull/1468/merge",
            "object": {"sha": merge},
        }
        current_merge = {
            "parents": [{"sha": BASE}, {"sha": HEAD}],
            "committer": {"date": "2026-10-11T03:00:01Z"},
        }
        # GitHub pull_requests[] metadata can point to the *current* PR
        # even when the workflow itself started before the base advanced.
        with mock.patch.object(
            GATE, "gh_json",
            side_effect=[
                pr(), {"workflow_runs": jobs}, merge_ref, current_merge,
            ],
        ):
            _, verdict = GATE.current(REPO, 1468, HEAD)
        self.assertFalse(verdict["qualified"])
        self.assertEqual(verdict["prospective_merge_ref"]["status"], "exact")
        self.assertEqual(
            set(verdict["required_pull_request_runs"].values()),
            {"missing_exact_pull_request_run"},
        )

        refreshed = [
            dict(item, created_at="2026-10-11T03:00:05Z") for item in jobs
        ]
        with mock.patch.object(
            GATE, "gh_json",
            side_effect=[
                pr(), {"workflow_runs": refreshed}, merge_ref, current_merge,
            ],
        ):
            _, verdict = GATE.current(REPO, 1468, HEAD)
        self.assertTrue(verdict["qualified"])

    def test_missing_merge_timestamp_and_missing_run_start_are_denied(self):
        with mock.patch.object(
            GATE, "gh_json",
            side_effect=[
                {
                    "ref": "refs/pull/1468/merge",
                    "object": {"sha": "d" * 40},
                },
                {"parents": [{"sha": BASE}, {"sha": HEAD}]},
            ],
        ):
            record = GATE.prospective_merge_identity(REPO, 1468, HEAD, BASE)
        self.assertFalse(record["qualified"])
        self.assertEqual(
            record["status"], "missing_or_unreadable_merge_ref",
        )
        self.assertFalse(GATE.run_started_after_merge(
            {}, "2026-10-11T03:00:01Z",
        ))
        self.assertFalse(GATE.run_started_after_merge(
            {"created_at": "not-a-timestamp"}, "2026-10-11T03:00:01Z",
        ))
        self.assertFalse(GATE.run_started_after_merge(
            {"created_at": "2026-10-11T02:00:01Z"},
            "2026-10-11T03:00:01Z",
        ))

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
