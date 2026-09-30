#!/usr/bin/env python3
from __future__ import annotations

import base64
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

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "1" * 40
TREE = "2" * 40
BASE = "3" * 40
MERGE = "4" * 40
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RUN_ID = "12345"
RUN_ATTEMPT = "2"
PR_NUMBER = 1011


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


def pull_request(
    head: str = SOURCE,
    base: str = BASE,
    merge: str = MERGE,
) -> dict[str, object]:
    return {
        "number": PR_NUMBER,
        "state": "open",
        "body": "intro\n",
        "head": {"sha": head, "repo": {"full_name": REPOSITORY}},
        "base": {"sha": base},
        "merge_commit_sha": merge,
    }


def workflow_text(marker: str) -> str:
    path = ROOT / MODULE.WORKFLOWS[marker]["path"]
    return path.read_text(encoding="utf-8")


def run_payload(marker: str) -> dict[str, object]:
    config = MODULE.WORKFLOWS[marker]
    return {
        "name": config["name"],
        "path": config["path"],
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_sha": SOURCE,
        "run_attempt": int(RUN_ATTEMPT),
        "head_repository": {"full_name": REPOSITORY},
        "pull_requests": [
            {
                "number": PR_NUMBER,
                "head": {"sha": SOURCE},
                "base": {"sha": BASE},
            }
        ],
    }


def source_jobs(compile_result: str = "success") -> dict[str, object]:
    config = MODULE.WORKFLOWS["source"]
    jobs = []
    for summary_key, job_name in config["required_jobs"].items():
        conclusion = compile_result if summary_key == "compileDefault" else "success"
        jobs.append(
            {
                "name": job_name,
                "conclusion": conclusion,
                "run_attempt": int(RUN_ATTEMPT),
            }
        )
    qualified = compile_result == "success"
    jobs.extend(
        [
            {
                "name": config["summary_job"],
                "conclusion": "success" if qualified else "failure",
                "run_attempt": int(RUN_ATTEMPT),
            },
            {
                "name": config["attestation_job"],
                "conclusion": "skipped",
                "run_attempt": int(RUN_ATTEMPT),
            },
        ]
    )
    return {"total_count": len(jobs), "jobs": jobs}


def exact_jobs(merge_result: str = "success") -> dict[str, object]:
    config = MODULE.WORKFLOWS["exact"]
    jobs = [
        {
            "name": "exact-head",
            "conclusion": "success",
            "run_attempt": int(RUN_ATTEMPT),
        },
        {
            "name": "exact-merge",
            "conclusion": merge_result,
            "run_attempt": int(RUN_ATTEMPT),
        },
        {
            "name": config["summary_job"],
            "conclusion": "success" if merge_result == "success" else "failure",
            "run_attempt": int(RUN_ATTEMPT),
        },
        {
            "name": config["attestation_job"],
            "conclusion": "skipped",
            "run_attempt": int(RUN_ATTEMPT),
        },
    ]
    return {"total_count": len(jobs), "jobs": jobs}


def content_payload(marker: str, text: str | None = None) -> dict[str, object]:
    raw = workflow_text(marker) if text is None else text
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(raw.encode()).decode(),
    }


