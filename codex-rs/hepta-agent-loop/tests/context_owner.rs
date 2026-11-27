#![cfg(feature = "context-v2")]

use codex_hepta_agent_loop::Error as LoopError;
use codex_hepta_agent_loop::*;
use codex_hepta_context_compiler::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|e| panic!("fixture ID: {e}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct FixtureCodec;
impl ExactTokenizerV2 for FixtureCodec {
    fn tokenizer_digest(&self) -> Digest32 {
        digest("tokenizer")
    }
    fn count_tokens(&self, bytes: &[u8]) -> std::result::Result<u64, ContextCompilerV2Error> {
        Ok(bytes.len() as u64)
    }
}
impl ContextSerializerV2 for FixtureCodec {
    fn serializer_digest(&self) -> Digest32 {
        digest("serializer")
    }
    fn template_digest(&self) -> Digest32 {
        digest("template")
    }
    fn tool_schema_digest(&self) -> Digest32 {
        digest("tools")
    }
    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> std::result::Result<Vec<u8>, ContextCompilerV2Error> {
        Ok(items.iter().flat_map(|v| v.content.clone()).collect())
    }
}
// Controlled verification fixture. Real hosts must inject their existing
// authenticated admission verifier; no such verifier is installed by this crate.
impl ContextAdmissionVerifierV2 for FixtureCodec {
    fn verifier_digest(&self) -> Digest32 {
        digest("verifier")
    }
    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.record_digest == record.compute_digest()
    }
    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.snapshot_digest == snapshot.compute_digest()
    }
}

fn snapshot(revoked: Vec<StableId>, epoch: u64) -> VerifiedAdmissionSnapshotV2 {
    let raw = ContextAdmissionSnapshotV2::new(
        id(&format!("snapshot:{epoch}")),
        digest("scope"),
        digest("authority"),
        10 + epoch,
        epoch,
        revoked,
        true,
        None,
    )
    .unwrap_or_else(|e| panic!("snapshot: {e}"));
    verify_admission_snapshot_v2(raw, &FixtureCodec)
        .unwrap_or_else(|e| panic!("verified snapshot: {e}"))
}

struct Fixture {
    compiled: CompiledContextV2,
    serialized: SerializedContextV2,
    attachment: ContextAttachmentV2,
    profile: ContextModelProfileV2,
    snapshot: VerifiedAdmissionSnapshotV2,
}

