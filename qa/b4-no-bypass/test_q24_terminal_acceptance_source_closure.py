"""The fresh ACK is an actual received result, separate from cold C history."""

from dataclasses import replace
import re
import tempfile
from pathlib import Path
import tomllib
import unittest

import test_q24_completed_history_control_source_closure as control


ROOT = control.ROOT
PROOF = control.PROOF
A = control.AGENT
CAP = A + "root_completed_learning_history.rs"
ACK = A + "root_completed_learning_acknowledgement.rs"
STATE = A + "state_q24_completed_history.rs"
CLIENT = A + "client_q24_completed_history.rs"
TERMINAL = A + "learning_iteration_terminal_acceptance.rs"
WAIT = A + "ordinary_q24_cold_acceptance_data_tests.rs"
DATA = "codex-rs/hepta-agent-protocol/src/q24_terminal_acceptance.rs"


def function(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one actual function is required")
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure("actual function body is required")
    return code[start:end + 1]


def require_install_is_last(source):
    code = function(source, "fn attach_original_q24_terminal_acceptance(")
    marker = "self.original_q24_terminal_acceptance"
    if code.count(marker) != 1:
        raise PROOF.VerificationFailure("one actual OnceLock publication is required")
    tail = re.sub(r"\s+", "", code[code.index(marker):])
    expected = (
        "self.original_q24_terminal_acceptance.set(acknowledged)"
        ".map_err(|_|{AgentdError::Invalid(.into())})}"
    )
    if tail != expected:
        raise PROOF.VerificationFailure("no fallible work may follow the published ACK")


def require_waits_for_received_ack(source):
    code = function(source, "fn wait_for_original_terminal_acceptance(")
    received = "if let Some(acknowledged)"
    if code.count(received) != 1:
        raise PROOF.VerificationFailure("one actual received acknowledgement is required")
    start = code.index(received)
    body_start = code.index("{", start)
    end = PROOF._rust_item_end(code, body_start)
    success = "return Ok(digest);"
    if end is None or code.count(success) != 1 or not (
        body_start < code.index(success) < end
    ):
        raise PROOF.VerificationFailure("disk Ready alone cannot end the parent wait")
    if "client.original_q24_terminal_acceptance().await?" not in code[start:body_start]:
        raise PROOF.VerificationFailure("the acknowledgement must come from the actual query")


class OriginalTerminalAcceptanceSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    rejects = control.OriginalCompletedHistoryControlSourceTests.rejects

    def test_all_original_ack_and_received_parent_protections_are_live(self):
        paths = {CAP, ACK, STATE, CLIENT, DATA, WAIT, TERMINAL,
                 A + "state.rs", A + "state_control.rs",
                 "codex-rs/hepta-agent-protocol/src/lib.rs"}
        rows = [row for row in self.manifest["protected_file"] if row["path"] in paths]
        self.assertEqual(paths, {row["path"] for row in rows})
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})

    def test_private_construction_and_only_actual_product_callers(self):
        rows = {row.identifier: row for row in PROOF._boundary_rows(self.manifest)}
        expected = {
            "root_completed_acknowledgement_construct": (),
            "root_completed_acknowledgement_data": (TERMINAL, STATE),
            "root_completed_acknowledgement_current": (STATE,),
            "q24_terminal_acceptance_state_attach": (TERMINAL,),
            "q24_terminal_acceptance_state_read": (A + "state_control.rs",),
            "q24_terminal_acceptance_client": (),
        }
        paths = {CAP, ACK, STATE, CLIENT, TERMINAL, A + "state_control.rs"}
        index = {
            path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            for path in paths
        }
        for identifier, callers in expected.items():
            with self.subTest(identifier=identifier):
                row = rows[identifier]
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, index, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), index, ())
                expression = (
                    "OriginalCompletedLearningAcknowledgementV1 { client, identity, data }"
                    if identifier == "root_completed_acknowledgement_construct"
                    else row.symbol + "()"
                )
                injected = dict(index)
                injected[A + "unregistered_terminal_ack.rs"] = "fn bypass(){" + expression + ";}"
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, injected, ())

    def test_private_proof_requires_the_actual_once_response_and_original_postcheck(self):
        for marker in (
            "Result<OriginalCompletedLearningAcknowledgementV1, AgentdError>",
            "let mut fence = FenceReadOnDrop", "armed: true",
            "RootHistoricalTaskReadClientV1::accept_completed_once(&self.client, &self.identity)?",
            "root_profile: response.profile", "initial: response.initial",
            "frozen_scope: response.frozen_scope", "terminal_head: response.terminal_head",
            "acceptance: response.acceptance", "data_cut: response.data_cut",
            "data.validate_data().map_err(AgentdError::Protocol)?",
            "self.client.require_completed_identity(&self.identity)?",
            "let acknowledged = OriginalCompletedLearningAcknowledgementV1 {",
            "client: Arc::clone(&self.client)", "identity: self.identity.clone()",
            "fence.armed = false", "Ok(acknowledged)",
        ):
            with self.subTest(marker=marker):
                self.rejects(CAP, "fn accept(", marker)

    def test_ack_observation_checks_the_actual_identity_even_if_data_validation_fails(self):
        for marker in (
            "let mut fence = FenceReadOnDrop", "armed: true",
            "self.client.require_completed_identity(identity)?",
            "if identity != &self.identity", "return Err(AgentdError::Io(refused()))",
            "let result = self.data.validate_data()",
            "let after = self.client.require_completed_identity(identity);",
            "after?;", "result?;", "fence.armed = false;",
        ):
            with self.subTest(marker=marker):
                self.rejects(ACK, "fn require_original_current(", marker)

    def test_reading_the_ack_cannot_issue_again_or_use_a_cold_context(self):
        source = (ROOT / ACK).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == ACK]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / ACK
            target.parent.mkdir(parents=True)
            for forbidden in ("exchange()", "accept_completed_once()",
                              "OriginalCompletedLearningContextV1", "File::open()",
                              "impl Clone for OriginalCompletedLearningAcknowledgementV1 {}"):
                with self.subTest(forbidden=forbidden):
                    target.write_text(source + "\nfn bypass() { " + forbidden + "; }\n")
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_state_installs_only_the_proof_after_both_error_postchecks(self):
        for marker in (
            "acknowledged: OriginalCompletedLearningAcknowledgementV1",
            "self.require_original_completed_history_current()?;",
            "let result = OriginalCompletedLearningAcknowledgementV1::data(&acknowledged)",
            ".validate_data()", "let root_after =",
            "let generation_after = self.require_original_completed_history_current();",
            "root_after?;", "generation_after?;", "result?;", ".set(acknowledged)",
        ):
            with self.subTest(marker=marker):
                self.rejects(STATE, "fn attach_original_q24_terminal_acceptance(", marker)
        for occurrence in (0, 1):
            self.rejects(STATE, "fn attach_original_q24_terminal_acceptance(",
                         "OriginalCompletedLearningAcknowledgementV1::require_original_current(", occurrence)

    def test_state_publication_is_the_last_fallible_operation(self):
        source = (ROOT / STATE).read_text()
        require_install_is_last(source)
        changed = source.replace(
            'AgentdError::Invalid("original terminal acceptance already attached".into())\n            })',
            'AgentdError::Invalid("original terminal acceptance already attached".into())\n            })?;\n'
            '        self.require_original_completed_history_current()?;\n        Ok(())', 1,
        )
        self.assertNotEqual(source, changed)
        with self.assertRaises(PROOF.VerificationFailure):
            require_install_is_last(changed)

    def test_missing_ack_stays_none_and_present_data_is_wrapped_in_current_checks(self):
        for marker in (
            "let Some(acknowledged) = self.original_q24_terminal_acceptance.get() else {",
            "return Ok(None);", "let data = OriginalCompletedLearningAcknowledgementV1::data(acknowledged).clone();",
            "let result = data.validate_data()", "let root_after =",
            "let generation_after = self.require_original_completed_history_current();",
            "root_after?;", "generation_after?;", "result?;", "Ok(Some(data))",
        ):
            with self.subTest(marker=marker):
                self.rejects(STATE, "fn read_original_q24_terminal_acceptance(", marker)
        for occurrence in (0, 1):
            self.rejects(STATE, "fn read_original_q24_terminal_acceptance(",
                         "OriginalCompletedLearningAcknowledgementV1::require_original_current(", occurrence)

    def test_control_query_has_no_business_input_and_rejects_other_replies(self):
        for marker in (
            "spawn_generation: self.spawn_generation",
            "method: crate::AgentdMethod::OriginalQ24TerminalAcceptance {}",
            "AgentdPayload::OriginalQ24TerminalAcceptance { data }",
            "data.validate_data().map_err(AgentdError::Protocol)?", "payload => unexpected(payload)",
        ):
            with self.subTest(marker=marker):
                self.rejects(CLIENT, "fn original_q24_terminal_acceptance(", marker)

    def test_every_digest_is_mandatory_and_canonical(self):
        for marker in (
            "self.schema != 1", "&self.identity_digest", "&self.root_profile", "&self.initial",
            "&self.frozen_scope", "&self.terminal_head", "&self.acceptance", "&self.data_cut",
            "value.len() != 64", "byte.is_ascii_digit()", "(b'a'..=b'f').contains(&byte)",
            "value.bytes().all(|byte| byte == b'0')",
        ):
            with self.subTest(marker=marker):
                self.rejects(DATA, "fn validate_data(", marker)

    def test_fresh_parent_must_join_actual_ack_with_the_unchanged_first_fact(self):
        for marker in (
            "before == after && after.phase == Phase::Ready && after.attempt >= 2",
            "client.original_q24_terminal_acceptance().await?", "acknowledged.validate_data()",
            "crate::neuron_generation_process_identity_digest_v1(",
            "acknowledged.initial == initial.head_digest.to_string()",
            "acknowledged.frozen_scope.as_str()", "acknowledged.terminal_head",
            "acknowledged.acceptance == digest.to_string()", "acknowledged.data_cut.as_str()",
            "actual == accepted && final_attempt == after", "super::root::write_json(",
            "&acknowledged,", "return Ok(digest);",
        ):
            with self.subTest(marker=marker):
                self.rejects(WAIT, "fn wait_for_original_terminal_acceptance(", marker)

    def test_disk_ready_alone_cannot_end_the_parent_wait(self):
        source = (ROOT / WAIT).read_text()
        require_waits_for_received_ack(source)
        changed = source.replace(
            "if let Some(acknowledged) =", "return Ok(digest);\n                        if let Some(acknowledged) =", 1,
        )
        self.assertNotEqual(source, changed)
        with self.assertRaises(PROOF.VerificationFailure):
            require_waits_for_received_ack(changed)
        changed = source.replace("client.original_q24_terminal_acceptance().await?", "cached_data", 1)
        with self.assertRaises(PROOF.VerificationFailure):
            require_waits_for_received_ack(changed)


if __name__ == "__main__":
    unittest.main()
