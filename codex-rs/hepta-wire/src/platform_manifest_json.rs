//! Strict product-owned JSON codecs for the three `platform.types` manifests.
//!
//! The native manifest types own semantic validation and HPTC commitments.
//! `platform.wire` owns JSON transport: raw size/depth bounds, duplicate and
//! unknown field rejection, precision-safe canonical integers, and projection
//! back through the native constructors before publication.

use std::error::Error;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::ExternalSystemClassV1;
use codex_hepta_types::ExternalSystemManifestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ManifestContractErrorV1;
use codex_hepta_types::RandomStreamManifestV1;
use codex_hepta_types::SensorCalibrationManifestV1;
use codex_hepta_types::SensorClassV1;
use codex_hepta_types::SensorFailurePolicyV1;
use codex_hepta_types::SensorOperatingRangeV1;
use codex_hepta_types::SensorUncertaintyProfileV1;
use codex_hepta_types::StableId;
use codex_hepta_types::UncertaintyDistributionV1;
use codex_hepta_types::protocol_catalog_v2::identity_profile_for_protocol_field_v2;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;

use super::platform_types_json::MAX_CANONICAL_U64_DECIMAL_BYTES_V1;
use super::platform_types_json::MAX_PLATFORM_TYPES_JSON_BYTES_V1;
use super::platform_types_json::MAX_PLATFORM_TYPES_JSON_DEPTH_V1;
use super::platform_types_json::PlatformTypesWireError;

pub const MAX_CANONICAL_I64_DECIMAL_BYTES_V1: usize = 20;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CanonicalU64String(u64);

impl Serialize for CanonicalU64String {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for CanonicalU64String {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        if raw.is_empty()
            || raw.len() > MAX_CANONICAL_U64_DECIMAL_BYTES_V1
            || (raw.len() > 1 && raw.starts_with('0'))
            || !raw.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(serde::de::Error::custom("non-canonical u64 string"));
        }
        raw.parse::<u64>()
            .map(Self)
            .map_err(|_| serde::de::Error::custom("u64 string out of range"))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct CanonicalI64String(i64);

impl Serialize for CanonicalI64String {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.0.to_string())
    }
}

