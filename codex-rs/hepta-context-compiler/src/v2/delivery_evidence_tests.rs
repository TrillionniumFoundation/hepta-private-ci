use std::error::Error;

use codex_hepta_contracts::PROVIDER_EVIDENCE_SCHEMA_VERSION;
use codex_hepta_contracts::ProviderInvocationIntent;
use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::ProviderRequestBinding;
use codex_hepta_contracts::ProviderRequestKind;
use codex_hepta_contracts::ProviderTerminal;
use codex_hepta_contracts::ProviderTransport;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde_json::Value;
use serde_json::json;

use crate::ContextAdmissionBindingV2;
use crate::ContextAdmissionRecordV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextAttachmentV2;
use crate::ContextCandidateV2;
use crate::ContextCompilationRequestV2;
use crate::ContextCompilerV2Error;
use crate::ContextDeliveryDispositionV2;
use crate::ContextDeliveryPreparationV2;
use crate::ContextDeliveryReceiptV2;
use crate::ContextDeliveryRequestV2;
use crate::ContextModelProfileV2;
use crate::ContextProviderDeliveryDecisionV2;
use crate::ContextProviderDeliveryVerifierV2;
use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;
use crate::ExactTokenizerV2;
use crate::SerializedContextV2;
use crate::TokenizationReceiptV2;
use crate::VerifiedAdmissionSnapshotV2;
use crate::build_attachment;
use crate::compile_v2;
use crate::observe_delivery;
use crate::prepare_delivery_v2;
use crate::record_canonical_serialization_v2;
use crate::verify_admission_snapshot_successor_v2;
use crate::verify_admission_snapshot_v2;
use crate::verify_admission_v2;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct ByteTokenizer;

impl ExactTokenizerV2 for ByteTokenizer {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("evidence-tokenizer")
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        u64::try_from(bytes.len()).map_err(|_| ContextCompilerV2Error::Arithmetic)
    }
}

struct AdmissionVerifier {
    record: ContextAdmissionRecordV2,
    snapshots: Vec<ContextAdmissionSnapshotV2>,
}

impl ContextAdmissionVerifierV2 for AdmissionVerifier {
    fn verifier_digest(&self) -> Digest32 {
        digest("evidence-admission-verifier")
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record == &self.record
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        self.snapshots.contains(snapshot)
    }
}

struct DeliveryVerifier<'a> {
    provider: &'a ProviderInvocationReceipt,
    preparation: &'a ContextDeliveryPreparationV2,
    decision: &'a ContextProviderDeliveryDecisionV2,
}

impl ContextProviderDeliveryVerifierV2 for DeliveryVerifier<'_> {
    fn verifier_digest(&self) -> Digest32 {
        digest("evidence-delivery-verifier")
    }

    fn verify_delivery(
        &self,
        receipt: &ProviderInvocationReceipt,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ContextProviderDeliveryDecisionV2, String> {
        if receipt != self.provider || preparation != self.preparation {
            return Err("fixture provider evidence does not bind this preparation".to_string());
        }
        Ok(self.decision.clone())
    }
}

struct Fixture {
    receipt: ContextDeliveryReceiptV2,
    preparation: ContextDeliveryPreparationV2,
    attachment: ContextAttachmentV2,
    serialization: SerializedContextV2,
    profile: ContextModelProfileV2,
    snapshot: VerifiedAdmissionSnapshotV2,
    provider: ProviderInvocationReceipt,
    decision: ContextProviderDeliveryDecisionV2,
}

