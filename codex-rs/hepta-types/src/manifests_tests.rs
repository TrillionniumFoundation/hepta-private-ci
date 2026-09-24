use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture ID")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
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

#[test]
fn random_stream_manifest_binds_every_semantic_field() {
    let value = RandomStreamManifestV1::new(
        id("random-manifest-1"),
        digest("root-seed"),
        "utility.ndu",
        id("episode-1"),
        id("decision-1"),
        id("stream-1"),
        10,
        20,
        "chacha20-counter",
        "1.0.0",
    )
    .expect("random manifest");
    let base = value.semantic_digest().expect("digest");
    let changed = RandomStreamManifestV1::new(
        id("random-manifest-1"),
        digest("root-seed"),
        "utility.ndu",
        id("episode-1"),
        id("decision-1"),
        id("stream-1"),
        10,
        21,
        "chacha20-counter",
        "1.0.0",
    )
    .expect("changed manifest");
    assert_ne!(base, changed.semantic_digest().expect("changed digest"));
    assert_eq!(value.counter_start(), 10);
    assert_eq!(value.counter_end_exclusive(), 20);
}

#[test]
fn random_stream_manifest_rejects_zero_seed_invalid_range_and_enum_tokens() {
    assert!(matches!(
        RandomStreamManifestV1::new(
            id("manifest"),
            Digest32::ZERO,
            "utility.ndu",
            id("episode"),
            id("decision"),
            id("stream"),
            0,
            1,
            "generator",
            "1",
        ),
        Err(ManifestContractErrorV1::EmptyDigest("root_seed_digest"))
    ));
    assert!(matches!(
        RandomStreamManifestV1::new(
            id("manifest"),
            digest("seed"),
            "utility.ndu",
            id("episode"),
            id("decision"),
            id("stream"),
            5,
            5,
            "generator",
            "1",
        ),
        Err(ManifestContractErrorV1::InvalidCounterRange)
    ));
    assert!(matches!(
        RandomStreamManifestV1::new(
            id("manifest"),
            digest("seed"),
            "Utility NDU",
            id("episode"),
            id("decision"),
            id("stream"),
            0,
            1,
            "generator",
            "1",
        ),
        Err(ManifestContractErrorV1::InvalidEnum("algorithm_namespace"))
    ));
}

#[test]
fn external_system_manifest_rejects_unknown_classes_timestamps_and_zero_witnesses() {
    assert_eq!(
        ExternalSystemClassV1::from_id("container_host"),
        Err(ManifestContractErrorV1::InvalidEnum("system_class"))
    );
    assert!(matches!(
        ExternalSystemManifestV1::new(
            id("external"),
            ExternalSystemClassV1::PosixService,
            digest("host"),
            digest("os"),
            digest("packages"),
            digest("services"),
            digest("filesystem"),
            digest("identities"),
            digest("network"),
            digest("secrets"),
            "2026-02-30T00:00:00Z",
            digest("authorization"),
        ),
        Err(ManifestContractErrorV1::InvalidTimestamp("observed_at"))
    ));
    let mut value = external_manifest();
    value.authorization_witness = Digest32::ZERO;
    assert_eq!(
        value.validate(),
        Err(ManifestContractErrorV1::EmptyDigest(
            "authorization_witness"
        ))
    );
}

#[test]
fn external_system_manifest_digest_is_stable_and_binds_inventory() {
    let value = external_manifest();
    let first = value.semantic_digest().expect("digest");
    let second = value.semantic_digest().expect("digest");
    assert_eq!(first, second);
    let mut changed = value;
    changed.package_inventory_digest = digest("other packages");
    assert_ne!(first, changed.semantic_digest().expect("changed digest"));
}

#[test]
fn utc_timestamp_is_strict_bounded_and_chronological() {
    let leap = UtcTimestampV1::new("2028-02-29T23:59:59.1Z").expect("leap timestamp");
    let later = UtcTimestampV1::new("2028-03-01T00:00:00Z").expect("later timestamp");
    assert!(leap.is_before(&later));
    for invalid in [
        "2027-02-29T00:00:00Z",
        "2026-01-01t00:00:00Z",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T24:00:00Z",
        "2026-01-01T00:00:00.1234567Z",
    ] {
        assert!(UtcTimestampV1::new(invalid).is_err(), "accepted {invalid}");
    }
}

fn uncertainty() -> SensorUncertaintyProfileV1 {
    SensorUncertaintyProfileV1::new(
        UncertaintyDistributionV1::BoundedInterval,
        -100,
        100,
        950_000,
    )
    .expect("uncertainty")
}

fn operating_range() -> SensorOperatingRangeV1 {
    SensorOperatingRangeV1::new("metres-per-second", -1_000, 1_000).expect("operating range")
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
        uncertainty(),
        operating_range(),
        SensorFailurePolicyV1::ReflexStop,
    )
    .expect("sensor manifest")
}

#[test]
fn sensor_calibration_manifest_binds_generation_range_and_uncertainty() {
    let value = sensor_manifest();
    assert_eq!(value.calibration_generation().get(), 7);
    assert_eq!(value.uncertainty_profile().confidence_ppm(), 950_000);
    assert_eq!(value.operating_range().unit(), "metres-per-second");
    let digest = value.semantic_digest().expect("digest");
    let mut changed = value;
    changed.failure_policy = SensorFailurePolicyV1::Reject;
    assert_ne!(digest, changed.semantic_digest().expect("changed digest"));
}

#[test]
fn sensor_calibration_manifest_rejects_invalid_ranges_windows_and_enums() {
    assert_eq!(
        SensorClassV1::from_id("camera"),
        Err(ManifestContractErrorV1::InvalidEnum("sensor_class"))
    );
    assert_eq!(
        UncertaintyDistributionV1::from_id("gaussian"),
        Err(ManifestContractErrorV1::InvalidEnum(
            "uncertainty_distribution"
        ))
    );
    assert_eq!(
        SensorFailurePolicyV1::from_id("continue"),
        Err(ManifestContractErrorV1::InvalidEnum("failure_policy"))
    );
    assert_eq!(
        SensorUncertaintyProfileV1::new(UncertaintyDistributionV1::BoundedInterval, 2, 1, 1,),
        Err(ManifestContractErrorV1::InvalidUncertaintyRange)
    );
    assert_eq!(
        SensorUncertaintyProfileV1::new(
            UncertaintyDistributionV1::BoundedInterval,
            0,
            1,
            1_000_001,
        ),
        Err(ManifestContractErrorV1::InvalidConfidencePpm)
    );
    assert_eq!(
        SensorOperatingRangeV1::new("metres", 2, 1),
        Err(ManifestContractErrorV1::InvalidOperatingRange)
    );
    assert!(matches!(
        SensorCalibrationManifestV1::new(
            id("sensor"),
            SensorClassV1::Simulator,
            digest("hardware"),
            Generation::new(1).expect("generation"),
            "clock",
            "2026-10-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
            uncertainty(),
            operating_range(),
            SensorFailurePolicyV1::Reject,
        ),
        Err(ManifestContractErrorV1::InvalidValidityWindow)
    ));
}
