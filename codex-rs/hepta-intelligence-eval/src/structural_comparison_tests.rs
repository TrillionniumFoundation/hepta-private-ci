use super::*;

fn d(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn i(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn plan() -> FrozenStructuralComparisonV1 {
    let mut plan = FrozenStructuralComparisonV1 {
        candidate_id: i("candidate:split"),
        predecessor_id: i("predecessor:current"),
        no_change_id: i("candidate:no-change"),
        mutation: StructuralMutationKindV1::Split,
        topology_admission_digest: d(b"admission"),
        objective_digest: d(b"objective"),
        rollback_plan_digest: d(b"rollback"),
        generation: 1,
        frozen_plan_digest: Digest32::ZERO,
        dataset_digest: d(b"dataset"),
        metric_policy_digest: d(b"policy"),
        frozen_at_unix_ms: 20_000,
        future_start_unix_ms: 30_000,
        future_end_unix_ms: 40_000,
        maximum_compute_increase_ppm: 0,
        maximum_latency_increase_ppm: 0,
        maximum_rss_increase_ppm: 0,
        maximum_negative_transfer_ppm: 0,
        maximum_retention_loss_ppm: 0,
        minimum_ablation_delta_q24: 1,
    };
    plan.frozen_plan_digest = structural_comparison_plan_digest_v1(&plan).unwrap();
    plan
}

fn result() -> StructuralComparisonObservationV1 {
    StructuralComparisonObservationV1 {
        candidate_utility_q24: 11,
        predecessor_utility_q24: 10,
        no_change_utility_q24: 10,
        ablated_utility_q24: 9,
        candidate_compute_units: 100,
        matched_baseline_compute_units: 100,
        candidate_latency_p95_us: 100,
        baseline_latency_p95_us: 100,
        candidate_rss_peak_bytes: 1_000,
        baseline_rss_peak_bytes: 1_000,
        candidate_throughput_q24: 20,
        baseline_throughput_q24: 20,
        negative_transfer_ppm: 0,
        retention_loss_ppm: 0,
        recovery_observation_digest: d(b"recovery"),
        rollback_observation_digest: d(b"rollback"),
        holdout_observation_digest: d(b"holdout"),
        rollback_verified: true,
        recovery_verified: true,
    }
}

#[test]
fn matched_compute_and_ablation_are_strict() {
    let plan = plan();
    let observed = result();
    assert!(passes(&plan, &observed));
    let mut changed = observed.clone();
    changed.candidate_compute_units += 1;
    assert!(!passes(&plan, &changed));
    let mut changed = observed.clone();
    changed.ablated_utility_q24 = observed.candidate_utility_q24;
    assert!(!passes(&plan, &changed));
    let mut changed = observed.clone();
    changed.retention_loss_ppm = 1;
    assert!(!passes(&plan, &changed));
    let mut changed = observed;
    changed.recovery_verified = false;
    assert!(!passes(&plan, &changed));
}

#[test]
fn frozen_plan_future_window_and_observations_are_signed() {
    let plan = plan();
    let observed = result();
    let exact = structural_comparison_signing_payload_v1(&plan, &observed).unwrap();
    let mut changed = observed.clone();
    changed.candidate_utility_q24 += 1;
    assert_ne!(
        structural_comparison_signing_payload_v1(&plan, &changed).unwrap(),
        exact
    );
    let mut invalid = plan;
    invalid.future_start_unix_ms = invalid.frozen_at_unix_ms;
    assert_eq!(
        structural_comparison_signing_payload_v1(&invalid, &observed),
        Err(StructuralComparisonErrorV1::InvalidDesign)
    );
}

#[test]
fn frozen_commitment_binds_every_design_field() {
    let original = plan();
    let mut variants = Vec::new();
    macro_rules! changed {
        ($field:ident, $value:expr) => {{
            let mut changed = original.clone();
            changed.$field = $value;
            variants.push((stringify!($field), changed));
        }};
    }
    changed!(candidate_id, i("candidate:changed"));
    changed!(predecessor_id, i("predecessor:changed"));
    changed!(no_change_id, i("no-change:changed"));
    changed!(mutation, StructuralMutationKindV1::Merge);
    changed!(topology_admission_digest, d(b"changed-admission"));
    changed!(objective_digest, d(b"changed-objective"));
    changed!(rollback_plan_digest, d(b"changed-rollback"));
    changed!(generation, 2);
    changed!(dataset_digest, d(b"changed-dataset"));
    changed!(metric_policy_digest, d(b"changed-policy"));
    changed!(frozen_at_unix_ms, 19_000);
    changed!(future_start_unix_ms, 29_000);
    changed!(future_end_unix_ms, 41_000);
    changed!(maximum_compute_increase_ppm, 1);
    changed!(maximum_latency_increase_ppm, 1);
    changed!(maximum_rss_increase_ppm, 1);
    changed!(maximum_negative_transfer_ppm, 1);
    changed!(maximum_retention_loss_ppm, 1);
    changed!(minimum_ablation_delta_q24, 2);
    assert_eq!(variants.len(), 19);
    for (field, changed) in variants {
        assert_ne!(
            structural_comparison_plan_digest_v1(&changed).unwrap(),
            original.frozen_plan_digest,
            "{field}"
        );
        assert_eq!(
            structural_comparison_signing_payload_v1(&changed, &result()),
            Err(StructuralComparisonErrorV1::InvalidDesign),
            "{field}"
        );
    }
}

#[test]
fn arbitrary_nonzero_plan_digest_is_not_a_frozen_design() {
    let mut opaque = plan();
    opaque.frozen_plan_digest = d(b"opaque-generator-claim");
    assert_eq!(
        structural_comparison_signing_payload_v1(&opaque, &result()),
        Err(StructuralComparisonErrorV1::InvalidDesign)
    );
}

fn signer(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> codex_hepta_learning_ledger::TrustedLearningSignerV1 {
    let key = ed25519_dalek::SigningKey::from_bytes(&[seed; 32])
        .verifying_key()
        .to_bytes();
    codex_hepta_learning_ledger::TrustedLearningSignerV1 {
        principal: codex_hepta_learning_ledger::AuthenticatedPrincipalV1 {
            principal_id: i(name),
            credential_chain_digest: d(name.as_bytes()),
            signing_key_digest: d(&key),
            scope_digest: d(b"scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: i(controller),
        verifying_key: key,
        roles: vec![role],
        revoked_at: None,
    }
}

fn verifier() -> LearningEvidenceVerifierV1 {
    LearningEvidenceVerifierV1::new(codex_hepta_learning_ledger::LearningEvidenceTrustV1 {
        scope_digest: d(b"scope"),
        objective_digest: d(b"objective"),
        authority_epoch: 7,
        signers: vec![
            signer(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            signer(
                "evaluator",
                "evaluator-controller",
                2,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ],
    })
    .unwrap()
}

fn signed(
    verifier: &LearningEvidenceVerifierV1,
    principal: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
    issued_at: u64,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    use ed25519_dalek::Signer;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: i(principal),
        principal_id: i(principal),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: d(b"scope"),
        objective_digest: d(b"objective"),
        authority_epoch: 7,
        issued_at,
        expires_at: 90,
        payload_digest: d(payload),
        signature: [0; 64],
    };
    evidence.signature = ed25519_dalek::SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

#[test]
fn independent_signatures_cannot_rebind_the_preregistered_plan() {
    let plan = plan();
    let observed = result();
    let verifier = verifier();
    let original_wire = structural_comparison_signing_payload_v1(&plan, &observed).unwrap();
    let generator_plan = signed(
        &verifier,
        "generator",
        1,
        LearningEvidenceRoleV1::Generator,
        20,
        plan.frozen_plan_digest.as_array(),
    );
    let evidence = SignedStructuralComparisonV1 {
        generator_plan: generator_plan.clone(),
        evaluator_observation: signed(
            &verifier,
            "evaluator",
            2,
            LearningEvidenceRoleV1::Evaluator,
            40,
            &original_wire,
        ),
    };
    let decision =
        assess_signed_structural_comparison_v1(&plan, &observed, &evidence, &verifier, 50).unwrap();
    assert_eq!(
        decision.disposition,
        StructuralComparisonDispositionV1::EligibleForIndependentStatisticalReview
    );

    let mut changed = plan.clone();
    changed.maximum_compute_increase_ppm = 1;
    // An evaluator can legitimately sign new wire bytes after the experiment.
    // These signatures do not authorize changing the generator's frozen design.
    let compute_offset = b"hepta.eval.structural-comparison.v1\0".len()
        + [&plan.candidate_id, &plan.predecessor_id, &plan.no_change_id]
            .iter()
            .map(|id| 4 + id.as_str().len())
            .sum::<usize>()
        + 1
        + 9 * 32
        + 12 * 8;
    let mut changed_wire = original_wire;
    assert_eq!(
        &changed_wire[compute_offset..compute_offset + 4],
        &0_u32.to_be_bytes()
    );
    changed_wire[compute_offset..compute_offset + 4]
        .copy_from_slice(&changed.maximum_compute_increase_ppm.to_be_bytes());
    let attack = SignedStructuralComparisonV1 {
        generator_plan,
        evaluator_observation: signed(
            &verifier,
            "evaluator",
            2,
            LearningEvidenceRoleV1::Evaluator,
            40,
            &changed_wire,
        ),
    };
    let generator = verifier
        .verify(
            LearningEvidenceRoleV1::Generator,
            &attack.generator_plan,
            changed.frozen_plan_digest.as_array(),
            50,
        )
        .unwrap();
    let evaluator = verifier
        .verify(
            LearningEvidenceRoleV1::Evaluator,
            &attack.evaluator_observation,
            &changed_wire,
            50,
        )
        .unwrap();
    verify_signed_role_separation(&generator, &evaluator, 50).unwrap();
    assert_eq!(
        assess_signed_structural_comparison_v1(&changed, &observed, &attack, &verifier, 50),
        Err(StructuralComparisonErrorV1::InvalidDesign)
    );
}
