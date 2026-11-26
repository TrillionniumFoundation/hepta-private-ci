use super::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

struct RecoveryClock(u64);
impl codex_hepta_contracts::AuthorityClock for RecoveryClock {
    fn now_unix_ms(&self) -> Result<u64, codex_hepta_contracts::AuthorityTrustError> {
        Ok(self.0)
    }
}

#[test]
fn restored_original_generator_publication_keeps_admitted_round_time_and_exact_frozen_purpose()
-> Result<(), Box<dyn std::error::Error>> {
    use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
    use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
    let payload = b"actual original full frozen candidate fixture bytes";
    let round: codex_hepta_agentd::AgentdSelfIterationRoundV1 =
        serde_json::from_value(serde_json::json!({
            "goal":"actual.fixture.goal", "ordinal":1, "candidate_admissions":2,
            "policy":Digest32::of_bytes(b"full policy").to_string(),
            "execution":Digest32::of_bytes(b"tight original execution").to_string(),
            "admitted_at_ms":1000, "deadline_ms":5000
        }))?;
    let original = SignedLearningEvidenceV1 {
        evidence_id: StableId::new("immutable.g.publication")?,
        principal_id: StableId::new("original.generator")?,
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: Digest32::of_bytes(b"activated trust"),
        scope_digest: Digest32::of_bytes(b"original scope"),
        objective_digest: Digest32::of_bytes(b"original training objective"),
        authority_epoch: 3,
        issued_at: 1500,
        expires_at: 4500,
        payload_digest: Digest32::of_bytes(payload),
        signature: [19; 64],
    };
    let bytes = original.signing_bytes();
    let now = RecoveryClock(3000);
    validate_generator_issuance(
        &original,
        &original,
        payload,
        round.admitted_at_ms(),
        5000,
        &now,
        Some(&round),
    )?;
    assert!(
        validate_generator_issuance(
            &original,
            &original,
            payload,
            3000,
            5000,
            &now,
            Some(&round),
        )
        .is_err()
    );
    for changed in [
        SignedLearningEvidenceV1 {
            issued_at: 999,
            ..original.clone()
        },
        SignedLearningEvidenceV1 {
            expires_at: 5001,
            ..original.clone()
        },
        SignedLearningEvidenceV1 {
            payload_digest: Digest32::of_bytes(b"other candidate"),
            ..original.clone()
        },
        SignedLearningEvidenceV1 {
            role: LearningEvidenceRoleV1::Selector,
            ..original.clone()
        },
    ] {
        assert!(
            validate_generator_issuance(
                &changed,
                &original,
                payload,
                round.admitted_at_ms(),
                6000,
                &now,
                Some(&round),
            )
            .is_err()
        );
    }
    assert!(
        validate_generator_issuance(
            &original,
            &original,
            payload,
            round.admitted_at_ms(),
            5000,
            &RecoveryClock(4500),
            Some(&round),
        )
        .is_err()
    );
    assert_eq!(original.signing_bytes(), bytes);
    // These are factual adapter checks; only the original runtime validates
    // the real signature and current trust before authorizing an effect.
    Ok(())
}

fn baseline() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"selected frozen heads"),
        normalization_digest: Digest32::of_bytes(b"fixed Q24 normalization"),
        generation: Generation::new(1).expect("generation"),
        width: 10,
        top_k: 1,
        temporal_decay_q24: 1 << 23,
        inhibition_gain_q24: 0,
        inhibition: Vec::new(),
        activity_decay_q24: 1 << 23,
        target_activity_q24: 1 << 20,
        threshold_rate_q24: 1 << 10,
        threshold_min_q24: 0,
        threshold_max_q24: 1 << 24,
        eligibility_decay_q24: 1 << 23,
    }
}

fn delta(parameter: &str, raw_q32: i64) -> ParameterDeltaV2 {
    ParameterDeltaV2 {
        layer_id: StableId::new(PARAMETER_LAYER).expect("layer"),
        parameter_id: StableId::new(parameter).expect("parameter"),
        delta: FixedQ32::from_raw(raw_q32),
        lower_bound: FixedQ32::from_raw(-(1 << 24)),
        upper_bound: FixedQ32::from_raw(1 << 24),
        evidence_digest: Digest32::of_bytes(b"original installed signal evidence"),
    }
}

#[test]
fn compiler_reapplies_exact_signed_q32_deltas_without_changing_frozen_or_structural_parameters() {
    let original = baseline();
    let generation = original.generation.next().expect("successor");
    let update = apply_sparse_deltas(
        &original,
        generation,
        &[
            delta("threshold_rate_q24", 512),
            delta("temporal_decay_q24", -256),
        ],
    )
    .expect("actual exact update");
    let mut expected = original.clone();
    expected.generation = generation;
    expected.threshold_rate_q24 += 2;
    expected.temporal_decay_q24 -= 1;
    assert_eq!(update, expected);
    assert_ne!(
        update.digest().expect("updated identity"),
        original.digest().expect("original identity")
    );
    assert_eq!(original, baseline());
}

#[test]
fn compiler_rejects_unknown_weights_fractional_q24_and_duplicate_coordinates_before_materialization()
 {
    let original = baseline();
    let generation = original.generation.next().expect("successor");
    for deltas in [
        vec![delta("weights", 256)],
        vec![delta("top_k", 256)],
        vec![delta("temporal_decay_q24", 1)],
        vec![
            delta("temporal_decay_q24", 256),
            delta("temporal_decay_q24", 256),
        ],
    ] {
        assert!(apply_sparse_deltas(&original, generation, &deltas).is_err());
    }
    let mut wrong_layer = delta("temporal_decay_q24", 256);
    wrong_layer.layer_id = StableId::new("authority").expect("layer");
    assert!(apply_sparse_deltas(&original, generation, &[wrong_layer]).is_err());
    assert_eq!(original, baseline());
}

#[test]
fn compiler_rejects_out_of_range_values_and_skipped_generation_and_uses_actual_norm_bytes() {
    let original = baseline();
    let generation = original.generation.next().expect("successor");
    let mut excessive = delta("temporal_decay_q24", 1 << 24);
    excessive.delta = FixedQ32::from_raw(1 << 33);
    excessive.upper_bound = excessive.delta;
    assert!(apply_sparse_deltas(&original, generation, &[excessive]).is_err());
    assert!(
        apply_sparse_deltas(
            &original,
            generation.next().expect("skipped"),
            &[delta("threshold_rate_q24", 256)],
        )
        .is_err()
    );
    let values = [
        1_i128 << 23,
        0,
        1 << 23,
        1 << 20,
        1 << 10,
        0,
        1 << 24,
        1 << 23,
    ];
    let expected: u128 = values
        .into_iter()
        .map(|value| (value * 256).unsigned_abs().pow(2))
        .sum();
    assert_eq!(
        norm_denominator(&original).expect("original actual norm"),
        expected
    );
    let mut changed = original;
    changed.threshold_max_q24 -= 1;
    assert_ne!(
        norm_denominator(&changed).expect("changed actual norm"),
        expected
    );
}
