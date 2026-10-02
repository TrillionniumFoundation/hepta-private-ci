//! Stable model-quality scope for the conservative CPU bootstrap consumer.
//! These unsigned bindings grant no authority. Only the independent E reader
//! can produce current evidence; each Goal still needs its own current use cut.
use codex_hepta_types::Digest32;
use std::error::Error;
use std::fmt;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "fixed-eval-host",
    derive(serde::Deserialize, serde::Serialize)
)]
pub enum OperationalModelUseV2 {
    /// A CPU observation can only abstain and fall back to the model service.
    /// This never authorizes accepting an answer or promoting an artifact.
    ConservativeCpuAbstentionOnlyV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "fixed-eval-host",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "fixed-eval-host", serde(deny_unknown_fields))]
pub struct OperationalCalibrationGatesV2 {
    pub zero_confidence_error_q24: u64,
    pub maximum_in_domain_error_q24: u64,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_accuracy_ppm: u32,
    pub maximum_ece_ppm: u32,
    pub maximum_false_acceptance_ppm: u32,
    pub maximum_p99_latency_micros: u64,
    pub maximum_resident_bytes: u64,
    pub maximum_transient_allocation_bytes: u64,
}

impl OperationalCalibrationGatesV2 {
    pub fn validate(&self) -> Result<(), OperationalModelLeaseErrorV2> {
        if !(1..=1 << 40).contains(&self.zero_confidence_error_q24)
            || !(1..=1 << 40).contains(&self.maximum_in_domain_error_q24)
            || [
                self.minimum_confidence_ppm,
                self.maximum_ood_ppm,
                self.minimum_accuracy_ppm,
                self.maximum_ece_ppm,
                self.maximum_false_acceptance_ppm,
            ]
            .into_iter()
            .any(|v| v > 1_000_000)
            || !(1..=1_000_000).contains(&self.maximum_p99_latency_micros)
            || !(1..=1 << 30).contains(&self.maximum_resident_bytes)
            || !(1..=1 << 28).contains(&self.maximum_transient_allocation_bytes)
        {
            return Err(OperationalModelLeaseErrorV2::Binding("calibration gates"));
        }
        Ok(())
    }

    fn append(&self, bytes: &mut Vec<u8>) {
        for value in [
            self.zero_confidence_error_q24,
            self.maximum_in_domain_error_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.minimum_confidence_ppm,
            self.maximum_ood_ppm,
            self.minimum_accuracy_ppm,
            self.maximum_ece_ppm,
            self.maximum_false_acceptance_ppm,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.maximum_p99_latency_micros,
            self.maximum_resident_bytes,
            self.maximum_transient_allocation_bytes,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
}

/// Root-declared execution ceilings, separately bound from actual E observations.
/// Checkpoint/write amplification/load/inflight limits are enforced by the
/// consumer. Their inclusion here does not claim they were independently measured.
#[derive(Clone, Debug, Eq, PartialEq)]
#[cfg_attr(
    feature = "fixed-eval-host",
    derive(serde::Deserialize, serde::Serialize)
)]
#[cfg_attr(feature = "fixed-eval-host", serde(deny_unknown_fields))]
pub struct ConservativeCpuRuntimeProfileV2 {
    pub input_feature_dimension: u32,
    pub state_width: u32,
    pub modulator_dimension: u32,
    pub maximum_inflight: u32,
    pub maximum_load_bytes: u64,
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
    pub calibration_gates: OperationalCalibrationGatesV2,
}

impl ConservativeCpuRuntimeProfileV2 {
    pub fn validate(&self) -> Result<(), OperationalModelLeaseErrorV2> {
        self.calibration_gates.validate()?;
        if !(1..=512).contains(&self.input_feature_dimension)
            || !(5..=256).contains(&self.state_width)
            || !(1..=8).contains(&self.modulator_dimension)
            || !(1..=64).contains(&self.maximum_inflight)
            || !(1..=1 << 30).contains(&self.maximum_load_bytes)
            || self.p95_latency_micros == 0
            || self.p99_latency_micros < self.p95_latency_micros
            || self.p99_latency_micros > self.calibration_gates.maximum_p99_latency_micros
            || self.transient_allocation_bytes == 0
            || self.transient_allocation_bytes
                > self.calibration_gates.maximum_transient_allocation_bytes
            || self.checkpoint_bytes == 0
            || !(1_000_000..=4_000_000).contains(&self.write_amplification_ppm)
        {
            return Err(OperationalModelLeaseErrorV2::Binding(
                "conservative CPU profile",
            ));
        }
        Ok(())
    }

    /// A new framed semantic domain; V1 execution profiles remain unchanged.
    /// No request, Goal, clock, scope epoch or lease lifetime enters this digest.
    pub fn semantic_digest(&self) -> Result<Digest32, OperationalModelLeaseErrorV2> {
        self.validate()?;
        let mut bytes = b"hepta.intelligence-eval.conservative-cpu-runtime-profile.v2".to_vec();
        for value in [
            self.input_feature_dimension,
            self.state_width,
            self.modulator_dimension,
            self.maximum_inflight,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.maximum_load_bytes,
            self.p95_latency_micros,
            self.p99_latency_micros,
            self.transient_allocation_bytes,
            self.checkpoint_bytes,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.write_amplification_ppm.to_be_bytes());
        self.calibration_gates.append(&mut bytes);
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperationalModelLeaseBindingV2 {
    pub model_generation: u64,
    pub model_manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub normalization_digest: Digest32,
    pub encoder_manifest_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub training_code_digest: Digest32,
    pub source_training_digest: Digest32,
    pub preregistration_digest: Digest32,
    pub body_implementation_digest: Digest32,
    pub model_runtime_profile_digest: Digest32,
    pub purpose: OperationalModelUseV2,
}

impl OperationalModelLeaseBindingV2 {
    pub fn validate(&self) -> Result<(), OperationalModelLeaseErrorV2> {
        // This bootstrap version is deliberately restricted to actual modelgen1.
        // A later promotion must enter through its own independently qualified API.
        if self.model_generation != 1 || self.pins().into_iter().any(Digest32::is_zero) {
            return Err(OperationalModelLeaseErrorV2::Binding(
                "generation-one model pins",
            ));
        }
        Ok(())
    }

    fn pins(&self) -> [Digest32; 10] {
        [
            self.model_manifest_digest,
            self.weights_digest,
            self.normalization_digest,
            self.encoder_manifest_digest,
            self.tokenizer_digest,
            self.training_code_digest,
            self.source_training_digest,
            self.preregistration_digest,
            self.body_implementation_digest,
            self.model_runtime_profile_digest,
        ]
    }

    pub fn binding_digest(&self) -> Result<Digest32, OperationalModelLeaseErrorV2> {
        self.validate()?;
        let mut bytes = b"hepta.intelligence-eval.operational-model-binding.v2".to_vec();
        bytes.extend_from_slice(&self.model_generation.to_be_bytes());
        for pin in self.pins() {
            bytes.extend_from_slice(pin.as_array());
        }
        match self.purpose {
            OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1 => bytes.push(1),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum OperationalModelLeaseErrorV2 {
    Binding(&'static str),
}
impl fmt::Display for OperationalModelLeaseErrorV2 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for OperationalModelLeaseErrorV2 {}

#[cfg(test)]
#[path = "operational_model_lease_v2_tests.rs"]
mod tests;
