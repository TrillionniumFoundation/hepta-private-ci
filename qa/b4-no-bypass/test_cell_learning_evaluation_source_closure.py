"""Keep Cell evaluation adaptation on original evidence and frozen profile paths."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cell_learning_evaluation_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
ARTIFACTS = "codex-rs/hepta-learning-artifacts/src/"
BRIDGE = AGENT + "neuron_cell_learning_evaluation.rs"
READBACK = AGENT + "learning_iteration_evaluation_evidence.rs"
MODEL_MATERIAL = AGENT + "cell_q24_model_projection.rs"
EVALUATION_OWNER = AGENT + "neuron_cell_evaluation_receipt_owner.rs"
GENERATION_READBACK = AGENT + "learning_iteration_generation_evidence.rs"
CODEC = AGENT + "learning_iteration_checkpoint_codec.rs"
PREPARE = "fn prepare_cell_learning_evaluation_v1"
READ = "fn read_cell_learning_evaluation_v1"
CALLERS = {
    "cell_learning_evaluation_profile_freeze": (),
    "cell_learning_evaluation_receipt_prepare": (READBACK, MODEL_MATERIAL, EVALUATION_OWNER, AGENT + "authority_host_q24_evaluation_execute.rs"),
    "cell_learning_evaluation_original_readback": (),
    "learning_evidence_original_owner_readback": (
        READBACK, GENERATION_READBACK,
        AGENT + "neuron_cell_evaluation_training_source.rs",
    ),
    "root_learning_original_stage_assembly": (),
}


class CellLearningEvaluationSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {
            path
            for identifier in CALLERS
            for path in (
                cls.boundaries[identifier].definition_path,
                *cls.boundaries[identifier].product_callers,
            )
        }
        cls.sources = {
            path: PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code((ROOT / path).read_text())
            )
            for path in paths
        }

    def rejects_source(self, path, changed):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        self.assertNotEqual(source, changed)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def rejects(self, path, item, marker, *, replacement=""):
        source = (ROOT / path).read_text()
        start = source.index(item) if item else 0
        end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start) if item else len(source)
        self.assertIsNotNone(end)
        assert end is not None
        offset = source[start : end + 1].find(marker)
        self.assertGreaterEqual(offset, 0, marker)
        offset += start
        self.rejects_source(path, source[:offset] + replacement + source[offset + len(marker) :])

    def test_product_callers_are_exact_without_granting_stage_authority(self):
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                self.assertIn(identifier, inventory)
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                sources = dict(self.sources)
                if row.receiver_type:
                    method = row.symbol.rsplit("::", 1)[1]
                    call = f"fn unregistered(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                else:
                    call = f"fn unregistered() {{ {row.symbol}(); }}"
                sources[AGENT + "unregistered_cell_learning_evaluation.rs"] = call
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_learning_profile_freeze_keeps_nonzero_and_signed_binding(self):
        row = self.boundaries["cell_learning_evaluation_profile_freeze"]
        source = (ROOT / row.definition_path).read_text()
        for marker in ("evaluation_profile.is_zero()", "Some(evaluation_profile.into_array())"):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                target = root / row.definition_path
                target.parent.mkdir(parents=True)
                target.write_text(source)
                PROOF._verify_boundary(root, row, self.sources, ())
                self.assertEqual(source.count(marker), 1)
                target.write_text(source.replace(marker, "", 1))
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(root, row, self.sources, ())

    def test_profile_is_required_before_training_and_in_checkpoint_identity(self):
        for path, item, marker in (
            (ARTIFACTS + "learning_iteration_types.rs", "struct LearningIterationRequestV1", "pub evaluation_profile: Digest32"),
            (ARTIFACTS + "learning_iteration_digest.rs", "fn initial_digest(", "hepta.learning.iteration-checkpoint.v2"),
            (ARTIFACTS + "learning_iteration_digest.rs", "fn initial_digest(", "request.evaluation_profile"),
            (ARTIFACTS + "learning_iteration.rs", "fn new(", "request.evaluation_profile.is_zero()"),
            (ARTIFACTS + "learning_iteration.rs", "fn validate_observation(", "lineage.evaluation_profile == request.evaluation_profile"),
            (ARTIFACTS + "learning_iteration.rs", "fn validate_observation(", "*evaluation_profile == request.evaluation_profile"),
        ):
            with self.subTest(path=path, marker=marker):
                self.rejects(path, item, marker)

    def test_checkpoint_codec_preserves_request_profile_without_legacy_inference(self):
        for item, marker in (
            (None, 'const MAGIC: &[u8; 8] = b"HEPLCP02"'),
            (None, 'const TRAINER_NO_UPDATE_MAGIC: &[u8; 8] = b"HEPLCP03"'),
            (None, 'const LOCAL_DECISION_MAGIC: &[u8; 8] = b"HEPLCP04"'),
            ("fn encode(", "w.put(if snapshot.local_decision_v2().is_some()"),
            ("fn encode(", "else if snapshot.training_no_update_v2().is_some()"),
            ("fn encode(", "TRAINER_NO_UPDATE_MAGIC"),
            ("fn encode(", "w.digest(request.evaluation_profile)?"),
            ("fn decode(", "let magic = r.take::<8>()?"),
            ("fn decode(", "let trainer_no_update = &magic == TRAINER_NO_UPDATE_MAGIC"),
            ("fn decode(", "if &magic != MAGIC && !trainer_no_update"),
            ("fn decode(", "evaluation_profile: r.digest()?"),
            ("fn decode(", "8 if trainer_no_update =>"),
            ("fn decode(", "snapshot.training_no_update_v2().is_some() != trainer_no_update"),
        ):
            with self.subTest(marker=marker):
                self.rejects(CODEC, item, marker)

    def test_bridge_binds_full_bundles_original_training_and_profile(self):
        for marker in (
            "LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?",
            "coordinator.next_stage()",
            "comparison != receipt.plan().record()",
            "Some(snapshot.request.evaluation_profile.into_array())",
            "manifest.bundle_digest != candidate_digest.into_array()",
            "manifest.bundle_digest != baseline_digest.into_array()",
            "learning_iteration_receipt_signing_bytes_v1(training)?",
            "training_receipt_digest != training_digest.into_array()",
            "product.generator.principal_id != snapshot.owners.trainer",
            "product.evaluator.principal_id != snapshot.owners.evaluator",
        ):
            with self.subTest(marker=marker):
                self.rejects(BRIDGE, PREPARE, marker)

    def test_bridge_revalidates_signed_result_before_mapping_or_recording(self):
        for marker in (
            "runner.qualification_bundle(receipt, request.context)?",
            "revalidate_product_qualification_v1(",
            "observed_unix_seconds: request.evidence.evaluator_bundle.issued_at",
            "coordinator.record(prepared.clone(), prepared.observed_unix_seconds)?",
        ):
            with self.subTest(marker=marker):
                self.rejects(BRIDGE, PREPARE, marker)
        source = (ROOT / BRIDGE).read_text()
        self.rejects_source(
            BRIDGE,
            source.replace("let disposition = match", "let result = match", 1).replace(
                "let decision = revalidate_product_qualification_v1(",
                "let disposition = match; let decision = revalidate_product_qualification_v1(", 1,
            ),
        )

    def test_original_readback_refreshes_clock_and_verifies_both_signed_roles(self):
        for item, marker in (
            (READ, "prepare(now_unix_seconds()?)?"),
            (READ, "trainer.readback(request.snapshot, training).await?"),
            (READ, "evaluator.readback(request.snapshot, &receipt).await?"),
            (READ, "let now = now_unix_seconds()?"),
            (READ, "prepare(now)? != receipt"),
            (READ, "LearningEvidenceRoleV1::Generator"),
            (READ, "LearningEvidenceRoleV1::Evaluator"),
            (READ, "learning_iteration_receipt_signing_bytes_v1(training)"),
            (READ, "learning_iteration_receipt_signing_bytes_v1(&receipt)"),
            (READ, "generator.principal() != &request.context.generator"),
            (READ, "observer.principal() != &request.context.evaluator"),
            (READ, "verify_signed_actor_separation(&generator, &observer, now)"),
            ("fn now_unix_seconds(", "SystemTime::now()"),
        ):
            with self.subTest(marker=marker):
                self.rejects(READBACK, item, marker)

    def test_fresh_clock_cannot_move_before_either_original_owner_wait(self):
        source = (ROOT / READBACK).read_text()
        clock = "let now = now_unix_seconds()?;"
        self.assertEqual(source.count(clock), 1)
        for before in ("let training_attestation =", "let attestation ="):
            with self.subTest(before=before):
                changed = source.replace(clock, "", 1).replace(before, clock + before, 1)
                self.rejects_source(READBACK, changed)


if __name__ == "__main__":
    unittest.main()
