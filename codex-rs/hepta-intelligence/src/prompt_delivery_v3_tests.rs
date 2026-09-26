use super::*;

use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_context_compiler::ContextAdmissionBindingV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_prompt_registry::FactorSource;
use codex_hepta_prompt_registry::Lifecycle;
use codex_hepta_prompt_registry::PromptFactor;
use codex_hepta_prompt_registry::PromptRealizationBindingV2;
use codex_hepta_prompt_registry::final_use_admission_binding;
use codex_hepta_prompt_registry::final_use_realization_binding;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone)]
struct StrictTestAdapters {
    verifier_digest: Digest32,
    tokenizer_digest: Digest32,
    product_profile_digest: Digest32,
    accepted_record_digest: Digest32,
    accepted_snapshot_digest: Digest32,
}

impl ContextAdmissionVerifierV2 for StrictTestAdapters {
    fn verifier_digest(&self) -> Digest32 {
        self.verifier_digest
    }

    fn verify_record(&self, record: &ContextAdmissionRecordV2) -> bool {
        record.record_digest == self.accepted_record_digest
    }

    fn verify_snapshot(&self, snapshot: &ContextAdmissionSnapshotV2) -> bool {
        snapshot.snapshot_digest == self.accepted_snapshot_digest
    }
}

impl ExactTokenizerV2 for StrictTestAdapters {
    fn tokenizer_digest(&self) -> Digest32 {
        self.tokenizer_digest
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        u64::try_from(bytes.len()).map_err(|_| ContextCompilerV2Error::Arithmetic)
    }
}

impl PromptCompilerProductAdaptersV3 for StrictTestAdapters {
    fn product_profile_digest(&self) -> Digest32 {
        self.product_profile_digest
    }
}

struct Fixture {
    registry: DurablePromptRegistry,
    tuple: PromptModelTupleV2,
    product_profile: ContextModelProfileRevisionV2,
    portfolio: SelectedPromptPortfolioV1,
    exercise_request: PromptExerciseRequestV1,
    snapshot: ContextAdmissionSnapshotV2,
    record: ContextAdmissionRecordV2,
    adapters: StrictTestAdapters,
    payload: Vec<u8>,
}

