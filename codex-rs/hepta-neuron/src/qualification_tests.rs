use super::*;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: digest(b"model"),
        normalization_digest: digest(b"normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![crate::InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q / 2,
        }],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn ticks() -> Vec<SparseTick> {
    (1..=4)
        .map(|sequence| SparseTick {
            scope_digest: digest(b"scope"),
            objective_digest: digest(b"objective"),
            ndu_digest: digest(b"ndu"),
            body_digest: digest(b"body"),
            input_digest: digest(format!("input:{sequence}").as_bytes()),
            sequence,
            monotonic_micros: sequence * 1_000,
            drive_q24: if sequence.is_multiple_of(2) {
                vec![0, Q, 0, 0, 0]
            } else {
                vec![Q, Q / 2, 0, 0, 0]
            },
            prediction_q24: vec![0; 5],
        })
        .collect()
}

#[test]
fn ablation_fixture_executes_full_and_four_lesions() {
    let receipt = checked(run_ablation_fixture(&config(), &ticks()));
    assert_eq!(receipt.results.len(), 5);
    let full = &receipt.results[0];
    let no_eligibility = match receipt
        .results
        .iter()
        .find(|value| value.ablation.no_eligibility)
    {
        Some(value) => value,
        None => panic!("missing eligibility lesion"),
    };
    assert_ne!(
        full.final_eligibility_digest,
        no_eligibility.final_eligibility_digest
    );
    assert_ne!(receipt.receipt_digest, Digest32::ZERO);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn longitudinal_binding_requires_preregistration_and_all_evidence_classes() {
    let binding = checked(LongitudinalEvidenceBindingV1::new(
        digest(b"preregistered-plan"),
        digest(b"future"),
        digest(b"retention"),
        digest(b"unlearning"),
        digest(b"evaluator"),
    ));
    assert_ne!(binding.binding_digest, Digest32::ZERO);
    assert_eq!(binding.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        LongitudinalEvidenceBindingV1::new(
            Digest32::ZERO,
            digest(b"future"),
            digest(b"retention"),
            digest(b"unlearning"),
            digest(b"evaluator"),
        ),
        Err(QualificationError::InvalidEvidence("preregistration"))
    );
}
