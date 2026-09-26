#!/usr/bin/env python3
"""Adversarial aggregate tests. Fixtures are not product qualification receipts."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import hepta_ui_native_aggregate as aggregate
import hepta_ui_native_evidence as evidence


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.candidate, self.base, self.workflow = "a" * 40, "b" * 40, "c" * 40
        self.subjects = {"head": {"sourceSha": self.candidate, "sourceTreeSha": "d" * 40},
                         "merge": {"sourceSha": "e" * 40, "sourceTreeSha": "f" * 40}}
        self.paths = []
        for profile in evidence.qualification_matrix()["include"]:
            folder = self.root / f"ui-native-qualification-{profile['runner']}-{profile['kind']}-{self.candidate}-attempt-1"
            checks_root = folder / "native-evidence/checks"
            checks_root.mkdir(parents=True)
            checks = []
            labels = evidence.REQUIRED + (evidence.LINUX_REQUIRED if profile["os"] == "Linux" else ())
            for label in labels:
                data = f"synthetic unit-test fixture: {label}\n".encode()
                (checks_root / f"{label}.log").write_bytes(data)
                check = {"schema": "hepta.ui.native.check.v1", **self.subjects[profile["kind"]],
                         "label": label, "runId": "101", "runAttempt": "1", "command": ["unit-fixture"],
                         "exitCode": 0, "timedOut": False, "sourceUnchanged": True,
                         "log": f"{label}.log", "logSha256": evidence.sha256(data),
                         "startedAt": "2026-09-27T00:00:00+00:00", "finishedAt": "2026-09-27T00:00:01+00:00"}
                evidence.write_json(checks_root / f"{label}.json", check)
                checks.append(check)
            packages = folder / "native-package"
            packages.mkdir()
            package = packages / "fixture.zip"
            package.write_bytes(b"synthetic artifact; not an installable product")
            receipt = {"schema": evidence.SCHEMA, **self.subjects[profile["kind"]],
                       "candidateSha": self.candidate, "baseSha": self.base, "sourceKind": profile["kind"],
                       "workflowSha": self.workflow, "workflowFileSha256": "1" * 64,
                       "runId": "101", "runAttempt": "1", "qualificationPassed": True,
                       "scope": "repository-controlled-candidate",
                       **dict.fromkeys(aggregate.NON_PROMOTING, False),
                       "platform": {"os": profile["os"], "ImageOS": profile["runner"],
                                    "ImageVersion": "unit-fixture", "RUNNER_ARCH": "X64"},
                       "checks": checks, "sourceInventorySha256": "2" * 64,
                       "testManifestSha256": "3" * 64,
                       "dependencyLocks": {"apps/hepta-native/Cargo.lock": "4" * 64,
                                           "codex-rs/Cargo.lock": "5" * 64},
                       "artifacts": [{"name": package.name, "bytes": package.stat().st_size,
                                      "sha256": aggregate.file_digest(package)}]}
            path = folder / "native-evidence/qualification.json"
            evidence.write_json(path, receipt)
            self.paths.append(path)

    def run_aggregate(self):
        return aggregate.aggregate(self.root, candidate=self.candidate, base=self.base,
            workflow_sha=self.workflow, workflow_digest="1" * 64, run_id="101", attempt="1",
            subjects=self.subjects)

    def mutate(self, change, index=0):
        path = self.paths[index]
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_complete_matrix_returns_six_nonpromoting_subjects(self):
        result = self.run_aggregate()
        self.assertEqual(len(result["subjects"]), 6)
        self.assertFalse(result["productionImplementation"])
        self.assertFalse(result["releaseAuthorized"])

    def test_missing_bundle(self):
        shutil.rmtree(self.paths[0].parents[1])
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_foreign_bundle(self):
        (self.root / "unexpected").mkdir()
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_missing_receipt(self):
        self.paths[0].unlink()
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_each_exact_identity_is_checked(self):
        original = self.paths[0].read_bytes()
        for field in ("candidateSha", "baseSha", "sourceSha", "sourceTreeSha", "workflowSha",
                      "workflowFileSha256", "runId", "runAttempt", "sourceKind"):
            with self.subTest(field=field):
                self.paths[0].write_bytes(original)
                self.mutate(lambda d: d.update({field: "foreign"}))
                with self.assertRaises(ValueError): self.run_aggregate()

    def test_boolean_success_must_be_exact(self):
        self.mutate(lambda d: d.update(qualificationPassed=1))
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_missing_false_or_promoting_flags(self):
        original = self.paths[0].read_bytes()
        for field in aggregate.NON_PROMOTING:
            for value in (True, None, 0):
                with self.subTest(field=field, value=value):
                    self.paths[0].write_bytes(original)
                    self.mutate(lambda d: d.update({field: value}))
                    with self.assertRaises(ValueError): self.run_aggregate()

    def test_modified_log(self):
        (self.paths[0].parent / "checks/app_tests.log").write_bytes(b"tampered")
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_modified_retained_check(self):
        path = self.paths[0].parent / "checks/app_tests.json"
        data = json.loads(path.read_text())
        data["exitCode"] = 1
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_failed_skipped_cancelled_embedded_checks(self):
        original = self.paths[0].read_bytes()
        for value in (1, None, 130, False):
            self.paths[0].write_bytes(original)
            self.mutate(lambda d: d["checks"][0].update(exitCode=value))
            with self.assertRaises(ValueError): self.run_aggregate()

    def test_missing_check(self):
        self.mutate(lambda d: d["checks"].pop())
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_modified_or_missing_package(self):
        package = self.paths[0].parents[1] / "native-package/fixture.zip"
        package.write_bytes(b"modified")
        with self.assertRaises(ValueError): self.run_aggregate()
        package.unlink()
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_unbound_extra_package(self):
        (self.paths[0].parents[1] / "native-package/extra.zip").write_bytes(b"unbound")
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_package_path_traversal(self):
        self.mutate(lambda d: d["artifacts"][0].update(name="../fixture.zip"))
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_duplicate_artifact(self):
        self.mutate(lambda d: d["artifacts"].append(copy.deepcopy(d["artifacts"][0])))
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_platform_and_inventory_substitution(self):
        original = self.paths[2].read_bytes()
        self.mutate(lambda d: d["platform"].update(os="Linux"), 2)
        with self.assertRaises(ValueError): self.run_aggregate()
        self.paths[2].write_bytes(original)
        self.mutate(lambda d: d.update(sourceInventorySha256="9" * 64), 2)
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_duplicate_json_key(self):
        self.paths[0].write_text('{"schema":"a","schema":"b"}')
        with self.assertRaises(ValueError): self.run_aggregate()

    @unittest.skipIf(os.name == "nt", "symlink creation requires host privilege")
    def test_symlink_bundle_refused(self):
        path = self.paths[0]
        target = self.root.parent / (self.root.name + "-receipt")
        target.write_bytes(path.read_bytes())
        self.addCleanup(target.unlink)
        path.unlink()
        path.symlink_to(target)
        with self.assertRaises(ValueError): self.run_aggregate()

    def test_empty_run_identity(self):
        with self.assertRaises(ValueError):
            aggregate.aggregate(self.root, candidate=self.candidate, base=self.base,
                workflow_sha=self.workflow, workflow_digest="1" * 64, run_id="", attempt="1",
                subjects=self.subjects)


class DeterministicSubjectTests(unittest.TestCase):
    def test_reconstructs_ordered_merge_from_real_git_objects(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
            git("init", "--quiet")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            (root / "base").write_text("base")
            git("add", ".")
            git("commit", "--quiet", "-m", "base")
            base = git("rev-parse", "HEAD")
            (root / "candidate").write_text("candidate")
            git("add", ".")
            git("commit", "--quiet", "-m", "candidate")
            candidate = git("rev-parse", "HEAD")
            result = aggregate.deterministic_subjects(root, candidate, base)
            self.assertEqual(result, aggregate.deterministic_subjects(root, candidate, base))
            self.assertEqual(git("show", "-s", "--format=%P", result["merge"]["sourceSha"]).split(),
                             [base, candidate])
            self.assertEqual(result["head"]["sourceTreeSha"], git("rev-parse", "HEAD^{tree}"))


if __name__ == "__main__":
    unittest.main()
