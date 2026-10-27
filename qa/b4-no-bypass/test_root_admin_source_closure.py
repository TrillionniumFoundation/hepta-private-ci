"""Remove actual live checks from a protected source copy; grant no authority."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_admin_caller_verifier", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RootAdminSourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        for relative in {row["path"] for row in self.manifest["protected_file"]}:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        MODULE._verify_protected_files(self.root, self.manifest)

    def rejects(self, relative, original, replacement, *, occurrences=1):
        path = self.root / relative
        source = path.read_text()
        self.assertEqual(source.count(original), occurrences)
        path.write_text(source.replace(original, replacement, 1))
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE._verify_protected_files(self.root, self.manifest)

    def test_slow_check_cannot_drop_its_post_check_deadline(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/authority_host_admin_deadline.rs",
            "check()?;\n    require_before(end)?;",
            "check()?;",
        )

    def test_original_registry_cannot_drop_its_locked_deadline(self):
        self.rejects(
            "codex-rs/hepta-contracts/src/authority_lease_revoke.rs",
            "deadline.check()?;\n    if let Some(existing)",
            "if let Some(existing)",
        )

    def test_two_cas_stages_cannot_skip_the_original_context_recheck(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/authority_host_admin_effect.rs",
            "context.check_for(self)?;\n        let result = revoked.revoke_original_grant();",
            "let result = revoked.revoke_original_grant();",
        )

    def test_consumer_confirmation_must_observe_both_original_owners(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/authority_host_admin_effect.rs",
            "consumers.notes.frontier_for_handoff(head)",
            "consumers.device.frontier_for_handoff(head)",
        )

    def test_strict_own_signature_cannot_be_replaced_by_ordinary_verify(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/deployment_signed_grant.rs",
            ".verify_strict(&bytes, &signature)",
            ".verify(&bytes, &signature)",
        )

    def test_valid_signed_artifact_cannot_skip_existing_full_lease_binding(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/deployment_notes_revoke.rs",
            "current.binding != expected",
            "current.lease_id.is_empty()",
        )

    def test_admin_activation_cannot_precede_original_ready_callback(self):
        self.rejects(
            "codex-rs/hepta-agentd/src/authority_host_session.rs",
            "let ready = || {\n                ready()?;",
            "let ready = || {",
        )


if __name__ == "__main__":
    unittest.main()
