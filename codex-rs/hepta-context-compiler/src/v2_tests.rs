use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn profile() -> ContextModelProfileV2 {
    ContextModelProfileV2 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tool-schema"),
        maximum_context_tokens: 1_000,
    }
}

fn candidate(
    item_id: &str,
    role: ContextRoleV2,
    token_count: u64,
    expected_value: FixedQ32,
) -> ContextCandidateV2 {
    let content_digest = digest(&format!("content:{item_id}"));
    ContextCandidateV2 {
        item_id: id(item_id),
        role,
        content_digest,
        source_digest: digest(&format!("source:{item_id}")),
        generation_vector_digest: digest("generation-vector"),
        tokenization: TokenizationReceiptV2::new(
            id(item_id),
            content_digest,
            digest("tokenizer"),
            token_count,
        )
        .unwrap_or_else(|error| panic!("valid tokenization: {error}")),
        expected_value,
        trusted_admission_digest: match role {
            ContextRoleV2::TrustedInstruction | ContextRoleV2::Schema => {
                Some(digest(&format!("admission:{item_id}")))
            }
            ContextRoleV2::UntrustedEvidence => None,
        },
        contains_secret: false,
    }
}

fn request(candidates: Vec<ContextCandidateV2>, token_budget: u64) -> ContextCompilationRequestV2 {
    ContextCompilationRequestV2 {
        compilation_id: id("compilation:1"),
        objective_digest: digest("objective"),
        prompt_portfolio_digest: digest("portfolio"),
        generation_vector_digest: digest("generation-vector"),
        model_profile: profile(),
        token_budget,
        truncation_policy_digest: digest("truncation-policy"),
        candidates,
        mandatory_groups: Vec::new(),
    }
}

#[test]
fn deterministic_value_per_token_preserves_mandatory_floors() {
    let trusted = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        40,
        FixedQ32::ONE,
    );
    let schema = candidate(
        "item:schema",
        ContextRoleV2::Schema,
        20,
        FixedQ32::ONE,
    );
    let high_ratio = candidate(
        "item:high-ratio",
        ContextRoleV2::UntrustedEvidence,
        20,
        FixedQ32::from_raw(1_i64 << 31),
    );
    let low_ratio = candidate(
        "item:low-ratio",
        ContextRoleV2::UntrustedEvidence,
        40,
        FixedQ32::from_raw(1_i64 << 31),
    );
    let candidates = vec![
        low_ratio.clone(),
        trusted.clone(),
        high_ratio.clone(),
        schema.clone(),
    ];
    let mut reversed = candidates.clone();
    reversed.reverse();
    let left = compile_v2(request(candidates, 80))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let right = compile_v2(request(reversed, 80))
        .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    assert_eq!(left, right);
    assert_eq!(left.receipt.used_tokens, 80);
    assert_eq!(
        left.receipt.selected_item_ids,
        vec![trusted.item_id, schema.item_id, high_ratio.item_id]
    );
    assert_eq!(left.receipt.omitted_item_ids, vec![low_ratio.item_id]);
}

#[test]
fn tiny_budget_refuses_instead_of_truncating_instruction_or_schema() {
    let trusted = candidate(
        "item:trusted",
        ContextRoleV2::TrustedInstruction,
        40,
        FixedQ32::ONE,
    );
    let schema = candidate(
        "item:schema",
        ContextRoleV2::Schema,
        20,
        FixedQ32::ONE,
    );
    assert_eq!(
        compile_v2(request(vec![trusted, schema], 50)),
        Err(ContextCompilerV2Error::InsufficientMandatoryBudget {
            required_tokens: 60,
            token_budget: 50,
        })
    );
}

#[test]
fn mandatory_evidence_group_is_all_or_nothing() {
    let first = candidate(
        "item:citation",
        ContextRoleV2::UntrustedEvidence,
        30,
        FixedQ32::ZERO,
    );
    let second = candidate(
        "item:contradiction",
        ContextRoleV2::UntrustedEvidence,
        30,
        FixedQ32::ZERO,
    );
    let mut grouped = request(vec![first.clone(), second.clone()], 60);
    grouped.mandatory_groups = vec![MandatoryContextGroupV2 {
        group_id: id("group:evidence"),
        item_ids: vec![first.item_id.clone(), second.item_id.clone()],
        reason_digest: digest("citation-contradiction-obligation"),
    }];
    let compiled = compile_v2(grouped)
        .unwrap_or_else(|error| panic!("valid grouped compilation: {error}"));
    assert_eq!(
        compiled.receipt.selected_item_ids,
        vec![first.item_id, second.item_id]
    );
}

