use super::*;

use crate::InhibitoryEdge;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn envelope() -> NeuronResourceEnvelopeV1 {
    NeuronResourceEnvelopeV1 {
        p95_latency_micros: 95,
        p99_latency_micros: 99,
        transient_allocation_bytes: 512 * 1024,
        checkpoint_bytes: 1024 * 1024,
        write_amplification_ppm: 4_000_000,
    }
}

fn sample(index: u64) -> NeuronResourceSampleV1 {
    NeuronResourceSampleV1 {
        host_profile_digest: Digest32::of_bytes(b"host-profile"),
        exact_candidate_digest: Digest32::of_bytes(b"candidate"),
        observed_at_micros: index + 1,
        receipt: NeuronResourceReceiptV1 {
            execution_micros: index + 1,
            transient_allocation_bytes: 32 * 1024,
            checkpoint_bytes: 512,
            journal_bytes_written: 384,
            write_amplification_ppm: 750_000,
            saturation_count: 0,
            queue_age_micros: 1,
        },
    }
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"model"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![InhibitoryEdge {
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

#[test]
fn supplied_resource_samples_have_deterministic_percentiles_without_claiming_authority() {
    let samples = (0..100).map(sample).collect::<Vec<_>>();
    let summary = checked(summarize_resource_samples(&samples, &envelope()));
    assert_eq!(summary.p95_execution_micros, 95);
    assert_eq!(summary.p99_execution_micros, 99);
    assert!(summary.pilot_ceiling_passed_for_supplied_samples);
    assert_eq!(summary.sample_count, 100);
    assert!(!summary.sample_set_digest.is_zero());
    assert!(!summary.authority.grants_any());
}

#[test]
fn resource_summary_rejects_mixed_host_profiles() {
    let mut samples = vec![sample(0), sample(1)];
    samples[1].host_profile_digest = Digest32::of_bytes(b"other-host");
    assert_eq!(
        summarize_resource_samples(&samples, &envelope()),
        Err(QualificationError::MixedHostProfile)
    );
}

#[test]
fn config_ablations_remove_only_the_named_mechanism() {
    let full = config();
    let no_inhibition =
        ablate_sparse_config(&full, NeuronAblationProfileV1::NoInhibition);
    assert!(no_inhibition.inhibition.is_empty());
    assert_eq!(no_inhibition.inhibition_gain_q24, 0);
    assert_eq!(no_inhibition.temporal_decay_q24, full.temporal_decay_q24);

    let no_homeostasis =
        ablate_sparse_config(&full, NeuronAblationProfileV1::NoHomeostasis);
    assert_eq!(no_homeostasis.threshold_rate_q24, 0);
    assert_eq!(no_homeostasis.inhibition, full.inhibition);

    let stateless =
        ablate_sparse_config(&full, NeuronAblationProfileV1::StatelessTemporal);
    assert_eq!(stateless.temporal_decay_q24, 0);
    assert_eq!(stateless.inhibition, full.inhibition);
}

#[test]
fn eligibility_and_modulator_ablations_are_explicit_and_deterministic() {
    let history = vec![EligibilityTraceSampleV1 {
        checkpoint_digest: Digest32::of_bytes(b"checkpoint"),
        eligibility_q24: vec![Q / 2, -Q / 4],
    }];
    let no_eligibility =
        ablate_eligibility_history(&history, NeuronAblationProfileV1::NoEligibility);
    assert_eq!(no_eligibility[0].eligibility_q24, vec![0, 0]);
    assert_eq!(history[0].eligibility_q24, vec![Q / 2, -Q / 4]);

    let groups = vec![
        ParameterGroupMapV1 {
            group_id: checked(StableId::new("a")),
            eligibility_projection_q24: vec![Q, 0],
            modulator_projection_q24: vec![Q, 0],
        },
        ParameterGroupMapV1 {
            group_id: checked(StableId::new("b")),
            eligibility_projection_q24: vec![0, Q],
            modulator_projection_q24: vec![0, Q],
        },
    ];
    let shuffled = checked(ablate_parameter_groups(
        &groups,
        NeuronAblationProfileV1::ShuffledModulator,
    ));
    assert_eq!(
        shuffled[0].modulator_projection_q24,
        groups[1].modulator_projection_q24
    );
    assert_eq!(
        shuffled[1].modulator_projection_q24,
        groups[0].modulator_projection_q24
    );
    assert!(requires_external_replay_ablation(
        NeuronAblationProfileV1::NoReplay
    ));
}