impl<'de> Deserialize<'de> for CanonicalI64String {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        let digits = raw.strip_prefix('-').unwrap_or(&raw);
        if raw.is_empty()
            || raw.len() > MAX_CANONICAL_I64_DECIMAL_BYTES_V1
            || digits.is_empty()
            || (digits.len() > 1 && digits.starts_with('0'))
            || raw == "-0"
            || !digits.bytes().all(|byte| byte.is_ascii_digit())
        {
            return Err(serde::de::Error::custom("non-canonical i64 string"));
        }
        raw.parse::<i64>()
            .map(Self)
            .map_err(|_| serde::de::Error::custom("i64 string out of range"))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RandomStreamManifestV1Json {
    kind: String,
    manifest_id: String,
    root_seed_digest: String,
    algorithm_namespace: String,
    episode_id: String,
    decision_id: String,
    stream_id: String,
    counter_start: CanonicalU64String,
    counter_end_exclusive: CanonicalU64String,
    generator_id: String,
    generator_version: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct ExternalSystemManifestV1Json {
    kind: String,
    system_id: String,
    system_class: String,
    host_identity_digest: String,
    os_release_digest: String,
    package_inventory_digest: String,
    service_graph_digest: String,
    filesystem_scope_digest: String,
    identity_map_digest: String,
    network_surface_digest: String,
    secret_reference_digest: String,
    observed_at: String,
    authorization_witness: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SensorCalibrationManifestV1Json {
    kind: String,
    sensor_id: String,
    sensor_class: String,
    hardware_or_adapter_digest: String,
    calibration_generation: CanonicalU64String,
    clock_domain: String,
    valid_from: String,
    valid_until: String,
    uncertainty_profile: SensorUncertaintyProfileV1Json,
    operating_range: SensorOperatingRangeV1Json,
    failure_policy: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SensorUncertaintyProfileV1Json {
    distribution_class: String,
    lower_q32: CanonicalI64String,
    upper_q32: CanonicalI64String,
    confidence_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SensorOperatingRangeV1Json {
    unit: String,
    minimum_q32: CanonicalI64String,
    maximum_q32: CanonicalI64String,
}

pub fn decode_random_stream_manifest_v1_json(
    bytes: &[u8],
) -> Result<RandomStreamManifestV1, PlatformManifestWireError> {
    let wire: RandomStreamManifestV1Json = decode_json(bytes)?;
    if wire.kind != "random_stream_manifest_v1" {
        return Err(PlatformManifestWireError::InvalidKind);
    }
    RandomStreamManifestV1::new(
        stable_id(
            "RandomStreamManifestV1",
            "manifest_id",
            &wire.manifest_id,
            "manifest_id",
        )?,
        nonzero_digest(&wire.root_seed_digest, "root_seed_digest")?,
        &wire.algorithm_namespace,
        stable_id(
            "RandomStreamManifestV1",
            "episode_id",
            &wire.episode_id,
            "episode_id",
        )?,
        stable_id(
            "RandomStreamManifestV1",
            "decision_id",
            &wire.decision_id,
            "decision_id",
        )?,
        stable_id(
            "RandomStreamManifestV1",
            "stream_id",
            &wire.stream_id,
            "stream_id",
        )?,
        wire.counter_start.0,
        wire.counter_end_exclusive.0,
        &wire.generator_id,
        &wire.generator_version,
    )
    .map_err(PlatformManifestWireError::Manifest)
}

pub fn encode_random_stream_manifest_v1_json(
    value: &RandomStreamManifestV1,
) -> Result<Vec<u8>, PlatformManifestWireError> {
    value
        .validate()
        .map_err(PlatformManifestWireError::Manifest)?;
    encode_json(&RandomStreamManifestV1Json {
        kind: "random_stream_manifest_v1".to_owned(),
        manifest_id: value.manifest_id().to_string(),
        root_seed_digest: value.root_seed_digest().to_string(),
        algorithm_namespace: value.algorithm_namespace().to_owned(),
        episode_id: value.episode_id().to_string(),
        decision_id: value.decision_id().to_string(),
        stream_id: value.stream_id().to_string(),
        counter_start: CanonicalU64String(value.counter_start()),
        counter_end_exclusive: CanonicalU64String(value.counter_end_exclusive()),
        generator_id: value.generator_id().to_owned(),
        generator_version: value.generator_version().to_owned(),
    })
}

pub fn decode_external_system_manifest_v1_json(
    bytes: &[u8],
) -> Result<ExternalSystemManifestV1, PlatformManifestWireError> {
    let wire: ExternalSystemManifestV1Json = decode_json(bytes)?;
    if wire.kind != "external_system_manifest_v1" {
        return Err(PlatformManifestWireError::InvalidKind);
    }
    let system_class = ExternalSystemClassV1::from_id(&wire.system_class)
        .map_err(PlatformManifestWireError::Manifest)?;
    ExternalSystemManifestV1::new(
        stable_id(
            "ExternalSystemManifestV1",
            "system_id",
            &wire.system_id,
            "system_id",
        )?,
        system_class,
        nonzero_digest(&wire.host_identity_digest, "host_identity_digest")?,
        nonzero_digest(&wire.os_release_digest, "os_release_digest")?,
        nonzero_digest(&wire.package_inventory_digest, "package_inventory_digest")?,
        nonzero_digest(&wire.service_graph_digest, "service_graph_digest")?,
        nonzero_digest(&wire.filesystem_scope_digest, "filesystem_scope_digest")?,
        nonzero_digest(&wire.identity_map_digest, "identity_map_digest")?,
        nonzero_digest(&wire.network_surface_digest, "network_surface_digest")?,
        nonzero_digest(&wire.secret_reference_digest, "secret_reference_digest")?,
        &wire.observed_at,
        nonzero_digest(&wire.authorization_witness, "authorization_witness")?,
    )
    .map_err(PlatformManifestWireError::Manifest)
}

pub fn encode_external_system_manifest_v1_json(
    value: &ExternalSystemManifestV1,
) -> Result<Vec<u8>, PlatformManifestWireError> {
    value
        .validate()
        .map_err(PlatformManifestWireError::Manifest)?;
    encode_json(&ExternalSystemManifestV1Json {
        kind: "external_system_manifest_v1".to_owned(),
        system_id: value.system_id().to_string(),
        system_class: value.system_class().id().to_owned(),
        host_identity_digest: value.host_identity_digest().to_string(),
        os_release_digest: value.os_release_digest().to_string(),
        package_inventory_digest: value.package_inventory_digest().to_string(),
        service_graph_digest: value.service_graph_digest().to_string(),
        filesystem_scope_digest: value.filesystem_scope_digest().to_string(),
        identity_map_digest: value.identity_map_digest().to_string(),
        network_surface_digest: value.network_surface_digest().to_string(),
        secret_reference_digest: value.secret_reference_digest().to_string(),
        observed_at: value.observed_at().as_str().to_owned(),
        authorization_witness: value.authorization_witness().to_string(),
    })
}

pub fn decode_sensor_calibration_manifest_v1_json(
    bytes: &[u8],
) -> Result<SensorCalibrationManifestV1, PlatformManifestWireError> {
    let wire: SensorCalibrationManifestV1Json = decode_json(bytes)?;
    if wire.kind != "sensor_calibration_manifest_v1" {
        return Err(PlatformManifestWireError::InvalidKind);
    }
    let sensor_class =
        SensorClassV1::from_id(&wire.sensor_class).map_err(PlatformManifestWireError::Manifest)?;
    let distribution_class =
        UncertaintyDistributionV1::from_id(&wire.uncertainty_profile.distribution_class)
            .map_err(PlatformManifestWireError::Manifest)?;
    let failure_policy = SensorFailurePolicyV1::from_id(&wire.failure_policy)
        .map_err(PlatformManifestWireError::Manifest)?;
    let uncertainty_profile = SensorUncertaintyProfileV1::new(
        distribution_class,
        wire.uncertainty_profile.lower_q32.0,
        wire.uncertainty_profile.upper_q32.0,
        wire.uncertainty_profile.confidence_ppm,
    )
    .map_err(PlatformManifestWireError::Manifest)?;
    let operating_range = SensorOperatingRangeV1::new(
        &wire.operating_range.unit,
        wire.operating_range.minimum_q32.0,
        wire.operating_range.maximum_q32.0,
    )
    .map_err(PlatformManifestWireError::Manifest)?;
    SensorCalibrationManifestV1::new(
        stable_id(
            "SensorCalibrationManifestV1",
            "sensor_id",
            &wire.sensor_id,
            "sensor_id",
        )?,
        sensor_class,
        nonzero_digest(
            &wire.hardware_or_adapter_digest,
            "hardware_or_adapter_digest",
        )?,
        generation(wire.calibration_generation, "calibration_generation")?,
        &wire.clock_domain,
        &wire.valid_from,
        &wire.valid_until,
        uncertainty_profile,
        operating_range,
        failure_policy,
    )
    .map_err(PlatformManifestWireError::Manifest)
}

pub fn encode_sensor_calibration_manifest_v1_json(
    value: &SensorCalibrationManifestV1,
) -> Result<Vec<u8>, PlatformManifestWireError> {
    value
        .validate()
        .map_err(PlatformManifestWireError::Manifest)?;
    let uncertainty = value.uncertainty_profile();
    let operating = value.operating_range();
    encode_json(&SensorCalibrationManifestV1Json {
        kind: "sensor_calibration_manifest_v1".to_owned(),
        sensor_id: value.sensor_id().to_string(),
        sensor_class: value.sensor_class().id().to_owned(),
        hardware_or_adapter_digest: value.hardware_or_adapter_digest().to_string(),
        calibration_generation: CanonicalU64String(value.calibration_generation().get()),
        clock_domain: value.clock_domain().to_owned(),
        valid_from: value.valid_from().as_str().to_owned(),
        valid_until: value.valid_until().as_str().to_owned(),
        uncertainty_profile: SensorUncertaintyProfileV1Json {
            distribution_class: uncertainty.distribution_class().id().to_owned(),
            lower_q32: CanonicalI64String(uncertainty.lower_q32()),
            upper_q32: CanonicalI64String(uncertainty.upper_q32()),
            confidence_ppm: uncertainty.confidence_ppm(),
        },
        operating_range: SensorOperatingRangeV1Json {
            unit: operating.unit().to_owned(),
            minimum_q32: CanonicalI64String(operating.minimum_q32()),
            maximum_q32: CanonicalI64String(operating.maximum_q32()),
        },
        failure_policy: value.failure_policy().id().to_owned(),
    })
}

fn decode_json<T>(bytes: &[u8]) -> Result<T, PlatformManifestWireError>
where
    T: for<'de> Deserialize<'de>,
{
    enforce_raw_limits(bytes)?;
    match super::strict_json::validate_json_structure(bytes) {
        Ok(()) => {}
        Err(super::strict_json::JsonStructureError::DuplicateKey) => {
            return Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::DuplicateKey,
            ));
        }
        Err(super::strict_json::JsonStructureError::InvalidJson) => {
            return Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::InvalidJson,
            ));
        }
    }
    serde_json::from_slice(bytes)
        .map_err(|_| PlatformManifestWireError::Wire(PlatformTypesWireError::InvalidJson))
}

fn encode_json<T>(value: &T) -> Result<Vec<u8>, PlatformManifestWireError>
where
    T: Serialize,
{
    let bytes = serde_json::to_vec(value)
        .map_err(|_| PlatformManifestWireError::Wire(PlatformTypesWireError::InvalidJson))?;
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformManifestWireError::Wire(
            PlatformTypesWireError::TooLarge,
        ));
    }
    Ok(bytes)
}

