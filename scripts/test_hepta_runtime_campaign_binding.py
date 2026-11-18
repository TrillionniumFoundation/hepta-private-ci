"""Local file/receipt binding controls; doubles do not qualify a real runtime."""

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import qualify_runtime_campaign as qualifier
from runtime_stdio import canonical, digest, strict_json


class CampaignBindingControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.pins = {
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "binary_sha256": "3" * 64,
            "config_sha256": "4" * 64,
        }
        self.candidate = {
            "runtime_identity": self.pins,
            "native": {"image_sha256": "5" * 64},
        }
        self.profile = {
            "namespace": "binding-control-double",
            "candidate_sha256": "6" * 64,
            "process": {
                "args": [
                    "-B",
                    str(Path(__file__).with_name("hepta_cell_joint_worker.py")),
                    "--candidate",
                    "/fixture/candidate.json",
                ],
                "timeout_seconds": 120,
            },
            "runtime": {"source_root": "/fixture/runtime"},
        }
        self.profiles = []

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical(value) + b"\n"
        path.write_bytes(raw)
        return digest(raw)

    def fixture(self, *, campaign="semantic_updates", variant="original"):
        semantic = campaign == "semantic_updates"
        prefix = "semantic-campaign" if semantic else "campaign"
        self.worker_output = self.output / (prefix + "-worker")
        self.runtime_report = self.output / (prefix + "-runtime.json")
        plan_hash = self.write(
            self.worker_output / "campaign/PLAN.json",
            {"native": self.candidate["native"], "fixture_variant": variant},
        )
        result = {
            "status": "SEMANTIC_FIXTURE_COMPLETE"
            if semantic
            else "CONTROLLED_FIXTURE_COMPLETE",
            "native_hia_enabled": True,
            "plan_sha256": plan_hash,
        }
        result_hash = self.write(self.worker_output / "campaign/RESULT.json", result)
        domain = {
            "status": "campaign_observed",
            "candidate_sha256": self.profile["candidate_sha256"],
            "request_id": "control-" + campaign + "-maintenance",
            "runtime_identity": self.pins,
            "native_image_sha256": self.candidate["native"]["image_sha256"],
            "native_counts": {key: {"completed": 1} for key in ("memory", "predictor")},
            "campaign_result": result,
            "campaign_result_sha256": result_hash,
        }
        if semantic:
            updates_plan_hash = self.write(
                self.worker_output / "updates/PLAN.json",
                {
                    "native": self.candidate["native"],
                    "learning_result_sha256": result_hash,
                },
            )
            updates = {
                "status": "THREE_UPDATE_EXAMPLES_OBSERVED",
                "plan_sha256": updates_plan_hash,
                "parameters": {"source_result_sha256": result_hash},
                "code": {"outputs_and_states_equal": True},
                "state": {"pending_preserved": True},
            }
            domain.update(
                updates=updates,
                updates_result_sha256=self.write(
                    self.worker_output / "updates/RESULT.json", updates
                ),
                updates_native_image_sha256=self.candidate["native"]["image_sha256"],
            )
        self.write(self.worker_output / "OBSERVATION.json", domain)
        return domain

    def run_double(
        self, domain, *, campaign="semantic_updates", on_cold=None, late_terminal=False
    ):
        test = self
        observation = {
            "state": "TERMINAL",
            "runtime_state": "succeeded",
            "exit_code": 0,
            "streams": {"stdout": {"bytes_hex": canonical(domain).hex()}},
        }
        executions = 0

        class RuntimeDouble:
            def __init__(self, *_args, **_kwargs):
                self.identity = {
                    "transport": "local_control_double",
                    "runtime_source_commit": test.pins["source_commit"],
                    "runtime_binary_sha256": test.pins["binary_sha256"],
                    "runtime_config_sha256": test.pins["config_sha256"],
                }
                self.records = [
                    {"request": {"method": "tools/call", "params": {"name": name}}}
                    for name in ("process_status", "process_read")
                ]

            def call(self, *_args, **_kwargs):
                raise AssertionError("This control must not invoke a runtime")

            def close(self):
                pass

        class BridgeDouble:
            def __init__(self, profile, *_args, **_kwargs):
                test.profiles.append(copy.deepcopy(profile))

            def execute(self, _request):
                nonlocal executions
                executions += 1
                if executions == 2 and on_cold:
                    on_cold()
                if executions == 1 and late_terminal:
                    return {"state": "UNKNOWN", "job_id": "control-only-job"}
                return copy.deepcopy(observation)

            def observe(self, _request_id):
                return copy.deepcopy(observation)

            def close(self):
                pass

        with (
            patch.object(qualifier, "StdioRuntime", RuntimeDouble),
            patch.object(qualifier, "RuntimeProcessBridge", BridgeDouble),
            patch.object(
                qualifier.subprocess,
                "check_output",
                return_value=(self.pins["source_tree"] + "\n").encode(),
            ),
            patch.object(
                qualifier.time,
                "monotonic",
                side_effect=[0, 0, 160, 180] if late_terminal else [0, 0, 1],
            ),
            patch.object(qualifier.time, "sleep"),
        ):
            return qualifier.run_campaign(
                self.profile,
                self.candidate,
                self.output,
                self.root / "private",
                {},
                "control",
                campaign=campaign,
            )

    def review(self, domain, *, campaign="semantic_updates", snapshot=False):
        path = self.root / "independent-review.json"
        result = {
            "schema": "hepta.semantic-maintenance-readonly-review.v1"
            if campaign == "semantic_updates"
            else "hepta.controlled-maintenance-readonly-review.v1",
            "status": "READ_ONLY_CONSISTENCY_PASS",
            "result_sha256": domain["campaign_result_sha256"],
            "plan_sha256": domain["campaign_result"]["plan_sha256"],
            "native_image_sha256": domain["native_image_sha256"],
            "root": "/untrusted/reviewer/path/is/not/followed",
        }
        if snapshot:
            # Shape follows actual review_hepta_maintenance_snapshot output,
            # including the six inventories and nested independent review.
            result["verifier_sha256"] = "7" * 64
            inventory = {
                "files": {
                    "RESULT.json": {"sha256": result["result_sha256"]},
                    "PLAN.json": {"sha256": result["plan_sha256"]},
                }
            }
            result = {
                "schema": "hepta.maintenance-readonly-snapshot-review.v1",
                "status": "READ_ONLY_SNAPSHOT_CONSISTENCY_PASS",
                "source_unchanged_verified": True,
                "snapshot_unchanged_during_review": True,
                "semantic_profile": campaign == "semantic_updates",
                "original_verifier_sha256": result["verifier_sha256"],
                "original_verifier_expected_sha256": result["verifier_sha256"],
                "review": result,
                **{
                    key: copy.deepcopy(inventory)
                    for key in (
                        "source_before",
                        "source_during_copy",
                        "source_after_copy",
                        "source_after_review",
                        "snapshot_before_review",
                        "snapshot_after_review",
                    )
                },
            }
        self.write(path, result)
        return path

    def test_semantic_originals_review_and_cli_bind_the_same_bytes(self):
        domain = self.fixture()
        original_profile = copy.deepcopy(self.profile)
        report = self.run_double(domain)
        self.assertEqual(self.profile, original_profile)
        self.assertEqual(
            [value["process"]["timeout_seconds"] for value in self.profiles], [180, 180]
        )
        expected = {
            path: digest((self.worker_output / path).read_bytes())
            for path in (
                "campaign/RESULT.json",
                "campaign/PLAN.json",
                "OBSERVATION.json",
                "updates/RESULT.json",
                "updates/PLAN.json",
            )
        }
        self.assertEqual(report["originals_binding"]["files_sha256"], expected)
        review_path = self.review(domain, snapshot=True)
        bound = qualifier.verify_review_binding(self.runtime_report, review_path)
        process = subprocess.run(
            [
                sys.executable,
                "-B",
                qualifier.__file__,
                "--runtime-report",
                str(self.runtime_report),
                "--review",
                str(review_path),
            ],
            check=True,
            capture_output=True,
        )
        self.assertEqual(strict_json(process.stdout), bound)
        self.assertEqual(bound["worker_stdout_sha256"], digest(canonical(domain)))
        self.assertEqual(bound["review_format"], "readonly_snapshot_review")

    def test_syntax_legacy_report_keeps_its_existing_format_and_timeout(self):
        domain = self.fixture(campaign="syntax")
        report = self.run_double(domain, campaign="syntax")
        self.assertEqual(
            [value["process"]["timeout_seconds"] for value in self.profiles], [120, 120]
        )
        for key in (
            "originals_binding",
            "originals_rechecked_after_cold",
            "worker_stdout_sha256",
        ):
            del report[key]
        self.write(self.runtime_report, report)
        self.assertEqual(
            qualifier.verify_review_binding(
                self.runtime_report, self.review(domain, campaign="syntax")
            )["status"],
            "REVIEW_BOUND_TO_RUNTIME_ORIGINALS",
        )

    def test_semantic_can_complete_after_the_old_observation_deadline(self):
        domain = self.fixture()
        self.assertEqual(self.run_double(domain, late_terminal=True)["status"], "PASS")

    def test_internally_consistent_replacement_originals_do_not_match_stdout(self):
        original = self.fixture()
        replacement = self.fixture(variant="replacement")
        self.assertNotEqual(
            original["campaign_result_sha256"], replacement["campaign_result_sha256"]
        )
        with self.assertRaisesRegex(ValueError, "campaign RESULT original differs"):
            self.run_double(original)
        failed = strict_json(self.runtime_report.read_bytes())
        self.assertEqual(failed["status"], "FAIL")
        self.assertEqual(failed["worker_result"], original)

    def test_each_missing_or_changed_original_is_rejected_without_mtime_help(self):
        domain = self.fixture()
        for relative in (
            "campaign/RESULT.json",
            "campaign/PLAN.json",
            "OBSERVATION.json",
            "updates/RESULT.json",
            "updates/PLAN.json",
        ):
            path = self.worker_output / relative
            raw, metadata = path.read_bytes(), path.stat()
            with self.subTest(path=relative, change="missing"):
                path.unlink()
                with self.assertRaises(OSError):
                    qualifier.bind_worker_originals(
                        self.worker_output, domain, campaign="semantic_updates"
                    )
                path.write_bytes(raw)
            with self.subTest(path=relative, change="same-mtime replacement"):
                self.write(path, {**strict_json(raw), "replacement": True})
                os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
                with self.assertRaises(ValueError):
                    qualifier.bind_worker_originals(
                        self.worker_output, domain, campaign="semantic_updates"
                    )
                path.write_bytes(raw)

    def test_root_directory_file_symlinks_and_parent_traversal_are_rejected(self):
        domain = self.fixture()
        alias = self.root / "outside-root-link"
        alias.symlink_to(self.worker_output, target_is_directory=True)
        with self.assertRaises(OSError):
            qualifier.bind_worker_originals(alias, domain, campaign="semantic_updates")
        for relative in ("campaign", "updates/RESULT.json", "OBSERVATION.json"):
            path, moved = self.worker_output / relative, self.root / "moved-original"
            path.rename(moved)
            path.symlink_to(moved, target_is_directory=moved.is_dir())
            with self.subTest(path=relative), self.assertRaises(OSError):
                qualifier.bind_worker_originals(
                    self.worker_output, domain, campaign="semantic_updates"
                )
            path.unlink()
            moved.rename(path)
        with self.assertRaises(ValueError):
            qualifier._read_original(self.worker_output, "../RESULT.json")

    def test_json_equivalent_observation_rewrite_during_cold_read_is_rejected(self):
        domain = self.fixture()
        path = self.worker_output / "OBSERVATION.json"
        with self.assertRaisesRegex(ValueError, "originals changed during cold"):
            self.run_double(
                domain, on_cold=lambda: path.write_bytes(path.read_bytes() + b"\n")
            )
        self.assertEqual(
            strict_json(self.runtime_report.read_bytes())["status"], "FAIL"
        )

    def test_review_result_mismatch_and_later_original_replacement_are_rejected(self):
        domain = self.fixture()
        self.run_double(domain)
        review_path = self.review(domain)
        review = strict_json(review_path.read_bytes())
        self.write(review_path, {**review, "result_sha256": "a" * 64})
        with self.assertRaisesRegex(ValueError, "independent review does not bind"):
            qualifier.verify_review_binding(self.runtime_report, review_path)
        self.write(review_path, review)
        self.fixture(variant="later-originals")
        with self.assertRaisesRegex(ValueError, "campaign RESULT original differs"):
            qualifier.verify_review_binding(self.runtime_report, review_path)

    def test_semantic_review_rejects_missing_binding_or_changed_reported_stdout(self):
        domain = self.fixture()
        report = self.run_double(domain)
        review_path = self.review(domain)
        unbound = copy.deepcopy(report)
        del unbound["originals_binding"]
        self.write(self.runtime_report, unbound)
        with self.assertRaisesRegex(ValueError, "before and after cold"):
            qualifier.verify_review_binding(self.runtime_report, review_path)
        report["worker_result"]["replacement"] = True
        self.write(self.runtime_report, report)
        with self.assertRaisesRegex(
            ValueError, "differs from the retained runtime stdout"
        ):
            qualifier.verify_review_binding(self.runtime_report, review_path)

    def test_snapshot_wrapper_status_invariance_and_inventory_are_required(self):
        domain = self.fixture()
        self.run_double(domain)
        review_path = self.review(domain, snapshot=True)
        original = strict_json(review_path.read_bytes())
        for key, value in (
            ("schema", "wrong-schema"),
            ("status", "FAIL"),
            ("source_unchanged_verified", False),
            ("snapshot_unchanged_during_review", False),
            ("semantic_profile", False),
        ):
            with self.subTest(field=key):
                self.write(review_path, {**original, key: value})
                with self.assertRaisesRegex(
                    ValueError, "snapshot review did not preserve"
                ):
                    qualifier.verify_review_binding(self.runtime_report, review_path)
        changed = copy.deepcopy(original)
        changed["snapshot_after_review"]["files"]["RESULT.json"]["sha256"] = "8" * 64
        self.write(review_path, changed)
        with self.assertRaisesRegex(ValueError, "snapshot review inventory differs"):
            qualifier.verify_review_binding(self.runtime_report, review_path)


if __name__ == "__main__":
    unittest.main()
