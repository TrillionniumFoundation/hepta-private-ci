#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_trusted_report",
    Path(__file__).with_name("hepta-learning-eval-trusted-report.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

SOURCE = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
MERGE = "4" * 40
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RUN_ID = "12345"
RUN_ATTEMPT = "2"


def source_summary() -> dict[str, object]:
    jobs = {name: "success" for name in MODULE.AGGREGATE.REQUIRED_JOBS}
    return MODULE.AGGREGATE.build(
        SOURCE,
        TREE,
        REPOSITORY,
        RUN_ID,
        RUN_ATTEMPT,
        jobs,
    )


def exact_summary() -> dict[str, object]:
    return MODULE.EXACT.build(
        SOURCE,
        TREE,
        BASE,
        MERGE,
        "pull_request",
        "success",
        REPOSITORY,
        RUN_ID,
        RUN_ATTEMPT,
    )


def pull_request(head: str = SOURCE) -> dict[str, object]:
    return {
        "state": "open",
        "body": "intro\n",
        "head": {"sha": head, "repo": {"full_name": REPOSITORY}},
    }


class TrustedReporterTests(unittest.TestCase):
    def test_source_summary_is_bound_to_exact_producer_context(self):
        MODULE.validate_bound_summary(
            source_summary(), "source", REPOSITORY, RUN_ID, RUN_ATTEMPT, SOURCE
        )
        changed = source_summary()
        changed["source"]["commit"] = "9" * 40
        with self.assertRaises(ValueError):
            MODULE.validate_bound_summary(
                changed, "source", REPOSITORY, RUN_ID, RUN_ATTEMPT, SOURCE
            )

    def test_exact_summary_requires_pull_request_scope_and_ordered_merge_identity(self):
        MODULE.validate_bound_summary(
            exact_summary(), "exact", REPOSITORY, RUN_ID, RUN_ATTEMPT, SOURCE
        )
        changed = exact_summary()
        changed["eventName"] = "push"
        changed["evidenceSha256"] = MODULE.EXACT.evidence_hash(changed)
        with self.assertRaises(ValueError):
            MODULE.validate_bound_summary(
                changed, "exact", REPOSITORY, RUN_ID, RUN_ATTEMPT, SOURCE
            )

    def test_artifact_discovery_accepts_one_bounded_regular_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "nested"
            nested.mkdir()
            path = nested / MODULE.SUMMARY_NAMES["source"]
            path.write_text(json.dumps(source_summary()), encoding="utf-8")
            self.assertEqual(MODULE.find_summary(root, path.name), path)

    def test_artifact_discovery_rejects_symlinked_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            link = root / MODULE.SUMMARY_NAMES["source"]
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                MODULE.find_summary(root, link.name)

    def test_stale_workflow_run_cannot_overwrite_newer_pr_head(self):
        with mock.patch.object(
            MODULE.PR_STATUS, "request_json", return_value=pull_request("8" * 40)
        ) as request:
            with self.assertRaises(ValueError):
                MODULE.update_current_pull_request(
                    source_summary(),
                    "source",
                    REPOSITORY,
                    1011,
                    SOURCE,
                    "token",
                )
        request.assert_called_once()

    def test_valid_current_head_updates_only_machine_owned_marker(self):
        responses = [pull_request(), {}]
        with mock.patch.object(
            MODULE.PR_STATUS, "request_json", side_effect=responses
        ) as request:
            body = MODULE.update_current_pull_request(
                source_summary(),
                "source",
                REPOSITORY,
                1011,
                SOURCE,
                "token",
            )
        self.assertIn("learning.eval source qualification", body)
        self.assertIn("intro", body)
        self.assertEqual(request.call_count, 2)
        patch_call = request.call_args_list[1]
        self.assertEqual(patch_call.kwargs["method"], "PATCH")
        self.assertEqual(patch_call.kwargs["payload"]["body"], body)


if __name__ == "__main__":
    unittest.main()
