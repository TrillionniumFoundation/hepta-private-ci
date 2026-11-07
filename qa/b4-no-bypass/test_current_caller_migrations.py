"""Mutate current production sources and keep the original caller guard strict."""

from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "current_caller_migration_verifier", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
MEMORY = "codex-rs/hepta-memory/src/"
CONTRACTS = "codex-rs/hepta-contracts/src/"
DISPATCH = "codex-rs/hepta-operations/src/durable_dispatch.rs"


class CurrentCallerMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, relative, original, replacement, *, occurrence=0, count=1):
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == relative
        ]
        self.assertTrue(rows, relative)
        source = (ROOT / relative).read_text()
        self.assertEqual(source.count(original), count, original)
        start = -1
        for _ in range(occurrence + 1):
            start = source.index(original, start + 1)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(source)
            manifest = {"protected_file": rows}
            PROOF._verify_protected_files(root, manifest)
            path.write_text(
                source[:start] + replacement + source[start + len(original) :]
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, manifest)

    def test_dispatch_registration_cannot_be_removed(self):
        boundary = self.boundaries["final_use_dispatch_raw"]
        code = PROOF._strip_cfg_test_items(
            PROOF._strip_rust_non_code((ROOT / DISPATCH).read_text())
        )
        sources = {DISPATCH: code}
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_boundary(
                ROOT, replace(boundary, product_callers=()), sources, ()
            )

    def test_dispatch_unregistered_caller_is_rejected(self):
        boundary = self.boundaries["final_use_dispatch_raw"]
        code = PROOF._strip_cfg_test_items(
            PROOF._strip_rust_non_code((ROOT / DISPATCH).read_text())
        )
        sources = {DISPATCH: code}
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        sources["codex-rs/unregistered/src/lib.rs"] = code
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_boundary(ROOT, boundary, sources, ())

    def test_dispatch_effect_cannot_move_outside_authority_boundary(self):
        self.rejects(
            DISPATCH,
            "Ok((admitted_at, effect(&operation.intent)))\n        });",
            "Ok(admitted_at)\n        });\n"
            "        let entry = entry.map(|entry| entry.and_then(|admitted_at| {\n"
            "            Ok((admitted_at, effect(&operation.intent)))\n        }));",
        )

    def test_dispatch_cannot_drop_owner_or_current_lease(self):
        for original in (
            "Arc::ptr_eq(&self.dispatch_owner, &authorized.dispatch_owner)",
            "require_current_lease(&mut tx, &claim, now_millis()?).await?",
            "validate_claim_snapshot(&status, &claim, admitted_at)?",
        ):
            with self.subTest(guard=original):
                self.rejects(DISPATCH, original, "true")

    def test_runtime_wrapper_cannot_stop_delegating(self):
        call = "run_with_shutdown(config, arg0_paths, shutdown_signal()).await"
        for replacement in (
            "Ok(())",
            "if false { " + call + " } else { Ok(()) }",
            "async fn unused() { " + call + "; }\n    Ok(())",
        ):
            with self.subTest(replacement=replacement):
                self.rejects(AGENT + "runtime.rs", call, replacement)

    def test_write_transaction_cannot_weaken_sqlite_lock(self):
        self.rejects(
            MEMORY + "cognitive_store_barrier.rs",
            'let transaction = self\n            .pool\n            .begin_with("BEGIN IMMEDIATE")',
            'let transaction = self\n            .pool\n            .begin_with("BEGIN DEFERRED")',
        )

    def test_write_transaction_requires_both_open_checks(self):
        for occurrence in range(2):
            with self.subTest(occurrence=occurrence):
                self.rejects(
                    MEMORY + "cognitive_store_barrier.rs",
                    "self.commit_gate.require_open()?;",
                    "",
                    occurrence=occurrence,
                    count=2,
                )

    def test_write_transaction_requires_publication_and_managed_refusal(self):
        for original in (
            "publication.begin_writes().await.map_err(unavailable)?;",
            "else if self.commit_gate.is_managed()",
        ):
            with self.subTest(guard=original):
                self.rejects(MEMORY + "cognitive_store_barrier.rs", original, "")

    def test_moved_issuer_helper_keeps_full_writer_and_effect_checks(self):
        for original in (
            "if actual_writer != writer || actual_effect != effect",
            ".with_pinned_issuer_joint_dispatch_boundary(",
            "(writer_token, &writer.binding)",
            "(effect_token, &effect.binding)",
        ):
            with self.subTest(guard=original):
                self.rejects(
                    AGENT + "deployment_issuer_dependencies.rs", original, "false"
                )

    def test_moved_issuer_helper_requires_live_parent_after_put(self):
        for name in ("deployment_notes.rs", "deployment_calculator.rs"):
            for original in (
                "issuer.with_live_issuer_writer_registration(&self.writer, canonical",
                "issuer.with_live_issuer_writer_effect(",
            ):
                with self.subTest(path=name, guard=original):
                    self.rejects(AGENT + name, original, "unchecked(")

    def test_registration_check_cannot_be_borrowed_from_effect_helper(self):
        self.rejects(
            AGENT + "deployment_issuer_dependencies.rs",
            "if actual_writer != writer {\n"
            "                        return Err(io::Error::new(\n"
            "                            io::ErrorKind::PermissionDenied,\n"
            '                            "registered writer lease changed",\n'
            "                        ));\n"
            "                    }",
            "",
            occurrence=1,
            count=2,
        )

    def test_effect_signature_expiry_keeps_parent_writer_and_effect_caps(self):
        for name, original in (
            ("deployment_notes.rs", ".min(actual_issuer.expires_at_unix_ms)"),
            ("deployment_notes.rs", ".min(effect.expires_at_unix_ms)"),
            (
                "deployment_calculator.rs",
                "parent\n                        .expires_at_unix_ms",
            ),
            ("deployment_calculator.rs", ".min(writer.expires_at_unix_ms)"),
            ("deployment_calculator.rs", ".min(effect.expires_at_unix_ms)"),
        ):
            with self.subTest(path=name, guard=original):
                self.rejects(AGENT + name, original, "u64::MAX")

    def test_pinned_joint_boundary_keeps_same_owner_distinct_and_live_records(self):
        for original in (
            "self.pair_token_owner(&first, expected_first)?;",
            "self.pair_token_owner(&second, expected_second)?;",
            "if first.lease.lease_id == second.lease.lease_id",
            "validate_live(\n            &first.lease,",
            "validate_live(\n            &second.lease,",
            "first.lease.revision,",
            "second.lease.revision,",
        ):
            with self.subTest(guard=original):
                self.rejects(
                    CONTRACTS + "authority_lease_issuer_boundary.rs", original, ""
                )

    def test_retirement_administration_keeps_explicit_parent_revoke_veto(self):
        self.rejects(
            CONTRACTS + "authority_lease_issuer_boundary.rs",
            "state.revocations.contains_key(pin.0)",
            "false",
        )

    def test_writer_rotation_cannot_use_unpinned_predecessor_boundary(self):
        self.rejects(
            AGENT + "deployment_writer_rotate.rs",
            ".with_retired_predecessor_for_pinned_issuer_boundary(",
            ".with_retired_predecessor_boundary(",
        )

    def test_writer_registration_keeps_post_io_parent_deadline(self):
        for occurrence in range(2):
            with self.subTest(occurrence=occurrence):
                self.rejects(
                    AGENT + "deployment_writer.rs",
                    "Self::validate_issuer_lease_time(issuer, state.head.authority_epoch, after)?;",
                    "",
                    occurrence=occurrence,
                    count=2,
                )

    def test_notes_policy_cas_keeps_post_io_parent_deadline(self):
        for occurrence in range(2):
            with self.subTest(occurrence=occurrence):
                self.rejects(
                    AGENT + "deployment_notes.rs",
                    "Self::validate_issuer_lease_time(issuer, state.head.authority_epoch, after)?;",
                    "",
                    occurrence=occurrence,
                    count=2,
                )

    def test_new_human_signature_cannot_ignore_parent_failure(self):
        self.rejects(
            AGENT + "deployment_text.rs",
            "Some(parent) => Some(parent.map_err(root::lease_error)?)",
            "Some(_) => None",
        )

    def test_human_checked_entry_cannot_drop_parent_binding(self):
        self.rejects(
            AGENT + "deployment_text_human.rs", "parent: Some(parent)", "parent: None"
        )

    def test_physical_boxing_keeps_retirement_and_current_cas(self):
        for original in (
            "predecessor.require_retired()?",
            "material.prepare(previous, &next)?",
            ".compare_and_set(STORE_OWNER, old, &next)",
        ):
            with self.subTest(guard=original):
                self.rejects(
                    AGENT + "authority_host_checkpoint_adoption.rs", original, ""
                )

    def test_notes_boxing_keeps_owner_and_callback_verification(self):
        self.rejects(
            AGENT + "notes_thread_recorded.rs",
            "!callback_matches(",
            "callback_matches(",
        )

    def test_launcher_keeps_seed_before_previous_recovery(self):
        self.rejects(
            AGENT + "production_launcher.rs",
            ".with_original_notes_thread_seed(*seed)?",
            "",
        )


if __name__ == "__main__":
    unittest.main()