impl Fixture {
    fn new(content: &[u8], terminal: ProviderTerminal) -> TestResult<Self> {
        let tokenizer = ByteTokenizer;
        let tokenization =
            TokenizationReceiptV2::from_exact_bytes(id("item:evidence")?, content, &tokenizer)?;
        let record = ContextAdmissionRecordV2::new(
            id("admission:evidence")?,
            ContextAdmissionBindingV2 {
                item_id: id("item:evidence")?,
                role: ContextRoleV2::TrustedInstruction,
                content_digest: tokenization.content_digest(),
                source_digest: digest("evidence-source"),
                generation_vector_digest: digest("evidence-generation"),
                scope_digest: digest("evidence-scope"),
                authority_domain_digest: digest("evidence-domain"),
                contains_secret: false,
            },
            /*issued_unix_ms*/ 1,
            /*expires_unix_ms*/ 1_000,
        )?;
        let initial = ContextAdmissionSnapshotV2::new(
            id("snapshot:initial")?,
            digest("evidence-scope"),
            digest("evidence-domain"),
            /*observed_unix_ms*/ 10,
            /*revocation_epoch*/ 7,
            Vec::new(),
            /*revocation_set_complete*/ true,
            /*predecessor_snapshot_digest*/ None,
        )?;
        let mut verifier = AdmissionVerifier {
            record: record.clone(),
            snapshots: vec![initial.clone()],
        };
        let initial = verify_admission_snapshot_v2(initial, &verifier)?;
        let admission = verify_admission_v2(record, &initial, &verifier)?;
        let successor = ContextAdmissionSnapshotV2::new(
            id("snapshot:current")?,
            digest("evidence-scope"),
            digest("evidence-domain"),
            /*observed_unix_ms*/ 20,
            /*revocation_epoch*/ 8,
            Vec::new(),
            /*revocation_set_complete*/ true,
            Some(initial.snapshot_digest()),
        )?;
        verifier.snapshots.push(successor.clone());
        let snapshot = verify_admission_snapshot_successor_v2(successor, &initial, &verifier)?;
        let profile = ContextModelProfileV2 {
            model_digest: digest("evidence-profile"),
            provider_id_digest: digest("evidence-provider"),
            provider_model_digest: digest("evidence-model"),
            tokenizer_digest: tokenizer.tokenizer_digest(),
            serializer_digest: digest("evidence-serializer"),
            template_digest: digest("evidence-template"),
            tool_schema_digest: digest("evidence-tools"),
            maximum_context_tokens: 4_096,
        };
        let compiled = compile_v2(ContextCompilationRequestV2 {
            compilation_id: id("compilation:evidence")?,
            objective_digest: digest("evidence-objective"),
            prompt_portfolio_digest: digest("evidence-portfolio"),
            generation_vector_digest: digest("evidence-generation"),
            scope_digest: digest("evidence-scope"),
            authority_domain_digest: digest("evidence-domain"),
            admission_verifier_digest: verifier.verifier_digest(),
            model_profile: profile.clone(),
            token_budget: 4_096,
            truncation_policy_digest: digest("evidence-truncation"),
            candidates: vec![ContextCandidateV2 {
                item_id: id("item:evidence")?,
                role: ContextRoleV2::TrustedInstruction,
                content_digest: tokenization.content_digest(),
                source_digest: digest("evidence-source"),
                generation_vector_digest: digest("evidence-generation"),
                tokenization,
                expected_value: FixedQ32::ONE,
                admission,
            }],
            mandatory_groups: Vec::new(),
        })?;
        let serialization = record_canonical_serialization_v2(
            &compiled,
            &profile,
            id("serialization:evidence")?,
            vec![ContextRealizedItemV2 {
                item_id: id("item:evidence")?,
                role: ContextRoleV2::TrustedInstruction,
                content: content.to_vec(),
            }],
            &tokenizer,
        )?
        .into_serialized_context();
        let attachment = build_attachment(
            &compiled,
            &serialization,
            &profile,
            &initial,
            id("attachment:evidence")?,
        )?;
        let preparation = prepare_delivery_v2(
            &compiled,
            &serialization,
            &attachment,
            &profile,
            &snapshot,
            id("preparation:evidence")?,
        )?;
        let binding = ProviderRequestBinding {
            schema_version: PROVIDER_EVIDENCE_SCHEMA_VERSION,
            thread_id: "evidence-thread".to_string(),
            turn_id: "evidence-turn".to_string(),
            host_request_binding_id_sha256: Sha256Digest::for_bytes(b"evidence-host-request"),
            request_kind: ProviderRequestKind::Turn,
            provider_id: "evidence-provider".to_string(),
            provider_config_sha256: Sha256Digest::for_bytes(b"evidence-provider-config"),
            model: "evidence-model".to_string(),
            transport: ProviderTransport::Http,
            endpoint_sha256: Sha256Digest::for_bytes(b"/responses"),
            logical_request_sha256: Sha256Digest::for_bytes(serialization.payload()),
            wire_semantic_sha256: Sha256Digest::for_bytes(serialization.payload()),
            ephemeral_input_sha256: Some(Sha256Digest::for_bytes(serialization.payload())),
            ephemeral_input_witness_sha256: Some(Sha256Digest::for_bytes(
                preparation.preparation_digest().as_array(),
            )),
            previous_response_id_sha256: None,
            generate: true,
        };
        let provider = ProviderInvocationReceipt::new(
            ProviderInvocationIntent::for_host_attempt_id("evidence-attempt", binding),
            terminal,
        );
        let mut evidence = provider.canonical_wire_bytes()?;
        evidence.extend_from_slice(preparation.preparation_digest().as_array());
        let decision = ContextProviderDeliveryDecisionV2 {
            evidence_digest: Digest32::of_bytes(&evidence),
            recorded_at_unix_ms: 30,
        };
        let receipt = observe_delivery(
            ContextDeliveryRequestV2 {
                preparation: &preparation,
                attachment: &attachment,
                serialization: &serialization,
                profile: &profile,
                delivery_id: id("delivery:evidence")?,
                provider_receipt: &provider,
                observed_unix_ms: 40,
            },
            &DeliveryVerifier {
                provider: &provider,
                preparation: &preparation,
                decision: &decision,
            },
        )?;
        Ok(Self {
            receipt,
            preparation,
            attachment,
            serialization,
            profile,
            snapshot,
            provider,
            decision,
        })
    }