#[test]
fn tokenizer_generation_secret_and_role_drift_fail_closed() {
    let mut wrong_tokenizer = candidate(
        "item:wrong-tokenizer",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
    );
    wrong_tokenizer.tokenization = TokenizationReceiptV2::new(
        wrong_tokenizer.item_id.clone(),
        wrong_tokenizer.content_digest,
        digest("different-tokenizer"),
        10,
    )
    .unwrap_or_else(|error| panic!("valid alternate receipt: {error}"));
    assert_eq!(
        compile_v2(request(vec![wrong_tokenizer], 100)),
        Err(ContextCompilerV2Error::TokenizerMismatch(
            "item:wrong-tokenizer".to_string()
        ))
    );

    let mut stale = candidate(
        "item:stale",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
    );
    stale.generation_vector_digest = digest("stale-vector");
    assert_eq!(
        compile_v2(request(vec![stale], 100)),
        Err(ContextCompilerV2Error::GenerationVectorMismatch(
            "item:stale".to_string()
        ))
    );

    let mut secret = candidate(
        "item:secret",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
    );
    secret.contains_secret = true;
    assert_eq!(
        compile_v2(request(vec![secret], 100)),
        Err(ContextCompilerV2Error::SecretRejected(
            "item:secret".to_string()
        ))
    );

    let mut confused = candidate(
        "item:confused",
        ContextRoleV2::UntrustedEvidence,
        10,
        FixedQ32::ONE,
    );
    confused.trusted_admission_digest = Some(digest("fake-admission"));
    assert_eq!(
        compile_v2(request(vec![confused], 100)),
        Err(ContextCompilerV2Error::EvidenceRoleConfusion(
            "item:confused".to_string()
        ))
    );
}

#[test]
fn compilation_serialization_attachment_and_delivery_form_one_digest_chain() {
    let compiled = compile_v2(request(
        vec![candidate(
            "item:trusted",
            ContextRoleV2::TrustedInstruction,
            20,
            FixedQ32::ONE,
        )],
        100,
    ))
    .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        id("serialization:1"),
        digest("exact-payload"),
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(&compiled, &serialization, id("attachment:1"))
        .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let observation = observe_delivery(
        &attachment,
        id("observation:1"),
        Some(digest("exact-payload")),
        true,
        ContextDeliveryDispositionV2::Delivered,
        10,
    )
    .unwrap_or_else(|error| panic!("valid delivery: {error}"));
    assert_eq!(observation.authority, AuthorityPosture::DENY_ALL);
    observation
        .validate_for(&attachment)
        .unwrap_or_else(|error| panic!("valid observation: {error}"));
}

#[test]
fn delivery_payload_mismatch_cannot_receive_delivered_status() {
    let compiled = compile_v2(request(
        vec![candidate(
            "item:evidence",
            ContextRoleV2::UntrustedEvidence,
            20,
            FixedQ32::ONE,
        )],
        100,
    ))
    .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        id("serialization:1"),
        digest("expected-payload"),
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(&compiled, &serialization, id("attachment:1"))
        .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    assert_eq!(
        observe_delivery(
            &attachment,
            id("observation:1"),
            Some(digest("different-payload")),
            true,
            ContextDeliveryDispositionV2::Delivered,
            10,
        ),
        Err(ContextCompilerV2Error::DeliveryMismatch)
    );
}

#[test]
fn nonterminal_delivery_is_indeterminate_not_success() {
    let compiled = compile_v2(request(
        vec![candidate(
            "item:evidence",
            ContextRoleV2::UntrustedEvidence,
            20,
            FixedQ32::ONE,
        )],
        100,
    ))
    .unwrap_or_else(|error| panic!("valid compilation: {error}"));
    let serialization = record_serialization(
        &compiled,
        id("serialization:1"),
        digest("payload"),
    )
    .unwrap_or_else(|error| panic!("valid serialization: {error}"));
    let attachment = build_attachment(&compiled, &serialization, id("attachment:1"))
        .unwrap_or_else(|error| panic!("valid attachment: {error}"));
    let observation = observe_delivery(
        &attachment,
        id("observation:1"),
        None,
        false,
        ContextDeliveryDispositionV2::Indeterminate,
        10,
    )
    .unwrap_or_else(|error| panic!("valid indeterminate observation: {error}"));
    assert_eq!(
        observation.disposition,
        ContextDeliveryDispositionV2::Indeterminate
    );
}
