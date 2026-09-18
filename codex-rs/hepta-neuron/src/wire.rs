//! Strict canonical-JSON adapters for the registered neuron runtime protocols.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use chrono::DateTime;
use chrono::SecondsFormat;
use chrono::Utc;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde_json::Map;
use serde_json::Value;
use serde_json::json;

use crate::FixedPointRoundingV1;
use crate::FixedPointScaleV1;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronEligibilityProfileV1;
use crate::NeuronFixedPointProfileV1;
use crate::NeuronHomeostasisProfileV1;
use crate::NeuronResourceEnvelopeV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronStateDimensionsV1;
use crate::NeuronTickInputV1;
use crate::NeuronTickReceiptV1;
use crate::NeuronTopKPolicyV1;
use crate::ProtocolError;
use crate::TopKTieBreakV1;

const MAX_PROTOCOL_BYTES: usize = 262_144;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronWireError {
    Oversize,
    Json(String),
    NonCanonical,
    ExpectedObject(&'static str),
    MissingField(&'static str),
    UnknownField(String),
    InvalidType(&'static str),
    InvalidValue(&'static str),
    InvalidIdentity(String),
    InvalidDigest(String),
    InvalidTimestamp,
    Protocol(ProtocolError),
}

impl fmt::Display for NeuronWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronWireError {}

impl From<ProtocolError> for NeuronWireError {
    fn from(error: ProtocolError) -> Self {
        Self::Protocol(error)
    }
}

pub fn decode_neuron_runtime_config_v1(
    bytes: &[u8],
) -> Result<NeuronRuntimeConfigV1, NeuronWireError> {
    let value = parse_canonical(bytes)?;
    let object = strict_object(
        &value,
        "NeuronRuntimeConfigV1",
        &[
            "configId",
            "generation",
            "encoderDigest",
            "headDigest",
            "stateDimensions",
            "fixedPointProfile",
            "topKPolicy",
            "inhibitionDigest",
            "homeostasisProfile",
            "eligibilityProfile",
            "resourceEnvelope",
            "expiry",
        ],
        &[],
    )?;
    let state = strict_object(
        field(object, "stateDimensions")?,
        "stateDimensions",
        &[
            "temporalState",
            "activation",
            "modulators",
            "inhibitionEdges",
        ],
        &[],
    )?;
    let fixed = strict_object(
        field(object, "fixedPointProfile")?,
        "fixedPointProfile",
        &[
            "stateScale",
            "rounding",
            "stateMinimumQ24",
            "stateMaximumQ24",
            "checkedWideIntermediates",
        ],
        &[],
    )?;
    let top_k = strict_object(
        field(object, "topKPolicy")?,
        "topKPolicy",
        &[
            "minimumRatioPpm",
            "maximumRatioPpm",
            "tieBreak",
            "perPopulationFirst",
        ],
        &[],
    )?;
    let homeostasis = strict_object(
        field(object, "homeostasisProfile")?,
        "homeostasisProfile",
        &[
            "movingAverageAlphaQ24",
            "thresholdStepQ24",
            "thresholdMinimumQ24",
            "thresholdMaximumQ24",
            "saturationLimit",
        ],
        &[],
    )?;
    let eligibility = strict_object(
        field(object, "eligibilityProfile")?,
        "eligibilityProfile",
        &[
            "traceDimension",
            "maximumNormQ24",
            "decayQ24",
            "localRuleDigest",
        ],
        &[],
    )?;
    let resources = strict_object(
        field(object, "resourceEnvelope")?,
        "resourceEnvelope",
        &[
            "p95LatencyMicros",
            "p99LatencyMicros",
            "transientAllocationBytes",
            "checkpointBytes",
            "writeAmplificationPpm",
        ],
        &[],
    )?;
    let config = NeuronRuntimeConfigV1 {
        config_id: parse_id(string(object, "configId")?)?,
        generation: parse_generation(unsigned(object, "generation")?)?,
        encoder_digest: parse_digest(string(object, "encoderDigest")?)?,
        head_digest: parse_digest(string(object, "headDigest")?)?,
        state_dimensions: NeuronStateDimensionsV1 {
            temporal_state: bounded_u32(unsigned(state, "temporalState")?, "temporalState")?,
            activation: bounded_u32(unsigned(state, "activation")?, "activation")?,
            modulators: bounded_u32(unsigned(state, "modulators")?, "modulators")?,
            inhibition_edges: bounded_u32(unsigned(state, "inhibitionEdges")?, "inhibitionEdges")?,
        },
        fixed_point_profile: NeuronFixedPointProfileV1 {
            state_scale: match string(fixed, "stateScale")? {
                "Q24" => FixedPointScaleV1::Q24,
                _ => return Err(NeuronWireError::InvalidValue("stateScale")),
            },
            rounding: match string(fixed, "rounding")? {
                "nearest_ties_even" => FixedPointRoundingV1::NearestTiesEven,
                _ => return Err(NeuronWireError::InvalidValue("rounding")),
            },
            state_minimum_q24: signed(fixed, "stateMinimumQ24")?,
            state_maximum_q24: signed(fixed, "stateMaximumQ24")?,
            checked_wide_intermediates: boolean(fixed, "checkedWideIntermediates")?,
        },
        top_k_policy: NeuronTopKPolicyV1 {
            minimum_ratio_ppm: bounded_u32(unsigned(top_k, "minimumRatioPpm")?, "minimumRatioPpm")?,
            maximum_ratio_ppm: bounded_u32(unsigned(top_k, "maximumRatioPpm")?, "maximumRatioPpm")?,
            tie_break: match string(top_k, "tieBreak")? {
                "canonical_unit_id" => TopKTieBreakV1::CanonicalUnitId,
                _ => return Err(NeuronWireError::InvalidValue("tieBreak")),
            },
            per_population_first: boolean(top_k, "perPopulationFirst")?,
        },
        inhibition_digest: parse_digest(string(object, "inhibitionDigest")?)?,
        homeostasis_profile: NeuronHomeostasisProfileV1 {
            moving_average_alpha_q24: signed(homeostasis, "movingAverageAlphaQ24")?,
            threshold_step_q24: signed(homeostasis, "thresholdStepQ24")?,
            threshold_minimum_q24: signed(homeostasis, "thresholdMinimumQ24")?,
            threshold_maximum_q24: signed(homeostasis, "thresholdMaximumQ24")?,
            saturation_limit: bounded_u32(
                unsigned(homeostasis, "saturationLimit")?,
                "saturationLimit",
            )?,
        },
        eligibility_profile: NeuronEligibilityProfileV1 {
            trace_dimension: bounded_u32(
                unsigned(eligibility, "traceDimension")?,
                "traceDimension",
            )?,
            maximum_norm_q24: signed(eligibility, "maximumNormQ24")?,
            decay_q24: signed(eligibility, "decayQ24")?,
            local_rule_digest: parse_digest(string(eligibility, "localRuleDigest")?)?,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: unsigned(resources, "p95LatencyMicros")?,
            p99_latency_micros: unsigned(resources, "p99LatencyMicros")?,
            transient_allocation_bytes: unsigned(resources, "transientAllocationBytes")?,
            checkpoint_bytes: unsigned(resources, "checkpointBytes")?,
            write_amplification_ppm: bounded_u32(
                unsigned(resources, "writeAmplificationPpm")?,
                "writeAmplificationPpm",
            )?,
        },
        expires_at_unix_micros: parse_timestamp_micros(string(object, "expiry")?)?,
    };
    config.validate()?;
    Ok(config)
}

pub fn encode_neuron_runtime_config_v1(
    config: &NeuronRuntimeConfigV1,
) -> Result<Vec<u8>, NeuronWireError> {
    config.validate()?;
    canonical_json(&json!({
        "configId": config.config_id.as_str(),
        "generation": config.generation.get(),
        "encoderDigest": config.encoder_digest.to_string(),
        "headDigest": config.head_digest.to_string(),
        "stateDimensions": {
            "temporalState": config.state_dimensions.temporal_state,
            "activation": config.state_dimensions.activation,
            "modulators": config.state_dimensions.modulators,
            "inhibitionEdges": config.state_dimensions.inhibition_edges,
        },
        "fixedPointProfile": {
            "stateScale": "Q24",
            "rounding": "nearest_ties_even",
            "stateMinimumQ24": config.fixed_point_profile.state_minimum_q24,
            "stateMaximumQ24": config.fixed_point_profile.state_maximum_q24,
            "checkedWideIntermediates": config.fixed_point_profile.checked_wide_intermediates,
        },
        "topKPolicy": {
            "minimumRatioPpm": config.top_k_policy.minimum_ratio_ppm,
            "maximumRatioPpm": config.top_k_policy.maximum_ratio_ppm,
            "tieBreak": "canonical_unit_id",
            "perPopulationFirst": config.top_k_policy.per_population_first,
        },
        "inhibitionDigest": config.inhibition_digest.to_string(),
        "homeostasisProfile": {
            "movingAverageAlphaQ24": config.homeostasis_profile.moving_average_alpha_q24,
            "thresholdStepQ24": config.homeostasis_profile.threshold_step_q24,
            "thresholdMinimumQ24": config.homeostasis_profile.threshold_minimum_q24,
            "thresholdMaximumQ24": config.homeostasis_profile.threshold_maximum_q24,
            "saturationLimit": config.homeostasis_profile.saturation_limit,
        },
        "eligibilityProfile": {
            "traceDimension": config.eligibility_profile.trace_dimension,
            "maximumNormQ24": config.eligibility_profile.maximum_norm_q24,
            "decayQ24": config.eligibility_profile.decay_q24,
            "localRuleDigest": config.eligibility_profile.local_rule_digest.to_string(),
        },
        "resourceEnvelope": {
            "p95LatencyMicros": config.resource_envelope.p95_latency_micros,
            "p99LatencyMicros": config.resource_envelope.p99_latency_micros,
            "transientAllocationBytes": config.resource_envelope.transient_allocation_bytes,
            "checkpointBytes": config.resource_envelope.checkpoint_bytes,
            "writeAmplificationPpm": config.resource_envelope.write_amplification_ppm,
        },
        "expiry": format_timestamp_micros(config.expires_at_unix_micros)?,
    }))
}

pub fn decode_neuron_tick_input_v1(bytes: &[u8]) -> Result<NeuronTickInputV1, NeuronWireError> {
    let value = parse_canonical(bytes)?;
    let object = strict_object(
        &value,
        "NeuronTickInputV1",
        &[
            "tickId",
            "subjectId",
            "logicalSequence",
            "monotonicTimeMicros",
            "checkpointDigest",
            "inputFeatureDigest",
            "featureVectorQ24",
            "objectiveDigest",
            "nduSnapshotDigest",
        ],
        &["bodyGeneration", "modulatorDigest"],
    )?;
    let features = field(object, "featureVectorQ24")?
        .as_array()
        .ok_or(NeuronWireError::InvalidType("featureVectorQ24"))?
        .iter()
        .map(|value| {
            value
                .as_i64()
                .ok_or(NeuronWireError::InvalidType("featureVectorQ24 item"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    if features.is_empty() || features.len() > 512 {
        return Err(NeuronWireError::InvalidValue("featureVectorQ24 length"));
    }
    let body_generation = object
        .get("bodyGeneration")
        .map(|value| {
            value
                .as_u64()
                .ok_or(NeuronWireError::InvalidType("bodyGeneration"))
                .and_then(parse_generation)
        })
        .transpose()?;
    let modulator_digest = object
        .get("modulatorDigest")
        .map(|value| {
            value
                .as_str()
                .ok_or(NeuronWireError::InvalidType("modulatorDigest"))
                .and_then(parse_digest)
        })
        .transpose()?;
    Ok(NeuronTickInputV1 {
        tick_id: parse_id(string(object, "tickId")?)?,
        subject_id: parse_id(string(object, "subjectId")?)?,
        logical_sequence: unsigned(object, "logicalSequence")?,
        monotonic_time_micros: unsigned(object, "monotonicTimeMicros")?,
        checkpoint_digest: parse_digest(string(object, "checkpointDigest")?)?,
        input_feature_digest: parse_digest(string(object, "inputFeatureDigest")?)?,
        feature_vector_q24: features,
        objective_digest: parse_digest(string(object, "objectiveDigest")?)?,
        ndu_snapshot_digest: parse_digest(string(object, "nduSnapshotDigest")?)?,
        body_generation,
        modulator_digest,
    })
}

pub fn encode_neuron_tick_input_v1(input: &NeuronTickInputV1) -> Result<Vec<u8>, NeuronWireError> {
    let mut object = Map::new();
    object.insert("tickId".to_string(), json!(input.tick_id.as_str()));
    object.insert("subjectId".to_string(), json!(input.subject_id.as_str()));
    object.insert("logicalSequence".to_string(), json!(input.logical_sequence));
    object.insert(
        "monotonicTimeMicros".to_string(),
        json!(input.monotonic_time_micros),
    );
    object.insert(
        "checkpointDigest".to_string(),
        json!(input.checkpoint_digest.to_string()),
    );
    object.insert(
        "inputFeatureDigest".to_string(),
        json!(input.input_feature_digest.to_string()),
    );
    object.insert(
        "featureVectorQ24".to_string(),
        json!(&input.feature_vector_q24),
    );
    object.insert(
        "objectiveDigest".to_string(),
        json!(input.objective_digest.to_string()),
    );
    object.insert(
        "nduSnapshotDigest".to_string(),
        json!(input.ndu_snapshot_digest.to_string()),
    );
    if let Some(generation) = input.body_generation {
        object.insert("bodyGeneration".to_string(), json!(generation.get()));
    }
    if let Some(digest) = input.modulator_digest {
        object.insert("modulatorDigest".to_string(), json!(digest.to_string()));
    }
    canonical_json(&Value::Object(object))
}

pub fn decode_neuron_tick_receipt_v1(
    bytes: &[u8],
) -> Result<NeuronTickReceiptV1, NeuronWireError> {
    let value = parse_canonical(bytes)?;
    let object = strict_object(
        &value,
        "NeuronTickReceiptV1",
        &[
            "tickId",
            "checkpointBefore",
            "checkpointAfter",
            "activationDigest",
            "activeIndices",
            "sparsityPpm",
            "thresholdDigest",
            "eligibilityDigest",
            "predictionErrorQ24",
            "confidencePpm",
            "oodPpm",
            "abstain",
            "resourceReceipt",
        ],
        &[],
    )?;
    let resources = strict_object(
        field(object, "resourceReceipt")?,
        "resourceReceipt",
        &[
            "executionMicros",
            "transientAllocationBytes",
            "checkpointBytes",
            "saturationCount",
            "queueAgeMicros",
        ],
        &[],
    )?;
    let indices = field(object, "activeIndices")?
        .as_array()
        .ok_or(NeuronWireError::InvalidType("activeIndices"))?;
    if indices.len() > 512 {
        return Err(NeuronWireError::InvalidValue("activeIndices length"));
    }
    let mut seen = BTreeSet::new();
    let active_indices = indices
        .iter()
        .map(|value| {
            let raw = value
                .as_u64()
                .ok_or(NeuronWireError::InvalidType("activeIndices item"))?;
            let index = bounded_u32(raw, "activeIndices item")?;
            if !seen.insert(index) {
                return Err(NeuronWireError::InvalidValue("activeIndices unique"));
            }
            Ok(index)
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(NeuronTickReceiptV1 {
        tick_id: parse_id(string(object, "tickId")?)?,
        checkpoint_before: parse_digest(string(object, "checkpointBefore")?)?,
        checkpoint_after: parse_digest(string(object, "checkpointAfter")?)?,
        activation_digest: parse_digest(string(object, "activationDigest")?)?,
        active_indices,
        sparsity_ppm: ppm_u32(unsigned(object, "sparsityPpm")?, "sparsityPpm")?,
        threshold_digest: parse_digest(string(object, "thresholdDigest")?)?,
        eligibility_digest: parse_digest(string(object, "eligibilityDigest")?)?,
        prediction_error_q24: signed(object, "predictionErrorQ24")?,
        confidence_ppm: ppm_u32(unsigned(object, "confidencePpm")?, "confidencePpm")?,
        ood_ppm: ppm_u32(unsigned(object, "oodPpm")?, "oodPpm")?,
        abstain: boolean(object, "abstain")?,
        resource_receipt: crate::NeuronResourceReceiptV1 {
            execution_micros: unsigned(resources, "executionMicros")?,
            transient_allocation_bytes: unsigned(resources, "transientAllocationBytes")?,
            checkpoint_bytes: unsigned(resources, "checkpointBytes")?,
            saturation_count: bounded_u32(
                unsigned(resources, "saturationCount")?,
                "saturationCount",
            )?,
            queue_age_micros: unsigned(resources, "queueAgeMicros")?,
        },
    })
}

pub fn encode_neuron_tick_receipt_v1(
    receipt: &NeuronTickReceiptV1,
) -> Result<Vec<u8>, NeuronWireError> {
    canonical_json(&json!({
        "tickId": receipt.tick_id.as_str(),
        "checkpointBefore": receipt.checkpoint_before.to_string(),
        "checkpointAfter": receipt.checkpoint_after.to_string(),
        "activationDigest": receipt.activation_digest.to_string(),
        "activeIndices": receipt.active_indices,
        "sparsityPpm": receipt.sparsity_ppm,
        "thresholdDigest": receipt.threshold_digest.to_string(),
        "eligibilityDigest": receipt.eligibility_digest.to_string(),
        "predictionErrorQ24": receipt.prediction_error_q24,
        "confidencePpm": receipt.confidence_ppm,
        "oodPpm": receipt.ood_ppm,
        "abstain": receipt.abstain,
        "resourceReceipt": {
            "executionMicros": receipt.resource_receipt.execution_micros,
            "transientAllocationBytes": receipt.resource_receipt.transient_allocation_bytes,
            "checkpointBytes": receipt.resource_receipt.checkpoint_bytes,
            "saturationCount": receipt.resource_receipt.saturation_count,
            "queueAgeMicros": receipt.resource_receipt.queue_age_micros,
        }
    }))
}

pub fn decode_neuron_signal_receipt_v1(
    bytes: &[u8],
) -> Result<NeuronSignalReceiptV1, NeuronWireError> {
    let value = parse_canonical(bytes)?;
    let object = strict_object(
        &value,
        "NeuronSignalReceiptV1",
        &[
            "signalSetId",
            "modelRuntimeDigest",
            "temporalStateDigest",
            "signals",
            "activationSparsityPpm",
            "oodPpm",
            "abstain",
        ],
        &[],
    )?;
    let raw_signals = field(object, "signals")?
        .as_array()
        .ok_or(NeuronWireError::InvalidType("signals"))?;
    if raw_signals.len() > 4096 {
        return Err(NeuronWireError::InvalidValue("signals length"));
    }
    let signals_q24 = raw_signals
        .iter()
        .map(|value| {
            value
                .as_i64()
                .ok_or(NeuronWireError::InvalidType("signals item"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    Ok(NeuronSignalReceiptV1 {
        signal_set_id: parse_id(string(object, "signalSetId")?)?,
        model_runtime_digest: parse_digest(string(object, "modelRuntimeDigest")?)?,
        temporal_state_digest: parse_digest(string(object, "temporalStateDigest")?)?,
        signals_q24,
        activation_sparsity_ppm: ppm_u32(
            unsigned(object, "activationSparsityPpm")?,
            "activationSparsityPpm",
        )?,
        ood_ppm: ppm_u32(unsigned(object, "oodPpm")?, "oodPpm")?,
        abstain: boolean(object, "abstain")?,
    })
}

pub fn encode_neuron_signal_receipt_v1(
    receipt: &NeuronSignalReceiptV1,
) -> Result<Vec<u8>, NeuronWireError> {
    canonical_json(&json!({
        "signalSetId": receipt.signal_set_id.as_str(),
        "modelRuntimeDigest": receipt.model_runtime_digest.to_string(),
        "temporalStateDigest": receipt.temporal_state_digest.to_string(),
        "signals": receipt.signals_q24,
        "activationSparsityPpm": receipt.activation_sparsity_ppm,
        "oodPpm": receipt.ood_ppm,
        "abstain": receipt.abstain,
    }))
}

pub fn decode_local_model_runtime_receipt_v1(
    bytes: &[u8],
) -> Result<LocalModelRuntimeReceiptV1, NeuronWireError> {
    let value = parse_canonical(bytes)?;
    let object = strict_object(
        &value,
        "LocalModelRuntimeReceiptV1",
        &[
            "modelId",
            "weightsDigest",
            "tokenizerDigest",
            "preprocessorDigest",
            "quantizationId",
            "backendId",
            "deviceIdentityDigest",
            "latencyMicros",
            "residentBytes",
        ],
        &[],
    )?;
    let receipt = LocalModelRuntimeReceiptV1 {
        model_id: parse_id(string(object, "modelId")?)?,
        weights_digest: parse_digest(string(object, "weightsDigest")?)?,
        tokenizer_digest: parse_digest(string(object, "tokenizerDigest")?)?,
        preprocessor_digest: parse_digest(string(object, "preprocessorDigest")?)?,
        quantization_id: parse_id(string(object, "quantizationId")?)?,
        backend_id: parse_id(string(object, "backendId")?)?,
        device_identity_digest: parse_digest(string(object, "deviceIdentityDigest")?)?,
        latency_micros: unsigned(object, "latencyMicros")?,
        resident_bytes: unsigned(object, "residentBytes")?,
    };
    receipt.validate()?;
    Ok(receipt)
}

pub fn encode_local_model_runtime_receipt_v1(
    receipt: &LocalModelRuntimeReceiptV1,
) -> Result<Vec<u8>, NeuronWireError> {
    receipt.validate()?;
    canonical_json(&json!({
        "modelId": receipt.model_id.as_str(),
        "weightsDigest": receipt.weights_digest.to_string(),
        "tokenizerDigest": receipt.tokenizer_digest.to_string(),
        "preprocessorDigest": receipt.preprocessor_digest.to_string(),
        "quantizationId": receipt.quantization_id.as_str(),
        "backendId": receipt.backend_id.as_str(),
        "deviceIdentityDigest": receipt.device_identity_digest.to_string(),
        "latencyMicros": receipt.latency_micros,
        "residentBytes": receipt.resident_bytes,
    }))
}

fn parse_canonical(bytes: &[u8]) -> Result<Value, NeuronWireError> {
    if bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(NeuronWireError::Oversize);
    }
    let value: Value =
        serde_json::from_slice(bytes).map_err(|error| NeuronWireError::Json(error.to_string()))?;
    if canonical_json(&value)? != bytes {
        return Err(NeuronWireError::NonCanonical);
    }
    Ok(value)
}

fn canonical_json(value: &Value) -> Result<Vec<u8>, NeuronWireError> {
    let mut value = value.clone();
    sort_value(&mut value);
    let bytes =
        serde_json::to_vec(&value).map_err(|error| NeuronWireError::Json(error.to_string()))?;
    if bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(NeuronWireError::Oversize);
    }
    Ok(bytes)
}

fn sort_value(value: &mut Value) {
    match value {
        Value::Array(items) => {
            for item in items {
                sort_value(item);
            }
        }
        Value::Object(map) => {
            let mut entries = std::mem::take(map).into_iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            for (_, item) in &mut entries {
                sort_value(item);
            }
            map.extend(entries);
        }
        _ => {}
    }
}

fn strict_object<'a>(
    value: &'a Value,
    name: &'static str,
    required: &[&'static str],
    optional: &[&'static str],
) -> Result<&'a Map<String, Value>, NeuronWireError> {
    let object = value
        .as_object()
        .ok_or(NeuronWireError::ExpectedObject(name))?;
    for &field in required {
        if !object.contains_key(field) {
            return Err(NeuronWireError::MissingField(field));
        }
    }
    let allowed: BTreeSet<&str> = required.iter().chain(optional).copied().collect();
    if let Some(field) = object
        .keys()
        .find(|field| !allowed.contains(field.as_str()))
    {
        return Err(NeuronWireError::UnknownField(field.clone()));
    }
    Ok(object)
}

fn field<'a>(
    object: &'a Map<String, Value>,
    name: &'static str,
) -> Result<&'a Value, NeuronWireError> {
    object.get(name).ok_or(NeuronWireError::MissingField(name))
}

fn string<'a>(
    object: &'a Map<String, Value>,
    name: &'static str,
) -> Result<&'a str, NeuronWireError> {
    field(object, name)?
        .as_str()
        .ok_or(NeuronWireError::InvalidType(name))
}

fn unsigned(object: &Map<String, Value>, name: &'static str) -> Result<u64, NeuronWireError> {
    field(object, name)?
        .as_u64()
        .ok_or(NeuronWireError::InvalidType(name))
}

fn signed(object: &Map<String, Value>, name: &'static str) -> Result<i64, NeuronWireError> {
    field(object, name)?
        .as_i64()
        .ok_or(NeuronWireError::InvalidType(name))
}

fn boolean(object: &Map<String, Value>, name: &'static str) -> Result<bool, NeuronWireError> {
    field(object, name)?
        .as_bool()
        .ok_or(NeuronWireError::InvalidType(name))
}

fn parse_id(value: &str) -> Result<StableId, NeuronWireError> {
    StableId::new(value.to_string())
        .map_err(|error| NeuronWireError::InvalidIdentity(error.to_string()))
}

fn parse_generation(value: u64) -> Result<Generation, NeuronWireError> {
    Generation::new(value).map_err(|error| NeuronWireError::InvalidIdentity(error.to_string()))
}

fn parse_digest(value: &str) -> Result<Digest32, NeuronWireError> {
    Digest32::from_str(value).map_err(|error| NeuronWireError::InvalidDigest(error.to_string()))
}

fn bounded_u32(value: u64, name: &'static str) -> Result<u32, NeuronWireError> {
    u32::try_from(value).map_err(|_| NeuronWireError::InvalidValue(name))
}

fn ppm_u32(value: u64, name: &'static str) -> Result<u32, NeuronWireError> {
    let value = bounded_u32(value, name)?;
    if value > 1_000_000 {
        return Err(NeuronWireError::InvalidValue(name));
    }
    Ok(value)
}

fn parse_timestamp_micros(value: &str) -> Result<u64, NeuronWireError> {
    let parsed =
        DateTime::parse_from_rfc3339(value).map_err(|_| NeuronWireError::InvalidTimestamp)?;
    u64::try_from(parsed.timestamp_micros()).map_err(|_| NeuronWireError::InvalidTimestamp)
}

fn format_timestamp_micros(value: u64) -> Result<String, NeuronWireError> {
    let value = i64::try_from(value).map_err(|_| NeuronWireError::InvalidTimestamp)?;
    let seconds = value.div_euclid(1_000_000);
    let micros = value.rem_euclid(1_000_000);
    let nanos = u32::try_from(micros)
        .map_err(|_| NeuronWireError::InvalidTimestamp)?
        .saturating_mul(1_000);
    let timestamp =
        DateTime::<Utc>::from_timestamp(seconds, nanos).ok_or(NeuronWireError::InvalidTimestamp)?;
    Ok(timestamp.to_rfc3339_opts(SecondsFormat::Micros, true))
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
