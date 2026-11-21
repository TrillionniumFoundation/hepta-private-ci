use super::*;
use crate::cell_test_support::checked;
use crate::hcsn_streaming_test_support::fixture;
use crate::restore_hcsn_research_state_v2;
use pretty_assertions::assert_eq;
use serde_json::Value;

#[test]
fn restores_real_python_population_statistics_and_complete_cost() {
    let (context, clock, bytes) = fixture();
    let restored = checked(restore_hcsn_research_state_v2(
        &context,
        &clock,
        &bytes,
        &HcsnStreamingCodecV1,
    ));
    assert_eq!(checked(restored.state.encode()), bytes);
    assert_eq!(restored.state.controller.observations, 2);
    assert_eq!(restored.state.controller.examples, 4);
    assert_eq!(restored.state.controller.solves, 1);
    assert_eq!(restored.state.cost.charged_training_examples, 4);
    assert_eq!(restored.state.cost.charged_encoder_events, 4);
    assert_eq!(restored.state.cost.charged_proposals, 1);
    assert_eq!(restored.state.time_micros(), restored.clock.last_micros());
    assert!(restored.state.cost.elapsed_micros > 0);
}

#[test]
fn rejects_rebound_invalid_density_controller_statistics_and_cost() {
    let (context, clock_bytes, bytes) = fixture();
    let restored = checked(restore_hcsn_research_state_v2(
        &context,
        &clock_bytes,
        &bytes,
        &HcsnStreamingCodecV1,
    ));
    for mutation in [
        "density",
        "time",
        "controller",
        "history",
        "indefinite",
        "cost",
        "optimizer",
    ] {
        let mut snapshot = restored.state.snapshot.clone();
        match mutation {
            "density" | "time" => {
                let mut value: Value = checked(serde_json::from_slice(&snapshot.backend));
                if mutation == "density" {
                    value["density"]["bits"][0] = Value::from(20_f64.to_bits());
                } else {
                    value["time_micros"] = Value::from(0);
                }
                snapshot.backend = checked(serde_json::to_vec(&value));
            }
            "controller" => {
                let mut value: Value = checked(serde_json::from_slice(&snapshot.controller));
                value["observations"] = Value::from(99);
                snapshot.controller = checked(serde_json::to_vec(&value));
            }
            "history" => {
                let mut value: Value = checked(serde_json::from_slice(&snapshot.history));
                let count = checked(value["gram"]["bits"].as_array().ok_or("bits")).len();
                value["gram"]["bits"][count - 1] = Value::from(0);
                snapshot.history = checked(serde_json::to_vec(&value));
            }
            "indefinite" => {
                let mut value: Value = checked(serde_json::from_slice(&snapshot.history));
                let width = restored.state.features + 1;
                let mut bits = vec![0_u64; width * width];
                for row in 0..width {
                    bits[row * width + row] = 1_f64.to_bits();
                }
                bits[1] = 2_f64.to_bits();
                bits[width] = 2_f64.to_bits();
                bits[width * width - 1] = (restored.state.controller.examples as f64).to_bits();
                value["gram"]["bits"] = checked(serde_json::to_value(bits));
                snapshot.history = checked(serde_json::to_vec(&value));
            }
            "cost" => snapshot.cost_ledger = b"{}".to_vec(),
            "optimizer" => snapshot.optimizer = HcsnOptimizerStateV2::Snapshot(vec![1]),
            _ => panic!("unknown mutation"),
        }
        let clock = checked(HcsnClockCheckpointV1::initial(
            &context.profile,
            context.identity,
            restored.clock.last_micros(),
            Digest32::of_bytes(&checked(snapshot.encode())),
        ));
        assert_eq!(
            HcsnStreamingCodecV1
                .restore_complete_state(&snapshot, &clock, &context.profile)
                .err(),
            Some(HcsnRecoveryErrorV2::Backend),
            "{mutation}"
        );
    }
}

#[test]
fn restoring_state_cannot_relabel_the_renewal_law_or_clock_profile() {
    let (mut context, clock_bytes, bytes) = fixture();
    let restored = checked(restore_hcsn_research_state_v2(
        &context,
        &clock_bytes,
        &bytes,
        &HcsnStreamingCodecV1,
    ));
    context.profile.integration = HcsnIntegrationV1::PopulationAge {
        max_step_micros: 25_000,
        max_substeps: 40,
    };
    assert_eq!(
        HcsnStreamingCodecV1
            .restore_complete_state(&restored.state.snapshot, &restored.clock, &context.profile)
            .err(),
        Some(HcsnRecoveryErrorV2::Backend)
    );
}
