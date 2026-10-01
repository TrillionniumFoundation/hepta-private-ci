"""Regression coverage for staged supervisor source authoring, without Rust effects."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from textwrap import dedent
import unittest
from unittest.mock import patch

from scripts import runtime_supervisor_six_phase_followup as followup
from scripts import runtime_supervisor_six_phase_materialize as materializer


class MaterializerTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        src = root / "codex-rs/hepta-supervisor/src"
        docs = root / "docs/modules/runtime.supervisor"
        src.mkdir(parents=True)
        docs.mkdir(parents=True)
        (src / "daemon_execution.rs").write_text(
            dedent("""
            pub(super) async fn handle(
                state: Arc<DaemonState<UnixProcessDriver>>,
                method: SupervisordMethod,
            ) -> SupervisordPayload {
                handle_with_request_id(state, 1, method).await
            }
        """).lstrip()
        )
        (src / "robrix_protocol.rs").write_text(
            dedent("""
            SupervisordPayload::MutationAccepted { .. }
            | SupervisordPayload::ReleaseSelection { .. }
            | SupervisordPayload::ProductionMutationStatus { .. } => {
        """).lstrip()
        )
        # These are pre-materialization client markers. patch_client itself
        # generates the previously failing dedented follow-up method.
        (src / "daemon_client.rs").write_text(
            "use crate::DurableReleaseTransaction;\n"
            "            next_request_id: AtomicU64::new(1),\n"
            "    pub async fn health(&self) -> Result<SupervisordHealth, SupervisorError> {\n"
            "    }\n"
            + dedent("""
                async fn mutation(
                    &self,
                    method: SupervisordMethod,
                ) -> Result<SupervisordMutationAccepted, SupervisorError> {
                    match self.send(method).await? {
                    }
                }
                async fn send(&self, method: SupervisordMethod) -> Result<SupervisordPayload, SupervisorError> {
                    let request_id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
                    let request = SupervisordRequest::new(request_id, method);
                }
                fn unexpected<T>(payload: SupervisordPayload) -> Result<T, SupervisorError> {
                }
            """).lstrip()
        )
        states = {
            "source": "not_implemented",
            "test_source": "absent",
            "exact_head": "not_applicable",
            "merge_candidate": "not_applicable",
            "target_host": "not_applicable",
            "independent_acceptance": "not_obtained",
            "activated": False,
        }
        matrix = {
            "current": {**states, "release": False, "claim": "partial candidate"},
            "capabilities": [
                {**states, "id": identifier, "summary": identifier}
                for identifier in (
                    "cross_daemon_exit_cleanup_witness",
                    "predecessor_replacement_lineage",
                    "atomic_recovery_observation_envelope",
                )
            ],
        }
        (docs / "CAPABILITY_STATUS.json").write_text(json.dumps(matrix))
        return src, docs

    def snapshot(self, root: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }

    def stage(self, root: Path) -> None:
        materializer.patch_client()
        materializer.patch_status_and_docs()
        followup.apply(root, materializer.read, materializer.write)

    def test_generated_client_and_docs_followup_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, docs = self.fixture(root)
            with (
                patch.object(materializer, "SRC", src),
                patch.object(materializer, "DOCS", docs),
            ):
                materializer.transact(lambda: self.stage(root))
                first = self.snapshot(root)
                materializer.transact(lambda: self.stage(root))
                self.assertEqual(self.snapshot(root), first)
            self.assertIn("if request_id == 0", (src / "daemon_client.rs").read_text())
            self.assertIn(
                "After daemon replacement",
                (docs / "MUTATION_RETRY_PROTOCOL.md").read_text(),
            )
            matrix = json.loads((docs / "CAPABILITY_STATUS.json").read_text())
            by_id = {entry["id"]: entry for entry in matrix["capabilities"]}
            self.assertEqual(matrix["current"]["source"], "partial")
            self.assertEqual(
                by_id["predecessor_replacement_lineage"]["source"], "partial"
            )
            self.assertEqual(
                by_id["atomic_recovery_observation_envelope"]["source"], "partial"
            )
            self.assertIn("`partial`", (docs / "CURRENT_STATUS.md").read_text())

    def test_changed_late_marker_leaves_every_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, docs = self.fixture(root)
            path = src / "robrix_protocol.rs"
            path.write_text(
                path.read_text().replace("ProductionMutationStatus", "ChangedStatus")
            )
            before = self.snapshot(root)
            with (
                patch.object(materializer, "SRC", src),
                patch.object(materializer, "DOCS", docs),
            ):
                with self.assertRaisesRegex(SystemExit, "follow-up marker changed"):
                    materializer.transact(lambda: self.stage(root))
            self.assertEqual(self.snapshot(root), before)
            self.assertIsNone(materializer._PENDING)

    def test_standalone_followup_rolls_back_earlier_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, docs = self.fixture(root)
            before = self.snapshot(root)
            with patch.object(followup, "ROOT", root):
                with self.assertRaisesRegex(SystemExit, "follow-up marker changed"):
                    followup.main()
            self.assertEqual(self.snapshot(root), before)

    def test_concurrent_input_edit_is_preserved_and_rejects_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source"
            path.write_text("before")

            def stage():
                self.assertEqual(materializer.read(path), "before")
                path.write_text("concurrent author")
                materializer.write(path, "staged edit")

            with self.assertRaisesRegex(
                SystemExit, "source changed while materializing"
            ):
                materializer.transact(stage)
            self.assertEqual(path.read_text(), "concurrent author")

    def test_publication_failure_restores_previously_written_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two = root / "one", root / "two"
            one.write_text("before")
            original_replace = os.replace

            def fail_second(source, destination):
                if destination == two:
                    raise OSError("injected publication failure")
                return original_replace(source, destination)

            def stage():
                materializer.write(one, "after")
                materializer.write(two, "created")

            with patch.object(materializer.os, "replace", fail_second):
                with self.assertRaisesRegex(OSError, "publication failure"):
                    materializer.transact(stage)
            self.assertEqual(one.read_text(), "before")
            self.assertFalse(two.exists())

    def test_per_file_publication_check_preserves_a_late_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two = root / "one", root / "two"
            one.write_text("before-one")
            two.write_text("before-two")
            original_replace = os.replace

            def concurrent_second(source, destination):
                result = original_replace(source, destination)
                if destination == one and one.read_text() == "staged-one":
                    two.write_text("concurrent author")
                return result

            def stage():
                materializer.write(one, "staged-one")
                materializer.write(two, "staged-two")

            with patch.object(materializer.os, "replace", concurrent_second):
                with self.assertRaisesRegex(
                    SystemExit, "source changed while materializing"
                ):
                    materializer.transact(stage)
            self.assertEqual(one.read_text(), "before-one")
            self.assertEqual(two.read_text(), "concurrent author")
            self.assertEqual(
                sorted(path.name for path in root.iterdir()), ["one", "two"]
            )

    @unittest.skipUnless(os.name == "posix", "POSIX symlink substitution fixture")
    def test_equal_byte_symlink_substitution_never_writes_external_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, external = root / "source", root / "external"
            source.write_text("before")
            external.write_text("before")

            def stage():
                materializer.write(source, "after")
                source.unlink()
                source.symlink_to(external)

            with self.assertRaisesRegex(SystemExit, "single-link regular file"):
                materializer.transact(stage)
            self.assertTrue(source.is_symlink())
            self.assertEqual(external.read_text(), "before")

    def test_rollback_failure_preserves_original_error_and_restores_other_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two, three = (root / name for name in ("one", "two", "three"))
            for path in (one, two, three):
                path.write_text("before")
            original_replace = os.replace
            publication_error = OSError("injected publication failure")

            def fail_publication_and_one_restore(source, destination):
                if destination == three:
                    raise publication_error
                if destination == two and Path(source).read_text() == "before":
                    raise OSError("injected rollback failure")
                return original_replace(source, destination)

            def stage():
                for path in (one, two, three):
                    materializer.write(path, "after")

            with patch.object(
                materializer.os, "replace", fail_publication_and_one_restore
            ):
                with self.assertRaises(materializer.SourceRollbackError) as raised:
                    materializer.transact(stage)
            error = raised.exception
            self.assertIs(error.publication_error, publication_error)
            self.assertIs(error.__cause__, publication_error)
            self.assertEqual(set(error.rollback_failures), {two})
            self.assertIn(str(two), str(error))
            self.assertIn("injected publication failure", str(error))
            self.assertEqual(
                [path.read_text() for path in (one, two, three)],
                ["before", "after", "before"],
            )

    @unittest.skipUnless(os.name == "posix", "POSIX rollback substitution fixture")
    def test_rollback_preserves_externally_substituted_paths_and_reports_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            one, two, three, external = (
                root / name for name in ("one", "two", "three", "external")
            )
            for path in (one, two, three):
                path.write_text("before")
            external.write_text("after")
            original_replace = os.replace

            def substitute_one_on_failure(source, destination):
                if destination == three:
                    one.unlink()
                    one.symlink_to(external)
                    raise OSError("injected publication failure")
                return original_replace(source, destination)

            def stage():
                for path in (one, two, three):
                    materializer.write(path, "after")

            with patch.object(materializer.os, "replace", substitute_one_on_failure):
                with self.assertRaises(materializer.SourceRollbackError) as raised:
                    materializer.transact(stage)
            self.assertEqual(set(raised.exception.rollback_failures), {one})
            self.assertTrue(one.is_symlink())
            self.assertEqual(external.read_text(), "after")
            self.assertEqual(
                [path.read_text() for path in (two, three)], ["before", "before"]
            )


if __name__ == "__main__":
    unittest.main()
