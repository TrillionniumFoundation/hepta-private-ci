//! Actual fixed-arm control work. This is a fresh, bounded self-distillation
//! computation on the existing baseline, not an invented pretraining history
//! or a reconstructed native Training receipt. Its Generator signs this DATA
//! as part of the original comparison plan.
#![cfg(test)]

use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronFeatureTerminalStatusV1;
use codex_hepta_neuron::NeuronFeatureWorkerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;

use super::super::post_a_plan::EPOCHS;
use super::super::post_a_plan::LEARNING_RATE_Q24;
use super::business;

const Q: i64 = 1 << 24;

#[derive(Clone, Serialize)]
pub(super) struct ArmData {
    pub(super) total_parameters: u64,
    pub(super) trainable_parameters: u64,
    pub(super) maximum_active_parameters: u64,
    pub(super) examples_seen: u64,
    pub(super) optimizer_steps: u64,
    pub(super) parameter_updates: u64,
    pub(super) compute_units: u64,
    pub(super) compute_unit_contract: [u8; 32],
    pub(super) update_policy: [u8; 32],
    pub(super) update_eligibility: [u8; 32],
    pub(super) update_schedule: [u8; 32],
    pub(super) maximum_parameters_per_step: u64,
    pub(super) structure_before: [u8; 32],
    pub(super) structure_after: [u8; 32],
}

pub(super) struct FixedControlData {
    pub(super) arm: ArmData,
    pub(super) receipt: [u8; 32],
}

/// A prospective one-row, native SGD declaration for this ordinary fixture.
/// It is computed independently of the fixed control's result. Root must
/// match it to the actual signed Training preimage before any B execution.
pub(super) fn declare_candidate(
    model_directory: &Path,
    structure: [u8; 32],
) -> anyhow::Result<ArmData> {
    let (model, bundle, _) = super::super::super::material::load(model_directory)?;
    let mut total_parameters = 0_u64;
    let mut head_width = None;
    for (name, expected) in [
        ("base", bundle.components.base),
        ("encoder", bundle.components.encoder),
        ("heads", bundle.components.heads),
    ] {
        let bytes = std::fs::read(model_directory.join(name))?;
        anyhow::ensure!(
            bytes.len() >= 12
                && &bytes[..8] == b"HQ24M001"
                && Digest32::of_bytes(&bytes) == expected,
            "actual baseline matrix bytes required for the candidate declaration"
        );
        let rows = u64::from(u16::from_le_bytes(bytes[8..10].try_into()?));
        let cols = u64::from(u16::from_le_bytes(bytes[10..12].try_into()?));
        anyhow::ensure!(
            rows > 0 && cols > 0 && bytes.len() as u64 == 12 + 8 * rows * cols,
            "original candidate matrix dimensions"
        );
        total_parameters += rows * cols;
        if name == "heads" {
            head_width = Some(cols);
        }
    }
    anyhow::ensure!(
        bundle.components.organ_adapter.is_none()
            && bundle.components.cell_adapter.is_none()
            && model.components() == &bundle.components,
        "this fixture declares only its actual three-matrix baseline"
    );
    let width = head_width.ok_or_else(|| anyhow::anyhow!("original head matrix absent"))?;
    let examples_seen = 1; // The ordinary A fixture submits exactly one frozen row.
    let optimizer_steps = examples_seen * u64::from(EPOCHS);
    let updates = optimizer_steps * width;
    let (compute, policy, eligibility, schedule) = work_contract();
    Ok(ArmData {
        total_parameters,
        trainable_parameters: width,
        maximum_active_parameters: total_parameters,
        examples_seen,
        optimizer_steps,
        parameter_updates: updates,
        compute_units: updates,
        compute_unit_contract: compute.into_array(),
        update_policy: policy.into_array(),
        update_eligibility: eligibility.into_array(),
        update_schedule: schedule.into_array(),
        maximum_parameters_per_step: width,
        structure_before: structure,
        structure_after: structure,
    })
}

fn work_contract() -> (Digest32, Digest32, Digest32, Digest32) {
    crate::cell_composed_q24::original_q24_work_contract(
        crate::CellQ24PrivateHeadV1::Drive { index: 0 },
        crate::CellQ24SgdRuleV1 {
            epochs: EPOCHS,
            learning_rate_q24: LEARNING_RATE_Q24,
        },
    )
}

