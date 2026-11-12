"""Pin the original Evaluator host composition and readonly material export.

These checks mutate source strings in isolated temporary directories and call
the unchanged protected-file verifier. They neither construct opaque evidence
nor execute B, sign an Evaluation, or establish an ordinary learning loop.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_evaluator_readback_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
HOST = AGENT + "neuron_cell_evaluation_host_training_readback.rs"
EXPORT = AGENT + "neuron_cell_evaluation_model_material_export.rs"
HOST_FUNCTION = "fn into_host_from_original_training_readback("
EXPORT_FUNCTION = "fn original_model_material("


class OriginalEvaluatorReadbackSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.rows = {}
        for path in (HOST, EXPORT):
            rows = [row for row in manifest["protected_file"] if row["path"] == path]
            if len(rows) != 1:
                raise AssertionError((path, "one audited Evaluator source row required"))
            cls.rows[path] = rows
        PROOF._verify_protected_files(
            ROOT, {"protected_file": [cls.rows[path][0] for path in (HOST, EXPORT)]}
        )

    def assert_rejected(self, path, changed):
        self.assertNotEqual(changed, (ROOT / path).read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": self.rows[path]})

    def function(self, path, function):
        original = (ROOT / path).read_text()
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(original))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return original, start, end + 1

    def mutate(self, path, function, marker, replacement=""):
        original, start, end = self.function(path, function)
        body = original[start:end]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_rejected(path, original[:start] + changed + original[end:])

    def test_consuming_host_requires_actual_training_and_original_panel_history(self):
        for marker, replacement in (
            ("        self,\n", "        &self,\n"),
            ("training.receipt().observed_unix_seconds", "0"),
            ("panel.fenced || receipt.training != *actual.snapshot()", "false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(HOST, HOST_FUNCTION, marker, replacement)

    def test_every_member_keeps_the_full_training_attestation_scope_and_original_trust(self):
        for marker, replacement in (
            (".chain(&panel.retention)", ""),
            ("original.training != *actual.snapshot()", "false"),
            ("original.training_evidence != *training.attestation()", "false"),
            ("original.scope != receipt.scope", "false"),
            ("original.verifier.trust_digest() != receipt.signing.verifier.trust_digest()", "false"),
            ("original.verifier.scope_digest() != receipt.signing.verifier.scope_digest()", "false"),
            ("original.verifier.objective_digest()\n                    != receipt.signing.verifier.objective_digest()", "false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(HOST, HOST_FUNCTION, marker, replacement)

    def test_same_bound_trainer_arc_replaces_only_each_members_readonly_transport(self):
        self.mutate(
            HOST, HOST_FUNCTION,
            "panel.primary.trainer = Arc::clone(&trainer);",
            "panel.primary.trainer = Arc::clone(&panel.primary.trainer);",
        )
        self.mutate(
            HOST, HOST_FUNCTION,
            "member.trainer = Arc::clone(&trainer);",
            "member.trainer = Arc::clone(&member.trainer);",
        )
        original = (ROOT / HOST).read_text()
        for marker in (
            "OriginalCellEvaluationReceiptOwnerV1::recover()",
            "panel.retention.clear()",
            "self.evaluator = other",
        ):
            with self.subTest(upgrade=marker):
                self.assert_rejected(HOST, original + "\nfn upgrade() { " + marker + "; }\n")

    def test_material_export_never_promotes_readback_to_execute(self):
        self.mutate(
            EXPORT, EXPORT_FUNCTION,
            "super::super::wire::Action::Readback",
            "super::super::wire::Action::Execute",
        )
        self.mutate(
            EXPORT, EXPORT_FUNCTION,
            "let after = self.read_panel().await?;",
            "let after = observed.clone();",
        )
        self.mutate(EXPORT, EXPORT_FUNCTION, "if after != observed", "if after == observed")
        self.mutate(EXPORT, EXPORT_FUNCTION, "self.fenced = true;", "self.fenced = false;")

    def test_final_original_receipt_is_read_after_all_panel_io(self):
        original, start, end = self.function(EXPORT, EXPORT_FUNCTION)
        body = original[start:end]
        receipt_read = (
            "        OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(\n"
            "            &mut self.evaluator,\n"
            "            evaluation.receipt(),\n"
            "            evaluation.attestation(),\n"
            "        )?;"
        )
        self.assertEqual(body.count(receipt_read), 1)
        self.mutate(EXPORT, EXPORT_FUNCTION, receipt_read)
        anchor = "        let after = self.read_panel().await?;"
        self.assertEqual(body.count(anchor), 1)
        self.assertLess(body.index(anchor), body.index(receipt_read))
        reordered = body.replace(receipt_read, "", 1).replace(
            anchor, receipt_read + "\n" + anchor, 1
        )
        self.assert_rejected(EXPORT, original[:start] + reordered + original[end:])

    def test_export_authenticates_fresh_clock_panel_and_complete_material_after_io(self):
        for marker in (
            "require_clock(started_at, current)?;",
            "self.authenticate_panel(&after, current)?;",
            "super::verify::material(context, &evaluation, &bytes, current)?;",
        ):
            with self.subTest(marker=marker):
                self.mutate(EXPORT, EXPORT_FUNCTION, marker)
        original = (ROOT / EXPORT).read_text()
        marker = "self.authenticate_panel(&after, current)?;"
        changed = original.replace(marker, "", 1)
        self.assert_rejected(
            EXPORT, changed + "\nfn unrelated_authentication() { " + marker + " }\n"
        )

    def test_member_projection_matches_original_signed_cell_manifests_and_scopes(self):
        for marker, replacement in (
            ("!= arm.snapshot_digest", "== arm.snapshot_digest"),
            ("|| &snapshot.scope != scope", "|| &snapshot.scope == scope"),
            ("now: current,", "now: 0,"),
            ("qualification_namespace: config.qualification_namespace,", "qualification_namespace: config.execution_namespace,"),
            ("execution.attestation(),", "&config.product_evidence.evaluator_bundle,"),
        ):
            with self.subTest(marker=marker):
                self.mutate(EXPORT, "fn member(", marker, replacement)

    def test_export_has_no_new_claim_signing_key_or_reconnected_owner(self):
        original = (ROOT / EXPORT).read_text()
        for marker in (
            "SigningKey::generate()",
            "owner.attest_original_completion()",
            "owner.commit_once()",
            'std::os::unix::net::UnixStream::connect("replacement")',
        ):
            with self.subTest(marker=marker):
                self.assert_rejected(EXPORT, original + "\nfn unrelated_effect() { " + marker + "; }\n")


if __name__ == "__main__":
    unittest.main()

