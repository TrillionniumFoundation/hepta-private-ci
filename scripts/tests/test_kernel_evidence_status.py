"""Regression tests for receipt identity, false-green prevention and status views."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("kernel_evidence_status", Path(__file__).resolve().parents[1] / "kernel_evidence_status.py")
status = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status)


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.downloads = self.root / "downloads"
        self.downloads.mkdir()
        self.source = "a" * 40
        self.tree = "b" * 40
        self.base = "c" * 40
        self.digest = "d" * 64
        self.lane = self.make_lane()
        self.aggregate = argparse.Namespace(
            source_commit=self.source, source_tree=self.tree,
            source_qualified="true", merge_qualified="false",
            source_artifact_digest=self.digest, merge_artifact_digest="",
            source_status=self.lane.output, merge_status=None,
            records_root=str(self.downloads), base_commit=self.base,
            workflow_run_id="123", workflow_run_attempt="2",
            workflow_ref="owner/repository/.github/workflows/evidence.yml@refs/heads/main",
            event_name="push", output=str(self.root / "STATUS.json"), github_output=None,
        )

    def make_lane(self, lane="source-head", event="push"):
        merge = lane == "base-merge"
        commit, tree = (("e" * 40, "f" * 40) if merge else (self.source, self.tree))
        parents = [self.base, self.source] if merge else [self.base]
        name = f"kernel-evidence-{lane}-records-{self.source}-123-2"
        directory = self.downloads / name
        directory.mkdir()
        candidate = {"schemaVersion": 1, "kind": "kernel_evidence_synthetic_merge" if merge else "kernel_evidence_exact_source", "commit": commit, "tree": tree, "parents": parents}
        (directory / "candidate.json").write_text(json.dumps(candidate))
        for key, (filename, command, minimum) in status.COMMANDS.items():
            log = directory / (key + ".log")
            log.write_bytes(b"test result: ok. 1 passed; 0 failed;\n")
            identity = {"commit": commit, "tree": tree, "parents": parents, "dirty": False}
            record = {"schema_version": 1, "status": "passed", "command": command,
                      "exit_code": 0, "command_exit_code": 0, "returncode": 0,
                      "observed_failed_tests": 0, "observed_passed_tests": max(1, minimum),
                      "timed_out": False, "output_limit_exceeded": False,
                      "run_id": "123", "run_attempt": "2", "source_sha": self.source,
                      "tested_sha": commit, "base_sha": self.base if merge else "",
                      "lane": lane, "before": identity, "after": identity,
                      "log_file": log.name, "log_bytes": log.stat().st_size,
                      "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
            (directory / filename).write_text(json.dumps(record))
        output = self.downloads / f"kernel-evidence-{lane}-status-{self.source}-123-2" / f"{lane}.json"
        args = argparse.Namespace(
            commit=commit, tree=tree, parents_json=json.dumps(parents),
            source_commit=self.source, base_commit=self.base if merge else None,
            candidate_kind="synthetic-merge" if merge else "exact-source", lane=lane,
            workflow_run_id="123", workflow_run_attempt="2",
            workflow_ref="owner/repository/.github/workflows/evidence.yml@refs/heads/main",
            event_name=event, artifact_name=name, artifact_digest=self.digest,
            records_dir=str(directory), output=str(output), github_output=None,
            check=[key + "=success" for key in status.REQUIRED_LANE_CHECKS],
        )
        self.assertEqual(status.build_lane(args), 0)
        self.assertTrue(status._load(output)["qualified"])
        return args

    def lane_value(self):
        return status._load(Path(self.lane.output))

    def mutate_record(self, key, mutate):
        path = Path(self.lane.records_dir) / status.COMMANDS[key][0]
        record = status._load(path)
        mutate(record)
        path.write_text(json.dumps(record))

    def assert_lane_fails(self):
        status.build_lane(self.lane)
        value = self.lane_value()
        self.assertFalse(value["qualified"])
        self.assertTrue(value["validationErrors"])

    def aggregate_value(self):
        status.build_aggregate(self.aggregate)
        return status._load(Path(self.aggregate.output))

    def test_valid_exact_lane_and_push_aggregate(self):
        value = self.aggregate_value()
        self.assertTrue(value["allRequiredQualificationLanesPassed"])
        self.assertFalse(value["mergeCandidateQualified"])
        status.validate_canonical(value)

    def test_no_artifact_digest_is_never_qualified(self):
        self.lane.artifact_digest = ""
        self.assert_lane_fails()

    def test_zero_artifact_digest_is_rejected(self):
        self.lane.artifact_digest = "0" * 64
        self.assert_lane_fails()

    def test_missing_check_is_not_success(self):
        self.lane.check.pop()
        self.assert_lane_fails()

    def test_skipped_check_is_not_success(self):
        self.lane.check[0] = "candidate_identity=skipped"
        self.assert_lane_fails()

    def test_empty_outcome_is_skipped(self):
        self.lane.check[0] = "candidate_identity="
        self.assert_lane_fails()

    def test_setup_failure_cannot_hide_behind_successful_commands(self):
        self.lane.check[1] = "setup_ci=failure"
        self.assert_lane_fails()

    def test_extra_check_is_not_accepted(self):
        self.lane.check.append("unreviewed=success")
        self.assert_lane_fails()

    def test_duplicate_check_is_rejected(self):
        self.lane.check.append(self.lane.check[0])
        with self.assertRaises(ValueError):
            status.build_lane(self.lane)

    def test_arbitrary_successful_command_is_not_evidence(self):
        self.mutate_record("evidence_tests", lambda r: r.update(command=["true"]))
        self.assert_lane_fails()

    def test_zero_observed_tests_is_not_green(self):
        self.mutate_record("status_tests", lambda r: r.update(observed_passed_tests=0))
        self.assert_lane_fails()

    def test_integer_false_cannot_replace_boolean_guard(self):
        self.mutate_record("evidence_tests", lambda r: r.update(timed_out=0))
        self.assert_lane_fails()

    def test_boolean_zero_exit_code_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(exit_code=False))
        self.assert_lane_fails()

    def test_boolean_schema_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(schema_version=True))
        self.assert_lane_fails()

    def test_wrong_run_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(run_id="124"))
        self.assert_lane_fails()

    def test_wrong_attempt_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(run_attempt="1"))
        self.assert_lane_fails()

    def test_dirty_source_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r["after"].update(dirty=True))
        self.assert_lane_fails()

    def test_source_tree_drift_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r["after"].update(tree="9" * 40))
        self.assert_lane_fails()

    def test_wrong_source_commit_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(source_sha="9" * 40))
        self.assert_lane_fails()

    def test_log_modification_is_rejected(self):
        (Path(self.lane.records_dir) / "evidence_tests.log").write_bytes(b"forged")
        self.assert_lane_fails()

    def test_missing_log_is_rejected(self):
        (Path(self.lane.records_dir) / "evidence_tests.log").unlink()
        self.assert_lane_fails()

    def test_log_path_escape_is_rejected(self):
        self.mutate_record("evidence_tests", lambda r: r.update(log_file="../outside.log"))
        self.assert_lane_fails()

    def test_symlink_log_is_rejected(self):
        log = Path(self.lane.records_dir) / "evidence_tests.log"
        outside = self.root / "outside.log"
        outside.write_bytes(log.read_bytes())
        log.unlink()
        log.symlink_to(outside)
        self.assert_lane_fails()

    def test_missing_record_is_rejected(self):
        (Path(self.lane.records_dir) / "evidence-tests.json").unlink()
        self.assert_lane_fails()

    def test_no_status_receipt_cannot_be_green(self):
        self.aggregate.source_status = None
        self.assertFalse(self.aggregate_value()["exactSourceQualified"])

    def test_incorrect_artifact_digest_cannot_be_green(self):
        self.aggregate.source_artifact_digest = "1" * 64
        self.assertFalse(self.aggregate_value()["exactSourceQualified"])

    def test_modified_downloaded_record_manifest_is_rejected(self):
        (Path(self.lane.records_dir) / "unrecorded.txt").write_text("extra")
        self.assertFalse(self.aggregate_value()["exactSourceQualified"])

    def test_aggregate_cannot_reuse_another_run(self):
        self.aggregate.workflow_run_id = "124"
        self.assertFalse(self.aggregate_value()["exactSourceQualified"])

    def test_aggregate_cannot_reuse_another_attempt(self):
        self.aggregate.workflow_run_attempt = "3"
        self.assertFalse(self.aggregate_value()["exactSourceQualified"])

    def test_boolean_strings_are_rejected(self):
        value = self.aggregate_value()
        value["exactSourceQualified"] = "false"
        with self.assertRaises(ValueError):
            status.validate_canonical(value)

    def test_canonical_receipt_coverage_is_required(self):
        value = self.aggregate_value()
        value["laneReceiptSha256"] = {}
        with self.assertRaises(ValueError):
            status.validate_canonical(value)

    def test_ci_cannot_self_issue_release_or_external_acceptance(self):
        value = self.aggregate_value()
        for field in status.LIFECYCLE_FLAGS:
            with self.subTest(field=field), self.assertRaises(ValueError):
                changed = copy.deepcopy(value)
                changed[field] = True
                status.validate_canonical(changed)

    def test_canonical_gate_algebra_is_enforced(self):
        value = self.aggregate_value()
        value["allRequiredQualificationLanesPassed"] = False
        with self.assertRaises(ValueError):
            status.validate_canonical(value)

    def test_duplicate_json_keys_are_rejected(self):
        path = self.root / "duplicate.json"
        path.write_text('{"qualified":false,"qualified":true}')
        with self.assertRaises(ValueError):
            status._load(path)

    def test_invalid_git_and_run_id_types(self):
        for invalid in ("", "0", "001", True, 123, "123\n", str(2**64)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                status._positive_id(invalid, "run")
        for invalid in (None, "0" * 40, "G" * 40, "a" * 39, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                status._hex(invalid, 40, "commit")

    def test_pr_requires_both_candidates(self):
        self.lane.event_name = "pull_request"
        status.build_lane(self.lane)
        self.aggregate.event_name = "pull_request"
        value = self.aggregate_value()
        self.assertTrue(value["exactSourceQualified"])
        self.assertFalse(value["allRequiredQualificationLanesPassed"])

    def test_pr_accepts_matching_deterministic_merge(self):
        self.lane.event_name = "pull_request"
        status.build_lane(self.lane)
        merge = self.make_lane("base-merge", "pull_request")
        self.aggregate.event_name = "pull_request"
        self.aggregate.merge_qualified = "true"
        self.aggregate.merge_status = merge.output
        self.aggregate.merge_artifact_digest = self.digest
        with patch.object(status.subprocess, "run", return_value=argparse.Namespace(stdout="f" * 40 + "\n")) as recompute:
            value = self.aggregate_value()
        self.assertTrue(value["allRequiredQualificationLanesPassed"])
        self.assertEqual(recompute.call_args.args[0][-2:], [self.base, self.source])

    def test_wrong_merge_tree_is_rejected(self):
        self.lane.event_name = "pull_request"
        status.build_lane(self.lane)
        merge = self.make_lane("base-merge", "pull_request")
        self.aggregate.event_name = "pull_request"
        self.aggregate.merge_qualified = "true"
        self.aggregate.merge_status = merge.output
        self.aggregate.merge_artifact_digest = self.digest
        with patch.object(status.subprocess, "run", return_value=argparse.Namespace(stdout="9" * 40 + "\n")):
            self.assertFalse(self.aggregate_value()["mergeCandidateQualified"])

    def test_merge_parent_order_is_enforced(self):
        self.lane.lane = "base-merge"
        self.lane.candidate_kind = "synthetic-merge"
        self.lane.base_commit = self.base
        self.lane.parents_json = json.dumps([self.source, self.base])
        with self.assertRaises(ValueError):
            status.build_lane(self.lane)

    def docs_args(self):
        self.aggregate_value()
        source = self.root / "source"
        for relative in status.DOC_PATHS[:-1]:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Existing design\n\nDo not remove this technical content.\n")
        return argparse.Namespace(path=self.aggregate.output, source_root=str(source), output_dir=str(self.root / "views"), check=False)

    def test_five_views_preserve_design_and_share_one_digest(self):
        args = self.docs_args()
        status.render(args)
        digest = status._sha256(Path(args.path))
        for relative in status.DOC_PATHS:
            text = (Path(args.output_dir) / relative).read_text()
            self.assertIn(digest, text)
            self.assertEqual(text.count(status.BEGIN), 1)
            self.assertEqual(text.count(status.END), 1)
        for relative in status.DOC_PATHS[:-1]:
            self.assertIn("Do not remove", (Path(args.output_dir) / relative).read_text())
        args.check = True
        self.assertEqual(status.render(args), 0)

    def test_generated_doc_drift_is_rejected(self):
        args = self.docs_args()
        status.render(args)
        (Path(args.output_dir) / status.DOC_PATHS[0]).write_text("drift")
        args.check = True
        with self.assertRaises(ValueError):
            status.render(args)

    def test_render_cannot_mutate_qualified_source(self):
        args = self.docs_args()
        args.output_dir = args.source_root
        with self.assertRaises(ValueError):
            status.render(args)

    def test_render_rejects_ambiguous_markers(self):
        args = self.docs_args()
        (Path(args.source_root) / status.DOC_PATHS[0]).write_text(status.BEGIN)
        with self.assertRaises(ValueError):
            status.render(args)

    def test_render_rejects_source_symlink_escape(self):
        args = self.docs_args()
        path = Path(args.source_root) / status.DOC_PATHS[0]
        path.unlink()
        outside = self.root / "outside.md"
        outside.write_text("outside")
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            status.render(args)


if __name__ == "__main__":
    unittest.main()
