#[test]
fn sealed_enumeration_rejects_binding_tamper() {
    let candidates = verified_candidates(&[4]);
    let mut tampered = candidates.as_v1().clone();
    tampered.candidates[0].binding_digest = digest("tampered");
    assert!(matches!(
        VerifiedEnumeratedPromptCandidatesV2::try_from_v1(tampered),
        Err(VerifiedPromptError::CandidateBinding(_))
    ));
}

#[test]
fn pricing_rejects_generator_evaluator_controller_collision() {
    let candidates = verified_candidates(&[4]);
    let policy = pricing_policy();
    let authority = evidence_authority(true, candidates.receipt.objective_digest);
    let (completeness, pricing) = signed_inputs(&candidates, &authority, &policy);
    assert!(matches!(
        price_factors_verified_v2(
            candidates,
            completeness,
            pricing,
            &authority.verifier,
            &policy,
            100,
        ),
        Err(VerifiedPromptError::EvidenceIndependence(_))
    ));
}

#[test]
fn pricing_binds_objective_scope_and_exact_realization() {
    let candidates = verified_candidates(&[4]);
    let policy = pricing_policy();
    let authority = evidence_authority(false, candidates.receipt.objective_digest);
    let (completeness, mut pricing) = signed_inputs(&candidates, &authority, &policy);
    pricing[0].realization_binding_digest = digest("wrong-binding");
    assert!(matches!(
        price_factors_verified_v2(
            candidates,
            completeness,
            pricing,
            &authority.verifier,
            &policy,
            100,
        ),
        Err(VerifiedPromptError::InvalidPricing(_))
    ));
}

#[test]
fn pricing_success_seals_independent_evidence() {
    let candidates = verified_candidates(&[4]);
    let policy = pricing_policy();
    let authority = evidence_authority(false, candidates.receipt.objective_digest);
    let (completeness, pricing) = signed_inputs(&candidates, &authority, &policy);
    let result = price_factors_verified_v2(
        candidates,
        completeness,
        pricing,
        &authority.verifier,
        &policy,
        100,
    )
    .unwrap_or_else(|error| panic!("verified pricing: {error}"));
    assert_eq!(result.rows.len(), 1);
    assert_ne!(result.evidence_binding_digest(), Digest32::ZERO);
    assert_ne!(
        result.generator_controller_id(),
        &result.evaluator_controller_ids()[0]
    );
}
