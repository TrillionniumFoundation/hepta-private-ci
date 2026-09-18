use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("test identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn model_profile() -> PromptModelProfileV1 {
    PromptModelProfileV1 {
        model_digest: digest("model"),
        tokenizer_digest: digest("tokenizer"),
        template_digest: digest("template"),
        tool_schema_digest: digest("tools"),
        locale_id: id("en-US"),
    }
}

fn binding(index: usize) -> PromptCandidateBindingV1 {
    let mut value = PromptCandidateBindingV1 {
        candidate_id: id(&format!("candidate:{index:03}")),
        factor_id: id(&format!("factor:{index:03}")),
        realization_id: id(&format!("realization:{index:03}")),
        role: PromptCandidateRoleV1::DeveloperInstruction,
        payload_digest: digest(&format!("payload:{index}")),
        admission_digest: digest(&format!("admission:{index}")),
        support_digest: digest(&format!("support:{index}")),
        token_cost: u64::try_from(index + 1).expect("small index"),
        expires_unix_ms: Some(10_000),
        binding_digest: Digest32::ZERO,
    };
    value.binding_digest = value.compute_binding_digest();
    value
}

fn source(count: usize) -> PromptCandidateSourceV1 {
    let mut value = PromptCandidateSourceV1 {
        owner_id: id("prompt.registry"),
        registry_snapshot_digest: digest("registry-snapshot"),
        registry_revision: 8,
        revocation_frontier: 7,
        generation_vector_digest: digest("generation-vector"),
        model_profile: model_profile(),
        bindings: (0..count).map(binding).collect(),
        omitted_count: 3,
        source_digest: Digest32::ZERO,
    };
    value.source_digest = value.compute_source_digest();
    value
}

struct AcceptSource;

impl PromptCandidateSourceAuthenticatorV1 for AcceptSource {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Ok(())
    }
}

struct RejectSource;

impl PromptCandidateSourceAuthenticatorV1 for RejectSource {
    fn authenticate_candidate_source(
        &self,
        _source: &PromptCandidateSourceV1,
        _objective_digest: Digest32,
        _now_unix_ms: u64,
    ) -> Result<(), PromptAuthenticationErrorV1> {
        Err(PromptAuthenticationErrorV1::Rejected)
    }
}

fn request(
    source: PromptCandidateSourceV1,
    maximum_candidates: usize,
) -> PromptCandidateEnumerationRequestV1 {
    PromptCandidateEnumerationRequestV1 {
        enumeration_id: id("enumeration:1"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        maximum_candidates,
        now_unix_ms: 100,
        source,
    }
}

#[test]
fn authenticated_enumeration_truncates_deterministically_and_binds_omissions() {
    let receipt = enumerate_factors_v1(request(source(3), 2), &AcceptSource)
        .expect("authenticated source should enumerate");

    assert_eq!(
        receipt
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect::<Vec<_>>(),
        vec![id("candidate:000"), id("candidate:001")]
    );
    assert_eq!(receipt.omitted_count_bound, 4);
    assert_eq!(
        receipt.no_intervention_arm_id,
        id(CANONICAL_NO_INTERVENTION_ID_V1)
    );
    assert!(!receipt.authority.grants_any());
    receipt
        .validate(/*now_unix_ms*/ 100)
        .expect("receipt validates");
}

#[test]
fn source_authentication_is_required_before_enumeration() {
    assert_eq!(
        enumerate_factors_v1(request(source(1), 1), &RejectSource),
        Err(CanonicalPromptErrorV1::SourceAuthenticationRejected)
    );
}

#[test]
fn tampered_or_expired_candidate_source_fails_closed() {
    let mut tampered = source(1);
    tampered.bindings[0].payload_digest = digest("tampered-payload");
    assert_eq!(
        enumerate_factors_v1(request(tampered, 1), &AcceptSource),
        Err(CanonicalPromptErrorV1::DigestMismatch("candidate binding"))
    );

    let mut expired = source(1);
    expired.bindings[0].expires_unix_ms = Some(50);
    expired.bindings[0].binding_digest = expired.bindings[0].compute_binding_digest();
    expired.source_digest = expired.compute_source_digest();
    assert_eq!(
        enumerate_factors_v1(request(expired, 1), &AcceptSource),
        Err(CanonicalPromptErrorV1::ExpiredCandidate(
            "candidate:000".to_string()
        ))
    );
}

#[test]
fn persisted_candidate_receipt_rejects_semantic_tampering() {
    let mut receipt = enumerate_factors_v1(request(source(1), 1), &AcceptSource)
        .expect("authenticated source should enumerate");
    receipt.omitted_count_bound += 1;
    assert_eq!(
        receipt.validate(/*now_unix_ms*/ 100),
        Err(CanonicalPromptErrorV1::DigestMismatch("candidate receipt"))
    );
}
