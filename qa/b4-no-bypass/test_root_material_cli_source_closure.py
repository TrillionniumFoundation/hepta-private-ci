"""Ordinary material recovery uses the existing original retirement ceremony."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "root_material_cli_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
CLI = AGENT + "bin/hepta-authority-host.rs"
SESSION = AGENT + "authority_host_session_material.rs"
RECOVERY = AGENT + "authority_host_material_recovery.rs"
ADOPTION = AGENT + "authority_host_checkpoint_material_recovery.rs"
CALLERS = {
    "root_material_fresh_registered_session": (
        AGENT + "native_g2_entry/activation.rs", CLI,
    ),
    "root_material_recover_registered_session": (
        AGENT + "native_g2_entry/recovery.rs", CLI,
    ),
    "root_same_registered_bootstrap_seal": (
        CLI, AGENT + "native_g2_entry/activation.rs", SESSION,
    ),
    "root_material_original_bootstrap": (CLI,),
    "root_registered_material_recovery": (SESSION,),
    "root_physical_recovery_retirement_admission": (RECOVERY,),
}


class RootMaterialCliSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, path, function, marker, occurrence=0):
        source = (ROOT / path).read_text()
        start = source.index(function) if function is not None else 0
        end = (
            PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
            if function is not None else len(source) - 1
        )
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start:end + 1]
        offset = -len(marker)
        for _ in range(occurrence + 1):
            offset = body.index(marker, offset + len(marker))
        offset += start
        rows = [r for r in self.manifest["protected_file"] if r["path"] == path]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(source[:offset] + source[offset + len(marker):])
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_actual_material_entry_and_original_owner_closed_callers(self):
        paths = {
            path
            for identifier in CALLERS
            for path in (
                self.boundaries[identifier].definition_path,
                *self.boundaries[identifier].product_callers,
            )
        }
        index = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
                (ROOT / path).read_text()
            )) for path in paths
        }
        for identifier, callers in CALLERS.items():
            with self.subTest(identifier=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, index, ())
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(
                        ROOT, replace(row, product_callers=()), index, ()
                    )

    def test_explicit_commands_preserve_original_session_and_ready_selection(self):
        for marker in (
            'command == "serve-fresh-session" || command == "serve-fresh-material-session"',
            'command == "serve-recovered-material-session"',
            'command == "serve-session" || fresh_session || recover_material_session',
            "if initial_peer_ready && !serving_session",
            "} else if serving_session {",
            "if fresh_session => Some((",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLI, None, marker)

    def test_recovery_requires_original_handoff_before_any_original_mutation(self):
        function = "} else if recover_material_session {"
        for marker in (
            "handoff.ok_or(", "let root = root_fd", ".ok_or(",
            "PreparedHostAuthoritySession::recover_with_physical_material(",
            "&config,", "&registration,", "owner,",
            "PreparedHostAuthoritySession::seal_original_material_bootstrap(",
            "send_root_production_handoff(", "UnixDatagram::from(handoff)",
            "&bootstrap,", "root,",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLI, function, marker)
        self.rejects(CLI, function, ".ok_or(", 1)

    def test_recovery_does_not_fall_back_to_fresh_state_or_select_an_image(self):
        source = PROOF._strip_rust_non_code((ROOT / CLI).read_text())
        start = source.index("} else if recover_material_session {") + 1
        end = PROOF._rust_item_end(source, start)
        self.assertIsNotNone(end)
        assert end is not None
        body = source[start:end + 1]
        for forbidden in (
            "prepare_fresh", "handoff_fresh_agent_filesystem", "create_dir",
            "create_new", "or_else", "rotate_host_writer_authorization",
            "image_path", "CognitiveCheckpointReceipt",
        ):
            self.assertNotIn(forbidden, body)
        self.assertIn("recover_with_physical_material(", body)
        self.assertIn("seal_original_material_bootstrap(", body)

    def test_material_bootstrap_rechecks_actual_cut_and_fixed_journal_parent(self):
        function = "fn seal_original_material_bootstrap("
        for marker in (
            "let end = Instant::now() + std::time::Duration::from_secs(30)",
            "self.registration.registered_identity.identity()?",
            '.join("final-use")', "self.seal_bootstrap(&consumer_root)?",
            "before.current() != after.current()",
            "before.material_sha256() != after.material_sha256()",
            "before.material_bytes() != after.material_bytes()",
            "verify_pinned_process(", "&self.owner_pidfd", "end,",
        ):
            with self.subTest(marker=marker):
                self.rejects(SESSION, function, marker)
        for occurrence in (0, 1):
            self.rejects(SESSION, function, "self.observe_physical_current()?", occurrence)

    def test_original_writer_and_retained_image_precede_install_adopt_release(self):
        function = "fn recover_material_from_registered("
        for marker in (
            "writer.registration.with_live(&writer.leases",
            "retained_writer_authorization(&writer.registration)?",
            "retain_original_writer_lock(&self.identity)?",
            "PreparedMaterialRecovery::observe(",
            "seize_registered_cognitive_root(&self.identity, config.peer_uid)?",
            ".install()", ".adopt()",
            ".release_to_registered_owner(config.peer_uid, config.peer_gid)",
        ):
            with self.subTest(marker=marker):
                self.rejects(RECOVERY, function, marker)
        for occurrence in (0, 1):
            self.rejects(RECOVERY, function, "verify_original_starting_record(&self.identity)?", occurrence)
            self.rejects(RECOVERY, function, "verify_pinned_process(", occurrence)

    def test_actual_retirement_and_original_expiry_are_not_replaced_by_cli_claims(self):
        for marker in (
            "self.predecessor.require_retired()?",
            "self.successor.require_alive()?",
            "let now = self.clock.now_unix_ms()?",
            "if now < old_expiry || now >= new_expiry",
            "return Err(AuthorityTrustError::Unavailable)",
        ):
            with self.subTest(marker=marker):
                self.rejects(ADOPTION, "fn require_retirement_window(", marker)


if __name__ == "__main__":
    unittest.main()
