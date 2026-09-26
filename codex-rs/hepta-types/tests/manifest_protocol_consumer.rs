use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::ExternalSystemClassV1;
use codex_hepta_types::ExternalSystemManifestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::RandomStreamManifestV1;
use codex_hepta_types::SensorCalibrationManifestV1;
use codex_hepta_types::SensorClassV1;
use codex_hepta_types::SensorFailurePolicyV1;
use codex_hepta_types::SensorOperatingRangeV1;
use codex_hepta_types::SensorUncertaintyProfileV1;
use codex_hepta_types::StableId;
use codex_hepta_types::UncertaintyDistributionV1;
use serde_json::Map;
use serde_json::Value;

const RANDOM_KEYS: &[&str] = &[
    "kind",
    "manifest_id",
    "root_seed_digest",
    "algorithm_namespace",
    "episode_id",
    "decision_id",
    "stream_id",
    "counter_start",
    "counter_end_exclusive",
    "generator_id",
    "generator_version",
];
const EXTERNAL_KEYS: &[&str] = &[
    "kind",
    "system_id",
    "system_class",
    "host_identity_digest",
    "os_release_digest",
    "package_inventory_digest",
    "service_graph_digest",
    "filesystem_scope_digest",
    "identity_map_digest",
    "network_surface_digest",
    "secret_reference_digest",
    "observed_at",
    "authorization_witness",
];
const SENSOR_KEYS: &[&str] = &[
    "kind",
    "sensor_id",
    "sensor_class",
    "hardware_or_adapter_digest",
    "calibration_generation",
    "clock_domain",
    "valid_from",
    "valid_until",
    "uncertainty_profile",
    "operating_range",
    "failure_policy",
];
const UNCERTAINTY_KEYS: &[&str] = &[
    "distribution_class",
    "lower_q32",
    "upper_q32",
    "confidence_ppm",
];
const OPERATING_KEYS: &[&str] = &["unit", "minimum_q32", "maximum_q32"];

fn vector_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("MANIFEST_V1_CONFORMANCE.json")
}

fn object<'a>(value: &'a Value, name: &str) -> Result<&'a Map<String, Value>, String> {
    value
        .as_object()
        .ok_or_else(|| format!("{name}: object required"))
}

fn strict_keys(value: &Map<String, Value>, expected: &[&str], name: &str) -> Result<(), String> {
    let actual = value.keys().map(String::as_str).collect::<BTreeSet<_>>();
    let wanted = expected.iter().copied().collect::<BTreeSet<_>>();
    if let Some(extra) = actual.difference(&wanted).next() {
        return Err(format!("unknown field in {name}: {extra}"));
    }
    if let Some(missing) = wanted.difference(&actual).next() {
        return Err(format!("missing field in {name}: {missing}"));
    }
    Ok(())
}

fn text<'a>(value: &'a Map<String, Value>, name: &str) -> Result<&'a str, String> {
    value
        .get(name)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("{name}: text"))
}

fn stable_id(value: &Map<String, Value>, name: &str) -> Result<StableId, String> {
    StableId::new(text(value, name)?).map_err(|_| format!("{name}: stable id"))
}

fn digest(value: &Map<String, Value>, name: &str) -> Result<Digest32, String> {
    let parsed = Digest32::from_str(text(value, name)?).map_err(|_| format!("{name}: digest"))?;
    if parsed.is_zero() {
        return Err(format!("{name}: zero digest"));
    }
    Ok(parsed)
}

fn u64_text(value: &Map<String, Value>, name: &str, positive: bool) -> Result<u64, String> {
    let raw = text(value, name)?;
    if raw != "0"
        && (raw.starts_with('0') || raw.is_empty() || !raw.bytes().all(|byte| byte.is_ascii_digit()))
    {
        return Err(format!("{name}: u64"));
    }
    let parsed = raw.parse::<u64>().map_err(|_| format!("{name}: u64"))?;
    if positive && parsed == 0 {
        return Err(format!("{name}: u64"));
    }
    Ok(parsed)
}