    fn expected_evidence(&self, disposition: &str, terminal_observed: bool) -> TestResult<Vec<u8>> {
        let fields = [
            ("schema", json!("hepta.context-delivery-evidence.v2")),
            ("delivery_id", json!("delivery:evidence")),
            (
                "preparation_digest",
                json!(self.preparation.preparation_digest().to_string()),
            ),
            (
                "attachment_digest",
                json!(self.attachment.attachment_digest().to_string()),
            ),
            (
                "serialization_receipt_digest",
                json!(self.serialization.receipt().receipt_digest().to_string()),
            ),
            (
                "payload_digest",
                json!(Digest32::of_bytes(self.serialization.payload()).to_string()),
            ),
            (
                "model_profile_digest",
                json!(self.profile.digest().to_string()),
            ),
            (
                "provider_id_digest",
                json!(digest(&self.provider.intent.binding.provider_id).to_string()),
            ),
            (
                "provider_model_digest",
                json!(digest(&self.provider.intent.binding.model).to_string()),
            ),
            (
                "provider_request_binding_digest",
                json!(digest(self.provider.request_binding_id.as_str()).to_string()),
            ),
            (
                "provider_attempt_digest",
                json!(digest(self.provider.attempt_id.as_str()).to_string()),
            ),
            (
                "provider_receipt_digest",
                json!(Digest32::of_bytes(&self.provider.canonical_wire_bytes()?).to_string()),
            ),
            (
                "provider_terminal_digest",
                json!(
                    Digest32::of_bytes(&self.provider.terminal.canonical_wire_bytes()?).to_string()
                ),
            ),
            (
                "provider_evidence_verifier_digest",
                json!(digest("evidence-delivery-verifier").to_string()),
            ),
            (
                "provider_evidence_digest",
                json!(self.decision.evidence_digest.to_string()),
            ),
            (
                "provider_recorded_at_unix_ms",
                json!(self.decision.recorded_at_unix_ms),
            ),
            (
                "admission_snapshot_digest",
                json!(self.snapshot.snapshot_digest().to_string()),
            ),
            (
                "admission_snapshot_verification_digest",
                json!(self.snapshot.verification_digest().to_string()),
            ),
            (
                "admission_snapshot_observed_unix_ms",
                json!(self.snapshot.observed_unix_ms()),
            ),
            ("revocation_epoch", json!(self.snapshot.revocation_epoch())),
            ("terminal_observed", json!(terminal_observed)),
            ("disposition", json!(disposition)),
            ("observed_unix_ms", json!(40)),
            (
                "receipt_digest",
                json!(self.receipt.receipt_digest().to_string()),
            ),
        ];
        let entries = fields
            .iter()
            .map(|(name, value)| -> serde_json::Result<String> {
                Ok(format!(
                    "{}:{}",
                    serde_json::to_string(name)?,
                    serde_json::to_string(value)?,
                ))
            })
            .collect::<serde_json::Result<Vec<_>>>()?;
        Ok(format!("{{{}}}", entries.join(",")).into_bytes())
    }
}

