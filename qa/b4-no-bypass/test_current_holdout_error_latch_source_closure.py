"""Keep uncertain original reads fenced across both private observation APIs.

These source mutations exercise the unchanged strict verifier. Native recovered
store and cursor behavior are qualified separately by the original Rust tests.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "current_holdout_error_latch_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PREFIX = "codex-rs/hepta-intelligence-eval/src/"
OWNER = PREFIX + "fenced_holdout.rs"
EXECUTION = PREFIX + "product_execution.rs"
RELEASE = PREFIX + "product_holdout_release.rs"
REPLAY = PREFIX + "fenced_holdout_file_replay.rs"
RAW_ID = "product_original_holdout_consumption_read"
EXECUTION_ID = "product_original_holdout_execution_read"
RAW_LATCH = (
    "if let Some(error) = self.read_error {\n"
    "            return Err(FencedHoldoutError::Store(error));\n"
    "        }"
)
CONSUME_LATCH = (
    "if self.read_error.is_some() {\n"
    "            self.poisoned = true;\n"
    "            return Err(FencedHoldoutError::Indeterminate);\n"
    "        }"
)
LATCH_ASSIGNMENT = "self.read_error = Some(FinalHoldoutCasStoreError::Indeterminate);"
STORE_UNCERTAIN = (
    "return Err(FencedHoldoutError::Store(\n"
    "                    FinalHoldoutCasStoreError::Indeterminate,\n"
    "                ));"
)
EXECUTION_MATCH = (
    "match self.read_consumption(plan) {\n"
    "            Err(FencedHoldoutError::Store(FinalHoldoutCasStoreError::Indeterminate)) => {\n"
    "                self.poisoned = true;\n"
    "                Err(FencedHoldoutError::Indeterminate)\n"
    "            }\n"
    "            observed => observed,\n"
    "        }"
)
POSITION = "let position = file.stream_position().map_err(io_error)?;"
RESTORE = "file.seek(SeekFrom::Start(position)).map_err(io_error)?;"
IMMEDIATE_READS = (
    "let observed = (|| {\n"
    "        let first = read_image(file)?;\n"
    "        if read_image(file)? != first {\n"
    "            return Err(LockedFileCasErrorV1::Indeterminate);\n"
    "        }\n"
    "        Ok(first)\n"
    "    })();"
)


class CurrentHoldoutErrorLatchSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }
        cls.rows = {
            row["path"]: row
            for row in cls.manifest["protected_file"]
            if row["path"] in (OWNER, EXECUTION, REPLAY)
        }

    def rejects(self, path, original, changed):
        source = (ROOT / path).read_text()
        self.assertEqual(source.count(original), 1, original)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": [self.rows[path]]}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(
                source.replace(original, changed, 1)
                + "\n/* Removed guard is only a comment:\n"
                + original
                + "\n*/\n"
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_current_source_and_required_boundary_inventory_pass(self):
        PROOF._verify_protected_files(
            ROOT, {"protected_file": list(self.rows.values())}
        )
        PROOF._verify_privileged_inventory(
            self.manifest, list(self.boundaries.values())
        )
        required = self.manifest["privileged_inventory"]["required_boundary_ids"]
        self.assertIn(RAW_ID, required)
        self.assertIn(EXECUTION_ID, required)

    def test_raw_observation_rejects_latched_error_before_store_io(self):
        for changed in (
            "",
            "if false {\n" + RAW_LATCH + "\n}",
            RAW_LATCH.replace("self.read_error", "other.read_error"),
            RAW_LATCH.replace("return Err", "let ignored = Err"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(OWNER, RAW_LATCH, changed)
        current = "let current = match self.store.load(self.binding)"
        source = (ROOT / OWNER).read_text()
        start = source.index(RAW_LATCH)
        end = source.index(current, start) + len(current)
        span = source[start:end]
        self.rejects(OWNER, span, current + "\n        " + RAW_LATCH)

    def test_indeterminate_read_latches_original_store_error_before_return(self):
        for changed in (
            "",
            "self.read_error = None;",
            "self.read_error = Some(FinalHoldoutCasStoreError::Rejected);",
            "self.poisoned = true;",
        ):
            with self.subTest(replacement=changed):
                self.rejects(OWNER, LATCH_ASSIGNMENT, changed)
        self.rejects(
            OWNER,
            STORE_UNCERTAIN,
            "return Err(FencedHoldoutError::Indeterminate);",
        )
        span = LATCH_ASSIGNMENT + "\n                " + STORE_UNCERTAIN
        self.rejects(
            OWNER, span, STORE_UNCERTAIN + "\n                " + LATCH_ASSIGNMENT
        )

    def test_latch_cannot_be_exported_or_reset_on_a_live_owner(self):
        field = "\n    read_error: Option<FinalHoldoutCasStoreError>,\n"
        for visibility in ("pub ", "pub(crate) "):
            with self.subTest(visibility=visibility):
                self.rejects(
                    OWNER,
                    field,
                    field.replace("read_error:", visibility + "read_error:"),
                )
        for reset in (
            "self.read_error = None;",
            "self.read_error.take();",
            "self.read_error.replace(FinalHoldoutCasStoreError::Rejected);",
        ):
            with self.subTest(reset=reset):
                self.rejects(OWNER, RAW_LATCH, reset + "\n        " + RAW_LATCH)

    def test_consumption_rejects_uncertainty_before_candidate_or_cas(self):
        for changed in (
            "",
            "if false {\n" + CONSUME_LATCH + "\n}",
            CONSUME_LATCH.replace("self.poisoned = true;", ""),
            CONSUME_LATCH.replace("return Err", "let ignored = Err"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(OWNER, CONSUME_LATCH, changed)
        candidate = "let mut candidate = self.journal.clone();"
        span = CONSUME_LATCH + "\n        " + candidate
        self.rejects(OWNER, span, candidate + "\n        " + CONSUME_LATCH)

    def test_poison_observation_includes_latched_read_uncertainty(self):
        expression = "\n        self.poisoned || self.read_error.is_some()\n"
        for changed in (
            "\n        self.poisoned\n",
            expression.replace(" || ", " && "),
            "\n        false\n",
        ):
            with self.subTest(replacement=changed):
                self.rejects(OWNER, expression, changed)

    def test_execution_wrapper_is_private_and_keeps_same_owner_plan_and_refusal(self):
        self.rejects(
            OWNER,
            "pub(crate) fn read_consumption_for_execution(",
            "pub fn read_consumption_for_execution(",
        )
        for changed in (
            EXECUTION_MATCH.replace(
                "self.read_consumption(plan)", "other.read_consumption(plan)"
            ),
            EXECUTION_MATCH.replace(
                "self.read_consumption(plan)", "self.read_consumption(other_plan)"
            ),
            EXECUTION_MATCH.replace("self.poisoned = true;", ""),
            EXECUTION_MATCH.replace(
                "Err(FencedHoldoutError::Indeterminate)", "Ok((self.binding, None))"
            ),
            EXECUTION_MATCH.replace(
                "observed => observed", "observed => Ok((self.binding, None))"
            ),
            "if false {\n" + EXECUTION_MATCH + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(OWNER, EXECUTION_MATCH, changed)

    def test_diagnostics_stay_internal_while_release_and_execution_use_fenced_reads(self):
        expected = {RAW_ID: (), EXECUTION_ID: (EXECUTION, RELEASE)}
        paths = (OWNER, RELEASE, EXECUTION, PREFIX + "product_runner.rs")
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        for identifier, callers in expected.items():
            boundary = self.boundaries[identifier]
            with self.subTest(boundary=identifier):
                self.assertEqual(boundary.product_callers, callers)
                self.assertEqual(boundary.receiver_type, "FencedFinalHoldoutOwnerV1")
                self.assertEqual(boundary.definition_path, OWNER)
                PROOF._verify_boundary(ROOT, boundary, sources, ())
                if callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(
                            ROOT, replace(boundary, product_callers=()), sources, ()
                        )
                injected = dict(sources)
                injected[PREFIX + "unregistered_holdout_read.rs"] = (
                    "fn bypass<S: FinalHoldoutCasStoreV1>(owner: &mut FencedFinalHoldoutOwnerV1<S>, "
                    "plan: &CrossFoldPlanReceiptV1) { "
                    + boundary.symbol
                    + "(owner, plan); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, boundary, injected, ())

    def test_all_three_execution_observations_use_the_fenced_execution_entry(self):
        source = (ROOT / EXECUTION).read_text()
        marker = ".read_consumption_for_execution(&request.plan.frozen_plan)"
        self.assertEqual(source.count(marker), 3)
        positions = []
        cursor = 0
        for _ in range(3):
            cursor = source.index(marker, cursor)
            positions.append(cursor)
            cursor += len(marker)
        for offset in positions:
            with self.subTest(offset=offset):
                # Include unique enclosing text so each original position is tested.
                span = source[max(0, offset - 90) : offset + len(marker) + 90]
                self.rejects(
                    EXECUTION,
                    span,
                    span.replace(
                        marker, ".read_consumption(&request.plan.frozen_plan)", 1
                    ),
                )

    def test_stable_image_keeps_two_real_reads_and_immediate_execution(self):
        for changed in (
            IMMEDIATE_READS.replace(
                "let first = read_image(file)?;", "let first = Vec::new();"
            ),
            IMMEDIATE_READS.replace("if read_image(file)? != first", "if false"),
            IMMEDIATE_READS.replace("})()", "})"),
            IMMEDIATE_READS.replace("read_image(file)?", "read_image(other_file)?", 1),
            "if false {\n" + IMMEDIATE_READS + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(REPLAY, IMMEDIATE_READS, changed)

    def test_same_cursor_is_saved_before_reads_and_restored_with_error_propagation(
        self,
    ):
        for changed in (
            "let position = 0;",
            POSITION.replace("file.stream_position()", "other.stream_position()"),
            POSITION.replace("?;", ".unwrap_or(0);"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(REPLAY, POSITION, changed)
        for changed in (
            "",
            RESTORE.replace("Start(position)", "Start(0)"),
            RESTORE.replace("file.seek", "other.seek"),
            RESTORE.replace("?;", ";"),
            "if observed.is_ok() { " + RESTORE + " }",
        ):
            with self.subTest(replacement=changed):
                self.rejects(REPLAY, RESTORE, changed)
        span = RESTORE + "\n    observed\n"
        self.rejects(REPLAY, span, "observed\n    " + RESTORE + "\n")


if __name__ == "__main__":
    unittest.main()