fn fixture(root: &std::path::Path) -> Fixture {
    let model_digest = digest("model:v3");
    let tokenizer_digest = digest("tokenizer:v3:byte-exact-test");
    let template_digest = digest("template:v3");
    let tool_schema_digest = digest("tool-schema:v3");
    let base_profile = ContextModelProfileV2 {
        model_digest,
        provider_id_digest: digest("provider:v3"),
        provider_model_digest: model_digest,
        tokenizer_digest,
        serializer_digest: digest("serializer:v3"),
        template_digest,
        tool_schema_digest,
        maximum_context_tokens: 16_384,
    };
    let product_profile = ContextModelProfileRevisionV2 {
        profile_id: id("context-profile:v3:test"),
        base_profile,
        provider_revision_digest: digest("provider-revision:v3"),
        model_revision_digest: digest("model-revision:v3"),
        tokenizer_binary_digest: digest("tokenizer-binary:v3"),
        tokenizer_vocabulary_digest: digest("tokenizer-vocabulary:v3"),
        tokenizer_normalization_digest: digest("tokenizer-normalization:v3"),
        serializer_revision_digest: canonical_prompt_serializer_revision_digest_v3(),
        template_revision_digest: digest("template-revision:v3"),
        tool_schema_revision_digest: digest("tool-schema-revision:v3"),
        role_profile_digest: canonical_prompt_role_profile_digest_v3(),
    };
    let tuple = PromptModelTupleV2 {
        model_id: id("model:hepta-v3"),
        model_version: "2026-09-27".to_owned(),
        model_digest,
        tokenizer_digest,
        template_digest,
        tool_schema_digest,
        context_profile_digest: product_profile.digest(),
        locale_id: id("locale:en-US"),
    };

    let mut registry = DurablePromptRegistry::open_state_dir(root, 64).expect("open registry");
    let factor = PromptFactor {
        factor_id: id("factor:v3"),
        proposer_id: id("proposer:v3"),
        semantic_version: id("v3"),
        semantic_purpose: "verify exact product compilation".to_owned(),
        authority_class: "registered_prompt_factor".to_owned(),
        eligible_objective_dimensions: vec![id("dimension:truth")],
        content_digest: digest("factor:v3"),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    };
    registry
        .register_factor(factor.clone())
        .expect("register factor");

    let signing_key = SigningKey::from_bytes(&[31; 32]);
    let authority = FinalUseAuthority::open_state_dir(
        &root.join("final-use"),
        "review-authority:prompt-v3".to_owned(),
        signing_key.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let wall_now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let reviewer = id("reviewer:v3");
    let factor_scope = digest("scope:factor:v3");
    let factor_evidence = digest("evidence:factor:v3");
    let factor_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt-v3".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:factor:v3".to_owned(),
        nonce: [32; 32],
        binding: final_use_admission_binding(&factor, &reviewer, factor_scope, factor_evidence)
            .expect("factor binding"),
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let factor_signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&factor_grant.signing_bytes().expect("factor signing bytes"))
            .to_bytes()
            .to_vec(),
        grant: factor_grant,
    };
    registry
        .admit_factor_final_use(
            &authority,
            &factor_signed,
            &factor.factor_id,
            factor_scope,
            factor_evidence,
        )
        .expect("admit factor");
    let admitted_factor = registry
        .registry()
        .expect("registry")
        .factor(&factor.factor_id)
        .cloned()
        .expect("factor");

    let payload = b"Do not mutate until evidence is checked.".to_vec();
    let realization = PromptRealizationBindingV2 {
        realization_id: id("realization:v3"),
        factor_id: factor.factor_id.clone(),
        model_id: tuple.model_id.clone(),
        model_version: tuple.model_version.clone(),
        model_digest: tuple.model_digest,
        tokenizer_digest: tuple.tokenizer_digest,
        template_digest: tuple.template_digest,
        tool_schema_digest: tuple.tool_schema_digest,
        context_profile_digest: tuple.context_profile_digest,
        locale_id: tuple.locale_id.clone(),
        role: PromptRoleV2::DeveloperInstruction,
        payload_digest: Digest32::of_bytes(&payload),
        token_cost: 1,
        expires_unix_ms: None,
    };
    let publisher = id("publisher:v3");
    let realization_scope = digest("scope:realization:v3");
    let realization_grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "review-authority:prompt-v3".to_owned(),
        authority_epoch: 1,
        grant_id: "grant:realization:v3".to_owned(),
        nonce: [33; 32],
        binding: final_use_realization_binding(
            &admitted_factor,
            &publisher,
            realization_scope,
            &realization,
            None,
        )
        .expect("realization binding"),
        not_before_unix_ms: wall_now.saturating_sub(1_000),
        expires_at_unix_ms: wall_now + 30_000,
    };
    let realization_signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(
                &realization_grant
                    .signing_bytes()
                    .expect("realization signing bytes"),
            )
            .to_bytes()
            .to_vec(),
        grant: realization_grant,
    };
    registry
        .register_realization_payload_final_use_v2(
            &authority,
            &realization_signed,
            &publisher,
            realization_scope,
            realization,
            payload.clone(),
            None,
        )
        .expect("register realization");

    let now = 100;
    let candidates = enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:v3"),
            objective_digest: digest("objective:v3"),
            state_digest: digest("state:v3"),
            generation_vector_digest: digest("generation:v3"),
            model_tuple: tuple.clone(),
            now_unix_ms: now,
            required_factor_ids: vec![factor.factor_id],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar:v3"),
        },
    )
    .expect("enumerate");
    let portfolio = SelectedPromptPortfolioV1 {
        receipt: PromptPortfolioReceiptV1 {
            portfolio_id: id("portfolio:v3"),
            candidate_set_digest: candidates.receipt.receipt_digest,
            factor_ids: vec![id("factor:v3")],
            interaction_digest: digest("interaction:v3"),
            expected_utility_q32: FixedQ32::ONE,
            total_token_upper_bound: 1,
            valid_until_unix_ms: 1_000,
            receipt_digest: digest("portfolio-receipt:v3"),
            authority: AuthorityPosture::DENY_ALL,
        },
        selected: candidates.candidates,
        objective_digest: digest("objective:v3"),
        state_digest: digest("state:v3"),
        model_tuple: tuple.clone(),
        model_tuple_digest: tuple.digest(),
        generation_vector_digest: digest("generation:v3"),
        pricing_set_digest: digest("pricing:v3"),
        graph_generation_digest: digest("graph:v3"),
        selection_method: PromptSelectionMethodV1::GreedyPrerequisiteBundleV1,
        optimality: PromptOptimalityDisclosureV1::HeuristicNoCertificate,
    };
    let exercise_request = PromptExerciseRequestV1 {
        decision_boundary: PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
        current_state_digest: digest("state:v3"),
        generation_vector_digest: digest("generation:v3"),
        model_tuple: tuple.clone(),
        now_unix_ms: now,
        wait_value_q32: FixedQ32::ZERO,
        policy_digest: digest("exercise-policy:v3"),
    };

    let scope_digest = digest("context-scope:v3");
    let authority_domain_digest = digest("context-authority:v3");
    let snapshot = ContextAdmissionSnapshotV2::new(
        id("snapshot:v3:root"),
        scope_digest,
        authority_domain_digest,
        now,
        1,
        Vec::new(),
        true,
        None,
    )
    .expect("snapshot");
    let selected = &portfolio.selected[0];
    let record = ContextAdmissionRecordV2::new(
        id("admission:v3"),
        ContextAdmissionBindingV2 {
            item_id: selected.realization.realization_id.clone(),
            role: ContextRoleV2::TrustedInstruction,
            content_digest: selected.realization.payload_digest,
            source_digest: selected.binding_digest,
            generation_vector_digest: portfolio.generation_vector_digest,
            scope_digest,
            authority_domain_digest,
            contains_secret: false,
        },
        50,
        1_000,
    )
    .expect("record");
    let adapters = StrictTestAdapters {
        verifier_digest: digest("admission-verifier:v3"),
        tokenizer_digest,
        product_profile_digest: product_profile.digest(),
        accepted_record_digest: record.record_digest,
        accepted_snapshot_digest: snapshot.snapshot_digest,
    };

    Fixture {
        registry,
        tuple,
        product_profile,
        portfolio,
        exercise_request,
        snapshot,
        record,
        adapters,
        payload,
    }
}