fn completed_terminal() -> ProviderTerminal {
    ProviderTerminal::Completed {
        response_id_sha256: Sha256Digest::for_bytes(b"evidence-response"),
        response_items_sha256: Sha256Digest::for_bytes(b"evidence-items"),
        token_usage_sha256: Sha256Digest::for_bytes(b"evidence-usage"),
        end_turn: Some(true),
    }
}

#[test]
fn canonical_evidence_keeps_all_fields_and_each_provider_terminal() -> TestResult {
    let cases = [
        (
            completed_terminal(),
            ContextDeliveryDispositionV2::Delivered,
            "delivered",
            true,
        ),
        (
            ProviderTerminal::CompletedUnary {
                response_items_sha256: Sha256Digest::for_bytes(b"evidence-unary-items"),
            },
            ContextDeliveryDispositionV2::Delivered,
            "delivered",
            true,
        ),
        (
            ProviderTerminal::Rejected {
                reason_code: "evidence-rejected".to_string(),
            },
            ContextDeliveryDispositionV2::Rejected,
            "rejected",
            true,
        ),
        (
            ProviderTerminal::NotDispatched {
                reason_code: "evidence-not-dispatched".to_string(),
            },
            ContextDeliveryDispositionV2::NotDispatched,
            "not_dispatched",
            true,
        ),
        (
            ProviderTerminal::Indeterminate {
                reason_code: "evidence-terminal-missing".to_string(),
                partial_response_sha256: None,
            },
            ContextDeliveryDispositionV2::Indeterminate,
            "indeterminate",
            false,
        ),
    ];
    for (terminal, disposition, label, terminal_observed) in cases {
        let fixture = Fixture::new("encoder-context-\u{2603}\n\u{0001}".as_bytes(), terminal)?;
        assert_eq!(fixture.receipt.disposition(), disposition);
        let actual = fixture.receipt.canonical_evidence_bytes()?;
        let expected = fixture.expected_evidence(label, terminal_observed)?;
        assert_eq!(
            serde_json::from_slice::<Value>(&actual)?,
            serde_json::from_slice::<Value>(&expected)?,
        );
        assert_eq!(actual, expected);
        fixture.receipt.validate_for(
            &fixture.preparation,
            &fixture.attachment,
            &fixture.serialization,
            &fixture.profile,
        )?;
    }
    Ok(())
}

#[test]
fn encoding_is_repeatable_without_mutating_or_disclosing_raw_context() -> TestResult {
    let content = "raw-context-must-not-enter-evidence-\u{2603}\n\u{0001}";
    let fixture = Fixture::new(content.as_bytes(), completed_terminal())?;
    let before = fixture.receipt.clone();
    let first = fixture.receipt.canonical_evidence_bytes()?;
    assert_eq!(first, fixture.receipt.canonical_evidence_bytes()?);
    assert_eq!(first, before.canonical_evidence_bytes()?);
    assert_eq!(fixture.receipt, before);
    assert_eq!(fixture.receipt.authority(), AuthorityPosture::DENY_ALL);
    let text = std::str::from_utf8(&first)?;
    assert!(!text.contains("raw-context-must-not-enter-evidence"));
    assert!(!text.contains(content));
    let value: Value = serde_json::from_slice(&first)?;
    assert!(value.get("authority").is_none());
    fixture.receipt.validate_for(
        &fixture.preparation,
        &fixture.attachment,
        &fixture.serialization,
        &fixture.profile,
    )?;
    Ok(())
}

#[test]
fn distinct_genuine_contexts_keep_distinct_evidence_bindings() -> TestResult {
    let first = Fixture::new(b"first-real-context", completed_terminal())?;
    let second = Fixture::new(b"second-real-context", completed_terminal())?;
    let first_bytes = first.receipt.canonical_evidence_bytes()?;
    let second_bytes = second.receipt.canonical_evidence_bytes()?;
    assert_eq!(
        first_bytes,
        first.expected_evidence("delivered", /*terminal_observed*/ true)?,
    );
    assert_eq!(
        second_bytes,
        second.expected_evidence("delivered", /*terminal_observed*/ true)?,
    );
    assert_ne!(first_bytes, second_bytes);
    assert_ne!(
        first.receipt.payload_digest(),
        second.receipt.payload_digest(),
    );
    assert_ne!(
        first.receipt.receipt_digest(),
        second.receipt.receipt_digest(),
    );
    Ok(())
}
