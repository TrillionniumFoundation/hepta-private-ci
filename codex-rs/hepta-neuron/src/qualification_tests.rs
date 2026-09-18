use super::*;
use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
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
fn resource_summary_uses_observations_not_configured_targets() {
    let samples = vec![
        NeuronResourceReceiptV1 {
            execution_micros: 10,
            transient_allocation_bytes: 100,
            checkpoint_bytes: 200,
            saturation_count: 0,
            queue_age_micros: 1,
        },
        NeuronResourceReceiptV1 {
            execution_micros: 20,
            transient_allocation_bytes: 150,
            checkpoint_bytes: 250,
            saturation_count: 2,
            queue_age_micros: 3,
        },
    ];
    let summary = checked(summarize_resource_samples(&samples));
    assert_eq!(summary.p95_execution_micros, 20);
    assert_eq!(summary.p99_execution_micros, 20);
    assert_eq!(summary.maximum_saturation_count, 2);
    assert_eq!(summary.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn ablation_fixture_executes_full_and_four_lesions() {
    let receipt = checked(run_ablation_fixture(&config(), &ticks()));
    assert_eq!(receipt.results.len(), 5);
    let full = &receipt.results[0];
    let no_eligibility = receipt
        .results
        .iter()
        .find(|value| value.ablation.no_eligibility)
        .unwrap_or_else(|| panic!("missing eligibility lesion"));
    assert_ne!(
        full.final_eligibility_digest,
        no_eligibility.final_eligibility_digest
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn longitudinal_binding_requires_all_independent_evidence_classes() {
    assert!(LongitudinalEvidenceBindingV1::new(
        digest(b"future"),
        digest(b"retention"),
        digest(b"unlearning"),
        digest(b"evaluator"),
    )
    .is_ok());
    assert_eq!(
        LongitudinalEvidenceBindingV1::new(
            Digest32::ZERO,
            digest(b"retention"),
            digest(b"unlearning"),
            digest(b"evaluator"),
        ),
        Err(QualificationError::InvalidEvidence("future window"))
    );
}
