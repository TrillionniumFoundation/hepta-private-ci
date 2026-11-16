"""Keep concrete writer admission and the original Objective join protected.

The API migration keeps the same owners and ordering. These mutations exercise
the current production source against the original strict manifest verifier.
They do not qualify native execution or any new publication authority.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "current_owner_api_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MODEL = AGENT + "circuit_learning_model_publication.rs"
RETAINED = AGENT + "circuit_retained_version_host.rs"
MODEL_HOST = AGENT + "circuit_model_version_host.rs"
RESIDENT = AGENT + "resident_learning_delivery.rs"
MODEL_WRITER = "GenerationArtifactOwnerV1::writer(&authorities.artifacts)?"
RETAINED_WRITER = (
    "GenerationArtifactOwnerV1::writer(\n"
    "                &inputs.authorities.artifacts,\n"
    "            )?"
)
ATTACH = (
    "state\n"
    "            .attach_circuit_learning_delivery(\n"
    "                vec![request.source_run_id.clone()],\n"
    "                crate::learning_iteration::CircuitLearningSourceV1::OriginalObjective,\n"
    "            )"
)
RECONCILE = (
    "host.reconcile_learning_outbox(store, Some(&request.source_run_id), state)\n"
    "            .await"
)
WRITER_CALLS = (
    (MODEL, MODEL_WRITER),
    (RETAINED, RETAINED_WRITER),
    (MODEL_HOST, RETAINED_WRITER),
)


class CurrentOwnerApiSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, relative, original, replacement):
        source = (ROOT / relative).read_text()
        self.assertEqual(source.count(original), 1, original)
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == relative
        ]
        self.assertEqual(len(rows), 1, relative)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            path.write_text(
                source.replace(original, replacement, 1)
                + "\n/* Original guard retained only as a comment:\n"
                + original
                + "\n*/\n"
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_all_publication_paths_require_the_same_original_writer(self):
        for path, call in WRITER_CALLS:
            for changed in (
                call.replace("::writer(", "::lock_initial("),
                call.replace(
                    "authorities.artifacts", "different_authorities.artifacts"
                ),
                call.replace("GenerationArtifactOwnerV1::", "OtherOwner::"),
            ):
                with self.subTest(path=path, replacement=changed):
                    self.rejects(path, call, changed)

    def test_writer_refusal_must_propagate_before_lock_or_clone(self):
        for path, call in WRITER_CALLS:
            with self.subTest(path=path):
                self.rejects(path, call, call.removesuffix("?") + ".unwrap()")

    def test_model_writer_admission_cannot_be_hidden_in_dead_code(self):
        block = (
            "let artifacts = "
            + MODEL_WRITER
            + '\n        .lock()\n        .map_err(|_| Error::Binding("original Artifact owner lock"))?;'
        )
        self.rejects(MODEL, block, "if false {\n" + block + "\n}")

    def test_version_hosts_cannot_clone_without_writer_admission(self):
        for path in (RETAINED, MODEL_HOST):
            with self.subTest(path=path):
                self.rejects(
                    path,
                    "Arc::clone(" + RETAINED_WRITER + ")",
                    "Arc::clone(&inputs.authorities.artifacts)",
                )

    def test_enrollment_keeps_same_source_and_original_objective_classification(self):
        for changed in (
            ATTACH.replace("state\n", "different_state\n", 1),
            ATTACH.replace("request.source_run_id", "other_request.source_run_id"),
            ATTACH.replace(
                "crate::learning_iteration::CircuitLearningSourceV1::OriginalObjective",
                "source_kind",
            ),
            "state\n            .attach_circuit_learning_sources(vec![request.source_run_id.clone()])",
        ):
            with self.subTest(replacement=changed):
                self.rejects(RESIDENT, ATTACH, changed)

    def test_outbox_reconcile_keeps_same_state_store_and_original_source(self):
        for changed in (
            RECONCILE.replace("host.", "different_host.", 1),
            RECONCILE.replace(", state)", ", different_state)"),
            RECONCILE.replace("(store,", "(different_store,"),
            RECONCILE.replace("request.source_run_id", "other_request.source_run_id"),
            RECONCILE.replace(", state)", ")"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(RESIDENT, RECONCILE, changed)

    def test_typed_attachment_keeps_exact_registered_callers(self):
        boundary = self.boundaries["q24_task_explicit_source_attach"]
        expected = (AGENT + "learning_iteration_delivery_runtime.rs", RESIDENT)
        self.assertEqual(boundary.product_callers, expected)
        self.assertEqual(boundary.receiver_type, "AgentdState")
        self.assertEqual(
            boundary.symbol, "AgentdState::attach_circuit_learning_delivery"
        )
        paths = (boundary.definition_path, *boundary.product_callers)
        sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        for caller in expected:
            with self.subTest(removed_caller=caller):
                changed = replace(
                    boundary,
                    product_callers=tuple(path for path in expected if path != caller),
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, changed, sources, ())
        injected = dict(sources)
        injected[AGENT + "unregistered_original_source.rs"] = (
            "fn bypass(state: &AgentdState) { "
            "state.attach_circuit_learning_delivery(vec![], source_kind); }"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, boundary, injected, ())

    def test_original_objective_attachment_precedes_outbox_reconcile(self):
        source = (ROOT / RESIDENT).read_text()
        attach = ATTACH + "\n            .map_err(|_| Error::WrongScope)?;"
        reconcile = RECONCILE + "\n            .map_err(|_| Error::CommitUncertain)?;"
        self.assertEqual(source.count(attach), 1)
        self.assertEqual(source.count(reconcile), 1)
        start = source.index(attach)
        end = source.index(reconcile, start) + len(reconcile)
        middle = source[start + len(attach) : end - len(reconcile)]
        self.rejects(
            RESIDENT,
            source[start:end],
            middle + reconcile + "\n        " + attach,
        )


if __name__ == "__main__":
    unittest.main()
