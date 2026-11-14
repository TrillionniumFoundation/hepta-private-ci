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
ACTION_DRIVER = "codex-rs/hepta-automation/src/action_skill_driver.rs"
ASYNC_EFFECT_OWNER = "codex-rs/hepta-automation/src/authorized_effect.rs"


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


    def test_action_skill_bridge_caller_set_stays_closed(self):
        boundary = self.boundaries["automation_taskflow_provider_effect_bridge"]
        code = PROOF._strip_cfg_test_items(
            PROOF._strip_rust_non_code((ROOT / ACTION_DRIVER).read_text())
        )
        sources = {ACTION_DRIVER: code}
        PROOF._verify_boundary(ROOT, boundary, sources, ())
        with self.subTest(mutation="remove_registration"):
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(
                    ROOT, replace(boundary, product_callers=()), sources, ()
                )
        sources["codex-rs/unregistered/src/lib.rs"] = (
            "fn extra() { ProviderEffectTaskFlowDriver::new(scope, adapter); }"
        )
        with self.subTest(mutation="add_unregistered_caller"):
            with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                PROOF._verify_boundary(ROOT, boundary, sources, ())

    def test_action_skill_constructor_keeps_contract_and_observer_binding(self):
        for original in (
            "contract.digest()?",
            "observer.observer_id() != contract.observer_id",
            "ProviderEffectTaskFlowDriver::new(contract.destination_id.clone(), adapter)",
        ):
            with self.subTest(guard=original):
                self.rejects(ACTION_DRIVER, original, "unchecked")

    def test_action_skill_invocation_keeps_original_wire_and_contract_binding(self):
        for original in (
            "wire_payload.len() > self.contract.budget.max_wire_bytes as usize",
            "provider_intent.validate().is_err()",
            "Sha256Digest::parse(effect_intent_digest.as_str()).is_err()",
            "Sha256Digest::for_bytes(wire_payload) != provider_intent.payload_sha256",
            "invocation.schema_version != ACTION_SKILL_SCHEMA_VERSION",
            "invocation.contract_digest != self.contract_digest",
            "invocation.destination_id != self.contract.destination_id",
        ):
            with self.subTest(guard=original):
                self.rejects(ACTION_DRIVER, original, "false")

    def test_action_skill_dispatch_keeps_precontact_checks(self):
        for original in (
            "request.intent.destination_id != self.contract.destination_id",
            "self.provider.adapter().capability()",
            "self.observer.check_initiation(&binding, &invocation.body)",
            "initiation.binding != binding",
            "initiation.observer_id != self.contract.observer_id",
            "initiation.condition != ActionConditionV1::Met",
            "Sha256Digest::parse(initiation.evidence_digest.as_str()).is_err()",
        ):
            with self.subTest(guard=original):
                self.rejects(ACTION_DRIVER, original, "false")

    def test_action_skill_guard_comment_cannot_replace_executed_code(self):
        guard = "initiation.binding != binding"
        self.rejects(ACTION_DRIVER, guard, "/* " + guard + " */ false")

    def test_action_skill_owner_keeps_original_step_and_final_use_binding(self):
        for original in (
            "provider_effect_intent(intent, wire_payload)?",
            "current.state != TaskFlowStepState::Claimed",
            "expected_binding.scope_sha256 != digest_bytes(&intent.final_use_scope_digest)?",
            "expected_binding.payload_sha256 != digest_bytes(payload_digest)?",
        ):
            with self.subTest(guard=original):
                self.rejects(ASYNC_EFFECT_OWNER, original, "unchecked", count=2 if original.startswith(("current.state", "expected_binding.")) else 1, occurrence=1 if original.startswith(("current.state", "expected_binding.")) else 0)

    def test_action_skill_dispatch_cannot_move_after_final_use_guard_returns(self):
        original = (
            "let provider = match authority\n"
            "            .with_verified_use_async(token, expected_binding, || driver.dispatch(request))\n"
            "            .await\n"
            "        {"
        )
        replacement = (
            "let admitted = authority\n"
            "            .with_verified_use_async(token, expected_binding, || async {})\n"
            "            .await;\n"
            "        let provider = match admitted {\n"
            "            Ok(()) => Ok(driver.dispatch(request).await),\n"
            "            Err(error) => Err(error),\n"
            "        };\n"
            "        let provider = match provider {"
        )
        self.rejects(ASYNC_EFFECT_OWNER, original, replacement)



if __name__ == "__main__":
    unittest.main()
