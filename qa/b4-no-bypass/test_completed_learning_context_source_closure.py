"""A completed-only borrow stays in the original current Root operation."""

from pathlib import Path
import importlib.util
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "completed_learning_context_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
PATH = "codex-rs/hepta-agentd/src/authority_host_completed_learning.rs"


class CompletedLearningContextSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.source = (ROOT / PATH).read_text()
        cls.rules = {
            "protected_file": [
                row for row in cls.manifest["protected_file"] if row["path"] == PATH
            ]
        }

    def reject(self, before, after=""):
        self.assertIn(before, self.source)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / PATH
            target.parent.mkdir(parents=True)
            target.write_text(self.source)
            PROOF._verify_protected_files(root, self.rules)
            target.write_text(self.source.replace(before, after, 1))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, self.rules)

    def test_current_root_scope_and_complete_checkpoint_checks_remain(self):
        for marker in (
            "service.with_learning_profile(",
            "self.profile.require_original_context(",
            "expected != initial",
            "self.phase.load(Ordering::Acquire) != SERVING",
            "read_original_completed_scoped(",
            "RootHistoricalLearningTrustV1::read_original_payload(",
            "trust.activate_for_recipient(",
            "trust.require_activation_pin(",
            "RootHistoricalLearningTrustV1::revalidate(",
            "context.revalidate_recorded_signers()?",
        ):
            with self.subTest(marker=marker):
                self.reject(marker)

    def test_borrow_cannot_leave_original_thread_or_change_root_and_end(self):
        for before, after in (
            ("not_send: PhantomData<Rc<()>>", "not_send: PhantomData<()>"),
            ("!std::ptr::eq(self.service, service)", "false"),
            ("self.end != end", "false"),
            ("signed.trust_digest != self.verifier.trust_digest()", "false"),
            ("require_signer_binding(signed.role, &signer, self.current_unix_seconds()?)", "Ok(())"),
        ):
            with self.subTest(before=before):
                self.reject(before, after)

    def test_postchecks_cannot_move_before_action(self):
        self.reject("let value = action(&context);", "")
        self.reject(
            "let value = action(&context);",
            "let value = action(&context)?; return Ok(value);",
        )

    def test_privileged_context_has_no_raw_external_constructor(self):
        self.assertNotIn("pub(crate) fn new(", self.source)
        self.assertNotIn("pub fn new(", self.source)
        inventory = self.manifest["privileged_inventory"]["required_boundary_ids"]
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        for identifier in (
            "root_completed_learning_context",
            "root_completed_learning_same_service",
        ):
            self.assertIn(identifier, inventory)
            self.assertEqual(rows[identifier]["definition_path"], PATH)
        self.assertIn(
            PATH,
            rows["root_learning_completed_checkpoint_data"]["product_callers"],
        )


if __name__ == "__main__":
    unittest.main()
