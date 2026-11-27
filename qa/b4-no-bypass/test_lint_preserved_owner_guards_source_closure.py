"""Retain original owner checks across reviewed mechanical lint changes."""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "lint_preserved_owner_guards_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PREFIX = "codex-rs/hepta-agentd/src/"
LANE = PREFIX + "cell_q24_training_model_lane.rs"
TASK = PREFIX + "circuit_model_version_task.rs"
POLICY = PREFIX + "neuron_cell_evaluation_on_policy_policy.rs"
SOURCE_AFTER = (
    "if let (Some(source), Some(operation)) = (source.as_ref(), operation.as_mut())\n"
    "            && OriginalCellQ24TrainingSourceOperationV1::read_after_native(operation, source)\n"
    "                .is_err()\n"
    "        {\n"
    "            owners.source_fenced = true;\n"
    "            return Err(Error::CommitUncertain);\n"
    "        }"
)
CURRENT_AFTER = (
    "if source_bound\n"
    "            && owners\n"
    "                .require_retained_attestation_current(&current)\n"
    "                .is_err()\n"
    "        {\n"
    "            owners.source_fenced = true;\n"
    "            return Err(Error::CommitUncertain);\n"
    "        }"
)


class LintPreservedOwnerGuardsSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        cls.rows = [
            row
            for row in cls.manifest["protected_file"]
            if row["path"] in (LANE, TASK, POLICY)
        ]

    def rejects(self, path, old, new):
        source = (ROOT / path).read_text()
        self.assertEqual(source.count(old), 1, old)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {
                "protected_file": [row for row in self.rows if row["path"] == path]
            }
            PROOF._verify_protected_files(root, manifest)
            target.write_text(
                source.replace(old, new, 1)
                + "\n/* Original only in comment:\n"
                + old
                + "\n*/\n"
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_current_guard_records_validate(self):
        PROOF._verify_protected_files(ROOT, {"protected_file": self.rows})

    def test_privileged_operation_keeps_explicit_call_and_exact_typed_callers(self):
        boundary = next(
            row
            for row in PROOF._boundary_rows(self.manifest)
            if row.identifier == "learning_original_source_operation_begin"
        )
        self.assertEqual(boundary.receiver_type, "OriginalCellQ24TrainingSourceV1")
        self.assertEqual(
            boundary.product_callers,
            (PREFIX + "cell_q24_training_stage.rs", LANE),
        )
        paths = (boundary.definition_path, *boundary.product_callers)
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        explicit = ".map(|source| crate::OriginalCellQ24TrainingSourceV1::begin_source_operation(source))"
        indirect = (
            ".map(crate::OriginalCellQ24TrainingSourceV1::begin_source_operation)"
        )
        self.assertEqual(sources[LANE].count(indirect), 1)
        for call in (explicit, indirect):
            with self.subTest(call=call):
                # The current scanner follows both qualified call expressions
                # and qualified function items; neither can hide an owner edge.
                changed = dict(sources)
                changed[LANE] = changed[LANE].replace(indirect, call, 1)
                PROOF._verify_boundary(ROOT, boundary, changed, ())
                for replacement in (
                    ".map(|_| None)",
                    ".map(OtherSource::begin_source_operation)",
                ):
                    removed = dict(changed)
                    removed[LANE] = removed[LANE].replace(call, replacement, 1)
                    with self.assertRaisesRegex(
                        PROOF.VerificationFailure, "caller set mismatch; missing="
                    ):
                        PROOF._verify_boundary(ROOT, boundary, removed, ())
                unregistered = dict(changed)
                unregistered[PREFIX + "unregistered_training_source_operation.rs"] = (
                    changed[LANE]
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, boundary, unregistered, ())

    def test_after_native_check_keeps_same_source_operation_and_fail_closed_body(self):
        for changed in (
            SOURCE_AFTER.replace("(operation, source)", "(operation, other_source)"),
            SOURCE_AFTER.replace("(operation, source)", "(other_operation, source)"),
            SOURCE_AFTER.replace(".is_err()", ".is_ok()"),
            SOURCE_AFTER.replace("owners.source_fenced = true;", ""),
            SOURCE_AFTER.replace("return Err(Error::CommitUncertain);", ""),
            "if enabled {\n" + SOURCE_AFTER + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(LANE, SOURCE_AFTER, changed)

    def test_retained_current_check_keeps_original_condition_owner_and_refusal(self):
        for changed in (
            CURRENT_AFTER.replace("if source_bound", "if enabled"),
            CURRENT_AFTER.replace("&& owners", "|| owners"),
            CURRENT_AFTER.replace("&& owners", "&& different_owners"),
            CURRENT_AFTER.replace("(&current)", "(&original)"),
            CURRENT_AFTER.replace(".is_err()", ".is_ok()"),
            CURRENT_AFTER.replace("owners.source_fenced = true;", ""),
            CURRENT_AFTER.replace("return Err(Error::CommitUncertain);", ""),
            "if enabled {\n" + CURRENT_AFTER + "\n}",
        ):
            with self.subTest(replacement=changed):
                self.rejects(LANE, CURRENT_AFTER, changed)

    def test_owned_move_and_borrowed_recheck_keep_the_same_candidate(self):
        self.rejects(TASK, "bundle: candidate,", "bundle: other_candidate,")
        self.rejects(
            TASK,
            "task.require_bundle(candidate)?",
            "task.require_bundle(other_candidate)?",
        )
        self.rejects(
            TASK,
            "task.require_bundle(candidate)?;",
            "let _ = task.require_bundle(candidate);",
        )
        self.rejects(
            TASK,
            "task.require_bundle(candidate)?;",
            "if enabled { task.require_bundle(candidate)?; }",
        )

    def test_object_length_still_checks_the_original_record_and_exact_six_fields(self):
        marker = "record.as_object().map(serde_json::Map::len) != Some(6)"
        for changed in (
            marker.replace("record.as_object()", "other_record.as_object()"),
            marker.replace("Some(6)", "Some(5)"),
            marker.replace(" != ", " == "),
            "false",
        ):
            with self.subTest(replacement=changed):
                self.rejects(POLICY, marker, changed)


if __name__ == "__main__":
    unittest.main()
