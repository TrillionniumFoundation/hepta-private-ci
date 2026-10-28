#!/usr/bin/env python3
"""Tiny synthetic evidence-boundary tests; no Cargo, Bazel, or model calls."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import hepta_dependency_validation as policy
import run_hepta_dependency_validation as runner


def xml(names, *, failed=(), errors=(), skipped=(), line=7):
    root = ET.Element(
        "testsuites",
        tests=str(len(names)),
        failures=str(len(failed)),
        errors=str(len(errors)),
    )
    suite = ET.SubElement(
        root,
        "testsuite",
        name="synthetic",
        tests=str(len(names)),
        failures=str(len(failed)),
        errors=str(len(errors)),
    )
    for index, name in enumerate(names):
        case = ET.SubElement(suite, "testcase", name=name, classname="synthetic")
        if index in failed:
            ET.SubElement(case, "failure", type="test failure").text = (
                f"thread '{name}' panicked at core-plugins/src/startup_sync_zip_tests.rs:{line}:5:\n"
                "assertion failed: `(left == right)`\nDiff: privileged mode differs"
            )
        if index in errors:
            ET.SubElement(case, "error").text = "process abort"
        if index in skipped:
            ET.SubElement(case, "skipped")
    return ET.tostring(root)


class DependencyValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        config = self.root / "codex-rs/.config/nextest.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[profile.default.junit]\npath = "junit.xml"\n[profile.local]\ninherits = "default"\n'
            '[profile.local.junit]\npath = "junit.xml"\n'
        )
        (self.root / "justfile").write_text(
            'set working-directory := "codex-rs"\n    NEXTEST_PROFILE=local python3 ../scripts/run-nextest.py "$@"\n'
        )
        self.out = self.root / "out"
        (self.out / "payload").mkdir(parents=True)
        (self.out / "delivery").mkdir()
        self.spec = policy.GROUPS[0]
        self.regression = {"assert_line": 7}
        self.result = {"exit_code": 100, "timed_out": False}
        self.candidate_dependencies = {
            "zip": "=9.1.2",
            "zstd": "=0.14.3",
            "serde_yaml": {"package": "serde_norway", "version": "=0.9.42"},
        }

    def parse(self, raw, **kwargs):
        return policy.junit_result(
            raw, self.result, self.spec, self.regression, baseline=True, **kwargs
        )

    def lock_pair(self):
        def package(name, version):
            return {
                "name": name,
                "version": version,
                "source": "registry+https://github.com/rust-lang/crates.io-index",
                "checksum": name + version,
            }

        common = [package(name, version) for name, version in policy.TLS.items()]
        old = {
            "version": 4,
            "package": common
            + [package("zip", "2.4.2"), package("serde_yaml", "0.9.34+deprecated")],
        }
        new = {
            "version": 4,
            "package": copy.deepcopy(common)
            + [
                package("zip", "9.1.2"),
                package("zstd", "0.14.3"),
                package("serde_norway", "0.9.42"),
                package("unsafe-libyaml-norway", "0.2.15"),
            ],
        }
        return old, new

    def receipt(self, mode="baseline"):
        return {
            "commands": [],
            "tests": [],
            "errors": [],
            "qualification": False,
            "mode": mode,
            "regression": self.regression,
            "source_head": "a" * 40,
            "source_tree": "b" * 40,
            "source_inputs": {},
            "validation_passed": False,
        }

    def test_formatted_source_line_and_hash_are_both_bound(self):
        raw = b"\n" * 6 + b"    assert_eq!(actual, expected);\n}\n"
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(policy.regression_contract(raw, digest)["assert_line"], 7)
        for altered, wanted in (
            (raw + b"\n", digest),
            (raw, "UNFILLED"),
            (raw * 2, hashlib.sha256(raw * 2).hexdigest()),
        ):
            with self.subTest(altered=altered), self.assertRaises(ValueError):
                policy.regression_contract(altered, wanted)

    def test_baseline_requires_the_expected_executed_failure(self):
        actual = self.parse(xml([policy.REGRESSION_NAME], failed=(0,)))
        self.assertEqual(
            (actual["tests"], actual["failures"], actual["errors"]), (1, 1, 0)
        )
        self.assertTrue(actual["expected_regression_observed"])
        self.assertTrue(actual["passed"])
        self.assertNotIn("names", actual)
        self.assertEqual(
            actual["filter_matches"],
            [{"filter": "=" + policy.REGRESSION_NAME, "executed_tests": 1}],
        )
        for code in (0, 1, 4, 101, 102, -9):
            with self.subTest(code=code), self.assertRaises(ValueError):
                policy.junit_result(
                    xml([policy.REGRESSION_NAME], failed=(0,)),
                    {"exit_code": code, "timed_out": False},
                    self.spec,
                    self.regression,
                    baseline=True,
                )

    def test_other_panic_empty_missing_case_skip_and_abort_are_not_a_counterexample(
        self,
    ):
        documents = [
            xml([policy.REGRESSION_NAME], failed=(0,), line=6),
            xml([]),
            xml(["wrong_test"], failed=(0,)),
            xml([policy.REGRESSION_NAME]),
            xml([policy.REGRESSION_NAME], skipped=(0,)),
            xml([policy.REGRESSION_NAME], errors=(0,)),
        ]
        for raw in documents:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.parse(raw)

    def test_retries_duplicates_and_bad_declared_counts_are_rejected(self):
        tree = ET.fromstring(xml([policy.REGRESSION_NAME], failed=(0,)))
        ET.SubElement(tree.find("testsuite/testcase"), "rerunFailure")
        raw_retry = ET.tostring(tree)
        tree = ET.fromstring(xml([policy.REGRESSION_NAME], failed=(0,)))
        tree.set("tests", "2")
        for raw in (
            raw_retry,
            ET.tostring(tree),
            xml([policy.REGRESSION_NAME] * 2, failed=(0, 1)),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.parse(raw)

    def test_timeout_cannot_pass_with_a_plausible_junit(self):
        with self.assertRaises(ValueError):
            policy.junit_result(
                xml([policy.REGRESSION_NAME], failed=(0,)),
                {"exit_code": 100, "timed_out": True},
                self.spec,
                self.regression,
                baseline=True,
            )

    def test_candidate_requires_every_filter_to_execute_and_all_cases_to_pass(self):
        spec = policy.group("mixed", "codex-example", "alpha::", "=beta")
        result = {"exit_code": 0, "timed_out": False}
        actual = policy.junit_result(
            xml(["alpha::one", "beta"]), result, spec, self.regression
        )
        names = json.dumps(
            ["alpha::one", "beta"], ensure_ascii=False, separators=(",", ":")
        ).encode()
        self.assertEqual(actual["names_sha256"], hashlib.sha256(names).hexdigest())
        self.assertEqual(
            actual["filter_matches"],
            [
                {"filter": "alpha::", "executed_tests": 1},
                {"filter": "=beta", "executed_tests": 1},
            ],
        )
        for raw in (
            xml(["alpha::one"]),
            xml(["alpha::one", "beta"], failed=(1,)),
            xml(["alpha::one", "beta", "outside"]),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                policy.junit_result(raw, result, spec, self.regression)

    def test_dtd_and_entity_evidence_are_rejected(self):
        with self.assertRaises(ValueError):
            self.parse(b'<!DOCTYPE testsuites [<!ENTITY x "x">]><testsuites/>')

    def test_manifest_arm_mismatch_is_not_accepted(self):
        old = {
            "workspace": {
                "dependencies": {"zip": "2.4.2", "zstd": "0.13", "serde_yaml": "0.9"}
            }
        }
        policy.manifest_contract(old, "Permissions::from_mode(mode)", "baseline")
        with self.assertRaises(ValueError):
            policy.manifest_contract(
                old, "Permissions::from_mode(mode & 0o777)", "baseline"
            )
        with self.assertRaises(ValueError):
            policy.manifest_contract(old, "Permissions::from_mode(mode)", "candidate")
        self.assertEqual(
            policy.manifest_contract(
                {"workspace": {"dependencies": self.candidate_dependencies}},
                "Permissions::from_mode(mode & 0o777)",
                "candidate",
            ),
            self.candidate_dependencies,
        )

    def test_candidate_caret_and_resolved_version_drift_are_rejected(self):
        for name, expected in self.candidate_dependencies.items():
            version = expected["version"] if isinstance(expected, dict) else expected
            for requirement in (version.removeprefix("="), "^" + version[1:]):
                changed = copy.deepcopy(self.candidate_dependencies)
                if isinstance(changed[name], dict):
                    changed[name]["version"] = requirement
                else:
                    changed[name] = requirement
                with (
                    self.subTest(name=name, requirement=requirement),
                    self.assertRaisesRegex(ValueError, "dependency declarations"),
                ):
                    policy.manifest_contract(
                        {"workspace": {"dependencies": changed}},
                        "Permissions::from_mode(mode & 0o777)",
                        "candidate",
                    )
        changed = copy.deepcopy(self.candidate_dependencies)
        changed["zip"] = "=9.1.3"
        with self.assertRaisesRegex(ValueError, "dependency declarations"):
            policy.manifest_contract(
                {"workspace": {"dependencies": changed}},
                "Permissions::from_mode(mode & 0o777)",
                "candidate",
            )
        before, after = self.lock_pair()
        for package in after["package"]:
            if package["name"] == "zip":
                package["version"] = "9.1.3"
        with self.assertRaisesRegex(ValueError, "root package did not resolve exactly"):
            policy.lock_delta(before, after)

    def test_real_extra_package_is_reported_for_review_not_blanket_approved(self):
        before, after = self.lock_pair()
        after["package"].append(
            {"name": "new-native-backend", "version": "4.2", "source": "git+review-me"}
        )
        original = copy.deepcopy((before, after))
        result = policy.lock_delta(before, after)
        self.assertFalse(result["qualification"])
        self.assertFalse(result["dependency_graph_approved"])
        self.assertIn(after["package"][-1], result["added"])
        self.assertEqual((before, after), original)

    def test_tls_package_source_version_checksum_and_duplicates_remain_protected(self):
        before, after = self.lock_pair()
        for field, value in (
            ("source", "git+different"),
            ("version", "0.23.47"),
            ("checksum", "changed"),
        ):
            mutated = copy.deepcopy(after)
            mutated["package"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                policy.lock_delta(before, mutated)
        after["package"].append(copy.deepcopy(after["package"][0]))
        with self.assertRaises(ValueError):
            policy.lock_delta(before, after)

    def test_original_yaml_cannot_remain_hidden_in_the_lock(self):
        before, after = self.lock_pair()
        after["package"].append({"name": "unsafe-libyaml", "version": "0.2.11"})
        with self.assertRaises(ValueError):
            policy.lock_delta(before, after)

    def test_partial_resolver_failure_still_has_an_unapproved_complete_delta(self):
        before, after = self.lock_pair()
        after["package"] = after["package"][:2]
        with self.assertRaises(ValueError):
            policy.lock_delta(before, after)
        delta = policy.package_difference(before, after)
        self.assertFalse(delta["dependency_graph_approved"])
        self.assertEqual(
            delta["removed"],
            [
                item
                for item in sorted(
                    before["package"],
                    key=lambda p: (p["name"], p["version"], p.get("source", "")),
                )
                if item not in after["package"]
            ],
        )

    def test_scope_allows_candidate_locks_only_and_baseline_no_mutations(self):
        policy.changed_scope(policy.LOCKS, "candidate")
        for paths, mode in (
            (policy.LOCKS, "baseline"),
            (("codex-rs/deny.toml",), "candidate"),
            (("codex-rs/Cargo.toml",), "candidate"),
        ):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                policy.changed_scope(paths, mode)

    def test_fresh_junit_cannot_be_replaced_by_old_success(self):
        target = self.root / "separate-cargo-target"
        untouched = target / "nextest/local/junit.xml"
        untouched.parent.mkdir(parents=True)
        untouched.write_bytes(b"Cargo target-dir is not the nextest store")
        junit = self.root / "codex-rs/target/nextest/local/junit.xml"
        junit.parent.mkdir(parents=True)
        stale = xml([policy.REGRESSION_NAME])
        fresh = xml([policy.REGRESSION_NAME], failed=(0,))
        junit.write_bytes(stale)
        rec = self.receipt()

        def simulate(*args, **kwargs):
            self.assertFalse(junit.exists())
            self.assertEqual(
                untouched.read_bytes(), b"Cargo target-dir is not the nextest store"
            )
            junit.write_bytes(fresh)
            return self.result

        with (
            patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target)}),
            patch.object(runner, "invoke", side_effect=simulate),
        ):
            runner.test_group(rec, self.out, self.root, self.spec)
        report = rec["tests"][0]
        self.assertTrue(report["passed"])
        self.assertEqual(
            report["stale_junit_removed"]["sha256"], hashlib.sha256(stale).hexdigest()
        )
        self.assertEqual((self.out / "payload/zip_mode.junit.xml").read_bytes(), fresh)
        self.assertEqual(
            untouched.read_bytes(), b"Cargo target-dir is not the nextest store"
        )

    def test_absent_new_junit_is_failure_even_if_command_returns_zero(self):
        target = self.root / "target"
        junit = self.root / "codex-rs/target/nextest/local/junit.xml"
        junit.parent.mkdir(parents=True)
        junit.write_bytes(xml([policy.REGRESSION_NAME]))
        rec = self.receipt("candidate")
        with (
            patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target)}),
            patch.object(
                runner, "invoke", return_value={"exit_code": 0, "timed_out": False}
            ),
        ):
            runner.test_group(rec, self.out, self.root, self.spec)
        self.assertFalse(rec["tests"][0]["passed"])
        self.assertIsNone(rec["tests"][0]["junit"])

    def test_oversized_junit_has_explicit_omission_and_never_passes(self):
        target = self.root / "target"
        junit = self.root / "codex-rs/target/nextest/local/junit.xml"
        junit.parent.mkdir(parents=True)
        junit.write_bytes(b"x" * 33)
        rec = self.receipt()
        with (
            patch.dict(os.environ, {"CARGO_TARGET_DIR": str(target)}),
            patch.object(runner, "JUNIT_CAP", 32),
            patch.object(runner, "invoke") as invoke,
        ):
            runner.test_group(rec, self.out, self.root, self.spec)
        invoke.assert_not_called()
        self.assertFalse(rec["tests"][0]["passed"])
        self.assertEqual(rec["tests"][0]["uncollected_junit"]["bytes"], 33)
        self.assertTrue(junit.exists())

    def test_head_and_tree_must_both_match(self):
        rec = self.receipt()
        with patch.object(
            runner, "git", return_value="a" * 40 + "\n" + "c" * 40 + "\n"
        ):
            with self.assertRaises(ValueError):
                runner.source_state(rec, self.out, self.root, "sample")

    def test_capture_failure_is_checkpointed_without_inventing_an_exit_code(self):
        rec = self.receipt()
        with patch.object(
            runner, "capture", side_effect=OSError("synthetic spawn failure")
        ):
            with self.assertRaises(OSError):
                runner.invoke(
                    rec, self.out, self.root, "fake", ["not-executed"], limit=128
                )
        stored = json.loads((self.out / "delivery/receipt.json").read_text())
        self.assertIn("capture_error", stored["commands"][0])
        self.assertNotIn("exit_code", stored["commands"][0])

    def test_duplicate_command_label_cannot_replace_prior_capture(self):
        rec = self.receipt()
        rec["commands"].append(
            {"label": "reused", "command": ["original"], "state": "started"}
        )
        original = copy.deepcopy(rec)
        retained = self.out / "payload/reused.stdout.log"
        retained.write_bytes(b"original capture bytes\n")
        with patch.object(runner, "capture") as capture:
            with self.assertRaisesRegex(ValueError, "command label already recorded"):
                runner.invoke(
                    rec, self.out, self.root, "reused", ["not-executed"], limit=128
                )
        capture.assert_not_called()
        self.assertEqual(rec, original)
        self.assertEqual(retained.read_bytes(), b"original capture bytes\n")
        self.assertEqual(list((self.out / "delivery").iterdir()), [])

    def test_payload_reservation_prevents_writing_over_the_bound(self):
        (self.out / "payload/old").write_bytes(b"123456")
        with patch.object(runner, "PAYLOAD_CAP", 10):
            with self.assertRaises(ValueError):
                runner.put_json(self.out, "too-large.json", {"sample": "more"})
        self.assertFalse((self.out / "payload/too-large.json").exists())

    def test_fixed_branch_and_nonplaceholder_identities_are_required(self):
        environment = {
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": policy.BRANCH,
            "GITHUB_SHA": "a" * 40,
            "BASELINE_SHA": "b" * 40,
        }
        with patch.dict(os.environ, environment):
            self.assertEqual(
                runner.phase_environment("baseline")["source_head"], "b" * 40
            )
        for key, value in (
            ("BASELINE_SHA", "REPLACE_ME"),
            ("GITHUB_REF", "refs/heads/main"),
            ("GITHUB_EVENT_NAME", "pull_request"),
        ):
            with (
                self.subTest(key=key),
                patch.dict(os.environ, {**environment, key: value}),
                self.assertRaises(ValueError),
            ):
                runner.phase_environment("candidate")

    def test_finalize_preserves_real_execution_failure_and_literal_locks(self):
        source = self.root / "source"
        (source / "codex-rs").mkdir(parents=True)
        (source / "codex-rs/Cargo.lock").write_text("version = 4\npackage = []\n")
        (source / "MODULE.bazel.lock").write_text("{}\n")
        rec = self.receipt("candidate")
        rec["effective_locks"] = runner.snapshot_locks(source, self.out, "before")
        rec["validation_passed"] = True
        with patch.object(runner, "source_state", return_value=[]):
            runner.finalize(source, self.out, rec, "failure")
        self.assertFalse(rec["validation_passed"])
        self.assertFalse(rec["qualification"])
        self.assertTrue(rec["finalized"])
        self.assertEqual(rec["final_locks"], rec["effective_locks"])
        self.assertTrue((self.out / "delivery/maintenance.tar.gz").is_file())
        self.assertIn("execution did not finish", rec["errors"][0])

    def test_final_lock_drift_cannot_be_reported_as_the_tested_input(self):
        source = self.root / "source"
        (source / "codex-rs").mkdir(parents=True)
        (source / "codex-rs/Cargo.lock").write_text("version = 4\npackage = []\n")
        (source / "MODULE.bazel.lock").write_text("{}\n")
        rec = self.receipt("candidate")
        rec["effective_locks"] = runner.snapshot_locks(source, self.out, "before")
        rec["validation_passed"] = True
        (source / "codex-rs/Cargo.lock").write_text("version = 3\npackage = []\n")
        with patch.object(runner, "source_state", return_value=list(policy.LOCKS)):
            runner.finalize(source, self.out, rec, "success")
        self.assertFalse(rec["validation_passed"])
        self.assertNotEqual(rec["final_locks"], rec["effective_locks"])
        delta = json.loads((self.out / "payload/FINAL_PACKAGE_DELTA.json").read_text())
        self.assertEqual(delta["lock_metadata_after"], {"version": 3})
        self.assertFalse(delta["dependency_graph_approved"])

    def test_local_junit_path_must_be_explicit(self):
        config = {
            "profile": {
                "default": {"junit": {"path": "junit.xml"}},
                "local": {"inherits": "default", "junit": {"path": "junit.xml"}},
            }
        }
        justfile = (self.root / "justfile").read_text()
        self.assertEqual(
            policy.junit_relative_path(config, justfile),
            "codex-rs/target/nextest/local/junit.xml",
        )
        for local in (
            {"inherits": "default"},
            {"inherits": "default", "junit": {}},
            {"inherits": "default", "junit": {"path": None}},
        ):
            with self.subTest(local=local):
                changed = copy.deepcopy(config)
                changed["profile"]["local"] = local
                with self.assertRaisesRegex(ValueError, "unsupported nextest"):
                    policy.junit_relative_path(changed, justfile)

    def test_unknown_store_profile_or_just_contract_fails_closed(self):
        config = {
            "profile": {
                "default": {"junit": {"path": "junit.xml"}},
                "local": {"inherits": "default", "junit": {"path": "junit.xml"}},
            }
        }
        justfile = (self.root / "justfile").read_text()
        for mutate in (
            lambda c: c.update(store={"dir": "different"}),
            lambda c: c["profile"]["local"].update(junit={"path": "other.xml"}),
            lambda c: c["profile"]["default"].update(
                overrides=[{"junit": {"store-failure-output": False}}]
            ),
        ):
            changed = copy.deepcopy(config)
            mutate(changed)
            with self.assertRaises(ValueError):
                policy.junit_relative_path(changed, justfile)
        with self.assertRaises(ValueError):
            policy.junit_relative_path(
                config, justfile.replace("NEXTEST_PROFILE=local", "NEXTEST_PROFILE=ci")
            )

    def test_receipt_exact_byte_boundary_and_overflow_fail_compaction(self):
        rec = self.receipt()
        rec["extra_metadata"] = "x" * 5000
        original = copy.deepcopy(rec)
        raw, overflow = policy.receipt_bytes(
            rec, "sample", "in_progress", "fixed-time", 8192
        )
        self.assertFalse(overflow)
        exact, overflow = policy.receipt_bytes(
            copy.deepcopy(original), "sample", "in_progress", "fixed-time", len(raw)
        )
        self.assertEqual(exact, raw)
        self.assertFalse(overflow)
        failed = copy.deepcopy(original)
        compact, overflow = policy.receipt_bytes(
            failed, "sample", "in_progress", "fixed-time", len(raw) - 1
        )
        self.assertTrue(overflow)
        self.assertLessEqual(len(compact), len(raw) - 1)
        self.assertFalse(failed["validation_passed"])
        self.assertEqual(failed["source_head"], original["source_head"])
        self.assertEqual(
            failed["receipt_overflow"]["sha256"], hashlib.sha256(raw).hexdigest()
        )

    def test_bounded_checkpoint_retains_raw_xml_and_readable_failed_receipt(self):
        rec = self.receipt()
        rec["validation_passed"] = True
        rec["extra_metadata"] = "x" * 5000
        raw_xml = xml([policy.REGRESSION_NAME], failed=(0,))
        (self.out / "payload/zip_mode.junit.xml").write_bytes(raw_xml)
        with patch.object(runner, "RECEIPT_CAP", 4096), self.assertRaises(ValueError):
            runner.checkpoint(self.out / "delivery", rec, "overflow")
        encoded = (self.out / "delivery/receipt.json").read_bytes()
        self.assertLessEqual(len(encoded), 4096)
        saved = json.loads(encoded)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["mode"], "baseline")
        self.assertFalse(saved["validation_passed"])
        self.assertFalse(saved["qualification"])
        self.assertEqual(
            (self.out / "payload/zip_mode.junit.xml").read_bytes(), raw_xml
        )
        self.assertFalse((self.out / "delivery/receipt.json.tmp").exists())

    def test_delivery_accounting_includes_manifest_receipt_temporary_and_archive(self):
        delivery = self.out / "delivery"
        values = {
            "receipt.json": 16,
            "receipt.json.tmp": 16,
            "MANIFEST.json": 32,
            "maintenance.tar.gz": 64,
        }
        for name, size in values.items():
            (delivery / name).write_bytes(b"x" * size)
        with (
            patch.object(runner, "RECEIPT_CAP", 16),
            patch.object(runner, "MANIFEST_CAP", 32),
            patch.object(runner, "ARCHIVE_CAP", 64),
            patch.object(runner, "DELIVERY_CAP", 128),
        ):
            self.assertEqual(runner.delivery_usage(delivery), values)
            with (
                patch.object(runner, "DELIVERY_CAP", 127),
                self.assertRaises(ValueError),
            ):
                runner.delivery_usage(delivery)
            (delivery / "MANIFEST.json").write_bytes(b"x" * 33)
            with self.assertRaises(ValueError):
                runner.delivery_usage(delivery)


if __name__ == "__main__":
    unittest.main(verbosity=2)
