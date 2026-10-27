"""Reject fake phase passes and prove old-data copies remain independently sealed."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ndu_port_candidate_common as common
import ndu_port_matrix_fixture as fixture
import ndu_port_fixture_layout as layout


def junit(
    name,
    *,
    extra="",
    count=1,
    classname="codex-hepta-matrix-sdk::store_version_migration",
):
    return f'<testsuites tests="{count}" failures="0" errors="0"><testsuite tests="{count}"><testcase name="{name}" classname="{classname}">{extra}</testcase></testsuite></testsuites>'


class PhaseEvidenceTests(unittest.TestCase):
    def test_only_exact_one_nonflaky_executed_phase_is_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "junit.xml"
            name = "prepare_old_version_fixture"
            path.write_text(junit(name))
            self.assertEqual(
                fixture.parse_phase_junit(path, name),
                {"name": name, "executed": 1, "passed": 1, "failed": 0, "skipped": 0},
            )
            invalid = (
                junit("reopen_old_version_fixture"),
                junit(name, extra="<skipped/>"),
                junit(name, extra="<failure>assertion failed</failure>"),
                junit(name, extra="<flakyFailure>failed before retry</flakyFailure>"),
                junit(name, extra="<rerunError>failed retry</rerunError>"),
                junit(name, count=2),
                junit(name, classname="another-package::same-test-name"),
                '<testsuites tests="0" failures="0" errors="0"/>',
            )
            for content in invalid:
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises(ValueError):
                        fixture.parse_phase_junit(path, name)


class OldFixtureBindingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "new-source"
        self.root.mkdir()
        self.driver_source = "1" * 40
        patch_bytes = b"reviewed fixture-only patch"
        self.recipe = {
            "matrix_baseline": {
                "fixture_patch_sha256": __import__("hashlib")
                .sha256(patch_bytes)
                .hexdigest()
            }
        }
        recipe_path = self.root / common.RECIPE
        recipe_path.parent.mkdir(parents=True)
        recipe_path.write_text(json.dumps(self.recipe))
        self.artifact = self.base / "old-artifact"
        self.artifact.mkdir()
        old = self.artifact / "fixture"
        old.mkdir()
        (old / "expected.json").write_text('{"identity":"old retained identity"}')
        (old / "store.db").write_bytes(b"synthetic fixture unit-test bytes")
        (old / "store.db-wal").write_bytes(b"synthetic WAL bytes")
        (old / "store.db-shm").write_bytes(b"synthetic SHM bytes")
        (old / "session.json").write_text('{"identity":"synthetic saved session"}')
        (old / "session.json").chmod(0o600)
        (self.artifact / layout.MANIFEST).write_text(
            json.dumps(layout.snapshot_layout(old))
        )
        for name, data in {
            "fixture-only.patch": patch_bytes,
            "compiled-source.tar.gz": b"source archive binding unit-test bytes",
            "binary": b"compiled binary binding unit-test bytes",
            "producer-junit.xml": junit("prepare_old_version_fixture").encode(),
            "original-files/codex-rs/Cargo.lock": (
                "version = 4\n"
                + "".join(
                    f'[[package]]\nname = "{package}"\nversion = "0.18.0"\n'
                    for package in fixture.OLD_PACKAGES
                )
            ).encode(),
        }.items():
            path = self.artifact / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.record = {
            "schema": fixture.SCHEMA,
            "status": "old_fixture_generated",
            "source_commit": common.OLD_SOURCE,
            "driver_source_commit": self.driver_source,
            "toolchain": "1.95.0",
            "recipe_sha256": common.checksum(recipe_path),
            "baseline_versions": {name: "0.18.0" for name in fixture.OLD_PACKAGES},
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "compiled_source_tree": "2" * 40,
            "fixture_files": common.tree_files(old),
            "artifacts": common.describe(
                self.artifact,
                (
                    "fixture-only.patch",
                    layout.MANIFEST,
                    "compiled-source.tar.gz",
                    "binary",
                    "producer-junit.xml",
                    "original-files/codex-rs/Cargo.lock",
                ),
            ),
            "migration_phase": {
                "exit_code": 0,
                "binary_unchanged_after_execution": True,
                "binary_sha256": common.checksum(self.artifact / "binary"),
                "junit": {"file": "producer-junit.xml"},
            },
        }
        self.seal()

    def seal(self):
        (self.artifact / "RESULT.json").write_text(json.dumps(self.record))
        self.result_sha = common.checksum(self.artifact / "RESULT.json")

    def runner(self, name="result"):
        return common.Recorder(self.root, self.base / name, "matrix-test")

    def consume(self, runner):
        fixture.consume_old_fixture(
            runner, self.recipe, self.artifact, self.result_sha, self.driver_source
        )

    def test_consumer_uses_separate_exact_copy_including_wal_and_shm(self):
        runner = self.runner()

        def reopen(recording, name, copy):
            self.assertEqual(name, "reopen_old_version_fixture")
            self.assertNotEqual(copy, self.artifact / "fixture")
            self.assertEqual(common.tree_files(copy), self.record["fixture_files"])
            (copy / "store.db").write_bytes(b"migrated copy")
            (copy / "store.db-wal").unlink()

        with patch.object(fixture, "run_phase", side_effect=reopen) as phase:
            self.consume(runner)
        phase.assert_called_once()
        self.assertEqual(
            common.tree_files(self.artifact / "fixture"), self.record["fixture_files"]
        )
        self.assertTrue(
            runner.record["old_fixture_input"][
                "producer_fixture_unchanged_after_reopen"
            ]
        )
        self.assertNotEqual(
            runner.record["old_fixture_input"]["files_after_reopen"],
            self.record["fixture_files"],
        )

    def test_wrong_old_head_or_new_driver_head_rejected_before_phase(self):
        for index, field in enumerate(("source_commit", "driver_source_commit")):
            before = self.record[field]
            self.record[field] = "f" * 40
            self.seal()
            with (
                patch.object(fixture, "run_phase") as phase,
                self.assertRaises(ValueError),
            ):
                self.consume(self.runner(f"wrong-source-{index}"))
            phase.assert_not_called()
            self.record[field] = before

    def test_missing_or_modified_sidecar_rejected_before_phase(self):
        wal = self.artifact / "fixture/store.db-wal"
        before = wal.read_bytes()
        wal.write_bytes(b"tampered sidecar")
        with (
            patch.object(fixture, "run_phase") as phase,
            self.assertRaisesRegex(ValueError, "database"),
        ):
            self.consume(self.runner("tampered"))
        phase.assert_not_called()
        wal.write_bytes(before)
        wal.unlink()
        with (
            patch.object(fixture, "run_phase") as phase,
            self.assertRaisesRegex(ValueError, "database"),
        ):
            self.consume(self.runner("missing"))
        phase.assert_not_called()

    def test_failed_reopen_keeps_after_state_and_does_not_erase_original(self):
        runner = self.runner()

        def failing_reopen(recording, name, copy):
            (copy / "partial.db").write_bytes(b"partial failed migration")
            raise RuntimeError("actual regression failure")

        with (
            patch.object(fixture, "run_phase", side_effect=failing_reopen),
            self.assertRaisesRegex(RuntimeError, "regression"),
        ):
            self.consume(runner)
        self.assertIn(
            "partial.db", runner.record["old_fixture_input"]["files_after_reopen"]
        )
        self.assertEqual(
            common.tree_files(self.artifact / "fixture"), self.record["fixture_files"]
        )

    def test_consumer_restores_bound_session_mode_before_actual_phase_dispatch(self):
        original = self.artifact / "fixture"
        (original / "session.json").chmod(0o644)
        transported = layout.snapshot_layout(original)
        expected = json.loads((self.artifact / layout.MANIFEST).read_text())
        runner = self.runner()

        def reopen(recording, name, working):
            self.assertEqual(layout.snapshot_layout(working), expected)
            self.assertEqual(layout.snapshot_layout(original), transported)
            self.assertEqual(working.stat().st_ino == original.stat().st_ino, False)

        with patch.object(fixture, "run_phase", side_effect=reopen) as phase:
            self.consume(runner)
        phase.assert_called_once()
        self.assertEqual(
            runner.record["old_fixture_input"]["layout_before_reopen"], expected
        )
        self.assertEqual(layout.snapshot_layout(original), transported)

    def test_unbound_or_tampered_permission_manifest_is_rejected_before_phase(self):
        entry = self.record["artifacts"].pop(layout.MANIFEST)
        self.seal()
        with (
            patch.object(fixture, "run_phase") as phase,
            self.assertRaisesRegex(ValueError, "permission manifest"),
        ):
            self.consume(self.runner("unbound-layout"))
        phase.assert_not_called()
        self.record["artifacts"][layout.MANIFEST] = entry
        self.seal()
        manifest = self.artifact / layout.MANIFEST
        original = manifest.read_text()
        altered = json.loads(original)
        altered["files"]["session.json"]["mode"] = 0o644
        manifest.write_text(json.dumps(altered))
        with (
            patch.object(fixture, "run_phase") as phase,
            self.assertRaisesRegex(ValueError, "artifact bytes"),
        ):
            self.consume(self.runner("tampered-layout"))
        phase.assert_not_called()
        manifest.unlink()
        with (
            patch.object(fixture, "run_phase") as phase,
            self.assertRaisesRegex(ValueError, "regular file"),
        ):
            self.consume(self.runner("missing-layout"))
        phase.assert_not_called()

    def test_consumer_detects_permission_changes_to_preserved_original(self):
        runner = self.runner()

        def tamper_original(recording, name, working):
            (self.artifact / "fixture/session.json").chmod(0o644)

        with (
            patch.object(fixture, "run_phase", side_effect=tamper_original),
            self.assertRaisesRegex(ValueError, "preserved original"),
        ):
            self.consume(runner)
        self.assertFalse(
            runner.record["old_fixture_input"][
                "producer_fixture_unchanged_after_reopen"
            ]
        )


if __name__ == "__main__":
    unittest.main()
