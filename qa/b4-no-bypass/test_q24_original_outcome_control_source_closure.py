"""Source guards for the original Q24 Observer control bridge.

These lexical mutation checks are not native receipts, an independently operated
Observer, a frozen Dataset, B evaluation, CURRENT adoption or a cold restart.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "q24_original_outcome_control_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
WIRE = "codex-rs/hepta-agent-protocol/src/q24_outcome.rs"
ADAPTER = AGENT + "cell_q24_task_outcome_control.rs"
CONFIG = AGENT + "config_q24_outcome.rs"
STATE = AGENT + "state_q24_outcome.rs"
CLIENT = AGENT + "client_q24_outcome.rs"
INSTALL = AGENT + "circuit_q24_task_ledger_install.rs"
RUNTIME = AGENT + "runtime.rs"
DISPATCH = AGENT + "state_control.rs"
OUTCOME = AGENT + "cell_q24_task_ledger_outcome.rs"
CALLERS = {
    "q24_task_original_outcome_submit": (ADAPTER,),
    "q24_outcome_control_original_identity": (CONFIG, STATE),
    "q24_outcome_control_original_submit": (STATE,),
    "q24_outcome_control_config_install": (INSTALL,),
    "q24_outcome_control_config_take": (RUNTIME,),
    "q24_outcome_control_state_attach": (RUNTIME,),
    "q24_outcome_control_state_submit": (DISPATCH,),
    "q24_outcome_control_client": (),
}


def code(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


def require_wire_fields(source):
    expected = {
        "Q24OriginalTerminalOutcomeRequestV1": (
            ("outcome_preimage_hex", "String"),
            ("evidence", "Q24OriginalObserverEvidenceV1"),
        ),
        "Q24OriginalObserverEvidenceV1": tuple(
            (field, "u64" if field in ("authority_epoch", "issued_at", "expires_at") else "String")
            for field in (
                "evidence_id", "principal_id", "role", "trust_digest", "scope_digest",
                "objective_digest", "authority_epoch", "issued_at", "expires_at",
                "payload_digest", "signature_hex",
            )
        ),
        "Q24OriginalTerminalOutcomeReceiptV1": (
            ("decision_sequence", "u64"), ("decision_chain_digest", "String"),
            ("outcome_sequence", "u64"), ("outcome_chain_digest", "String"),
        ),
    }
    for name, fields in expected.items():
        found = re.findall(
            r"#\[serde\(deny_unknown_fields\)\]\s*pub struct " + name + r"\s*\{([^}]+)\}",
            code(source),
        )
        if len(found) != 1 or tuple(re.findall(r"pub\s+(\w+):\s*(\w+)\s*,", found[0])) != fields:
            raise PROOF.VerificationFailure("only the fixed strict data-only wire is allowed")


class OriginalQ24OutcomeControlSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def check_mutation(self, path, mutate):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        original = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)

            def verify(source):
                target.write_text(source)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                if path == WIRE:
                    require_wire_fields(source)

            verify(original)
            changed = mutate(original)
            self.assertNotEqual(original, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    def rejects_removal(self, path, function, markers):
        for marker in markers:
            with self.subTest(path=path, function=function, marker=marker):
                def remove(source):
                    start = source.index("fn " + function + "(")
                    end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
                    self.assertIsNotNone(end)
                    offset = source.index(marker, start, end + 1)
                    return source[:offset] + "/* " + marker + " */" + source[offset + len(marker):]
                self.check_mutation(path, remove)

    def test_original_identity_cannot_be_replaced(self):
        self.rejects_removal(ADAPTER, "require_original_control_identity",
                             ("if &self.identity != identity", "return Err(invalid("))
        self.rejects_removal(CONFIG, "with_original_q24_outcome_control",
                             ("producer.require_original_control_identity(self.identity())?;",))
        self.rejects_removal(STATE, "attach_original_q24_outcome_control",
                             ("producer.require_original_control_identity(&self.identity)?;",))

    def test_adapter_decodes_then_calls_only_the_original_producer(self):
        self.rejects_removal(ADAPTER, "submit_original_control_outcome", (
            "let (outcome, signed) = decode(request)?;",
            ".submit_original_terminal_outcome(outcome, &signed)",
            "OriginalCellQ24TaskLedgerStatusV1::Complete",
            "decision_sequence: decision.sequence.get()", "outcome_sequence: outcome.sequence.get()",
            "OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome",
        ))

    def test_wire_is_bounded_canonical_and_keeps_the_original_signature(self):
        self.rejects_removal(ADAPTER, "encode", (
            "outcome_signing_payload_v2(outcome)", "signature_hex: hex(&signed.signature)",
            "signed.role != LearningEvidenceRoleV1::Observer",
            "decode(&request)? != (outcome.clone(), signed.clone())",
        ))
        self.rejects_removal(ADAPTER, "decode", (
            "MAX_Q24_OUTCOME_PREIMAGE_BYTES", "outcome_codec::decode(&payload).map_err(invalid)?",
            "if evidence.role !=", "role: LearningEvidenceRoleV1::Observer",
            "signature: fixed(&evidence.signature_hex)?",
            "signed.payload_digest != Digest32::of_bytes(&payload)",
        ))
        self.rejects_removal(ADAPTER, "id", ("!(1..=128).contains(&value.len())",))
        self.rejects_removal(ADAPTER, "unhex", (
            "value.is_empty() || !value.len().is_multiple_of(2) || value.len() > maximum * 2",
            ".chunks_exact(2)", ".map(|pair| Ok(digit(pair[0])? * 16 + digit(pair[1])?))",
        ))

    def test_wire_has_no_authority_fields_or_unknown_field_fallback(self):
        self.check_mutation(WIRE, lambda source: source.replace(
            "#[serde(deny_unknown_fields)]", "", 1))
        for field in ("owner", "controller", "capability", "root_key"):
            with self.subTest(field=field):
                self.check_mutation(WIRE, lambda source: source.replace(
                    "pub struct Q24OriginalTerminalOutcomeRequestV1 {",
                    "pub struct Q24OriginalTerminalOutcomeRequestV1 {\n    pub " + field + ": String,",
                    1,
                ))

    def test_installation_requires_the_actual_circuit_and_unique_owner(self):
        self.rejects_removal(CONFIG, "with_original_q24_outcome_control", (
            "self.original_q24_outcome_control.is_some()", "self.circuit_task_bootstrap.is_none()",
            "self.circuit_task_invocation.is_none()", "self.original_q24_outcome_control = Some(producer);",
        ))
        self.rejects_removal(CONFIG, "take_original_q24_outcome_control",
                             ("self.original_q24_outcome_control.take()",))
        self.rejects_removal(INSTALL, "install_original_task_ledger", (
            "OriginalCellQ24TaskLedgerProducerV1::open_original(",
            "producer: Arc::clone(&producer)",
            "config.with_circuit_task_bootstrap(self.bootstrap, invocation)?",
            "config.with_original_q24_outcome_control(Arc::clone(&producer))?",
            "ledger: producer",
        ))

    def test_runtime_moves_original_custody_after_real_circuit_attachment(self):
        self.rejects_removal(RUNTIME, "run_with_shutdown", (
            "config.take_original_q24_outcome_control()",
            ".circuit_task\n            .set(bootstrap.handle())",
            ".circuit_task_invocation\n            .set(invocation)",
            "AgentdState::attach_original_q24_outcome_control(&state, producer)?;",
        ))
        self.rejects_removal(STATE, "attach_original_q24_outcome_control", (
            "self.circuit_task.get().is_none() || self.circuit_task_invocation.get().is_none()",
            ".set(producer)",
        ))

    def test_state_requires_current_both_before_and_after_real_append(self):
        self.rejects_removal(STATE, "submit_original_q24_control_outcome", (
            "self.require_original_q24_outcome_current()?;\n        let producer:",
            "producer.require_original_control_identity(&self.identity)?;",
            "let receipt = producer.submit_original_control_outcome(request)?;",
            "self.require_original_q24_outcome_current()?;\n        Ok(receipt)",
        ))

    def test_late_current_check_cannot_move_before_submission(self):
        def move(source):
            source = source.replace(
                "self.require_original_q24_outcome_current()?;\n        Ok(receipt)",
                "Ok(receipt)", 1)
            return source.replace(
                "let receipt = producer.submit_original_control_outcome(request)?;",
                "self.require_original_q24_outcome_current()?;\n        "
                "let receipt = producer.submit_original_control_outcome(request)?;", 1)
        self.check_mutation(STATE, move)

    def test_current_readiness_and_generation_fence_are_all_required(self):
        self.rejects_removal(STATE, "require_original_q24_outcome_current", (
            "self.refresh_generation()?;", "self.runtime.lock().map_err(poisoned_state)?",
            "runtime.current_generation != self.identity.spawn_generation",
            "runtime.lifecycle != AgentLifecycle::Running", "!runtime.app_server_ready",
            "!runtime.critical_stores_ready", "!runtime.revocation_ready",
            "!runtime.required_ports_ready", "!runtime.admission_open",
            "runtime.drain_requested", "runtime.fenced",
        ))

    def test_original_outcome_journal_trust_and_source_checks_remain(self):
        self.rejects_removal(OUTCOME, "submit_original_terminal_outcome", (
            "self.capture(&mut state)?", "self.require_ledger(ledger)?",
            "self.require_outcome(&outcome, &captured)?",
            "ledger.validate_observed_outcome(&outcome, signed, now()?)?",
            "state.journal.commit_once(&self.outcome_key",
            "original_payload != payload || &original_signed != signed",
            "self.resume_original_outcome(&mut state, ledger, &captured)?",
        ))

    def test_client_preserves_evidence_and_response_type(self):
        self.rejects_removal(CLIENT, "submit_original_q24_terminal_outcome", (
            "crate::cell_q24_task_ledger::control::encode(outcome, signed)?;",
            "spawn_generation: self.spawn_generation",
            "AgentdPayload::Q24OriginalTerminalOutcome(receipt) => Ok(receipt)",
            "payload => unexpected(payload)",
        ))
        self.rejects_removal(DISPATCH, "response", (
            "spawn_generation != self.identity.spawn_generation",
            "self.submit_original_q24_control_outcome(&request)?",
        ))

    def test_control_adapter_never_detaches_signs_or_activates_trust(self):
        for path in (ADAPTER, CONFIG, STATE, CLIENT):
            for marker in ("SigningKey", ".sign(", "ActivatedLearningTrustV1::activate",
                           "LearningTrustRootV1::new", "spawn_blocking", "tokio::spawn"):
                with self.subTest(path=path, marker=marker):
                    self.check_mutation(path, lambda source: source + "\n" + marker)


class OriginalQ24OutcomeControlCallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {path for identifier, expected in CALLERS.items()
                 for path in (cls.boundaries[identifier].definition_path, *expected)}
        paths.update((AGENT + "config.rs", AGENT + "state.rs"))
        cls.sources = {path: code((ROOT / path).read_text()) for path in paths}

    def test_exact_product_callers_and_inventory(self):
        for identifier, expected in CALLERS.items():
            with self.subTest(identifier=identifier):
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_every_real_caller_remains_required(self):
        for identifier, expected in CALLERS.items():
            for missing in expected:
                with self.subTest(identifier=identifier, missing=missing):
                    row = replace(self.boundaries[identifier],
                                  product_callers=tuple(path for path in expected if path != missing))
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, row, self.sources, ())

    def test_unregistered_calls_cannot_hide_outside_closed_sets(self):
        for identifier in CALLERS:
            row = self.boundaries[identifier]
            method = row.symbol.rsplit("::", 1)[-1]
            sources = dict(self.sources)
            sources[AGENT + "unregistered_observer.rs"] = (
                "fn unregistered(owner: &" + row.receiver_type + ") { owner." + method + "(input); }")
            with self.subTest(identifier=identifier):
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, sources, ())

    def test_comments_cannot_supply_a_missing_real_caller(self):
        for identifier, expected in CALLERS.items():
            for missing in expected:
                sources = dict(self.sources)
                sources[missing] = code("/* " + self.boundaries[identifier].symbol + "(input); */")
                with self.subTest(identifier=identifier, missing=missing):
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, self.boundaries[identifier], sources, ())


if __name__ == "__main__":
    unittest.main()