fn i64_text(value: &Map<String, Value>, name: &str) -> Result<i64, String> {
    let raw = text(value, name)?;
    let canonical = raw == "0"
        || raw
            .strip_prefix('-')
            .map_or_else(|| !raw.starts_with('0'), |rest| !rest.is_empty() && !rest.starts_with('0'));
    if !canonical
        || raw == "-0"
        || !raw
            .trim_start_matches('-')
            .bytes()
            .all(|byte| byte.is_ascii_digit())
    {
        return Err(format!("{name}: i64"));
    }
    raw.parse::<i64>().map_err(|_| format!("{name}: i64"))
}

fn random_digest(value: &Map<String, Value>) -> Result<Digest32, String> {
    strict_keys(value, RANDOM_KEYS, "random manifest")?;
    if text(value, "kind")? != "random_stream_manifest_v1" {
        return Err("kind".to_owned());
    }
    let counter_start = u64_text(value, "counter_start", false)?;
    let counter_end_exclusive = u64_text(value, "counter_end_exclusive", false)?;
    if counter_end_exclusive <= counter_start {
        return Err("counter range".to_owned());
    }
    RandomStreamManifestV1::new(
        stable_id(value, "manifest_id")?,
        digest(value, "root_seed_digest")?,
        text(value, "algorithm_namespace")?,
        stable_id(value, "episode_id")?,
        stable_id(value, "decision_id")?,
        stable_id(value, "stream_id")?,
        counter_start,
        counter_end_exclusive,
        text(value, "generator_id")?,
        text(value, "generator_version")?,
    )
    .map_err(|error| format!("manifest: {error}"))?
    .semantic_digest()
    .map_err(|error| format!("manifest: {error}"))
}

fn external_digest(value: &Map<String, Value>) -> Result<Digest32, String> {
    strict_keys(value, EXTERNAL_KEYS, "external manifest")?;
    if text(value, "kind")? != "external_system_manifest_v1" {
        return Err("kind".to_owned());
    }
    let system_class = ExternalSystemClassV1::from_id(text(value, "system_class")?)
        .map_err(|_| "system_class".to_owned())?;
    ExternalSystemManifestV1::new(
        stable_id(value, "system_id")?,
        system_class,
        digest(value, "host_identity_digest")?,
        digest(value, "os_release_digest")?,
        digest(value, "package_inventory_digest")?,
        digest(value, "service_graph_digest")?,
        digest(value, "filesystem_scope_digest")?,
        digest(value, "identity_map_digest")?,
        digest(value, "network_surface_digest")?,
        digest(value, "secret_reference_digest")?,
        text(value, "observed_at")?,
        digest(value, "authorization_witness")?,
    )
    .map_err(|error| {
        if format!("{error:?}").contains("InvalidTimestamp") {
            "timestamp".to_owned()
        } else {
            format!("manifest: {error}")
        }
    })?
    .semantic_digest()
    .map_err(|error| format!("manifest: {error}"))
}

