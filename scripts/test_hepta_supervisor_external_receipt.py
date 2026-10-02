from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.hepta_supervisor_external_receipt import validate_production
from scripts.hepta_supervisor_external_receipt import validate_target
from scripts.hepta_supervisor_external_receipt import validate_run_binding
from scripts.hepta_supervisor_external_receipt import load
from scripts.hepta_supervisor_external_receipt import require_production_source

SHA40 = "a" * 40
SHA256 = "b" * 64
ROOT = Path(__file__).resolve().parents[1]


def canonical_profile_digest(profile: dict) -> str:
    return hashlib.sha256(
        (json.dumps(profile, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


class ExternalReceiptTests(unittest.TestCase):
    def target_profile(self) -> dict:
        return {
            "profile_id": "target-v1",
            "hosts": [
                {"os": "linux", "architectures": ["x86_64"], "filesystems": ["ext4"]},
                {"os": "macos", "architectures": ["arm64"], "filesystems": ["apfs"]},
            ],
            "fleet": {"real_processes_required": 256},
            "fault_scenarios": ["daemon_sigkill", "enospc"],
            "slo": {"tick_lateness_p99_ms": {"operator": "lte", "value": 100}},
        }

    def target(self, os_name: str = "linux") -> dict:
        profile = self.target_profile()
        architecture, filesystem = (
            ("x86_64", "ext4") if os_name == "linux" else ("arm64", "apfs")
        )
        return {
            "schema_version": 1,
            "kind": "runtime-supervisor-target-host",
            "profile_id": "target-v1",
            "lane": "final-merge",
            "source_sha": SHA40,
            "base_sha": "c" * 40,
            "merge_candidate_sha": "d" * 40,
            "tested_sha": "e" * 40,
            "final_merge_sha": "e" * 40,
            "workflow_sha": "f" * 40,
            "workflow_run_id": "17",
            "workflow_run_attempt": "1",
            "binary_sha256": SHA256,
            "cargo_lock_sha256": "c" * 64,
            "feature_set": ["production-verifier"],
            "target_triple": (
                "x86_64-unknown-linux-gnu"
                if os_name == "linux"
                else "aarch64-apple-darwin"
            ),
            "runner_image_or_host_fingerprint": "host-fingerprint",
            "host": {
                "os": os_name,
                "architecture": architecture,
                "kernel": "kernel",
                "filesystem": filesystem,
            },
            "profile_sha256": canonical_profile_digest(profile),
            "workload_sha256": "d" * 64,
            "real_processes": 256,
            "fault_results": [
                {
                    "scenario": scenario,
                    "status": "passed",
                    "fault_cut": scenario,
                    "raw_log_sha256": "1" * 64,
                    "durable_snapshot_before_sha256": "2" * 64,
                    "durable_snapshot_after_sha256": "3" * 64,
                }
                for scenario in profile["fault_scenarios"]
            ],
            "metrics": {"tick_lateness_p99_ms": 99},
            "forbidden_binaries_present": [],
            "clean_tree": True,
            "completed_at_utc": "2026-09-30T00:00:00Z",
            "activation": False,
        }

    def production_profile(self) -> dict:
        return {
            "profile_id": "production-v1",
            "required_target_hosts": ["linux", "macos"],
            "artifact_boundary": {"daemon_feature_set": ["production-verifier"]},
            "key_custody": {
                "required_receipts": [
                    "custody",
                    "rotation",
                    "revocation",
                    "emergency_restore",
                ]
            },
            "independent_acceptance": {
                "required_roles": ["code", "security", "operations"]
            },
        }

    def test_target_accepts_complete_exact_receipt(self):
        validate_target(self.target(), self.target_profile())

    def test_target_rejects_missing_fault_failed_slo_and_signer_artifact(self):
        for update in ("missing_fault", "failed_slo", "signer"):
            data = self.target()
            if update == "missing_fault":
                data["fault_results"].pop()
            elif update == "failed_slo":
                data["metrics"]["tick_lateness_p99_ms"] = 101
            else:
                data["forbidden_binaries_present"] = ["hepta-authority-signer"]
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_target(data, self.target_profile())

    def test_source_head_cannot_claim_a_final_merge(self):
        data = self.target()
        data["lane"] = "source-head"
        data["tested_sha"] = data["source_sha"]
        with self.assertRaises(ValueError):
            validate_target(data, self.target_profile())
        data["final_merge_sha"] = None
        validate_target(data, self.target_profile())

    def test_target_rejects_wrong_host_triple_boolean_schema_and_invalid_completion(
        self,
    ):
        for field, value in (
            ("target_triple", "aarch64-apple-darwin"),
            ("schema_version", True),
            ("real_processes", 256.0),
            ("workflow_run_attempt", "0"),
            ("completed_at_utc", "2026-02-30T00:00:00Z"),
            ("completed_at_utc", ""),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_target({**self.target(), field: value}, self.target_profile())

    def test_operator_receipt_cannot_substitute_current_run_or_artifact(self):
        receipt = self.target()
        expected = {
            field: receipt[field]
            for field in (
                "lane",
                "source_sha",
                "base_sha",
                "merge_candidate_sha",
                "tested_sha",
                "final_merge_sha",
                "workflow_sha",
                "workflow_run_id",
                "workflow_run_attempt",
                "binary_sha256",
            )
        }
        arguments = (
            expected,
            receipt["binary_sha256"],
            receipt["cargo_lock_sha256"],
            receipt["tested_sha"],
            "linux",
            "x86_64",
        )
        validate_run_binding(receipt, *arguments)
        for field in (*expected, "binary_sha256", "cargo_lock_sha256"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_run_binding({**receipt, field: "stale"}, *arguments)
        legacy = copy.deepcopy(receipt)
        del legacy["workflow_run_attempt"]
        validate_target(legacy, self.target_profile())
        with self.assertRaisesRegex(ValueError, "workflow_run_attempt drift"):
            validate_run_binding(legacy, *arguments)
        for git_sha, host, architecture in (
            ("b" * 40, "linux", "x86_64"),
            (receipt["tested_sha"], "macos", "x86_64"),
            (receipt["tested_sha"], "linux", "aarch64"),
        ):
            with (
                self.subTest(host=host, architecture=architecture),
                self.assertRaises(ValueError),
            ):
                validate_run_binding(
                    receipt, *arguments[:3], git_sha, host, architecture
                )

    def test_receipt_loading_rejects_nonfinite_extensions_and_linked_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "receipt.json"
            for value in ('{"x":NaN}', '{"x":1e999}', '{"x":1,"x":2}'):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    load(path)
            path.write_text("{}")
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                load(link)

    def test_production_source_gate_rejects_incomplete_observation(self):
        for status in ("not_implemented", "partial"):
            matrix = load(
                ROOT / "docs/modules/runtime.supervisor/CAPABILITY_STATUS.json"
            )
            observation = next(
                capability
                for capability in matrix["capabilities"]
                if capability["id"] == "atomic_recovery_observation_envelope"
            )
            observation["source"] = status
            if status == "partial":
                observation["exact_head"] = observation["merge_candidate"] = "pending"
            with (
                self.subTest(status=status),
                patch(
                    "scripts.hepta_supervisor_external_receipt.load",
                    return_value=matrix,
                ),
                self.assertRaisesRegex(
                    ValueError, "implemented and tested atomic recovery observation"
                ),
            ):
                require_production_source(ROOT)

    def test_production_requires_distinct_host_and_review_receipts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = []
            refs = []
            for os_name in ("linux", "macos"):
                path = root / f"{os_name}.json"
                receipt = self.target(os_name)
                path.write_text(json.dumps(receipt, sort_keys=True))
                targets.append((path, receipt))
                refs.append(
                    {
                        "os": os_name,
                        "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
            production = {
                "schema_version": 1,
                "kind": "runtime-supervisor-production-acceptance",
                "profile_id": "production-v1",
                "source_sha": SHA40,
                "base_sha": "c" * 40,
                "merge_candidate_sha": "d" * 40,
                "final_merge_sha": "e" * 40,
                "workflow_sha": "f" * 40,
                "workflow_run_id": "18",
                "binary_sha256": SHA256,
                "cargo_lock_sha256": "c" * 64,
                "feature_set": ["production-verifier"],
                "target_receipts": refs,
                "key_custody_receipts": {
                    name: str(index + 4) * 64
                    for index, name in enumerate(
                        ("custody", "rotation", "revocation", "emergency_restore")
                    )
                },
                "atomic_recovery_observation_sha256": "8" * 64,
                "operator_drill_receipt_sha256": "9" * 64,
                "independent_reviews": [
                    {
                        "role": role,
                        "reviewer": reviewer,
                        "decision": "accepted",
                        "receipt_sha256": digit * 64,
                    }
                    for role, reviewer, digit in (
                        ("code", "code-reviewer", "a"),
                        ("security", "security-reviewer", "b"),
                        ("operations", "operations-reviewer", "c"),
                    )
                ],
                "activation": False,
            }
            validate_production(production, self.production_profile(), targets)
            # Complete-looking external digests cannot lift the current source
            # blocker. The CLI always loads the authoritative checkout matrix.
            production_path = root / "production.json"
            production_profile_path = root / "production-profile.json"
            target_profile_path = root / "target-profile.json"
            production_path.write_text(json.dumps(production))
            production_profile_path.write_text(json.dumps(self.production_profile()))
            target_profile_path.write_text(json.dumps(self.target_profile()))
            command = [
                sys.executable,
                str(ROOT / "scripts/hepta_supervisor_external_receipt.py"),
                "production",
                str(production_path),
                "--profile",
                str(production_profile_path),
                "--target-profile",
                str(target_profile_path),
            ]
            for path, _ in targets:
                command.extend(("--target-receipt", str(path)))
            result = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "implemented and tested atomic recovery observation", result.stderr
            )
            broken = copy.deepcopy(production)
            broken["independent_reviews"][1]["reviewer"] = "code-reviewer"
            with self.assertRaises(ValueError):
                validate_production(broken, self.production_profile(), targets)
            broken = copy.deepcopy(production)
            broken["activation"] = True
            with self.assertRaises(ValueError):
                validate_production(broken, self.production_profile(), targets)
            broken = copy.deepcopy(production)
            broken["target_receipts"].append(
                copy.deepcopy(broken["target_receipts"][0])
            )
            with self.assertRaises(ValueError):
                validate_production(broken, self.production_profile(), targets)
            drifted_targets = copy.deepcopy(targets)
            drifted_targets[0][1]["cargo_lock_sha256"] = "d" * 64
            with self.assertRaises(ValueError):
                validate_production(
                    production, self.production_profile(), drifted_targets
                )
            # Native binaries differ across operating systems. Each target must
            # bind its own artifact while source and lock identities stay shared.
            targets[1][1]["binary_sha256"] = "d" * 64
            targets[1][0].write_text(json.dumps(targets[1][1], sort_keys=True))
            production["target_receipts"][1]["receipt_sha256"] = hashlib.sha256(
                targets[1][0].read_bytes()
            ).hexdigest()
            production["target_binary_sha256"] = {"linux": SHA256, "macos": "d" * 64}
            validate_production(production, self.production_profile(), targets)
            for binaries in ({"linux": SHA256}, {"linux": SHA256, "macos": "e" * 64}):
                with self.subTest(binaries=binaries), self.assertRaises(ValueError):
                    validate_production(
                        {**production, "target_binary_sha256": binaries},
                        self.production_profile(),
                        targets,
                    )
            targets[0][0].write_text(
                json.dumps({**targets[0][1], "schema_version": True})
            )
            production["target_receipts"][0]["receipt_sha256"] = hashlib.sha256(
                targets[0][0].read_bytes()
            ).hexdigest()
            with self.assertRaisesRegex(ValueError, "changed after validation"):
                validate_production(production, self.production_profile(), targets)


if __name__ == "__main__":
    unittest.main()
