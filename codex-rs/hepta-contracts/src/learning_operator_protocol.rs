//! Untrusted transport views of the registered learning.operator protocols.
//!
//! The V1 field order and bounds come from PROTOCOL_SCHEMAS.json. Like the
//! existing contract codecs, encoding uses compact serde_json UTF-8; nested
//! objects are sorted explicitly, including under serde's preserve_order feature.
//! Nested numeric tokens must use serde_json's i64/u64/finite-f64 spelling even
//! when arbitrary_precision is unified by a consumer; other spellings reject
//! rather than silently rounding a caller's profile value.
//! Object members using serde_json's reserved private prefix are rejected so
//! feature unification cannot reinterpret an object as a numeric or raw value.
//! Strict decoding accepts only those bytes (no normalization during admission).
//! No DTO or transport digest is an evaluator signature, owner capability or
//! proof of the native profile's assumptions. Native profiles need additional
//! lifecycle, horizon and measured-profile context and are not implicitly cast.
//! The registry does not define enum values or bounded-object member schemas;
//! those are preserved, bounded and left to the independent semantic evaluator.

use std::error::Error;
use std::fmt;
use std::io;
use std::io::Write;

use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::Value;

use crate::Sha256Digest;

pub const MAX_LEARNING_OPERATOR_PROTOCOL_BYTES: usize = 262_144;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UntrustedOperatorSensorCoreManifestV1 {
    pub sensor_core_id: String,
    pub state_axis_digest: String,
    pub points_digest: String,
    pub count: u32,
    pub fill_distance_q32: i64,
    pub separation_radius_q32: i64,
    pub mesh_ratio_q32: i64,
    pub hull_digest: String,
    pub construction_algorithm: String,
    pub seed_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub predecessor_id: Option<String>,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UntrustedRegularityProfileV1 {
    pub profile_id: String,
    pub artifact_digest: String,
    pub mode: String,
    pub measured_rank: u32,
    pub reconstruction_gain_q32: i64,
    pub monotonicity_violations: u32,
    pub positivity_violations: u32,
    pub holder_residuals: Value,
    pub action_lipschitz_residuals: Value,
    pub ood_margin_q32: i64,
    pub total_error_q32: i64,
    pub decision: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct UntrustedOperatorApplicabilityCertificateV1 {
    pub certificate_id: String,
    pub axis_partition_digest: String,
    pub domain_digest: String,
    pub action_space_digest: String,
    pub holder_exponents: Value,
    pub holder_constants: Value,
    pub state_lipschitz: Value,
    pub action_lipschitz: Value,
    pub ellipticity_nu_lcb_q32: i64,
    pub horizon_micros: u64,
    pub control_interval_profile_digest: String,
    pub jump_policy_digest: String,
    pub ood_policy_digest: String,
    pub evaluator_identity: String,
    pub expires_unix_ms: u64,
    pub decision: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UntrustedLearningOperatorProtocolV1 {
    SensorCore(Box<UntrustedOperatorSensorCoreManifestV1>),
    Regularity(Box<UntrustedRegularityProfileV1>),
    Applicability(Box<UntrustedOperatorApplicabilityCertificateV1>),
}

impl UntrustedLearningOperatorProtocolV1 {
    pub fn protocol_id(&self) -> &'static str {
        match self {
            Self::SensorCore(_) => "OperatorSensorCoreManifestV1",
            Self::Regularity(_) => "RegularityProfileV1",
            Self::Applicability(_) => "OperatorApplicabilityCertificateV1",
        }
    }

    pub fn encode_canonical(&self) -> Result<Vec<u8>, LearningOperatorProtocolError> {
        match self {
            Self::SensorCore(value) => encode(value.as_ref()),
            Self::Regularity(value) => encode(value.as_ref()),
            Self::Applicability(value) => encode(value.as_ref()),
        }
    }

    /// SHA-256 of every semantic wire field, including lineage and expiry.
    /// Protocol identity/version remain explicit dispatch inputs; this digest
    /// does not authorize cross-protocol reinterpretation or native admission.
    pub fn semantic_digest(&self) -> Result<Sha256Digest, LearningOperatorProtocolError> {
        Ok(Sha256Digest::for_bytes(&self.encode_canonical()?))
    }
}

/// No implicit migration or downgrade: only the registered V1 transport is
/// supported. Re-encoding preserves its fields, not native fitting eligibility.
pub fn decode_learning_operator_protocol(
    protocol_id: &str,
    version: u32,
    bytes: &[u8],
) -> Result<UntrustedLearningOperatorProtocolV1, LearningOperatorProtocolError> {
    if version != 1 {
        return Err(LearningOperatorProtocolError::UnsupportedVersion(version));
    }
    match protocol_id {
        "OperatorSensorCoreManifestV1" => decode(bytes)
            .map(|value| UntrustedLearningOperatorProtocolV1::SensorCore(Box::new(value))),
        "RegularityProfileV1" => decode(bytes)
            .map(|value| UntrustedLearningOperatorProtocolV1::Regularity(Box::new(value))),
        "OperatorApplicabilityCertificateV1" => decode(bytes)
            .map(|value| UntrustedLearningOperatorProtocolV1::Applicability(Box::new(value))),
        // CONTRACTS registers this identity, but PROTOCOL_SCHEMAS defines no
        // fields/types/bounds. HEPTTB01 and the conceptual Holder spec are not
        // substitutes for a canonical schema approved by its protocol owners.
        "BellmanOperatorArtifactV1" => Err(LearningOperatorProtocolError::MissingCanonicalSchema),
        _ => Err(LearningOperatorProtocolError::UnknownProtocol),
    }
}

trait Transport: Clone + Serialize + DeserializeOwned {
    fn validate(&self) -> Result<(), LearningOperatorProtocolError>;
    fn sort_objects(&mut self) {}
}

impl Transport for UntrustedOperatorSensorCoreManifestV1 {
    fn validate(&self) -> Result<(), LearningOperatorProtocolError> {
        text(&self.sensor_core_id, 128)?;
        for value in [
            &self.state_axis_digest,
            &self.points_digest,
            &self.hull_digest,
            &self.seed_digest,
        ] {
            digest(value)?;
        }
        text(&self.construction_algorithm, 64)?;
        if let Some(value) = &self.predecessor_id {
            text(value, 128)?;
        }
        Ok(())
    }
}

impl Transport for UntrustedRegularityProfileV1 {
    fn validate(&self) -> Result<(), LearningOperatorProtocolError> {
        text(&self.profile_id, 128)?;
        digest(&self.artifact_digest)?;
        text(&self.mode, 32)?;
        text(&self.decision, 32)?;
        object(&self.holder_residuals, 16_384)?;
        object(&self.action_lipschitz_residuals, 16_384)
    }
    fn sort_objects(&mut self) {
        self.holder_residuals.sort_all_objects();
        self.action_lipschitz_residuals.sort_all_objects();
    }
}

impl Transport for UntrustedOperatorApplicabilityCertificateV1 {
    fn validate(&self) -> Result<(), LearningOperatorProtocolError> {
        text(&self.certificate_id, 128)?;
        text(&self.evaluator_identity, 128)?;
        text(&self.decision, 32)?;
        for value in [
            &self.axis_partition_digest,
            &self.domain_digest,
            &self.action_space_digest,
            &self.control_interval_profile_digest,
            &self.jump_policy_digest,
            &self.ood_policy_digest,
        ] {
            digest(value)?;
        }
        for value in [
            &self.holder_exponents,
            &self.holder_constants,
            &self.state_lipschitz,
            &self.action_lipschitz,
        ] {
            object(value, 8_192)?;
        }
        Ok(())
    }
    fn sort_objects(&mut self) {
        for value in [
            &mut self.holder_exponents,
            &mut self.holder_constants,
            &mut self.state_lipschitz,
            &mut self.action_lipschitz,
        ] {
            value.sort_all_objects();
        }
    }
}

fn encode<T: Transport>(value: &T) -> Result<Vec<u8>, LearningOperatorProtocolError> {
    value.validate()?;
    let mut canonical = value.clone();
    canonical.sort_objects();
    bounded_json(&canonical, MAX_LEARNING_OPERATOR_PROTOCOL_BYTES)
}

fn decode<T: Transport>(bytes: &[u8]) -> Result<T, LearningOperatorProtocolError> {
    if bytes.len() > MAX_LEARNING_OPERATOR_PROTOCOL_BYTES {
        return Err(LearningOperatorProtocolError::Bounds);
    }
    let value: T =
        serde_json::from_slice(bytes).map_err(|_| LearningOperatorProtocolError::Json)?;
    if encode(&value)? != bytes {
        return Err(LearningOperatorProtocolError::NonCanonical);
    }
    Ok(value)
}

fn text(value: &str, maximum: usize) -> Result<(), LearningOperatorProtocolError> {
    if value.is_empty() || value.len() > maximum || value.contains('\0') {
        return Err(LearningOperatorProtocolError::Bounds);
    }
    Ok(())
}

fn digest(value: &str) -> Result<(), LearningOperatorProtocolError> {
    // Sha256Digest::parse owns its input; bound the borrow before that clone.
    if value.len() != 64 {
        return Err(LearningOperatorProtocolError::Digest);
    }
    Sha256Digest::parse(value)
        .map(|_| ())
        .map_err(|_| LearningOperatorProtocolError::Digest)
}

fn object(value: &Value, maximum: usize) -> Result<(), LearningOperatorProtocolError> {
    if !value.is_object() {
        return Err(LearningOperatorProtocolError::Object);
    }
    // Match serde_json's bounded parser depth and reject huge caller-constructed
    // trees before cloning/sorting or recursively serializing them.
    let mut remaining_bytes = maximum;
    tree_bound(value, 1, &mut remaining_bytes)?;
    bounded_json(value, maximum).map(|_| ())
}

fn tree_bound(
    value: &Value,
    depth: usize,
    remaining: &mut usize,
) -> Result<(), LearningOperatorProtocolError> {
    match value {
        Value::Array(values) => {
            if depth >= 127 {
                return Err(LearningOperatorProtocolError::Bounds);
            }
            charge(remaining, 2)?;
            charge(remaining, values.len().saturating_sub(1))?;
            for value in values {
                tree_bound(value, depth + 1, remaining)?;
            }
        }
        Value::Object(values) => {
            if depth >= 127 {
                return Err(LearningOperatorProtocolError::Bounds);
            }
            charge(remaining, 2)?;
            charge(remaining, values.len().saturating_sub(1))?;
            for (key, value) in values {
                if key.starts_with("$serde_json::private::") {
                    return Err(LearningOperatorProtocolError::ReservedMember);
                }
                // UTF-8 byte lengths are constant-time even for huge owned
                // strings. Reject before escaping, cloning or sorting keys.
                charge(remaining, key.len())?;
                charge(remaining, 3)?;
                tree_bound(value, depth + 1, remaining)?;
            }
        }
        Value::String(value) => {
            charge(remaining, value.len())?;
            charge(remaining, 2)?;
        }
        Value::Number(value) => {
            // The bounded writer also handles arbitrary_precision's possibly
            // long numeric token without allocating an unbounded to_string.
            let bytes = bounded_json(value, *remaining)?;
            charge(remaining, bytes.len())?;
            let canonical = if let Some(value) = value.as_i64() {
                serde_json::Number::from(value)
            } else if let Some(value) = value.as_u64() {
                serde_json::Number::from(value)
            } else {
                value
                    .as_f64()
                    .and_then(serde_json::Number::from_f64)
                    .ok_or(LearningOperatorProtocolError::NonCanonical)?
            };
            if bounded_json(&canonical, 64)? != bytes {
                return Err(LearningOperatorProtocolError::NonCanonical);
            }
        }
        Value::Bool(value) => charge(remaining, if *value { 4 } else { 5 })?,
        Value::Null => charge(remaining, 4)?,
    }
    Ok(())
}

fn charge(remaining: &mut usize, bytes: usize) -> Result<(), LearningOperatorProtocolError> {
    *remaining = remaining
        .checked_sub(bytes)
        .ok_or(LearningOperatorProtocolError::Bounds)?;
    Ok(())
}

struct BoundedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}

impl Write for BoundedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.len() > self.maximum.saturating_sub(self.bytes.len()) {
            return Err(io::Error::other("protocol byte bound exceeded"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn bounded_json<T: Serialize>(
    value: &T,
    maximum: usize,
) -> Result<Vec<u8>, LearningOperatorProtocolError> {
    let mut writer = BoundedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|error| {
        if error.is_io() {
            LearningOperatorProtocolError::Bounds
        } else {
            LearningOperatorProtocolError::Json
        }
    })?;
    Ok(writer.bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LearningOperatorProtocolError {
    UnknownProtocol,
    UnsupportedVersion(u32),
    MissingCanonicalSchema,
    Json,
    Bounds,
    Digest,
    Object,
    NonCanonical,
    ReservedMember,
}

impl fmt::Display for LearningOperatorProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for LearningOperatorProtocolError {}

#[cfg(test)]
#[path = "learning_operator_protocol_tests.rs"]
mod tests;
