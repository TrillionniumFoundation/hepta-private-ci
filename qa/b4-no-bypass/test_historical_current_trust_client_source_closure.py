"""Current trust must come from the actual same-session bounded Root exchange."""

import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT
CLIENT = AGENT + "root_historical_task_read_client.rs"
TRUST = AGENT + "root_historical_learning_trust_client.rs"
OPERATION = AGENT + "root_historical_learning_operation.rs"


class HistoricalCurrentTrustClientSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers

    def test_current_capsule_has_no_unimplemented_product_caller(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        self.assertEqual(rows["root_historical_current_trust_capsule"]["product_callers"], [AGENT + "production_post_a_q24.rs"])
        self.assertEqual(rows["root_historical_current_trust_read"]["product_callers"], [AGENT + "cell_q24_dataset_historical_ledger.rs"])
        self.assertEqual(rows["root_historical_current_trust_receipt"]["product_callers"], [AGENT + "cell_q24_dataset_historical_ledger.rs", AGENT + "cell_q24_dataset_operation.rs", AGENT + "production_post_a_continuation.rs", AGENT + "cell_q24_dataset_historical_preparation.rs"])
        self.assertEqual(rows["root_historical_fixed_client_exchange"]["product_callers"], [TRUST, AGENT + "root_post_a_learning_client.rs", AGENT + "root_completed_learning_history.rs"])
        self.assertEqual(rows["root_historical_recipient_trust_reply"]["product_callers"], [CLIENT])

    def test_capsule_uses_original_receipt_session_clock_cut_and_pin(self):
        for occurrence in (0, 1):
            self.reject_removal(TRUST, "fn activate_current_learning_trust(",
                                "OriginalHistoricalTaskReadReceiptV1::require_original_client(self, client, session)", occurrence)
        self.check_markers(TRUST, "fn activate_current_learning_trust(", (
            "let clock = session.clock()", "RootHistoricalTaskReadClientV1::exchange(",
            "HistoricalReadOperationV1::LearningTrust", "Reply::Task(_)", "Reply::PostAFrozenLearning(_)",
            "Reply::Acceptance(_)", "Reply::History(_) => return Err(refused())",
            "response.data_cut != self.data.data_cut.to_string()",
            "OriginalHistoricalTaskReadReceiptV1::with_current_read(self, |_|",
            "clock.now_unix_ms()", "activate_for_recipient(&self.client.initial, now)?",
            "response.payload.require_activation_pin(", "receipt: Arc::clone(self)", "self.client.fence()"))

    def test_each_trust_operation_reactivates_before_and_after_the_callback(self):
        self.check_markers(TRUST, "fn with_current_trust<T>(", (
            "OriginalHistoricalLearningTrustV1::with_original_operation(", "OriginalHistoricalOperationV1::read_for(operation, self, &self.receipt, action)"))
        for occurrence in (0, 1):
            self.reject_removal(OPERATION, "fn with_original_operation<T, E>(",
                                ('self.current_operation_activation().inspect_err(|_| {\n                    let _ = std::io::stderr()\n                        .write_all(b"daemon_stage=historical.operation.activation_before\\n");\n                })?', 'self.current_operation_activation().inspect_err(|_| {\n                    let _ = std::io::stderr()\n                        .write_all(b"daemon_stage=historical.operation.activation_after\\n");\n                })?')[occurrence], 0)
            self.reject_removal(OPERATION, "fn read_for<T>(",
                                ('self.trust.current_operation_activation().inspect_err(|_| {\n                    let _ = std::io::stderr()\n                        .write_all(b"daemon_stage=historical.read_for.activation_before\\n");\n                })?', 'self.trust.current_operation_activation().inspect_err(|_| {\n                let _ = std::io::stderr()\n                    .write_all(b"daemon_stage=historical.read_for.activation_after\\n");\n            })?')[occurrence], 0)
        self.check_markers(OPERATION, "fn current_operation_activation(", (
            'OriginalHistoricalLearningTrustV1::original_unix_seconds(self).inspect_err(|_| {\n                let _ = std::io::stderr().write_all(b"daemon_stage=historical.activation.clock\\n");\n            })?',
            'activate_for_recipient(self.initial_snapshot(), now)\n            .inspect_err(|_| {\n                let _ =\n                    std::io::stderr().write_all(b"daemon_stage=historical.activation.activate\\n");\n            })?',
            'self.require_same_activation(&activated, &evaluator)\n            .inspect_err(|_| {\n                let _ = std::io::stderr().write_all(b"daemon_stage=historical.activation.pin\\n");\n            })?'))
        self.check_markers(OPERATION, "fn read_for<T>(", (
            "!std::ptr::eq(self.trust, trust)", "!Arc::ptr_eq(&self.trust.receipt, receipt)",
            'let value =\n                action(self.data, activated.verifier(), &evaluator, now).inspect_err(|_| {\n                    let _ =\n                        std::io::stderr().write_all(b"daemon_stage=historical.read_for.action\\n");\n                });',
            "self.trust.receipt.client.fence()"))

    def test_borrow_cannot_escape_the_actual_root_operation(self):
        self.check_markers(OPERATION, "fn with_original_operation<T, E>(", (
            "action: impl for<'read> FnOnce(&OriginalHistoricalOperationV1<'read>)",
            "OriginalHistoricalTaskReadReceiptV1::with_current_read(&self.receipt",
            "trust: self", 'let value = action(&operation).inspect_err(|_| {\n                    let _ =\n                        std::io::stderr().write_all(b"daemon_stage=historical.operation.action\\n");\n                });',
            "!matches!(&result, Ok(Ok(_)))", "self.receipt.client.fence()"))

    def test_failed_callback_and_unwind_cannot_skip_the_root_postcheck(self):
        for occurrence in (0, 1):
            self.reject_removal(CLIENT, "fn with_current_read<T>(",
                                ('self.client.observe().inspect_err(|_| {\n                let _ = std::io::Write::write_all(\n                    &mut io::stderr(),\n                    b"daemon_stage=historical_client.observe_before_action\\n",\n                );\n            })? != self.data', 'self.client.observe().inspect_err(|_| {\n                let _ = std::io::Write::write_all(\n                    &mut io::stderr(),\n                    b"daemon_stage=historical_client.observe_after_action\\n",\n                );\n            })? != self.data')[occurrence], 0)
        self.check_markers(CLIENT, "fn with_current_read<T>(", (
            "let mut fence = FenceReadOnDrop", "client: &self.client", "armed: true",
            'let value = action(&self.data.ledger).inspect_err(|_| {\n                let _ = std::io::Write::write_all(\n                    &mut io::stderr(),\n                    b"daemon_stage=historical_client.action\\n",\n                );\n            });', "if result.is_err()",
            "self.client.fence()", "fence.armed = false"))
        self.check_markers(CLIENT, "fn drop(", ("if self.armed", "self.client.fence()"))

    def test_current_authority_cannot_switch_receipt_or_signer(self):
        self.check_markers(TRUST, "fn require_original_receipt(", (
            "!Arc::ptr_eq(&self.receipt, receipt)", "self.receipt.client.fence()", "return Err(refused())"))
        self.check_markers(TRUST, "fn require_same_activation(", (
            "self.payload.require_activation_pin(", "&self.receipt.client.learning_trust",
            "activated.root_digest() != self.activated.root_digest()",
            "activated.distribution_digest() != self.activated.distribution_digest()",
            "activated.verifier().trust_digest() != self.activated.verifier().trust_digest()",
            "evaluator != &self.evaluator"))

    def test_one_lane_and_sequence_carry_both_strict_operations(self):
        for occurrence in (0, 1):
            self.reject_removal(CLIENT, "fn exchange(",
                                "self.connection\n                .require_original_session()", occurrence)
        self.check_markers(CLIENT, "fn exchange(", (
            'self\n            .lane\n            .try_lock()', 'held.take().ok_or_else(refused).inspect_err(|_| {\n                let _ = std::io::Write::write_all(\n                    &mut io::stderr(),\n                    b"daemon_stage=historical_client.lane_missing\\n",\n                );\n            })?', "let request_id = lane.sequence",
            "!(1..=MAX_READS).contains(&request_id)", "purpose: operation.purpose().into()",
            'lane\n                .stream\n                .exchange_with_response_bound(&request, operation.response_bound())\n                .inspect_err(|_| {\n                    let _ = std::io::Write::write_all(\n                        &mut io::stderr(),\n                        b"daemon_stage=historical_client.transport\\n",\n                    );\n                })?', 'require_complete_reply(&bytes, request_id, &self.profile).inspect_err(\n                        |_| {\n                            let _ = std::io::Write::write_all(\n                                &mut io::stderr(),\n                                b"daemon_stage=historical_client.decode_task\\n",\n                            );\n                        },\n                    )?',
            "require_original_trust_reply(", "&self.learning_trust", "&self.initial",
            'request_id\n                .checked_add(1)', "*held = Some(lane)", "if result.is_err()"))

    def test_original_absolute_end_and_sealed_pin_reach_the_same_client(self):
        self.check_markers(AGENT + "root_historical_task_read_inputs.rs", "fn connect_original(", (
            "connection.original_end().min(launch_end)", "bundle.profile.require_original_context(",
            "OriginalPublicationStream::from_stream_until(",
            "RootHistoricalTaskReadClientV1::from_original_stream(", "bundle.profile.learning_trust"))
        self.reject_removal(CLIENT, "fn from_original_stream(", "learning_trust.require_initial(&initial)?")


if __name__ == "__main__":
    unittest.main()
