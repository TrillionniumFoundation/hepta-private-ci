//! Reproducible local engineering measurements, not field efficacy claims.
use super::*;
use crate::LoadedTabularOperatorV1;
use crate::TabularPayloadPinV1;
use crate::encode_tabular_payload_v1;
use std::time::Instant;

fn quantile(values: &mut [u128], percentile: usize) -> u128 {
    values.sort_unstable();
    values[(values.len() * percentile).div_ceil(100).saturating_sub(1)]
}

fn resident_high_water_kib() -> Option<u64> {
    std::fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find(|line| line.starts_with("VmHWM:"))?
        .split_whitespace()
        .nth(1)?
        .parse()
        .ok()
}

fn loaded(model: &TabularOperatorArtifactV1) -> LoadedTabularOperatorV1 {
    let bytes = encode_tabular_payload_v1(model).unwrap();
    let pin = TabularPayloadPinV1 {
        payload_digest: Digest32::of_bytes(&bytes),
        artifact_digest: model.artifact_digest,
        objective_digest: model.objective_digest,
        dataset_digest: model.dataset_digest,
        sensor_core_digest: model.sensor_core_digest,
        training_profile_digest: model.training_profile_digest,
        generation: model.generation,
    };
    LoadedTabularOperatorV1::from_pinned_payload(&bytes, &pin).unwrap()
}

#[test]
#[ignore = "explicit real-filesystem measurement; not a release or field-efficacy gate"]
fn owner_terminal_quality_and_history_profile() {
    let unit = FixedQ32::ONE.raw();
    // A separate authenticated owner supplies held-out observations; none are
    // added to training. Prediction targets/actions are materialized from that
    // owner's Decision/Outcome records by the same typed derivation.
    let heldout_files = support::Fixture::new();
    let mut heldout_owner = heldout_files.writer_with_limit(128);
    for index in 0..16 {
        collect(
            &mut heldout_owner,
            &format!("heldout-read-{index}"),
            "read",
            unit / 2,
        );
        collect(
            &mut heldout_owner,
            &format!("heldout-abstain-{index}"),
            "abstain",
            unit / 4,
        );
    }
    let holdout = freeze_terminal_cell_from_owner_v1(
        &heldout_owner,
        &owner_dataset(&heldout_owner),
        owner_profile(),
        50,
    )
    .unwrap();
    for pairs in [32_usize, 128, 512] {
        let files = support::Fixture::new();
        let capacity = pairs * 4;
        let mut owner = files.writer_with_limit(capacity);
        let mut append_us = Vec::with_capacity(pairs);
        for index in 0..pairs {
            let before = Instant::now();
            let noise = if index % 2 == 0 { unit / 8 } else { -unit / 8 };
            collect(
                &mut owner,
                &format!("train-read-{index}"),
                "read",
                unit / 2 + noise,
            );
            collect(
                &mut owner,
                &format!("train-abstain-{index}"),
                "abstain",
                unit / 4 - noise,
            );
            append_us.push(before.elapsed().as_micros());
        }
        let before = Instant::now();
        let dataset = owner_dataset(&owner);
        let frozen =
            freeze_terminal_cell_from_owner_v1(&owner, &dataset, owner_profile(), 50).unwrap();
        let freeze_us = before.elapsed().as_micros();
        let before = Instant::now();
        let model = fit_terminal_cell_from_owner_v1(&owner, frozen.clone(), 50).unwrap();
        let fit_us = before.elapsed().as_micros();
        let predictor = loaded(&model);
        let mut model_sse = 0_i128;
        let mut baseline_sse = 0_i128;
        for sample in &holdout.plan.samples {
            let value = predictor
                .predict(&sample.sensor_id, &sample.action_id)
                .unwrap();
            let target = i128::from(sample.target.raw());
            let error = i128::from(value.value.raw()) - target;
            model_sse += error * error;
            baseline_sse += target * target;
        }
        assert!(model_sse < baseline_sse);
        let denominator = i128::try_from(holdout.sample_count()).unwrap() * i128::from(unit).pow(2);
        let mut prediction_ns = Vec::with_capacity(1000);
        for _ in 0..1000 {
            let before = Instant::now();
            let value = predictor
                .predict(&id("constant-state"), &id("read"))
                .unwrap();
            assert!(!value.authority.grants_any());
            prediction_ns.push(before.elapsed().as_nanos());
        }
        let frontier = owner.witness_frontier().unwrap();
        drop(owner);
        let before = Instant::now();
        let owner = files.recover_writer(capacity, frontier);
        let recovery_us = before.elapsed().as_micros();
        assert_eq!(
            fit_terminal_cell_from_owner_v1(&owner, frozen, 50).unwrap(),
            model
        );
        let filesystem_bytes: u64 = std::fs::read_dir(&files.root)
            .unwrap()
            .map(|entry| entry.unwrap().metadata().unwrap().len())
            .sum();
        println!(
            "OWNER_TERMINAL_PROFILE {{\"pairs\":{pairs},\"records\":{capacity},\"append_pair_p50_us\":{},\"append_pair_p95_us\":{},\"append_pair_p99_us\":{},\"freeze_us\":{freeze_us},\"fit_us\":{fit_us},\"recovery_us\":{recovery_us},\"prediction_p95_ns\":{},\"prediction_p99_ns\":{},\"filesystem_bytes\":{filesystem_bytes},\"process_peak_rss_kib\":{},\"heldout_samples\":{},\"candidate_mse_ppm\":{},\"zero_baseline_mse_ppm\":{}}}",
            quantile(&mut append_us, 50),
            quantile(&mut append_us, 95),
            quantile(&mut append_us, 99),
            quantile(&mut prediction_ns, 95),
            quantile(&mut prediction_ns, 99),
            resident_high_water_kib().map_or_else(|| "null".to_owned(), |value| value.to_string()),
            holdout.sample_count(),
            model_sse * 1_000_000 / denominator,
            baseline_sse * 1_000_000 / denominator
        );
    }
}