def producer_api(
    marker: str,
    *,
    jobs: dict[str, object] | None = None,
    text: str | None = None,
    tree: str = TREE,
    current: dict[str, object] | None = None,
):
    selected_jobs = jobs or (source_jobs() if marker == "source" else exact_jobs())

    def request(url: str, token: str) -> dict[str, object]:
        del token
        if url.endswith(f"/actions/runs/{RUN_ID}"):
            return run_payload(marker)
        if "/jobs?" in url:
            return selected_jobs
        if "/git/commits/" in url:
            return {"tree": {"sha": tree}}
        if "/pulls/" in url:
            return current or pull_request()
        if "/contents/" in url:
            return content_payload(marker, text)
        raise AssertionError(f"unexpected API URL: {url}")

    return request


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

    def test_checked_in_candidate_workflows_match_trusted_policy_and_identity(self):
        for marker in MODULE.WORKFLOWS:
            text = workflow_text(marker)
            MODULE.validate_candidate_workflow_text(text, marker)
            MODULE.validate_trusted_workflow_identity(text, marker)

    def test_candidate_workflow_drift_from_default_branch_is_rejected(self):
        with self.assertRaises(ValueError):
            MODULE.validate_trusted_workflow_identity(
                workflow_text("source") + "# candidate drift\n", "source"
            )

    def test_candidate_workflow_write_permission_is_rejected(self):
        changed = workflow_text("source").replace(
            "permissions:\n  contents: read",
            "permissions:\n  contents: read\n  pull-requests: write",
            1,
        )
        with self.assertRaises(ValueError):
            MODULE.validate_candidate_workflow_text(changed, "source")

    def test_actual_source_run_jobs_tree_and_workflow_are_verified(self):
        with mock.patch.object(
            MODULE, "request_json", side_effect=producer_api("source")
        ):
            MODULE.validate_producer_run(
                source_summary(),
                "source",
                REPOSITORY,
                RUN_ID,
                RUN_ATTEMPT,
                SOURCE,
                PR_NUMBER,
                "token",
            )

    def test_forged_source_success_is_rejected_against_actual_jobs(self):
        with mock.patch.object(
            MODULE,
            "request_json",
            side_effect=producer_api("source", jobs=source_jobs("failure")),
        ):
            with self.assertRaises(ValueError):
                MODULE.validate_producer_run(
                    source_summary(),
                    "source",
                    REPOSITORY,
                    RUN_ID,
                    RUN_ATTEMPT,
                    SOURCE,
                    PR_NUMBER,
                    "token",
                )

    def test_substituted_source_tree_is_rejected_against_commit_object(self):
        with mock.patch.object(
            MODULE,
            "request_json",
            side_effect=producer_api("source", tree="9" * 40),
        ):
            with self.assertRaises(ValueError):
                MODULE.validate_producer_run(
                    source_summary(),
                    "source",
                    REPOSITORY,
                    RUN_ID,
                    RUN_ATTEMPT,
                    SOURCE,
                    PR_NUMBER,
                    "token",
                )

    def test_actual_exact_matrix_is_verified(self):
        with mock.patch.object(
            MODULE, "request_json", side_effect=producer_api("exact")
        ):
            MODULE.validate_producer_run(
                exact_summary(),
                "exact",
                REPOSITORY,
                RUN_ID,
                RUN_ATTEMPT,
                SOURCE,
                PR_NUMBER,
                "token",
            )

    def test_stale_base_is_rejected(self):
        current = pull_request(base="9" * 40)
        with mock.patch.object(
            MODULE,
            "request_json",
            side_effect=producer_api("exact", current=current),
        ):
            with self.assertRaises(ValueError):
                MODULE.validate_producer_run(
                    exact_summary(),
                    "exact",
                    REPOSITORY,
                    RUN_ID,
                    RUN_ATTEMPT,
                    SOURCE,
                    PR_NUMBER,
                    "token",
                )

    def test_substituted_synthetic_merge_is_rejected(self):
        current = pull_request(merge="9" * 40)
        with mock.patch.object(
            MODULE,
            "request_json",
            side_effect=producer_api("exact", current=current),
        ):
            with self.assertRaises(ValueError):
                MODULE.validate_producer_run(
                    exact_summary(),
                    "exact",
                    REPOSITORY,
                    RUN_ID,
                    RUN_ATTEMPT,
                    SOURCE,
                    PR_NUMBER,
                    "token",
                )

    def test_stale_workflow_run_cannot_overwrite_newer_pr_head(self):
        with mock.patch.object(
            MODULE.PR_STATUS,
            "request_json",
            return_value=pull_request(head="8" * 40),
        ) as request:
            with self.assertRaises(ValueError):
                MODULE.update_current_pull_request(
                    source_summary(),
                    "source",
                    REPOSITORY,
                    PR_NUMBER,
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
                PR_NUMBER,
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