fn compile(
    fixture: &Fixture,
    token_budget: u64,
) -> Result<PromptRegistryCompiledContextV3, PromptRegistryCompilationErrorV3> {
    compile_prompt_registry_v3(
        &fixture.registry,
        &fixture.portfolio,
        &fixture.exercise_request,
        PromptRegistryCompilationRequestV3 {
            compilation_id: id("compilation:v3"),
            serialization_id: id("serialization:v3"),
            attachment_id: id("attachment:v3"),
            registry_model_tuple: fixture.tuple.clone(),
            product_profile: fixture.product_profile.clone(),
            now_unix_ms: fixture.exercise_request.now_unix_ms,
            token_budget,
            truncation_policy_digest: digest("truncation:v3"),
            admission_snapshot: fixture.snapshot.clone(),
            predecessor_lineage: None,
            admission_records: vec![fixture.record.clone()],
        },
        &fixture.adapters,
    )
}

#[test]
fn v3_tokenizes_the_actual_canonical_payload_and_redacts_debug() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = fixture(&temporary.path().join("registry"));
    let output = compile(&fixture, 16_384).expect("compile v3");

    assert_eq!(
        output
            .serialized_context
            .receipt()
            .serialized_token_count(),
        u64::try_from(output.serialized_context.payload().len()).expect("payload length")
    );
    assert!(
        output
            .serialized_context
            .payload()
            .ends_with(&fixture.payload)
    );
    assert!(output.serialized_context.segments().iter().any(|segment| {
        segment.kind == ContextSerializationSegmentKindV2::Framing
    }));
    assert!(output.serialized_context.segments().iter().any(|segment| {
        segment.kind == ContextSerializationSegmentKindV2::Item
    }));
    let rendered = format!("{output:?}");
    assert!(!rendered.contains("Do not mutate until evidence is checked."));
    output.validate().expect("valid v3 output");
}

#[test]
fn framing_overhead_cannot_hide_behind_registry_token_cost() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let fixture = fixture(&temporary.path().join("registry"));
    let output = compile(&fixture, 16_384).expect("compile high budget");
    let actual_tokens = output
        .serialized_context
        .receipt()
        .serialized_token_count();
    assert!(actual_tokens > u64::from(fixture.portfolio.receipt.total_token_upper_bound));

    let error = compile(&fixture, actual_tokens - 1).expect_err("framing overflow must fail");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV3::Context(
            ContextCompilerV2Error::SerializedTokenBudgetExceeded { .. }
        )
    ));
}

#[test]
fn unaccepted_external_admission_record_fails_closed() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let mut fixture = fixture(&temporary.path().join("registry"));
    fixture.adapters.accepted_record_digest = digest("different-record");
    let error = compile(&fixture, 16_384).expect_err("unaccepted record must fail");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV3::Context(
            ContextCompilerV2Error::AdmissionRecordUnverified(_)
        )
    ));
}

#[test]
fn concrete_profile_revision_drift_fails_before_compilation() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let mut fixture = fixture(&temporary.path().join("registry"));
    fixture.product_profile.tokenizer_vocabulary_digest = digest("other-vocabulary");
    let error = compile(&fixture, 16_384).expect_err("profile drift must fail");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV3::ProfileMismatch
    ));
}
