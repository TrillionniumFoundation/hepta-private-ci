#![no_main]

use codex_hepta_intuition::AssignmentCommitmentV2;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::PolicyGeneration;
use codex_hepta_intuition::ProductionDispositionV1;
use codex_hepta_intuition::ProductionPolicyError;
use codex_hepta_intuition::ProductionSlowPathReasonV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::ScoringCommitmentV2;
use codex_hepta_intuition::canonical_assignment_commitment_digest_v2;
use codex_hepta_intuition::canonical_assignment_distribution_digest_v2;
use codex_hepta_intuition::canonical_candidate_identity_digest_v2;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_runtime_commitment_payload_v2;
use codex_hepta_intuition::canonical_scored_outputs_digest_v2;
use codex_hepta_intuition::canonical_scoring_commitment_digest_v2;
use codex_hepta_intuition::decide_calibrated_v4;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use libfuzzer_sys::fuzz_target;

fn digest(label: &[u8]) -> Digest32 {
    Digest32::of_bytes(label)
}

fn id(value: String) -> StableId {
    StableId::new(value).expect("generated stable id")
}

fuzz_target!(|data: &[u8]| {
    if data.is_empty() {
        return;
    }
    let count = usize::from(data[0] % 128) + 1;
    let mut candidates = Vec::with_capacity(count);
    for index in 0..count {
        let byte = data.get(index + 1).copied().unwrap_or(index as u8);
        let probability = ProbabilityQ32::from_raw(
            u64::from(byte) * ProbabilityQ32::ONE.raw() / u64::from(u8::MAX),
        )
        .expect("bounded probability");
        candidates.push(CalibratedActionCandidateV1 {
            candidate_id: id(format!("candidate:{index:03}")),
            legal: byte & 1 == 0,
            hard_veto: byte & 2 != 0,
            utility: FixedQ32::from_raw(i64::from(byte) - 128),
            calibrated_confidence: probability,
            ood_score: ProbabilityQ32::from_raw(
                u64::from(
                    data.get(index + count + 1)
                        .copied()
                        .unwrap_or(byte.rotate_left(3)),
                ) * ProbabilityQ32::ONE.raw()
                    / u64::from(u8::MAX),
            )
            .expect("bounded OOD score"),
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest(&[byte, index as u8]),
        });
    }

    let Ok(candidate_set_digest) = canonical_candidate_set_digest_v1(&candidates) else {
        return;
    };
    let Ok(canonical_order_digest) = canonical_candidate_order_digest_v1(&candidates) else {
        return;
    };
    let threshold =
        ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() / 2).expect("bounded threshold");
    let mut request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:fuzz".to_string()),
        objective_digest: digest(b"objective"),
        objective_class_digest: digest(b"objective-class"),
        state_digest: digest(b"state"),
        policy_digest: digest(b"policy"),
        policy_generation: 1,
        sequence: 1,
        minimum_confidence: threshold,
        maximum_ece_ppm: 1_000_000,
        maximum_ood_false_acceptance_ppm: 1_000_000,
        risk_class: match data.get(3).copied().unwrap_or(0) % 3 {
            0 => RiskClass::Low,
            1 => RiskClass::Elevated,
            _ => RiskClass::High,
        },
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"completeness"),
            generator_digest: digest(b"generator"),
            grammar_digest: digest(b"grammar"),
            hard_filter_digest: digest(b"hard-filter"),
            truncation_digest: digest(b"truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest(b"calibration"),
            policy_digest: digest(b"policy"),
            objective_class_digest: digest(b"objective-class"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest(b"subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest(b"ood"),
            policy_digest: digest(b"policy"),
            detector_digest: digest(b"detector"),
            support_digest: digest(b"ood-support"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 1,
            maximum_in_domain_score: threshold,
            measured_false_acceptance_ppm: 0,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };

    if data.get(1).copied().unwrap_or(0) & 1 != 0 {
        let eligible = request
            .candidates
            .iter()
            .enumerate()
            .filter_map(|(index, candidate)| {
                (candidate.legal
                    && !candidate.hard_veto
                    && candidate.calibrated_confidence >= request.minimum_confidence
                    && candidate.ood_score <= request.ood.maximum_in_domain_score)
                    .then_some(index)
            })
            .collect::<Vec<_>>();
        let include_abstain = eligible.is_empty() || data.get(2).copied().unwrap_or(0) & 1 != 0;
        let slots = eligible.len() as u64 + u64::from(include_abstain);
        let base_mass = ProbabilityQ32::ONE.raw() / slots;
        let remainder = ProbabilityQ32::ONE.raw() % slots;
        for (slot, index) in eligible.iter().copied().enumerate() {
            request.candidates[index].assignment_probability =
                ProbabilityQ32::from_raw(base_mass + u64::from((slot as u64) < remainder))
                    .expect("normalized candidate mass");
        }
        let abstain_probability = if include_abstain {
            ProbabilityQ32::from_raw(base_mass + u64::from((eligible.len() as u64) < remainder))
                .expect("normalized abstain mass")
        } else {
            ProbabilityQ32::ZERO
        };
        let draw = (0..4).fold(0_u64, |value, index| {
            (value << 8) | u64::from(data.get(index + 5).copied().unwrap_or(0))
        });
        request.assignment = AssignmentModeV1::CounterBased {
            random_stream_digest: digest(b"stream"),
            draw: ProbabilityQ32::from_raw(draw).expect("draw below one"),
            abstain_probability,
        };
        request.completeness.candidate_set_digest =
            canonical_candidate_set_digest_v1(&request.candidates).expect("normalized set");
    }

    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:fuzz".to_string()),
        policy_digest: request.policy_digest,
        objective_class_digest: request.objective_class_digest,
        generation: request.policy_generation,
        valid_from_sequence: 1,
        expires_after_sequence: 1,
        minimum_confidence: request.minimum_confidence,
        maximum_ece_ppm: request.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: request.maximum_ood_false_acceptance_ppm,
        maximum_in_domain_score: request.ood.maximum_in_domain_score,
        risk_rule: match data.get(4).copied().unwrap_or(0) % 3 {
            0 => CanonicalRiskRuleV1::HighOnlySlowPath,
            1 => CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
            _ => CanonicalRiskRuleV1::AlwaysSlowPath,
        },
        scorer: LearnedScorerContractV1 {
            model_digest: digest(b"model"),
            feature_schema_digest: digest(b"feature-schema"),
            output_schema_digest: digest(b"output-schema"),
            score_semantics_digest: digest(b"score-semantics"),
            scorer_contract_digest: digest(b"scorer-contract"),
        },
        calibration_dataset_digest: digest(b"calibration-data"),
        ood_dataset_digest: digest(b"ood-data"),
        calibration_artifact_digest: request.calibration.artifact_digest,
        ood_artifact_digest: request.ood.artifact_digest,
    };

    let Ok(identity) = canonical_candidate_identity_digest_v2(&request.candidates) else {
        return;
    };
    let Ok(scored) = canonical_scored_outputs_digest_v2(&request) else {
        return;
    };
    let Ok(distribution) = canonical_assignment_distribution_digest_v2(&request) else {
        return;
    };
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: digest(b"model"),
        feature_snapshot_digest: digest(b"feature-snapshot"),
        feature_schema_digest: digest(b"feature-schema"),
        scorer_contract_digest: digest(b"scorer-contract"),
        candidate_identity_digest: identity,
        scored_outputs_digest: scored,
        policy_digest: digest(b"policy"),
        policy_generation: PolicyGeneration::new(1).expect("generation"),
    };
    let assignment = match &request.assignment {
        AssignmentModeV1::Deterministic => AssignmentCommitmentV2::Deterministic {
            distribution_digest: distribution,
        },
        AssignmentModeV1::CounterBased {
            random_stream_digest,
            draw,
            ..
        } => AssignmentCommitmentV2::CounterBased {
            rng_owner_digest: digest(b"rng-owner"),
            random_stream_digest: *random_stream_digest,
            counter: request.sequence,
            draw: *draw,
            distribution_digest: distribution,
        },
    };
    canonical_scoring_commitment_digest_v2(&scoring).expect("scoring commitment");
    canonical_assignment_commitment_digest_v2(&request, &assignment)
        .expect("assignment commitment");
    canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
        .expect("runtime commitment");
    let mut changed_scoring = scoring.clone();
    changed_scoring.scored_outputs_digest = digest(b"substituted-scores");
    assert_eq!(
        canonical_runtime_commitment_payload_v2(&request, &profile, &changed_scoring, &assignment),
        Err(ProductionPolicyError::ScoringDigestMismatch)
    );
    let mut changed_assignment = assignment.clone();
    match &mut changed_assignment {
        AssignmentCommitmentV2::Deterministic {
            distribution_digest,
        }
        | AssignmentCommitmentV2::CounterBased {
            distribution_digest,
            ..
        } => {
            *distribution_digest = digest(b"substituted-distribution");
        }
    }
    assert_eq!(
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &changed_assignment),
        Err(ProductionPolicyError::AssignmentDistributionMismatch)
    );
    let receipt = decide_calibrated_v4(request.clone(), &profile).expect("valid bounded policy");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(receipt.propensities.len(), count);
    let total = receipt
        .propensities
        .iter()
        .map(|candidate| candidate.probability.raw())
        .sum::<u64>()
        + receipt.abstain_probability.raw()
        + receipt.slow_path_probability.raw();
    assert_eq!(total, ProbabilityQ32::ONE.raw());
    let forced = request.risk_class == RiskClass::High
        || profile.risk_rule == CanonicalRiskRuleV1::AlwaysSlowPath
        || (request.risk_class == RiskClass::Elevated
            && profile.risk_rule == CanonicalRiskRuleV1::ElevatedAndHighSlowPath);
    if forced {
        let reason = if request.risk_class == RiskClass::High {
            ProductionSlowPathReasonV1::RequestHighRisk
        } else {
            ProductionSlowPathReasonV1::ProfileRiskRule
        };
        assert_eq!(
            receipt.disposition,
            ProductionDispositionV1::SlowPath(reason)
        );
    }
    if let ProductionDispositionV1::Selected(selected) = receipt.disposition {
        let candidate = request
            .candidates
            .iter()
            .find(|candidate| candidate.candidate_id == selected)
            .expect("selected candidate belongs to complete set");
        assert!(candidate.legal && !candidate.hard_veto);
        assert!(candidate.calibrated_confidence >= request.minimum_confidence);
        assert!(candidate.ood_score <= request.ood.maximum_in_domain_score);
        assert!(!forced);
    }
});
