#!/usr/bin/env python3
"""Adversarial aggregate tests. Fixtures are not product qualification receipts."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import hepta_ui_native_aggregate as aggregate
import hepta_ui_native_evidence as evidence
import hepta_ui_native_product_evidence as product_evidence


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate, self.base, self.workflow = "a" * 40, "b" * 40, "c" * 40
        self.subjects = {
            "head": {"sourceSha": self.candidate, "sourceTreeSha": "d" * 40},
            "merge": {"sourceSha": "e" * 40, "sourceTreeSha": "f" * 40},
        }
        self.paths = []
        self.product_paths = []
        for profile in evidence.qualification_matrix()["include"]:
            folder = self.root / (
                f"ui-native-qualification-{profile['runner']}-{profile['kind']}-"
                f"{self.candidate}-attempt-1"
            )
            checks_root = folder / "native-evidence/checks"
            checks_root.mkdir(parents=True)
            checks = []
            labels = evidence.REQUIRED + (
                evidence.LINUX_REQUIRED if profile["os"] == "Linux" else ()
            )
            for label in labels:
                data = f"synthetic unit-test fixture: {label}\n".encode()
                (checks_root / f"{label}.log").write_bytes(data)
                check = {
                    "schema": "hepta.ui.native.check.v1",
                    **self.subjects[profile["kind"]],
                    "label": label,
                    "runId": "101",
                    "runAttempt": "1",
                    "command": ["unit-fixture"],
                    "exitCode": 0,
                    "timedOut": False,
                    "sourceUnchanged": True,
                    "log": f"{label}.log",
                    "logSha256": evidence.sha256(data),
                    "startedAt": "2026-09-27T00:00:00+00:00",
                    "finishedAt": "2026-09-27T00:00:01+00:00",
                }
                evidence.write_json(checks_root / f"{label}.json", check)
                checks.append(check)
            packages = folder / "native-package"
            packages.mkdir()
            package = packages / "fixture.zip"
            package.write_bytes(b"synthetic artifact; not an installable product")
            binary_digests = {
                "usr/bin/hepta-native": "6" * 64,
                "usr/bin/hepta-native-credential": "7" * 64,
            }
            manifest = {
                "schema": "hepta.ui-native-unsigned-package.v1",
                "platform": profile["os"].lower(),
                "architecture": "x86_64",
                "binarySha256": binary_digests,
            }
            package_receipt = {
                "schema": product_evidence.PACKAGE_SCHEMA,
                "platform": profile["os"].lower(),
                "architecture": "x86_64",
                "archive": package.name,
                "archiveSha256": aggregate.file_digest(package),
                "manifest": manifest,
            }
            (packages / "package-receipt.json").write_text(
                json.dumps(package_receipt), encoding="utf-8"
            )
            platform = {
                "os": profile["os"],
                "ImageOS": profile["runner"],
                "ImageVersion": "unit-fixture",
                "RUNNER_ARCH": "X64",
            }
            receipt = {
                "schema": evidence.SCHEMA,
                **self.subjects[profile["kind"]],
                "candidateSha": self.candidate,
                "baseSha": self.base,
                "sourceKind": profile["kind"],
                "workflowSha": self.workflow,
                "workflowFileSha256": "1" * 64,
                "runId": "101",
                "runAttempt": "1",
                "qualificationPassed": True,
                "scope": "repository-controlled-candidate",
                **dict.fromkeys(aggregate.NON_PROMOTING, False),
                "platform": platform,
                "checks": checks,
                "sourceInventorySha256": "2" * 64,
                "testManifestSha256": "3" * 64,
                "dependencyLocks": {
                    "apps/hepta-native/Cargo.lock": "4" * 64,
                    "codex-rs/Cargo.lock": "5" * 64,
                },
                "artifacts": [
                    {
                        "name": package.name,
                        "bytes": package.stat().st_size,
                        "sha256": aggregate.file_digest(package),
                    }
                ],
            }
            path = folder / "native-evidence/qualification.json"
            evidence.write_json(path, receipt)
            self.paths.append(path)
            if profile["os"] == "Linux":
                product_path = folder / product_evidence.PRODUCT_RELATIVE
                product_path.parent.mkdir(parents=True)
                product_path.write_text(
                    json.dumps(
                        self.product_receipt(
                            profile, binary_digests, manifest, platform
                        ),
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                self.product_paths.append(product_path)

    def product_receipt(self, profile, binary_digests, manifest, platform):
        starts = []
        for index in range(2):
            starts.append(
                {
                    "process_id": 2000 + index,
                    "session": {
                        "session_id": f"ordinary-session-{profile['kind']}-{index}"
                    },
                    "normal_close_exit_code": 0,
                    "measurements": {
                        "schema": product_evidence.MEASUREMENT_SCHEMA,
                        "packageBinarySha256": binary_digests,
                        "launchToReadinessMs": 10.0 + index,
                        "launchToVisibleWindowMs": 12.0 + index,
                        "keyboardCommandMs": 2.0 + index,
                        "normalCloseMs": 4.0 + index,
                        "residentKiBAtObservation": 1024 + index,
                        "focusedWindowBefore": 3000 + index,
                        "focusedWindowAfter": 3000 + index,
                        "sampleIndex": index,
                        "virtualFocusObserved": True,
                        "keyboardEventsDelivered": True,
                        "inputLatencyMeasured": False,
                        "soakMeasured": False,
                        "productionThresholdEvaluated": False,
                    },
                }
            )
        return {
            "schema": product_evidence.PRODUCT_SCHEMA,
            "candidateSha": self.candidate,
            **self.subjects[profile["kind"]],
            "sourceKind": profile["kind"],
            "workflowSha": self.workflow,
            "runId": "101",
            "runAttempt": "1",
            "runner": {
                "ImageOS": platform["ImageOS"],
                "ImageVersion": platform["ImageVersion"],
                "RUNNER_ARCH": platform["RUNNER_ARCH"],
            },
            "packageBinarySha256": binary_digests,
            "packageManifestSha256": hashlib.sha256(
                (json.dumps(manifest, indent=2) + "\n").encode()
            ).hexdigest(),
            "gatewaySha256": "8" * 64,
            "keyringProvisionReceipt": {
                "schema": "hepta.native-gateway-credential-provision.v1",
                "account": "native.qual.fixture",
                "token_digest": "9" * 64,
            },
            "keyringDeleteReceipt": {
                "schema": "hepta.native-gateway-credential-delete.v1",
                "account": "native.qual.fixture",
                "deleted": True,
            },
            "keyringCredentialLifecycleObserved": True,
            "normalConnection": {"session": {"session_id": "connection-session"}},
            "ordinaryGuiStarts": starts,
            "visibleWindowObserved": True,
            "virtualFocusObserved": True,
            "keyboardEventsDelivered": True,
            "normalCloseVerified": True,
            "ownerStateUnchanged": True,
            "environment": "isolated Linux Xvfb/DBus with real OS keyring and owner-format fixture",
            "physicalDisplayAcceptance": False,
            "physicalInputAcceptance": False,
            "screenReaderAcceptance": False,
            "cjkImeAcceptance": False,
            "independentAcceptance": False,
            "productionKeyCustodyAcceptance": False,
            "release": False,
        }

    def run_aggregate(self):
        return aggregate.aggregate(
            self.root,
            candidate=self.candidate,
            base=self.base,
            workflow_sha=self.workflow,
            workflow_digest="1" * 64,
            run_id="101",
            attempt="1",
            subjects=self.subjects,
        )

    def mutate(self, change, index=0):
        path = self.paths[index]
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def mutate_product(self, change, index=0):
        path = self.product_paths[index]
        data = json.loads(path.read_text(encoding="utf-8"))
        change(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_complete_matrix_returns_six_nonpromoting_subjects(self):
        result = self.run_aggregate()
        self.assertEqual(result["schema"], "hepta.ui.native.aggregate.v2")
        self.assertEqual(len(result["subjects"]), 6)
        self.assertEqual(
            len(
                [
                    subject
                    for subject in result["subjects"]
                    if subject["linuxProductObservation"] is not None
                ]
            ),
            2,
        )
        self.assertFalse(result["productionImplementation"])
        self.assertFalse(result["releaseAuthorized"])

    def test_missing_bundle(self):
        shutil.rmtree(self.paths[0].parents[1])
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_foreign_bundle(self):
        (self.root / "unexpected").mkdir()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_missing_receipt(self):
        self.paths[0].unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_each_exact_identity_is_checked(self):
        original = self.paths[0].read_bytes()
        for field in (
            "candidateSha",
            "baseSha",
            "sourceSha",
            "sourceTreeSha",
            "workflowSha",
            "workflowFileSha256",
            "runId",
            "runAttempt",
            "sourceKind",
        ):
            with self.subTest(field=field):
                self.paths[0].write_bytes(original)
                self.mutate(lambda data: data.update({field: "foreign"}))
                with self.assertRaises(ValueError):
                    self.run_aggregate()

    def test_boolean_success_must_be_exact(self):
        self.mutate(lambda data: data.update(qualificationPassed=1))
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_missing_false_or_promoting_flags(self):
        original = self.paths[0].read_bytes()
        for field in aggregate.NON_PROMOTING:
            for value in (True, None, 0):
                with self.subTest(field=field, value=value):
                    self.paths[0].write_bytes(original)
                    self.mutate(lambda data: data.update({field: value}))
                    with self.assertRaises(ValueError):
                        self.run_aggregate()

    def test_modified_log(self):
        (self.paths[0].parent / "checks/app_tests.log").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_modified_retained_check(self):
        path = self.paths[0].parent / "checks/app_tests.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["exitCode"] = 1
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_failed_skipped_cancelled_embedded_checks(self):
        original = self.paths[0].read_bytes()
        for value in (1, None, 130, False):
            self.paths[0].write_bytes(original)
            self.mutate(lambda data: data["checks"][0].update(exitCode=value))
            with self.assertRaises(ValueError):
                self.run_aggregate()

    def test_missing_check(self):
        self.mutate(lambda data: data["checks"].pop())
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_modified_or_missing_package(self):
        package = self.paths[0].parents[1] / "native-package/fixture.zip"
        package.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            self.run_aggregate()
        package.unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_unbound_extra_package(self):
        (self.paths[0].parents[1] / "native-package/extra.zip").write_bytes(b"unbound")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_package_path_traversal(self):
        self.mutate(lambda data: data["artifacts"][0].update(name="../fixture.zip"))
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_duplicate_artifact(self):
        self.mutate(
            lambda data: data["artifacts"].append(copy.deepcopy(data["artifacts"][0]))
        )
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_platform_and_inventory_substitution(self):
        original = self.paths[2].read_bytes()
        self.mutate(lambda data: data["platform"].update(os="Linux"), 2)
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.paths[2].write_bytes(original)
        self.mutate(lambda data: data.update(sourceInventorySha256="9" * 64), 2)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_missing_or_foreign_linux_product_receipt(self):
        original = self.product_paths[0].read_bytes()
        self.product_paths[0].unlink()
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.product_paths[0].write_bytes(original)
        self.mutate_product(lambda data: data.update(sourceSha="0" * 40))
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_linux_product_cannot_promote_virtual_host_evidence(self):
        self.mutate_product(lambda data: data.update(physicalDisplayAcceptance=True))
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_linux_product_requires_keyring_deletion_and_package_binding(self):
        original = self.product_paths[0].read_bytes()
        self.mutate_product(
            lambda data: data["keyringDeleteReceipt"].update(deleted=False)
        )
        with self.assertRaises(ValueError):
            self.run_aggregate()
        self.product_paths[0].write_bytes(original)
        self.mutate_product(
            lambda data: data["packageBinarySha256"].update(
                {"usr/bin/hepta-native": "0" * 64}
            )
        )
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_non_linux_product_receipt_is_refused(self):
        source = self.product_paths[0]
        destination = self.paths[2].parents[1] / product_evidence.PRODUCT_RELATIVE
        destination.parent.mkdir(parents=True)
        destination.write_bytes(source.read_bytes())
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_duplicate_json_key(self):
        self.paths[0].write_text('{"schema":"a","schema":"b"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_aggregate()

    @unittest.skipIf(os.name == "nt", "symlink creation requires host privilege")
    def test_symlink_bundle_refused(self):
        path = self.paths[0]
        target = self.root.parent / (self.root.name + "-receipt")
        target.write_bytes(path.read_bytes())
        self.addCleanup(target.unlink)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(ValueError):
            self.run_aggregate()

    def test_empty_run_identity(self):
        with self.assertRaises(ValueError):
            aggregate.aggregate(
                self.root,
                candidate=self.candidate,
                base=self.base,
                workflow_sha=self.workflow,
                workflow_digest="1" * 64,
                run_id="",
                attempt="1",
                subjects=self.subjects,
            )


class DeterministicSubjectTests(unittest.TestCase):
    def test_reconstructs_ordered_merge_from_real_git_objects(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            def git(*args):
                return subprocess.check_output(
                    ["git", *args],
                    cwd=root,
                    text=True,
                    encoding="utf-8",
                    errors="strict",
                ).strip()

            git("init", "--quiet")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "base").write_text("base", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            (root / "candidate").write_text("candidate", encoding="utf-8")
            git("add", ".")
            git("commit", "--quiet", "-m", "candidate")
            candidate = git("rev-parse", "HEAD")
            check_output = subprocess.check_output
            with patch.object(
                aggregate.subprocess, "check_output", wraps=check_output
            ) as invoked:
                result = aggregate.deterministic_subjects(root, candidate, base)
            commit_calls = [
                call
                for call in invoked.call_args_list
                if call.args[0][1] == "commit-tree"
            ]
            self.assertEqual(len(commit_calls), 1)
            self.assertIsInstance(commit_calls[0].kwargs["input"], bytes)
            self.assertFalse(commit_calls[0].kwargs.get("text", False))
            payload = check_output(
                ["git", "cat-file", "commit", result["merge"]["sourceSha"]],
                cwd=root,
            )
            self.assertEqual(
                payload.split(b"\n\n", 1)[1],
                b"deterministic ui.native qualification merge\n",
            )
            self.assertEqual(
                result, aggregate.deterministic_subjects(root, candidate, base)
            )
            self.assertEqual(
                git("show", "-s", "--format=%P", result["merge"]["sourceSha"]).split(),
                [base, candidate],
            )
            self.assertEqual(
                result["head"]["sourceTreeSha"], git("rev-parse", "HEAD^{tree}")
            )


if __name__ == "__main__":
    unittest.main()