impl Fixture {
    fn new() -> Self {
        let snapshot = snapshot(Vec::new(), 1);
        let profile = ContextModelProfileV2 {
            model_digest: digest("profile"),
            provider_id_digest: digest("provider"),
            provider_model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            serializer_digest: digest("serializer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            maximum_context_tokens: 64,
        };
        let mut candidates = Vec::new();
        let mut realized = Vec::new();
        for (name, role, content) in [
            ("instruction", ContextRoleV2::TrustedInstruction, "system"),
            ("tool", ContextRoleV2::UntrustedEvidence, "result"),
            (
                "optional",
                ContextRoleV2::UntrustedEvidence,
                "old-optional-evidence",
            ),
        ] {
            let tokens = TokenizationReceiptV2::from_exact_bytes(
                id(name),
                content.as_bytes(),
                &FixtureCodec,
            )
            .unwrap_or_else(|e| panic!("tokens: {e}"));
            let record = ContextAdmissionRecordV2::new(
                id(&format!("admission:{name}")),
                ContextAdmissionBindingV2 {
                    item_id: id(name),
                    role,
                    content_digest: tokens.content_digest(),
                    source_digest: digest(name),
                    generation_vector_digest: digest("generation"),
                    scope_digest: digest("scope"),
                    authority_domain_digest: digest("authority"),
                    contains_secret: false,
                },
                1,
                1000,
            )
            .unwrap_or_else(|e| panic!("admission: {e}"));
            candidates.push(ContextCandidateV2 {
                item_id: id(name),
                role,
                content_digest: tokens.content_digest(),
                source_digest: digest(name),
                generation_vector_digest: digest("generation"),
                tokenization: tokens,
                expected_value: FixedQ32::ONE,
                admission: verify_admission_v2(record, &snapshot, &FixtureCodec)
                    .unwrap_or_else(|e| panic!("verified admission: {e}")),
            });
            realized.push(ContextRealizedItemV2 {
                item_id: id(name),
                role,
                content: content.as_bytes().to_vec(),
            });
        }
        let compiled = compile_v2(ContextCompilationRequestV2 {
            compilation_id: id("context:1"),
            objective_digest: digest("objective"),
            prompt_portfolio_digest: digest("portfolio"),
            generation_vector_digest: digest("generation"),
            scope_digest: digest("scope"),
            authority_domain_digest: digest("authority"),
            admission_verifier_digest: digest("verifier"),
            model_profile: profile.clone(),
            token_budget: 12,
            truncation_policy_digest: digest("policy"),
            candidates,
            mandatory_groups: vec![MandatoryContextGroupV2 {
                group_id: id("pending-call"),
                item_ids: vec![id("tool")],
                reason_digest: digest("tool continuation"),
            }],
        })
        .unwrap_or_else(|e| panic!("compile: {e}"));
        realized.retain(|item| {
            compiled
                .receipt()
                .selected_item_ids()
                .contains(&item.item_id)
        });
        let serialized = record_serialization(
            &compiled,
            &profile,
            id("serialization:1"),
            realized,
            &FixtureCodec,
            &FixtureCodec,
        )
        .unwrap_or_else(|e| panic!("serialize: {e}"));
        let attachment = build_attachment(
            &compiled,
            &serialized,
            &profile,
            &snapshot,
            id("attachment:1"),
        )
        .unwrap_or_else(|e| panic!("attach: {e}"));
        Self {
            compiled,
            serialized,
            attachment,
            profile,
            snapshot,
        }
    }

    fn input(&self) -> NativeContextInputV2<'_> {
        NativeContextInputV2 {
            objective_digest: digest("objective"),
            compiled: &self.compiled,
            serialized: &self.serialized,
            attachment: &self.attachment,
            model_profile: &self.profile,
            current_snapshot: &self.snapshot,
        }
    }
}

#[test]
fn context_recompile_preserves_mandatory_instruction_and_tool() {
    let fixture = Fixture::new();
    let prepared = prepare_native_context_v2(id("request:1"), 8, fixture.input()).unwrap();
    assert_eq!(prepared.request.payload.as_ref(), "systemresult");
    assert_eq!(prepared.request.input_tokens, 12);
    assert_eq!(
        fixture.compiled.receipt().omitted_item_ids(),
        &[id("optional")]
    );
    assert_eq!(
        prepared.preparation.payload_digest(),
        prepared.request.context_digest
    );
}

#[test]
fn revoked_context_is_rejected_before_native_dispatch() {
    let fixture = Fixture::new();
    let revoked = snapshot(vec![id("admission:instruction")], 2);
    let mut input = fixture.input();
    input.current_snapshot = &revoked;
    assert!(matches!(
        prepare_native_context_v2(id("request:1"), 8, input),
        Err(LoopError::Contract("context delivery preparation"))
    ));
}

#[test]
fn foreign_objective_cannot_reuse_valid_context_receipts() {
    let fixture = Fixture::new();
    let mut input = fixture.input();
    input.objective_digest = digest("different objective");
    assert!(matches!(
        prepare_native_context_v2(id("request:1"), 8, input),
        Err(LoopError::Contract("context objective"))
    ));
}

#[test]
fn output_reservation_must_fit_the_existing_model_profile() {
    let fixture = Fixture::new();
    assert!(matches!(
        prepare_native_context_v2(id("request:1"), 53, fixture.input()),
        Err(LoopError::Limit(
            "model context including output reservation"
        ))
    ));
}