pub(super) fn execute(
    model_directory: &Path,
    evidence_directory: &Path,
    input: &[u8],
    structure: [u8; 32],
    end: Instant,
) -> anyhow::Result<FixedControlData> {
    let started = Instant::now();
    let (model, bundle, definition) = super::super::super::material::load(model_directory)?;
    let identity = |rows: u16, values: &[i64]| {
        let mut bytes = b"HQ24M001".to_vec();
        bytes.extend_from_slice(&rows.to_le_bytes());
        bytes.extend_from_slice(&2_u16.to_le_bytes());
        for value in values {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes
    };
    // The pre-existing ordinary baseline is exactly this two-wide graph.
    // Checking its actual bytes makes its first two native drive coordinates
    // the original hidden features, without inventing a hidden-state API.
    let base = std::fs::read(model_directory.join("base"))?;
    let encoder = std::fs::read(model_directory.join("encoder"))?;
    let heads = std::fs::read(model_directory.join("heads"))?;
    anyhow::ensure!(
        base == identity(2, &[Q, 0, 0, Q])
            && encoder == base
            && heads
                == identity(
                    10,
                    &[Q, 0, 0, Q, 0, 0, 0, 0, 0, 0, Q, 0, 0, Q, 0, 0, 0, 0, 0, 0]
                ),
        "fixed control requires the actual original identity baseline"
    );
    anyhow::ensure!(
        input.len() == 26 && &input[..8] == b"HQ24I001" && input[8..10] == 2_u16.to_le_bytes(),
        "fixed control input shape"
    );
    let features = input[10..]
        .chunks_exact(8)
        .map(|bytes| <[u8; 8]>::try_from(bytes).map(i64::from_le_bytes))
        .collect::<Result<Vec<_>, _>>()?;
    let worker = crate::CellQ24FeatureWorkerV1::new(Arc::clone(&model), &bundle, &definition)?;
    let target = Q; // Predeclared self-distillation target, not a B business label.
    let mut weights = [Q, 0];
    let before = weights;
    let mut steps = 0_u64;
    let mut updates = 0_u64;
    let mut native_observations = Vec::new();
    for epoch in 0..EPOCHS {
        anyhow::ensure!(Instant::now() < end, "original fixed control end");
        let observed = worker.execute(&NeuronFeatureRequestV1 {
            request_id: StableId::new(format!("original-fixed-control-{epoch}"))?,
            generation: bundle.generation,
            model_id: bundle.artifact_id.clone(),
            encoder_digest: bundle.components.encoder,
            head_digest: bundle.components.heads,
            weights_digest: model.effective_weights_digest(),
            input_digest: Digest32::of_bytes(input),
            feature_vector_q24: features.clone(),
            expected_output_width: model.output_width(),
        })?;
        anyhow::ensure!(
            observed.status == NeuronFeatureTerminalStatusV1::Succeeded
                && observed.drive_q24.len() >= 2,
            "actual fixed-arm native forward required"
        );
        let hidden = &observed.drive_q24[..2];
        let prediction = (weights
            .iter()
            .zip(hidden)
            .map(|(weight, value)| i128::from(*weight) * i128::from(*value))
            .sum::<i128>()
            / i128::from(Q))
        .clamp(-8 * i128::from(Q), 8 * i128::from(Q));
        let error = prediction - i128::from(target);
        for (weight, value) in weights.iter_mut().zip(hidden) {
            let delta = i128::from(LEARNING_RATE_Q24) * error * i128::from(*value)
                / (i128::from(Q) * i128::from(Q));
            *weight =
                (i128::from(*weight) - delta).clamp(-8 * i128::from(Q), 8 * i128::from(Q)) as i64;
            updates += 1;
        }
        steps += 1;
        native_observations.push((
            observed.drive_q24,
            observed.prediction_q24,
            observed.queue_age_micros,
            observed.latency_micros,
            observed.observed_memory_bytes,
            observed.transient_allocation_bytes,
        ));
        anyhow::ensure!(
            weights == before,
            "fixed baseline control changed the original model"
        );
    }
    let (compute, policy, eligibility, schedule) = work_contract();
    let total_parameters = ((base.len() + encoder.len() + heads.len() - 36) / 8) as u64;
    let arm = ArmData {
        total_parameters,
        trainable_parameters: weights.len() as u64,
        maximum_active_parameters: total_parameters,
        examples_seen: 1,
        optimizer_steps: steps,
        parameter_updates: updates,
        compute_units: updates,
        compute_unit_contract: compute.into_array(),
        update_policy: policy.into_array(),
        update_eligibility: eligibility.into_array(),
        update_schedule: schedule.into_array(),
        maximum_parameters_per_step: weights.len() as u64,
        structure_before: structure,
        structure_after: structure,
    };
    let bytes = serde_json::to_vec(&(
        "ordinary-original-fixed-control-observation-v1",
        bundle.digest()?.into_array(),
        Digest32::of_bytes(input).into_array(),
        target,
        before,
        weights,
        &arm,
        native_observations,
        started.elapsed().as_micros(),
        business::now()?,
    ))?;
    business::write_once(
        &evidence_directory.join("original-fixed-control.data"),
        &bytes,
    )?;
    anyhow::ensure!(
        std::fs::read(model_directory.join("base"))? == base
            && std::fs::read(model_directory.join("encoder"))? == encoder
            && std::fs::read(model_directory.join("heads"))? == heads
            && Instant::now() < end,
        "original fixed baseline changed or end elapsed"
    );
    Ok(FixedControlData {
        arm,
        receipt: Digest32::of_bytes(&bytes).into_array(),
    })
}