fn enforce_raw_limits(bytes: &[u8]) -> Result<(), PlatformManifestWireError> {
    if bytes.len() > MAX_PLATFORM_TYPES_JSON_BYTES_V1 {
        return Err(PlatformManifestWireError::Wire(
            PlatformTypesWireError::TooLarge,
        ));
    }
    std::str::from_utf8(bytes)
        .map_err(|_| PlatformManifestWireError::Wire(PlatformTypesWireError::InvalidUtf8))?;
    let mut depth = 0_usize;
    let mut in_string = false;
    let mut escaped = false;
    for byte in bytes {
        if in_string {
            if escaped {
                escaped = false;
            } else if *byte == b'\\' {
                escaped = true;
            } else if *byte == b'"' {
                in_string = false;
            }
            continue;
        }
        match byte {
            b'"' => in_string = true,
            b'{' | b'[' => {
                depth = depth.checked_add(1).ok_or(PlatformManifestWireError::Wire(
                    PlatformTypesWireError::DepthExceeded,
                ))?;
                if depth > MAX_PLATFORM_TYPES_JSON_DEPTH_V1 {
                    return Err(PlatformManifestWireError::Wire(
                        PlatformTypesWireError::DepthExceeded,
                    ));
                }
            }
            b'}' | b']' => depth = depth.saturating_sub(1),
            _ => {}
        }
    }
    Ok(())
}

