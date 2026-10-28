//! Typed bounded continuous signals consumed by the unchanged native sparse kernel.
use crate::Q;
use crate::Result;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Continuous {
    pub margin_q24: i64,
    pub risk_q24: i64,
    pub flow_q24: i64,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Features {
    pub raw_q24: Vec<i64>,
    pub continuous: Continuous,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Kernel {
    pub width: usize,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Stage {
    Transform,
    Act,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub schema: String,
    pub profile_id: String,
    pub source_model_digest: String,
    pub objective_digest: String,
    pub arm_id: String,
    pub stage: Stage,
    pub feature_names: Vec<String>,
    pub use_margin: bool,
    pub use_risk: bool,
    pub use_flow: bool,
    pub kernel: Kernel,
    pub encoder_weights_q24: Vec<Vec<i64>>,
    pub encoder_bias_q24: Vec<i64>,
    pub head_weights_q24: Vec<Vec<i64>>,
    pub head_bias_q24: Vec<i64>,
    pub risk_ceiling_q24: i64,
    pub maximum_ticks: u64,
    pub tick_micros: u64,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Readout {
    pub scores_q24: Vec<i64>,
    pub action: String,
    pub tie: bool,
    pub native_ndu_digest: String,
    pub native_ndu_frontier: Vec<String>,
}

pub fn mul(a: i64, b: i64) -> i64 {
    let p = i128::from(a) * i128::from(b);
    let q = p.abs() / i128::from(Q);
    let r = p.abs() % i128::from(Q);
    let up = r * 2 > i128::from(Q) || (r * 2 == i128::from(Q) && q % 2 != 0);
    ((q + i128::from(up)) * p.signum()) as i64
}
impl Profile {
    pub fn validate(&self) -> Result<()> {
        if self.schema != "hepta.continuous-boundary.native-profile.v1"
            || self.profile_id.is_empty()
            || self.arm_id.is_empty()
            || self.feature_names.is_empty()
            || self.feature_names.len() > 32
            || self.maximum_ticks == 0
            || self.maximum_ticks > 512
            || self.tick_micros == 0
            || self.tick_micros > 1_000_000_000
            || self.risk_ceiling_q24 != Q
        {
            return Err("Invalid bounded native profile".into());
        }
        let d = self.feature_names.len() + 3;
        let w = self.kernel.width;
        for s in [&self.source_model_digest, &self.objective_digest] {
            if s.parse::<Digest32>()?.is_zero() {
                return Err("Missing source/objective digest".into());
            }
        }
        StableId::new(&self.profile_id)?;
        StableId::new(&self.arm_id)?;
        if self.encoder_weights_q24.len() != w
            || self.encoder_bias_q24.len() != w
            || self.head_weights_q24.len() != 3
            || self.head_bias_q24.len() != 3
            || self.encoder_weights_q24.iter().any(|row| row.len() != d)
            || self.head_weights_q24.iter().any(|row| row.len() != w)
            || self
                .encoder_weights_q24
                .iter()
                .flatten()
                .chain(self.head_weights_q24.iter().flatten())
                .chain(&self.encoder_bias_q24)
                .chain(&self.head_bias_q24)
                .any(|x| !(-8 * Q..=8 * Q).contains(x))
        {
            return Err("Invalid encoder/head shape or coefficients".into());
        }
        if self.head_bias_q24[2] != 0 || self.head_weights_q24[2].iter().any(|x| *x != 0) {
            return Err(
                "Task stop payoff is exactly zero; its native abstain head is fixed".into(),
            );
        }
        self.native(Digest32::of_bytes(b"profile-validation"))?
            .digest()?;
        Ok(())
    }
    pub fn feature_vector(&self, x: &Features) -> Result<Vec<i64>> {
        if x.raw_q24.len() != self.feature_names.len()
            || x.raw_q24.iter().any(|v| !(-8 * Q..=8 * Q).contains(v))
            || !(-8 * Q..=8 * Q).contains(&x.continuous.margin_q24)
            || !(-8 * Q..=8 * Q).contains(&x.continuous.flow_q24)
            || !(0..=Q).contains(&x.continuous.risk_q24)
        {
            return Err("Continuous feature domain violation".into());
        }
        let mut f = x.raw_q24.clone();
        f.extend([
            x.continuous.margin_q24,
            x.continuous.risk_q24,
            x.continuous.flow_q24,
        ]);
        Ok(f)
    }
    pub fn encode(&self, raw: &[i64]) -> Result<Vec<i64>> {
        if raw.len() != self.feature_names.len() + 3
            || raw.iter().any(|x| !(-8 * Q..=8 * Q).contains(x))
            || !(0..=Q).contains(&raw[self.feature_names.len() + 1])
        {
            return Err("Feature encoding domain mismatch".into());
        }
        let mut x = raw.to_vec();
        let d = self.feature_names.len();
        for (i, enabled) in [self.use_margin, self.use_risk, self.use_flow]
            .iter()
            .enumerate()
        {
            if !enabled {
                x[d + i] = 0;
            }
        }
        Ok(self
            .encoder_weights_q24
            .iter()
            .zip(&self.encoder_bias_q24)
            .map(|(row, bias)| {
                row.iter()
                    .zip(&x)
                    .fold(*bias, |sum, (w, v)| sum + mul(*w, *v))
                    .clamp(-8 * Q, 8 * Q)
            })
            .collect())
    }
    pub fn scores(&self, activation: &[i64]) -> Result<Vec<i64>> {
        if activation.len() != self.kernel.width
            || activation.iter().any(|x| !(0..=8 * Q).contains(x))
        {
            return Err("Readout requires actual bounded sparse activation".into());
        }
        Ok(self
            .head_weights_q24
            .iter()
            .zip(&self.head_bias_q24)
            .map(|(row, bias)| {
                row.iter()
                    .zip(activation)
                    .fold(*bias, |sum, (w, v)| sum + mul(*w, *v))
            })
            .collect())
    }
    pub fn native(&self, bundle: Digest32) -> Result<SparseConfig> {
        let k = &self.kernel;
        Ok(SparseConfig {
            model_digest: bundle,
            normalization_digest: Digest32::of_bytes(b"continuous-feature-q24.v1"),
            generation: Generation::new(1)?,
            width: k.width,
            top_k: k.top_k,
            temporal_decay_q24: k.temporal_decay_q24,
            inhibition_gain_q24: 0,
            inhibition: vec![],
            activity_decay_q24: k.activity_decay_q24,
            target_activity_q24: k.target_activity_q24,
            threshold_rate_q24: k.threshold_rate_q24,
            threshold_min_q24: k.threshold_min_q24,
            threshold_max_q24: k.threshold_max_q24,
            eligibility_decay_q24: k.eligibility_decay_q24,
        })
    }
    pub fn runtime(&self, bundle: Digest32, binary: Digest32) -> Result<NeuronRuntimeConfigV1> {
        let native = self.native(bundle)?;
        Ok(NeuronRuntimeConfigV1 {
            config_id: StableId::new("continuous-boundary.native.v1")?,
            generation: native.generation,
            model_id: StableId::new(&self.profile_id)?,
            model_manifest_digest: bundle,
            encoder_digest: Digest32::of_bytes(&serde_json::to_vec(&(
                &self.encoder_weights_q24,
                &self.encoder_bias_q24,
            ))?),
            head_digest: bundle,
            weights_digest: bundle,
            tokenizer_digest: Digest32::of_bytes(b"no-tokenizer"),
            preprocessor_digest: native.normalization_digest,
            quantization_digest: Digest32::of_bytes(b"q24-ties-even.v1"),
            runtime_digest: binary,
            device_digest: Digest32::of_bytes(std::env::consts::ARCH.as_bytes()),
            normalization_digest: native.normalization_digest,
            native_config_digest: native.digest()?,
            input_feature_dimension: self.feature_names.len() + 3,
            state_width: native.width,
            modulator_dimension: 1,
            calibration: NeuronCalibrationProfileV1 {
                calibration_artifact_digest: bundle,
                ood_artifact_digest: bundle,
                generation: native.generation,
                valid_from_sequence: 1,
                expires_after_sequence: self.maximum_ticks,
                zero_confidence_error_q24: Q,
                maximum_in_domain_error_q24: Q,
                minimum_confidence_ppm: 750_000,
                maximum_ood_ppm: 250_000,
                minimum_active_ppm: 0,
                maximum_active_ppm: 1_000_000,
                maximum_projection_count: 1000,
                measured_ece_ppm: 0,
                maximum_ece_ppm: 30_000,
                measured_false_acceptance_ppm: 0,
                maximum_false_acceptance_ppm: 4_999,
            },
            resource_envelope: NeuronResourceEnvelopeV1 {
                p95_latency_micros: 1_000_000,
                p99_latency_micros: 10_000_000,
                transient_allocation_bytes: 16 << 20,
                checkpoint_bytes: 1 << 20,
                write_amplification_ppm: 4_000_000,
            },
        })
    }
}
