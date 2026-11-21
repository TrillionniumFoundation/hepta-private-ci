//! Concrete CPU-FP64 BatchedFlow/ridge state codec. Numerical continuation runs
//! in the named PyTorch backend; Rust reconstructs and validates every state
//! section before a host dispatches those exact bytes. No sparse/Q24 migration.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use crate::HcsnClockCheckpointV1;
use crate::HcsnClockIdentityV1;
use crate::HcsnIntegrationV1;
use crate::HcsnOptimizerStateV2;
use crate::HcsnRecoveryErrorV2;
use crate::HcsnResearchStateCodecV2;
use crate::HcsnResearchStateV2;
use crate::HcsnStreamingCostV1;
use crate::HcsnTimeProfileV1;
use crate::hcsn_streaming_cost::validate_cost;

const SCHEMA: &str = "hepta.hcsn.streaming-ridge-state.v1.cpu-f64.erlang.population";

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct Tensor {
    pub shape: Vec<usize>,
    pub bits: Vec<u64>,
}

impl Tensor {
    pub(crate) fn values(&self, shape: &[usize]) -> Result<Vec<f64>, HcsnRecoveryErrorV2> {
        let count = shape
            .iter()
            .try_fold(1_usize, |a, b| a.checked_mul(*b))
            .ok_or(HcsnRecoveryErrorV2::Backend)?;
        if self.shape != shape || self.bits.len() != count || count > 4_000_000 {
            return Err(HcsnRecoveryErrorV2::Backend);
        }
        let values: Vec<_> = self
            .bits
            .iter()
            .map(|value| f64::from_bits(*value))
            .collect();
        if values.iter().any(|value| !value.is_finite()) {
            return Err(HcsnRecoveryErrorV2::Backend);
        }
        Ok(values)
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Config {
    input_size: usize,
    content_size: usize,
    bins: usize,
    stages: usize,
    max_batch: usize,
    extent: f64,
    dt: f64,
    sigma: f64,
    base_drift: f64,
    drift_scale: f64,
    reset_margin: f64,
    refractory: f64,
    discount: f64,
    gain: f64,
    maintenance: f64,
    spike_cost: f64,
    write_fraction: f64,
    boundary_limit: f64,
    drift_limit: f64,
    upper_mode: String,
    transport_precision: String,
}

impl Config {
    fn validate(&self) -> Result<(), HcsnRecoveryErrorV2> {
        if !(1..=256).contains(&self.input_size)
            || !(1..=64).contains(&self.content_size)
            || !(2..=64).contains(&self.bins)
            || !(1..=128).contains(&self.stages)
            || !(1..=256).contains(&self.max_batch)
            || [
                self.extent,
                self.dt,
                self.sigma,
                self.base_drift,
                self.drift_scale,
                self.reset_margin,
                self.refractory,
                self.discount,
                self.gain,
                self.maintenance,
                self.spike_cost,
                self.write_fraction,
                self.boundary_limit,
                self.drift_limit,
            ]
            .iter()
            .any(|v| !v.is_finite())
            || [
                self.extent,
                self.dt,
                self.sigma,
                self.refractory,
                self.discount,
                self.boundary_limit,
                self.drift_limit,
            ]
            .iter()
            .any(|v| *v <= 0.0)
            || self.drift_scale < 0.0
            || self.base_drift.abs() + self.drift_scale > self.drift_limit
            || !(0.0..=1.0).contains(&self.write_fraction)
            || self.reset_margin <= self.extent / (2 * self.bins) as f64
            || self.reset_margin >= self.extent * (1.0 - 1.0 / (2 * self.bins) as f64)
            || !["absorbing", "reflecting"].contains(&self.upper_mode.as_str())
            || !["native", "float64"].contains(&self.transport_precision.as_str())
        {
            return Err(HcsnRecoveryErrorV2::Backend);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(crate) struct Parameters {
    pub flow: BTreeMap<String, Tensor>,
    pub readout: BTreeMap<String, Tensor>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Backend {
    schema: String,
    config: Config,
    batch: usize,
    output_size: usize,
    density: Tensor,
    boundary: Tensor,
    time_micros: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Controller {
    rule: String,
    pub ridge: f64,
    pub observations: u64,
    pub examples: u64,
    pub solves: u64,
    pub discarded_observations: u64,
    pub discarded_examples: u64,
    pub discarded_solves: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct Rng {
    kind: String,
    reason: String,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct History {
    kind: String,
    gram: Tensor,
    cross: Tensor,
    past_autograd_retained: bool,
}

/// A fully decoded concrete backend state, retaining the original IEEE tensor
/// bits, cost journal and metadata for an exact handoff to its numerical worker.
#[derive(Clone, Debug)]
pub struct HcsnStreamingStateV1 {
    pub(crate) snapshot: HcsnResearchStateV2,
    pub(crate) parameters: Parameters,
    pub(crate) controller: Controller,
    pub(crate) gram: Vec<f64>,
    pub(crate) cross: Vec<f64>,
    pub(crate) features: usize,
    pub(crate) outputs: usize,
    cost: HcsnStreamingCostV1,
    clock: HcsnClockCheckpointV1,
    profile: HcsnTimeProfileV1,
}

impl HcsnStreamingStateV1 {
    /// Exact admitted bytes, including full phase populations and learning state.
    pub fn encode(&self) -> Result<Vec<u8>, HcsnRecoveryErrorV2> {
        self.snapshot.encode()
    }

    pub fn cost(&self) -> &HcsnStreamingCostV1 {
        &self.cost
    }

    pub fn clock_identity(&self) -> HcsnClockIdentityV1 {
        self.clock.identity()
    }

    pub fn time_micros(&self) -> u64 {
        self.clock.last_micros()
    }

    pub fn clock_digest(&self) -> Digest32 {
        self.clock.digest()
    }

    pub(crate) fn revalidate(&self) -> Result<Self, HcsnRecoveryErrorV2> {
        HcsnStreamingCodecV1.restore_complete_state(&self.snapshot, &self.clock, &self.profile)
    }
}

#[derive(Clone, Copy, Debug, Default)]
pub struct HcsnStreamingCodecV1;

impl HcsnResearchStateCodecV2 for HcsnStreamingCodecV1 {
    type State = HcsnStreamingStateV1;

    fn schema_digest(&self) -> Digest32 {
        Digest32::of_bytes(SCHEMA.as_bytes())
    }

    fn restore_complete_state(
        &self,
        snapshot: &HcsnResearchStateV2,
        clock: &HcsnClockCheckpointV1,
        profile: &HcsnTimeProfileV1,
    ) -> Result<Self::State, HcsnRecoveryErrorV2> {
        let invalid = HcsnRecoveryErrorV2::Backend;
        let verified_clock = HcsnClockCheckpointV1::restore(
            profile,
            clock.identity(),
            &clock.encode().map_err(|_| invalid)?,
            clock.digest(),
        )
        .map_err(|_| invalid)?;
        let parameters: Parameters =
            serde_json::from_slice(&snapshot.parameters).map_err(|_| invalid)?;
        let backend: Backend = serde_json::from_slice(&snapshot.backend).map_err(|_| invalid)?;
        let controller: Controller =
            serde_json::from_slice(&snapshot.controller).map_err(|_| invalid)?;
        let rng: Rng = serde_json::from_slice(&snapshot.rng).map_err(|_| invalid)?;
        let history: History = serde_json::from_slice(&snapshot.history).map_err(|_| invalid)?;
        if Digest32::of_bytes(&snapshot.encode()?) != clock.state_digest()
            || Digest32::of_bytes(&snapshot.parameters) != clock.identity().model_digest
            || snapshot.binding.backend_state_schema_digest != self.schema_digest()
        {
            return Err(invalid);
        }
        let mut mask = b"hepta.hcsn.parameter-mask.v2\0".to_vec();
        for name in ["readout.bias", "readout.weight"] {
            mask.extend_from_slice(&(name.len() as u64).to_be_bytes());
            mask.extend_from_slice(name.as_bytes());
        }
        backend.config.validate()?;
        let c = &backend.config;
        let features = c.content_size + 5;
        let size = c.bins + c.stages + 1;
        // Grid admission remains the native owner's responsibility. This codec
        // verifies the recovered final clock, not a fabricated execution receipt.
        let on_grid = match profile.integration {
            HcsnIntegrationV1::PopulationGrid { step_micros, .. } => {
                step_micros != 0 && backend.time_micros.is_multiple_of(step_micros)
            }
            HcsnIntegrationV1::ValueKernel | HcsnIntegrationV1::PopulationAge { .. } => false,
        };
        if backend.schema != SCHEMA
            || snapshot.optimizer != HcsnOptimizerStateV2::NotUsed
            || snapshot.binding.learning_rule_digest
                != Digest32::of_bytes(b"hepta.hcsn.learning-rule.closed-form-readout.v1")
            || snapshot.binding.parameter_mask_digest != Digest32::of_bytes(&mask)
            || backend.time_micros != clock.last_micros()
            || backend.time_micros >= 1_u64 << 63
            || !on_grid
            || !(1..=c.max_batch).contains(&backend.batch)
            || !(1..=64).contains(&backend.output_size)
            || controller.rule != "closed_form_readout"
            || !controller.ridge.is_finite()
            || controller.ridge <= 0.0
            || rng.kind != "not_used"
            || rng.reason != "deterministic_frozen_encoder_and_ridge"
            || history.kind != "ridge_sufficient_statistics"
            || history.past_autograd_retained
            || [
                controller.observations,
                controller.examples,
                controller.solves,
                controller.discarded_observations,
                controller.discarded_examples,
                controller.discarded_solves,
            ]
            .iter()
            .any(|n| *n >= 1_u64 << 53)
            || controller.examples
                > controller
                    .observations
                    .checked_mul(backend.batch as u64)
                    .ok_or(invalid)?
            || !controller.examples.is_multiple_of(backend.batch as u64)
        {
            return Err(invalid);
        }
        let expected_flow = [
            ("drive.bias", vec![1]),
            ("drive.weight", vec![1, c.input_size]),
            ("writer.bias", vec![c.content_size]),
            ("writer.weight", vec![c.content_size, c.input_size]),
        ];
        if parameters.flow.len() != expected_flow.len() || parameters.readout.len() != 2 {
            return Err(invalid);
        }
        for (name, shape) in expected_flow {
            parameters.flow.get(name).ok_or(invalid)?.values(&shape)?;
        }
        parameters
            .readout
            .get("weight")
            .ok_or(invalid)?
            .values(&[backend.output_size, features])?;
        parameters
            .readout
            .get("bias")
            .ok_or(invalid)?
            .values(&[backend.output_size])?;
        let density = backend
            .density
            .values(&[backend.batch, 1 + c.content_size, size])?;
        let boundary = backend.boundary.values(&[backend.batch])?;
        for (batch, values) in density
            .chunks_exact((1 + c.content_size) * size)
            .enumerate()
        {
            let probability = &values[..size];
            if (probability.iter().sum::<f64>() - 1.0).abs() > 1e-10
                || probability.iter().any(|value| *value < -1e-10)
                || boundary[batch].abs() > c.boundary_limit
            {
                return Err(invalid);
            }
            for content in values.chunks_exact(size).skip(1) {
                if content
                    .iter()
                    .zip(probability)
                    .any(|(value, p)| value.abs() > p + 1e-10)
                {
                    return Err(invalid);
                }
            }
            if c.upper_mode == "reflecting"
                && values
                    .chunks_exact(size)
                    .any(|part| part[size - 1].abs() > 1e-10)
            {
                return Err(invalid);
            }
        }
        let width = features + 1;
        let gram = history.gram.values(&[width, width])?;
        let cross = history.cross.values(&[width, backend.output_size])?;
        if gram[width * width - 1] != controller.examples as f64 {
            return Err(invalid);
        }
        for row in 0..width {
            if gram[row * width + row] < 0.0 {
                return Err(invalid);
            }
            for col in 0..row {
                if gram[row * width + col] != gram[col * width + row] {
                    return Err(invalid);
                }
            }
        }
        if controller.examples == 0 {
            if gram.iter().chain(&cross).any(|value| *value != 0.0) {
                return Err(invalid);
            }
        } else {
            let mut lower = vec![0.0_f64; width * width];
            for row in 0..width {
                for col in 0..=row {
                    let mut value = gram[row * width + col]
                        + if row == col && col != features {
                            controller.ridge
                        } else {
                            0.0
                        };
                    for k in 0..col {
                        value -= lower[row * width + k] * lower[col * width + k];
                    }
                    if !value.is_finite() || (row == col && value <= 0.0) {
                        return Err(invalid);
                    }
                    lower[row * width + col] = if row == col {
                        value.sqrt()
                    } else {
                        value / lower[col * width + col]
                    };
                }
            }
        }
        let cost = validate_cost(
            &snapshot.cost_ledger,
            snapshot.binding.request_digest,
            &controller,
            backend.batch as u64,
        )?;
        Ok(HcsnStreamingStateV1 {
            snapshot: snapshot.clone(),
            parameters,
            controller,
            gram,
            cross,
            features,
            outputs: backend.output_size,
            cost,
            clock: verified_clock,
            profile: *profile,
        })
    }
}

#[cfg(test)]
#[path = "hcsn_streaming_tests.rs"]
mod tests;