fn sensor_digest(value: &Map<String, Value>) -> Result<Digest32, String> {
    strict_keys(value, SENSOR_KEYS, "sensor manifest")?;
    if text(value, "kind")? != "sensor_calibration_manifest_v1" {
        return Err("kind".to_owned());
    }
    let uncertainty = object(
        value
            .get("uncertainty_profile")
            .ok_or_else(|| "missing uncertainty_profile".to_owned())?,
        "uncertainty_profile",
    )?;
    strict_keys(uncertainty, UNCERTAINTY_KEYS, "uncertainty_profile")?;
    let operating = object(
        value
            .get("operating_range")
            .ok_or_else(|| "missing operating_range".to_owned())?,
        "operating_range",
    )?;
    strict_keys(operating, OPERATING_KEYS, "operating_range")?;

    let sensor_class = SensorClassV1::from_id(text(value, "sensor_class")?)
        .map_err(|_| "sensor_class".to_owned())?;
    let distribution = UncertaintyDistributionV1::from_id(text(
        uncertainty,
        "distribution_class",
    )?)
    .map_err(|_| "distribution_class".to_owned())?;
    let failure_policy = SensorFailurePolicyV1::from_id(text(value, "failure_policy")?)
        .map_err(|_| "failure_policy".to_owned())?;
    let confidence = uncertainty
        .get("confidence_ppm")
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .ok_or_else(|| "confidence".to_owned())?;
    if confidence == 0 || confidence > 1_000_000 {
        return Err("confidence".to_owned());
    }
    let uncertainty = SensorUncertaintyProfileV1::new(
        distribution,
        i64_text(uncertainty, "lower_q32")?,
        i64_text(uncertainty, "upper_q32")?,
        confidence,
    )
    .map_err(|error| format!("uncertainty: {error}"))?;
    let operating = SensorOperatingRangeV1::new(
        text(operating, "unit")?,
        i64_text(operating, "minimum_q32")?,
        i64_text(operating, "maximum_q32")?,
    )
    .map_err(|error| format!("operating: {error}"))?;
    SensorCalibrationManifestV1::new(
        stable_id(value, "sensor_id")?,
        sensor_class,
        digest(value, "hardware_or_adapter_digest")?,
        Generation::new(u64_text(value, "calibration_generation", true)?)
            .map_err(|_| "calibration_generation: u64".to_owned())?,
        text(value, "clock_domain")?,
        text(value, "valid_from")?,
        text(value, "valid_until")?,
        uncertainty,
        operating,
        failure_policy,
    )
    .map_err(|error| {
        let debug = format!("{error:?}");
        if debug.contains("InvalidValidityWindow") {
            "validity window".to_owned()
        } else if debug.contains("InvalidTimestamp") {
            "timestamp".to_owned()
        } else {
            format!("manifest: {error}")
        }
    })?
    .semantic_digest()
    .map_err(|error| format!("manifest: {error}"))
}

fn semantic_digest(value: &Value) -> Result<Digest32, String> {
    let object = object(value, "manifest")?;
    match text(object, "kind")? {
        "random_stream_manifest_v1" => random_digest(object),
        "external_system_manifest_v1" => external_digest(object),
        "sensor_calibration_manifest_v1" => sensor_digest(object),
        _ => Err("kind".to_owned()),
    }
}

#[test]
fn strict_json_transport_matches_native_manifest_semantics() {
    let document: Value = serde_json::from_str(
        &fs::read_to_string(vector_path()).expect("read manifest vectors"),
    )
    .expect("parse manifest vectors");
    let valid = document["validVectors"].as_array().expect("valid vectors");
    for vector in valid {
        let id = vector["id"].as_str().expect("vector id");
        let expected = vector["expectedHptcSha256"]
            .as_str()
            .expect("expected digest");
        let actual = semantic_digest(&vector["json"])
            .unwrap_or_else(|error| panic!("{id}: valid vector rejected: {error}"));
        assert_eq!(actual.to_string(), expected, "{id}");
    }

    let invalid = document["invalidVectors"]
        .as_array()
        .expect("invalid vectors");
    for vector in invalid {
        let id = vector["id"].as_str().expect("vector id");
        let expected = vector["expectedError"].as_str().expect("expected error");
        let error = semantic_digest(&vector["json"])
            .unwrap_err_or_else(|_| panic!("{id}: invalid vector accepted"));
        assert!(
            error.contains(expected),
            "{id}: expected {expected:?}, got {error:?}"
        );
    }
}

trait ResultExt<T, E> {
    fn unwrap_err_or_else(self, accepted: impl FnOnce(T) -> !) -> E;
}

impl<T, E> ResultExt<T, E> for Result<T, E> {
    fn unwrap_err_or_else(self, accepted: impl FnOnce(T) -> !) -> E {
        match self {
            Ok(value) => accepted(value),
            Err(error) => error,
        }
    }
}
