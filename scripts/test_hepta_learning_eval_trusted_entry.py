#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "learning_eval_trusted_entry",
    Path(__file__).with_name("hepta-learning-eval-trusted-entry.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
SOURCE = "1" * 40
BASE = "2" * 40
MERGE = "3" * 40
PR_NUMBER = 1011


def pull_request(
    *,
    draft: bool = True,
    head: str = SOURCE,
    base: str = BASE,
    merge: str = MERGE,
    body: str = "intro\n",
    base_repository: str = REPOSITORY,
) -> dict[str, object]:
    return {
        "number": PR_NUMBER,
        "state": "open",
        "draft": draft,
        "body": body,
        "head": {"sha": head, "repo": {"full_name": REPOSITORY}},
        "base": {
            "sha": base,
            "repo": {"full_name": base_repository},
        },
        "merge_commit_sha": merge,
    }


def exact_summary(*, base: str = BASE, merge: str = MERGE) -> dict[str, object]:
    return {
        "baseCommit": base,
        "syntheticMergeCommit": merge,
    }


def fake_reporter(request):
    def validate_current(current, repository, number, source):
        if current.get("number") != number:
            raise ValueError("pull request identity mismatch")
        if current.get("state") != "open":
            raise ValueError("refusing to update a non-open pull request")
        head = current.get("head")
        if not isinstance(head, dict) or head.get("sha") != source:
            raise ValueError("producer run is stale relative to the current PR head")
        repo = head.get("repo")
        if not isinstance(repo, dict) or repo.get("full_name") != repository:
            raise ValueError("pull request head repository mismatch")

    def render(summary, marker):
        del summary
        start, end = MODULE.MARKERS[marker]
        return f"{start}\nvalidated\n{end}\n"

    return SimpleNamespace(
        validate_current_pull_request=validate_current,
        PR_STATUS=SimpleNamespace(request_json=request, render=render),
    )


class StrictArtifactTests(unittest.TestCase):
    def write(self, root: Path, text: str = '{"ok": true}') -> Path:
        path = root / MODULE.SUMMARY_NAMES["source"]
        path.write_text(text, encoding="utf-8")
        companion = {
            "schema": "hepta.learning-eval.current-run-status.v1",
            "module": "learning.eval",
        }
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            for key in (
                "source",
                "evidenceSha256",
                "releasePosture",
                "authority",
                "claims",
                "jobs",
            ):
                if key in parsed:
                    companion[key] = parsed[key]
        (root / "CURRENT_STATUS.run.json").write_text(
            json.dumps(companion), encoding="utf-8"
        )
        return path

    def test_one_strict_summary_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root)
            self.assertEqual(
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"]),
                {"ok": True},
            )

    def test_source_status_companion_must_match_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root)
            status = json.loads((root / "CURRENT_STATUS.run.json").read_text())
            status["authority"] = "ALLOW"
            (root / "CURRENT_STATUS.run.json").write_text(json.dumps(status))
            with self.assertRaisesRegex(ValueError, "companion disagrees"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_duplicate_key_in_source_status_companion_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root)
            (root / "CURRENT_STATUS.run.json").write_text(
                '{"schema":"hepta.learning-eval.current-run-status.v1",'
                '"module":"learning.eval","claims":{},"claims":{}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_missing_source_status_companion_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root)
            (root / "CURRENT_STATUS.run.json").unlink()
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_exact_artifact_accepts_only_exact_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / MODULE.SUMMARY_NAMES["exact"]
            path.write_text('{"ok": true}', encoding="utf-8")
            self.assertEqual(MODULE.load_strict_summary(root, path.name), {"ok": True})

    def test_duplicate_top_level_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, '{"claims": {}, "claims": {}}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_duplicate_nested_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, '{"outer": {"runId": "1", "runId": "2"}}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_nonfinite_json_constant_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, '{"value": NaN}')
            with self.assertRaisesRegex(ValueError, "non-finite JSON"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_extra_regular_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root)
            (root / "companion.txt").write_text("untrusted", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_symlinked_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            self.write(outside)
            link = root / "linked"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_artifact_depth_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root
            for index in range(MODULE.MAX_ARTIFACT_DEPTH + 1):
                nested = nested / f"d{index}"
                nested.mkdir()
            self.write(nested)
            with self.assertRaisesRegex(ValueError, "depth"):
                MODULE.load_strict_summary(root, MODULE.SUMMARY_NAMES["source"])

    def test_artifact_entry_count_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(MODULE.MAX_ARTIFACT_ENTRIES + 1):
                (root / f"entry-{index}.txt").write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "entry count"):
                MODULE.artifact_files(root)