fn stable_id(
    protocol_id: &'static str,
    field_path: &'static str,
    value: &str,
    field: &'static str,
) -> Result<StableId, PlatformManifestWireError> {
    let profile = identity_profile_for_protocol_field_v2(protocol_id, field_path)
        .ok_or(PlatformManifestWireError::StableId(field))?;
    StableId::with_profile(value, profile).map_err(|_| PlatformManifestWireError::StableId(field))
}

fn digest(value: &str, field: &'static str) -> Result<Digest32, PlatformManifestWireError> {
    Digest32::from_str(value).map_err(|_| PlatformManifestWireError::Digest(field))
}

fn nonzero_digest(value: &str, field: &'static str) -> Result<Digest32, PlatformManifestWireError> {
    let value = digest(value, field)?;
    if value.is_zero() {
        return Err(PlatformManifestWireError::Digest(field));
    }
    Ok(value)
}

fn generation(
    value: CanonicalU64String,
    field: &'static str,
) -> Result<Generation, PlatformManifestWireError> {
    Generation::new(value.0).map_err(|_| PlatformManifestWireError::CanonicalInteger(field))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformManifestWireError {
    Wire(PlatformTypesWireError),
    InvalidKind,
    CanonicalInteger(&'static str),
    StableId(&'static str),
    Digest(&'static str),
    Manifest(ManifestContractErrorV1),
}

impl fmt::Display for PlatformManifestWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlatformManifestWireError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn random_manifest() -> RandomStreamManifestV1 {
        RandomStreamManifestV1::new(
            id("random-manifest-1"),
            digest("seed"),
            "utility.ndu",
            id("episode-1"),
            id("decision-1"),
            id("stream-1"),
            10,
            20,
            "chacha20-counter",
            "1.0.0",
        )
        .expect("random manifest")
    }

    fn external_manifest() -> ExternalSystemManifestV1 {
        ExternalSystemManifestV1::new(
            id("external-system-1"),
            ExternalSystemClassV1::DebianHost,
            digest("host"),
            digest("os"),
            digest("packages"),
            digest("services"),
            digest("filesystem"),
            digest("identities"),
            digest("network"),
            digest("secrets"),
            "2026-09-25T01:02:03.123456Z",
            digest("authorization"),
        )
        .expect("external manifest")
    }

    fn sensor_manifest() -> SensorCalibrationManifestV1 {
        SensorCalibrationManifestV1::new(
            id("sensor-1"),
            SensorClassV1::PhysicalSensor,
            digest("hardware"),
            Generation::new(7).expect("generation"),
            "monotonic-host-clock",
            "2026-09-25T00:00:00Z",
            "2026-10-25T00:00:00Z",
            SensorUncertaintyProfileV1::new(
                UncertaintyDistributionV1::BoundedInterval,
                -100,
                100,
                950_000,
            )
            .expect("uncertainty"),
            SensorOperatingRangeV1::new("metres-per-second", -1_000, 1_000)
                .expect("operating range"),
            SensorFailurePolicyV1::ReflexStop,
        )
        .expect("sensor manifest")
    }

    #[test]
    fn all_manifest_codecs_roundtrip_through_native_validation() {
        let random = random_manifest();
        let random_json = encode_random_stream_manifest_v1_json(&random).expect("encode random");
        assert_eq!(
            decode_random_stream_manifest_v1_json(&random_json).expect("decode random"),
            random
        );

        let external = external_manifest();
        let external_json =
            encode_external_system_manifest_v1_json(&external).expect("encode external");
        assert_eq!(
            decode_external_system_manifest_v1_json(&external_json).expect("decode external"),
            external
        );

        let sensor = sensor_manifest();
        let sensor_json =
            encode_sensor_calibration_manifest_v1_json(&sensor).expect("encode sensor");
        assert_eq!(
            decode_sensor_calibration_manifest_v1_json(&sensor_json).expect("decode sensor"),
            sensor
        );
    }

    #[test]
    fn manifest_codecs_reject_duplicate_unknown_and_precision_unsafe_fields() {
        let random = String::from_utf8(
            encode_random_stream_manifest_v1_json(&random_manifest()).expect("encode random"),
        )
        .expect("utf8");
        let duplicate = random.replacen(
            "\"kind\":\"random_stream_manifest_v1\"",
            "\"kind\":\"random_stream_manifest_v1\",\"kind\":\"random_stream_manifest_v1\"",
            1,
        );
        assert_eq!(
            decode_random_stream_manifest_v1_json(duplicate.as_bytes()),
            Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::DuplicateKey
            ))
        );
        let unknown = random.replacen("{", "{\"unexpected\":true,", 1);
        assert_eq!(
            decode_random_stream_manifest_v1_json(unknown.as_bytes()),
            Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::InvalidJson
            ))
        );

        let sensor = String::from_utf8(
            encode_sensor_calibration_manifest_v1_json(&sensor_manifest()).expect("encode sensor"),
        )
        .expect("utf8");
        let overlong = sensor.replace(
            "\"minimum_q32\":\"-1000\"",
            "\"minimum_q32\":\"-92233720368547758080\"",
        );
        assert_eq!(
            decode_sensor_calibration_manifest_v1_json(overlong.as_bytes()),
            Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::InvalidJson
            ))
        );
    }

    #[test]
    fn manifest_codecs_reject_excess_raw_depth_before_deserialization() {
        let deep = format!("{}0{}", "[".repeat(18), "]".repeat(18));
        assert_eq!(
            decode_random_stream_manifest_v1_json(deep.as_bytes()),
            Err(PlatformManifestWireError::Wire(
                PlatformTypesWireError::DepthExceeded
            ))
        );
    }

    #[test]
    fn manifest_codecs_reject_numeric_enum_tokens_and_lone_surrogates() {
        let random = String::from_utf8(
            encode_random_stream_manifest_v1_json(&random_manifest()).expect("encode random"),
        )
        .expect("utf8");
        for (field, original) in [
            ("algorithm_namespace", "utility.ndu"),
            ("generator_id", "chacha20-counter"),
        ] {
            let changed = random.replace(
                &format!("\"{field}\":\"{original}\""),
                &format!("\"{field}\":\"7\""),
            );
            assert_eq!(
                decode_random_stream_manifest_v1_json(changed.as_bytes()),
                Err(PlatformManifestWireError::Manifest(
                    ManifestContractErrorV1::InvalidEnum(field)
                ))
            );
        }
        let sensor = String::from_utf8(
            encode_sensor_calibration_manifest_v1_json(&sensor_manifest()).expect("encode sensor"),
        )
        .expect("utf8");
        for surrogate in ["\\ud800", "\\udc00"] {
            let changed = random.replace(
                "\"generator_version\":\"1.0.0\"",
                &format!("\"generator_version\":\"{surrogate}\""),
            );
            assert!(decode_random_stream_manifest_v1_json(changed.as_bytes()).is_err());
            for (field, original) in [
                ("clock_domain", "monotonic-host-clock"),
                ("unit", "metres-per-second"),
            ] {
                let changed = sensor.replace(
                    &format!("\"{field}\":\"{original}\""),
                    &format!("\"{field}\":\"{surrogate}\""),
                );
                assert!(decode_sensor_calibration_manifest_v1_json(changed.as_bytes()).is_err());
            }
        }
    }

    #[test]
    fn manifest_product_decoders_reject_shared_raw_vectors() {
        let document: serde_json::Value = serde_json::from_str(include_str!(
            "../../hepta-types/MANIFEST_V1_CONFORMANCE.json"
        ))
        .expect("manifest conformance vectors");
        for vector in document["rawInvalidVectors"]
            .as_array()
            .expect("raw vectors")
        {
            let id = vector["id"].as_str().expect("vector id");
            let raw = vector["rawJson"].as_str().expect("raw JSON").as_bytes();
            let rejected = match vector["kind"].as_str().expect("vector kind") {
                "random_stream_manifest_v1" => decode_random_stream_manifest_v1_json(raw).is_err(),
                "external_system_manifest_v1" => {
                    decode_external_system_manifest_v1_json(raw).is_err()
                }
                "sensor_calibration_manifest_v1" => {
                    decode_sensor_calibration_manifest_v1_json(raw).is_err()
                }
                kind => panic!("{id}: unexpected vector kind {kind}"),
            };
            assert!(rejected, "{id}: invalid raw manifest accepted");
        }
    }
}
