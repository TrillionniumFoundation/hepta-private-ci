use super::*;
use codex_hepta_contracts::{FinalUseAuthority, FinalUseGrant, SignedFinalUseGrant};
use codex_hepta_prompt_optimizer::canonical::*;
use codex_hepta_prompt_registry::final_use_revoke_binding;
use ed25519_dalek::{Signer, SigningKey};

#[path = "prompt_optimizer_evidence_fixture.rs"]
mod evidence_fixture;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

pub(crate) fn admitted_registry(
    root: &std::path::Path,
    payload: &[u8],
) -> (
    DurablePromptRegistry,
    PromptModelTupleV2,
    FinalUseAuthority,
    SigningKey,
    u64,
) {
    evidence_fixture::admitted_registry(root, payload)
}

pub(crate) struct CanonicalSelection {
    pub(crate) portfolio: SelectedPromptPortfolioV1,
    pub(crate) exercise_request: PromptExerciseRequestV1,
}

pub(crate) fn canonical_selection(
    registry: &DurablePromptRegistry,
    tuple: &PromptModelTupleV2,
    now: u64,
) -> CanonicalSelection {
    let candidates = enumerate_factors_v1(
        registry.registry().expect("registry"),
        PromptEnumerationRequestV1 {
            set_id: id("set:canonical"),
            objective_digest: digest("objective"),
            state_digest: digest("state"),
            generation_vector_digest: digest("generation-vector"),
            model_tuple: tuple.clone(),
            now_unix_ms: now,
            required_factor_ids: vec![id("factor:verify")],
            maximum_candidates: 8,
            selection_grammar_digest: digest("grammar"),
        },
    )
    .expect("enumerate current registry");
    let (portfolio, exercise_request, _source) = evidence_fixture::select(candidates, now);
    CanonicalSelection {
        portfolio,
        exercise_request,
    }
}

fn compilation_request(
    tuple: &PromptModelTupleV2,
    suffix: &str,
) -> PromptRegistryCompilationRequestV2 {
    PromptRegistryCompilationRequestV2 {
        compilation_id: id(&format!("compilation:prompt:{suffix}")),
        serialization_id: id(&format!("serialization:prompt:{suffix}")),
        attachment_id: id(&format!("attachment:prompt:{suffix}")),
        registry_model_tuple: tuple.clone(),
        context_model_profile: ContextModelProfileV2 {
            model_digest: tuple.model_digest,
            provider_id_digest: digest("provider"),
            provider_model_digest: tuple.model_digest,
            tokenizer_digest: tuple.tokenizer_digest,
            serializer_digest: digest("serializer"),
            template_digest: tuple.template_digest,
            tool_schema_digest: tuple.tool_schema_digest,
            maximum_context_tokens: 128,
        },
        now_unix_ms: 100,
        token_budget: 128,
        truncation_policy_digest: digest("truncation"),
    }
}

#[test]
fn exercised_registry_payload_is_the_exact_context_attachment_input() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let payload = b"Inspect evidence before mutation.";
    let (registry, tuple, _authority, _signing_key, _grant_now) =
        admitted_registry(&temporary.path().join("prompt-registry"), payload);
    let selected = canonical_selection(&registry, &tuple, 100);
    let output = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        compilation_request(&tuple, "1"),
    )
    .expect("compile exercised prompt registry context");
    assert_eq!(
        output.compiled.receipt().selected_item_ids(),
        vec![id("realization:verify")]
    );
    assert_eq!(output.selected_deliveries.len(), 1);
    assert_eq!(output.selected_deliveries[0].payload, payload);
    assert_eq!(
        output.selected_deliveries[0].binding.digest(),
        selected.portfolio.selected[0].binding_digest
    );
    assert_eq!(
        output.exercise_receipt_digest,
        exercise_v1(
            registry.registry().expect("registry"),
            &selected.portfolio,
            selected.exercise_request.clone()
        )
        .expect("exercise")
        .receipt_digest
    );
    assert_eq!(
        output.portfolio_receipt_digest,
        selected.portfolio.receipt.receipt_digest
    );
    assert_eq!(
        Digest32::of_bytes(&output.serialized_payload),
        output.serialization.payload_digest()
    );
    assert_eq!(
        output.attachment.payload_digest(),
        output.serialization.payload_digest()
    );
    assert!(
        output
            .serialized_payload
            .windows(payload.len())
            .any(|window| window == payload)
    );
    let factor_v1 = registry
        .registry()
        .expect("registry")
        .factor_protocol_v1(&id("factor:verify"))
        .expect("factor projection")
        .expect("factor exists");
    assert_eq!(
        factor_v1.semantic_purpose,
        "inspect evidence before mutation"
    );
    let realization_v1 = registry
        .registry()
        .expect("registry")
        .realization_protocol_v1(&id("realization:verify"))
        .expect("realization projection")
        .expect("realization exists");
    assert_eq!(realization_v1.model_id, tuple.model_id);
    assert_eq!(realization_v1.model_version, tuple.model_version);
    output.validate().expect("compiled delivery validates");
}

#[test]
fn revocation_after_exercise_prevents_delivery_of_the_selected_realization() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let (mut registry, tuple, authority, signing_key, grant_now) = admitted_registry(
        &temporary.path().join("prompt-registry-revocation"),
        b"Bound instruction",
    );
    let selected = canonical_selection(&registry, &tuple, 100);
    revoke_registry(&mut registry, &authority, &signing_key, grant_now);
    let error = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        compilation_request(&tuple, "2"),
    )
    .expect_err("stale exercised selection must not deliver");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV2::Pipeline(_)
    ));
}

#[test]
fn compiler_rejects_registry_and_context_model_drift() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let (registry, tuple, _authority, _signing_key, _grant_now) = admitted_registry(
        &temporary.path().join("prompt-registry-model-drift"),
        b"Bound instruction",
    );
    let selected = canonical_selection(&registry, &tuple, 100);
    let mut request = compilation_request(&tuple, "3");
    request.context_model_profile.model_digest = digest("other-model");
    let error = compile_prompt_registry_v2(
        &registry,
        &selected.portfolio,
        &selected.exercise_request,
        request,
    )
    .expect_err("model drift must fail");
    assert!(matches!(
        error,
        PromptRegistryCompilationErrorV2::Pipeline(_)
    ));
}

pub(crate) fn revoke_registry(
    registry: &mut DurablePromptRegistry,
    authority: &FinalUseAuthority,
    signing_key: &SigningKey,
    grant_now: u64,
) {
    let factor = registry
        .registry()
        .expect("registry")
        .factor(&id("factor:verify"))
        .cloned()
        .expect("admitted factor");
    let actor = id("revoker:test");
    let revoke_scope = digest("scope:revoke:test");
    let reason = digest("reason:revoke");
    let cutoff = grant_now + 5_000;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "authority:fixture".to_owned(),
        authority_epoch: 1,
        grant_id: "revoke:prompt:1".to_owned(),
        nonce: [25; 32],
        binding: final_use_revoke_binding(&factor, &actor, revoke_scope, reason, cutoff)
            .expect("revoke binding"),
        not_before_unix_ms: grant_now.saturating_sub(1_000),
        expires_at_unix_ms: grant_now + 30_000,
    };
    let signed = SignedFinalUseGrant {
        signature: signing_key
            .sign(&grant.signing_bytes().expect("revoke signing bytes"))
            .to_bytes()
            .to_vec(),
        grant,
    };
    registry
        .revoke_factor_final_use(
            authority,
            &signed,
            &factor.factor_id,
            &actor,
            revoke_scope,
            reason,
            cutoff,
        )
        .expect("final-use revocation");
}