class ProducerConclusionTests(unittest.TestCase):
    def jobs(self, conclusion: str) -> dict[str, object]:
        return {
            "total_count": 1,
            "jobs": [
                {
                    "name": "compile-default",
                    "conclusion": conclusion,
                    "run_attempt": 2,
                }
            ],
        }

    def test_extended_failure_conclusions_are_normalized_fail_closed(self):
        for conclusion in (
            "failure",
            "neutral",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
        ):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(
                    MODULE.normalized_job_conclusions(self.jobs(conclusion), "2"),
                    {"compile-default": "failure"},
                )

    def test_success_cancelled_and_skipped_are_preserved(self):
        for conclusion in ("success", "cancelled", "skipped"):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(
                    MODULE.normalized_job_conclusions(self.jobs(conclusion), "2")[
                        "compile-default"
                    ],
                    conclusion,
                )

    def test_unknown_conclusion_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unapproved conclusion"):
            MODULE.normalized_job_conclusions(self.jobs("mystery"), "2")

    def test_duplicate_job_name_is_rejected(self):
        value = self.jobs("success")
        value["total_count"] = 2
        value["jobs"].append(dict(value["jobs"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate producer job"):
            MODULE.normalized_job_conclusions(value, "2")

    def test_incomplete_paginated_inventory_is_rejected(self):
        value = self.jobs("success")
        value["total_count"] = 2
        with self.assertRaisesRegex(ValueError, "incomplete or malformed"):
            MODULE.normalized_job_conclusions(value, "2")

    def test_wrong_attempt_is_rejected(self):
        value = self.jobs("success")
        value["jobs"][0]["run_attempt"] = 3
        with self.assertRaisesRegex(ValueError, "another run attempt"):
            MODULE.normalized_job_conclusions(value, "2")


class ControlPlaneIdentityTests(unittest.TestCase):
    def test_checked_in_control_plane_inventory_is_regular(self):
        if not ((MODULE.ROOT / ".git").is_dir() or (MODULE.ROOT / ".git").is_file()):
            self.skipTest(
                "repository checkout is not mounted in this unit-test sandbox"
            )
        for relative in MODULE.TRUSTED_CONTROL_PLANE_PATHS:
            with self.subTest(path=relative):
                self.assertTrue(MODULE.trusted_control_plane_text(relative))

    def test_matching_control_plane_text_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "scripts/check.py"
            path.parent.mkdir(parents=True)
            path.write_text("print('ok')\n", encoding="utf-8")
            MODULE.validate_control_plane_text(
                "print('ok')\n", "scripts/check.py", root=root
            )

    def test_control_plane_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "scripts/check.py"
            path.parent.mkdir(parents=True)
            path.write_text("trusted\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from trusted"):
                MODULE.validate_control_plane_text(
                    "candidate\n", "scripts/check.py", root=root
                )

    def test_symlinked_trusted_control_plane_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("trusted\n", encoding="utf-8")
            link = root / "scripts/check.py"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "not regular"):
                MODULE.trusted_control_plane_text("scripts/check.py", root=root)

    def test_all_declared_control_plane_files_are_compared(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = {}
            for index, relative in enumerate(MODULE.TRUSTED_CONTROL_PLANE_PATHS):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                value = f"trusted-{index}\n"
                path.write_text(value, encoding="utf-8")
                content[relative] = value

            fetched = []

            def fetch(repository, path, source, token):
                self.assertEqual(repository, REPOSITORY)
                self.assertEqual(source, SOURCE)
                self.assertEqual(token, "token")
                fetched.append(path)
                return content[path]

            with mock.patch.object(
                MODULE,
                "_REPORTER",
                SimpleNamespace(fetch_candidate_workflow=fetch),
            ):
                MODULE.validate_trusted_control_plane_identity(
                    REPOSITORY, SOURCE, "token", root=root
                )
            self.assertEqual(tuple(fetched), MODULE.TRUSTED_CONTROL_PLANE_PATHS)

    def test_one_changed_control_plane_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = {}
            for relative in MODULE.TRUSTED_CONTROL_PLANE_PATHS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("trusted\n", encoding="utf-8")
                content[relative] = "trusted\n"
            for changed in (
                MODULE.TRUSTED_CONTROL_PLANE_PATHS[-1],
                "scripts/just-shell.py",
            ):
                content[changed] = "changed\n"
                with (
                    self.subTest(changed=changed),
                    mock.patch.object(
                        MODULE,
                        "_REPORTER",
                        SimpleNamespace(
                            fetch_candidate_workflow=lambda repository, path, source, token: (
                                content[path]
                            )
                        ),
                    ),
                ):
                    with self.assertRaisesRegex(ValueError, "differs from trusted"):
                        MODULE.validate_trusted_control_plane_identity(
                            REPOSITORY, SOURCE, "token", root=root
                        )
                content[changed] = "trusted\n"


class CompleteJobInventoryTests(unittest.TestCase):
    def reporter(self, original):
        return SimpleNamespace(
            WORKFLOWS={
                "source": {
                    "required_jobs": {
                        "identityRecorder": "identity-recorder",
                        "compileDefault": "compile-default",
                    },
                    "summary_job": "immutable-qualification-summary",
                    "attestation_job": "attest-source-summary",
                },
                "exact": {
                    "matrix_jobs": ("exact-head", "exact-merge"),
                    "summary_job": "exact-matrix-summary",
                    "attestation_job": "attest-exact-summary",
                },
            },
            _strict_original_validate_actual_job_results=original,
        )

    def test_complete_source_job_inventory_delegates_to_semantic_validator(self):
        original = mock.Mock()
        conclusions = {
            "identity-recorder": "success",
            "compile-default": "success",
            "immutable-qualification-summary": "success",
            "attest-source-summary": "skipped",
        }
        with mock.patch.object(MODULE, "_REPORTER", self.reporter(original)):
            MODULE.validate_complete_job_results({}, "source", conclusions)
        original.assert_called_once_with({}, "source", conclusions)

    def test_missing_attestation_job_is_rejected(self):
        original = mock.Mock()
        conclusions = {
            "exact-head": "success",
            "exact-merge": "success",
            "exact-matrix-summary": "success",
        }
        with mock.patch.object(MODULE, "_REPORTER", self.reporter(original)):
            with self.assertRaisesRegex(ValueError, "inventory mismatch"):
                MODULE.validate_complete_job_results({}, "exact", conclusions)
        original.assert_not_called()


class MarkerTests(unittest.TestCase):
    def block(self, marker: str = "source") -> str:
        start, end = MODULE.MARKERS[marker]
        return f"{start}\nold\n{end}\n"

    def test_duplicate_modern_marker_is_rejected(self):
        body = self.block() + self.block()
        with self.assertRaisesRegex(ValueError, "duplicate machine marker"):
            MODULE.validate_marker_inventory(body, "source")

    def test_half_marker_is_rejected(self):
        body = MODULE.MARKERS["source"][0]
        with self.assertRaisesRegex(ValueError, "malformed"):
            MODULE.validate_marker_inventory(body, "source")

    def test_modern_and_legacy_marker_together_are_rejected(self):
        legacy = (
            f"{MODULE.LEGACY_SOURCE_MARKER[0]}\nold\n{MODULE.LEGACY_SOURCE_MARKER[1]}\n"
        )
        with self.assertRaisesRegex(ValueError, "both modern and legacy"):
            MODULE.validate_marker_inventory(self.block() + legacy, "source")

    def test_source_replacement_rejects_duplicate_exact_marker(self):
        exact = self.block("exact") + self.block("exact")
        replacement = (
            f"{MODULE.MARKERS['source'][0]}\nnew\n{MODULE.MARKERS['source'][1]}\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate machine marker"):
            MODULE.replace_single_marker(exact, replacement, "source")

    def test_replacement_preserves_all_non_marker_text(self):
        body = "prefix\n" + self.block() + "suffix\n"
        replacement = (
            f"{MODULE.MARKERS['source'][0]}\nnew\n{MODULE.MARKERS['source'][1]}\n"
        )
        changed = MODULE.replace_single_marker(body, replacement, "source")
        self.assertEqual(changed, "prefix\n" + replacement + "suffix\n")

    def test_legacy_marker_is_canonically_replaced(self):
        body = (
            "prefix\n"
            f"{MODULE.LEGACY_SOURCE_MARKER[0]}\nold\n"
            f"{MODULE.LEGACY_SOURCE_MARKER[1]}\n"
            "suffix\n"
        )
        replacement = (
            f"{MODULE.MARKERS['source'][0]}\nnew\n{MODULE.MARKERS['source'][1]}\n"
        )
        changed = MODULE.replace_single_marker(body, replacement, "source")
        self.assertNotIn(MODULE.LEGACY_SOURCE_MARKER[0], changed)
        self.assertEqual(changed, "prefix\n" + replacement + "suffix\n")


class FinalPullRequestScopeTests(unittest.TestCase):
    def test_no_go_reporter_rejects_ready_for_review_pr(self):
        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(mock.Mock())):
            with self.assertRaisesRegex(ValueError, "non-draft"):
                MODULE.validate_final_pr_scope(
                    pull_request(draft=False),
                    {},
                    "source",
                    REPOSITORY,
                    PR_NUMBER,
                    SOURCE,
                )

    def test_base_repository_substitution_is_rejected(self):
        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(mock.Mock())):
            with self.assertRaisesRegex(ValueError, "base repository"):
                MODULE.validate_final_pr_scope(
                    pull_request(base_repository="attacker/fork"),
                    {},
                    "source",
                    REPOSITORY,
                    PR_NUMBER,
                    SOURCE,
                )

    def test_exact_base_change_before_patch_is_rejected(self):
        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(mock.Mock())):
            with self.assertRaisesRegex(ValueError, "base changed"):
                MODULE.validate_final_pr_scope(
                    pull_request(base="9" * 40),
                    exact_summary(),
                    "exact",
                    REPOSITORY,
                    PR_NUMBER,
                    SOURCE,
                )

    def test_exact_merge_change_before_patch_is_rejected(self):
        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(mock.Mock())):
            with self.assertRaisesRegex(ValueError, "synthetic merge changed"):
                MODULE.validate_final_pr_scope(
                    pull_request(merge="9" * 40),
                    exact_summary(),
                    "exact",
                    REPOSITORY,
                    PR_NUMBER,
                    SOURCE,
                )

    def test_patch_response_is_revalidated(self):
        current = pull_request()
        stale = pull_request(head="9" * 40)
        request = mock.Mock(side_effect=[current, stale])
        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(request)):
            with self.assertRaisesRegex(ValueError, "stale"):
                MODULE.update_current_pull_request_strict(
                    {},
                    "source",
                    REPOSITORY,
                    PR_NUMBER,
                    SOURCE,
                    "token",
                )
        self.assertEqual(request.call_count, 2)

    def test_successful_patch_updates_only_canonical_marker(self):
        current = pull_request()
        expected_start, expected_end = MODULE.MARKERS["source"]
        responses: list[dict[str, object]] = [current]

        def request(url, token, method="GET", payload=None):
            del url, token
            if method == "GET":
                return responses[0]
            self.assertEqual(method, "PATCH")
            self.assertEqual(set(payload), {"body"})
            updated = pull_request(body=payload["body"])
            return updated

        with mock.patch.object(MODULE, "_REPORTER", fake_reporter(request)):
            body = MODULE.update_current_pull_request_strict(
                {},
                "source",
                REPOSITORY,
                PR_NUMBER,
                SOURCE,
                "token",
            )
        self.assertIn("intro", body)
        self.assertEqual(body.count(expected_start), 1)
        self.assertEqual(body.count(expected_end), 1)


if __name__ == "__main__":
    unittest.main()
