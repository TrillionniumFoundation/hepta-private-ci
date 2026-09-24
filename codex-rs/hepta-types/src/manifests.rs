use std::error::Error;
use std::fmt;

use crate::BoundedText;
use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalMapEntryV1;
use crate::CanonicalValueV1;
use crate::Digest32;
use crate::Generation;
use crate::StableId;
use crate::canonical_digest_v1;

pub const MAX_MANIFEST_ENUM_BYTES_V1: usize = 64;
pub const MAX_MANIFEST_VERSION_BYTES_V1: usize = 64;
pub const MAX_MANIFEST_TIMESTAMP_BYTES_V1: usize = 64;
pub const MAX_CLOCK_DOMAIN_BYTES_V1: usize = 128;
pub const MAX_OPERATING_UNIT_BYTES_V1: usize = 64;
pub const MAX_CONFIDENCE_PPM_V1: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ManifestContractErrorV1 {
    InvalidText(&'static str),
    InvalidEnum(&'static str),
    EmptyDigest(&'static str),
    InvalidCounterRange,
    InvalidTimestamp(&'static str),
    InvalidValidityWindow,
    InvalidUncertaintyRange,
    InvalidConfidencePpm,
    InvalidOperatingRange,
    InvalidTypeIdentity,
    Canonical(CanonicalDigestError),
}

impl fmt::Display for ManifestContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ManifestContractErrorV1 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UtcTimestampV1 {
    text: BoundedText<MAX_MANIFEST_TIMESTAMP_BYTES_V1>,
    sort_key: [u32; 7],
}

impl UtcTimestampV1 {
    pub fn new(value: &str) -> Result<Self, ManifestContractErrorV1> {
        let text = BoundedText::try_from_str(value)
            .map_err(|_| ManifestContractErrorV1::InvalidTimestamp("timestamp"))?;
        let sort_key = parse_utc_timestamp(value)
            .ok_or(ManifestContractErrorV1::InvalidTimestamp("timestamp"))?;
        Ok(Self { text, sort_key })
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        self.text.as_str()
    }

    fn is_before(&self, other: &Self) -> bool {
        self.sort_key < other.sort_key
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RandomStreamManifestV1 {
    manifest_id: StableId,
    root_seed_digest: Digest32,
    algorithm_namespace: BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>,
    episode_id: StableId,
    decision_id: StableId,
    stream_id: StableId,
    counter_start: u64,
    counter_end_exclusive: u64,
    generator_id: BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>,
    generator_version: BoundedText<MAX_MANIFEST_VERSION_BYTES_V1>,
}

impl RandomStreamManifestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        manifest_id: StableId,
        root_seed_digest: Digest32,
        algorithm_namespace: &str,
        episode_id: StableId,
        decision_id: StableId,
        stream_id: StableId,
        counter_start: u64,
        counter_end_exclusive: u64,
        generator_id: &str,
        generator_version: &str,
    ) -> Result<Self, ManifestContractErrorV1> {
        let value = Self {
            manifest_id,
            root_seed_digest,
            algorithm_namespace: bounded_enum(algorithm_namespace, "algorithm_namespace")?,
            episode_id,
            decision_id,
            stream_id,
            counter_start,
            counter_end_exclusive,
            generator_id: bounded_enum(generator_id, "generator_id")?,
            generator_version: BoundedText::try_from_str(generator_version)
                .map_err(|_| ManifestContractErrorV1::InvalidText("generator_version"))?,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ManifestContractErrorV1> {
        require_digest(self.root_seed_digest, "root_seed_digest")?;
        if self.counter_end_exclusive <= self.counter_start {
            return Err(ManifestContractErrorV1::InvalidCounterRange);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, ManifestContractErrorV1> {
        self.validate()?;
        let type_id = manifest_type_id("platform.types:random-stream-manifest-v1")?;
        let fields = [
            CanonicalFieldV1 {
                name: "algorithm_namespace",
                value: CanonicalValueV1::Text(self.algorithm_namespace.as_str()),
            },
            CanonicalFieldV1 {
                name: "counter_end_exclusive",
                value: CanonicalValueV1::U64(self.counter_end_exclusive),
            },
            CanonicalFieldV1 {
                name: "counter_start",
                value: CanonicalValueV1::U64(self.counter_start),
            },
            CanonicalFieldV1 {
                name: "decision_id",
                value: CanonicalValueV1::StableId(&self.decision_id),
            },
            CanonicalFieldV1 {
                name: "episode_id",
                value: CanonicalValueV1::StableId(&self.episode_id),
            },
            CanonicalFieldV1 {
                name: "generator_id",
                value: CanonicalValueV1::Text(self.generator_id.as_str()),
            },
            CanonicalFieldV1 {
                name: "generator_version",
                value: CanonicalValueV1::Text(self.generator_version.as_str()),
            },
            CanonicalFieldV1 {
                name: "manifest_id",
                value: CanonicalValueV1::StableId(&self.manifest_id),
            },
            CanonicalFieldV1 {
                name: "root_seed_digest",
                value: CanonicalValueV1::Digest(self.root_seed_digest),
            },
            CanonicalFieldV1 {
                name: "stream_id",
                value: CanonicalValueV1::StableId(&self.stream_id),
            },
        ];
        canonical_digest_v1(&type_id, 1, &fields).map_err(ManifestContractErrorV1::Canonical)
    }

    #[must_use]
    pub fn manifest_id(&self) -> &StableId {
        &self.manifest_id
    }

    #[must_use]
    pub const fn root_seed_digest(&self) -> Digest32 {
        self.root_seed_digest
    }

    #[must_use]
    pub fn algorithm_namespace(&self) -> &str {
        self.algorithm_namespace.as_str()
    }

    #[must_use]
    pub fn episode_id(&self) -> &StableId {
        &self.episode_id
    }

    #[must_use]
    pub fn decision_id(&self) -> &StableId {
        &self.decision_id
    }

    #[must_use]
    pub fn stream_id(&self) -> &StableId {
        &self.stream_id
    }

    #[must_use]
    pub const fn counter_start(&self) -> u64 {
        self.counter_start
    }

    #[must_use]
    pub const fn counter_end_exclusive(&self) -> u64 {
        self.counter_end_exclusive
    }

    #[must_use]
    pub fn generator_id(&self) -> &str {
        self.generator_id.as_str()
    }

    #[must_use]
    pub fn generator_version(&self) -> &str {
        self.generator_version.as_str()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExternalSystemClassV1 {
    DebianHost,
    DebianService,
    PosixHost,
    PosixService,
    DigitalAdapter,
}

impl ExternalSystemClassV1 {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::DebianHost => "debian_host",
            Self::DebianService => "debian_service",
            Self::PosixHost => "posix_host",
            Self::PosixService => "posix_service",
            Self::DigitalAdapter => "digital_adapter",
        }
    }

    pub fn from_id(value: &str) -> Result<Self, ManifestContractErrorV1> {
        match value {
            "debian_host" => Ok(Self::DebianHost),
            "debian_service" => Ok(Self::DebianService),
            "posix_host" => Ok(Self::PosixHost),
            "posix_service" => Ok(Self::PosixService),
            "digital_adapter" => Ok(Self::DigitalAdapter),
            _ => Err(ManifestContractErrorV1::InvalidEnum("system_class")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExternalSystemManifestV1 {
    system_id: StableId,
    system_class: ExternalSystemClassV1,
    host_identity_digest: Digest32,
    os_release_digest: Digest32,
    package_inventory_digest: Digest32,
    service_graph_digest: Digest32,
    filesystem_scope_digest: Digest32,
    identity_map_digest: Digest32,
    network_surface_digest: Digest32,
    secret_reference_digest: Digest32,
    observed_at: UtcTimestampV1,
    authorization_witness: Digest32,
}

impl ExternalSystemManifestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        system_id: StableId,
        system_class: ExternalSystemClassV1,
        host_identity_digest: Digest32,
        os_release_digest: Digest32,
        package_inventory_digest: Digest32,
        service_graph_digest: Digest32,
        filesystem_scope_digest: Digest32,
        identity_map_digest: Digest32,
        network_surface_digest: Digest32,
        secret_reference_digest: Digest32,
        observed_at: &str,
        authorization_witness: Digest32,
    ) -> Result<Self, ManifestContractErrorV1> {
        let value = Self {
            system_id,
            system_class,
            host_identity_digest,
            os_release_digest,
            package_inventory_digest,
            service_graph_digest,
            filesystem_scope_digest,
            identity_map_digest,
            network_surface_digest,
            secret_reference_digest,
            observed_at: UtcTimestampV1::new(observed_at)
                .map_err(|_| ManifestContractErrorV1::InvalidTimestamp("observed_at"))?,
            authorization_witness,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ManifestContractErrorV1> {
        for (name, digest) in [
            ("host_identity_digest", self.host_identity_digest),
            ("os_release_digest", self.os_release_digest),
            ("package_inventory_digest", self.package_inventory_digest),
            ("service_graph_digest", self.service_graph_digest),
            ("filesystem_scope_digest", self.filesystem_scope_digest),
            ("identity_map_digest", self.identity_map_digest),
            ("network_surface_digest", self.network_surface_digest),
            ("secret_reference_digest", self.secret_reference_digest),
            ("authorization_witness", self.authorization_witness),
        ] {
            require_digest(digest, name)?;
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, ManifestContractErrorV1> {
        self.validate()?;
        let type_id = manifest_type_id("platform.types:external-system-manifest-v1")?;
        let fields = [
            CanonicalFieldV1 {
                name: "authorization_witness",
                value: CanonicalValueV1::Digest(self.authorization_witness),
            },
            CanonicalFieldV1 {
                name: "filesystem_scope_digest",
                value: CanonicalValueV1::Digest(self.filesystem_scope_digest),
            },
            CanonicalFieldV1 {
                name: "host_identity_digest",
                value: CanonicalValueV1::Digest(self.host_identity_digest),
            },
            CanonicalFieldV1 {
                name: "identity_map_digest",
                value: CanonicalValueV1::Digest(self.identity_map_digest),
            },
            CanonicalFieldV1 {
                name: "network_surface_digest",
                value: CanonicalValueV1::Digest(self.network_surface_digest),
            },
            CanonicalFieldV1 {
                name: "observed_at",
                value: CanonicalValueV1::Text(self.observed_at.as_str()),
            },
            CanonicalFieldV1 {
                name: "os_release_digest",
                value: CanonicalValueV1::Digest(self.os_release_digest),
            },
            CanonicalFieldV1 {
                name: "package_inventory_digest",
                value: CanonicalValueV1::Digest(self.package_inventory_digest),
            },
            CanonicalFieldV1 {
                name: "secret_reference_digest",
                value: CanonicalValueV1::Digest(self.secret_reference_digest),
            },
            CanonicalFieldV1 {
                name: "service_graph_digest",
                value: CanonicalValueV1::Digest(self.service_graph_digest),
            },
            CanonicalFieldV1 {
                name: "system_class",
                value: CanonicalValueV1::Text(self.system_class.id()),
            },
            CanonicalFieldV1 {
                name: "system_id",
                value: CanonicalValueV1::StableId(&self.system_id),
            },
        ];
        canonical_digest_v1(&type_id, 1, &fields).map_err(ManifestContractErrorV1::Canonical)
    }

    #[must_use]
    pub fn system_id(&self) -> &StableId {
        &self.system_id
    }

    #[must_use]
    pub const fn system_class(&self) -> ExternalSystemClassV1 {
        self.system_class
    }

    #[must_use]
    pub const fn host_identity_digest(&self) -> Digest32 {
        self.host_identity_digest
    }

    #[must_use]
    pub const fn os_release_digest(&self) -> Digest32 {
        self.os_release_digest
    }

    #[must_use]
    pub const fn package_inventory_digest(&self) -> Digest32 {
        self.package_inventory_digest
    }

    #[must_use]
    pub const fn service_graph_digest(&self) -> Digest32 {
        self.service_graph_digest
    }

    #[must_use]
    pub const fn filesystem_scope_digest(&self) -> Digest32 {
        self.filesystem_scope_digest
    }

    #[must_use]
    pub const fn identity_map_digest(&self) -> Digest32 {
        self.identity_map_digest
    }

    #[must_use]
    pub const fn network_surface_digest(&self) -> Digest32 {
        self.network_surface_digest
    }

    #[must_use]
    pub const fn secret_reference_digest(&self) -> Digest32 {
        self.secret_reference_digest
    }

    #[must_use]
    pub fn observed_at(&self) -> &UtcTimestampV1 {
        &self.observed_at
    }

    #[must_use]
    pub const fn authorization_witness(&self) -> Digest32 {
        self.authorization_witness
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorClassV1 {
    PhysicalSensor,
    BrowserSession,
    MatrixSession,
    ProviderRuntime,
    FilesystemMount,
    ServiceAdapter,
    Simulator,
}

impl SensorClassV1 {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::PhysicalSensor => "physical_sensor",
            Self::BrowserSession => "browser_session",
            Self::MatrixSession => "matrix_session",
            Self::ProviderRuntime => "provider_runtime",
            Self::FilesystemMount => "filesystem_mount",
            Self::ServiceAdapter => "service_adapter",
            Self::Simulator => "simulator",
        }
    }

    pub fn from_id(value: &str) -> Result<Self, ManifestContractErrorV1> {
        match value {
            "physical_sensor" => Ok(Self::PhysicalSensor),
            "browser_session" => Ok(Self::BrowserSession),
            "matrix_session" => Ok(Self::MatrixSession),
            "provider_runtime" => Ok(Self::ProviderRuntime),
            "filesystem_mount" => Ok(Self::FilesystemMount),
            "service_adapter" => Ok(Self::ServiceAdapter),
            "simulator" => Ok(Self::Simulator),
            _ => Err(ManifestContractErrorV1::InvalidEnum("sensor_class")),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UncertaintyDistributionV1 {
    BoundedInterval,
    NormalApproximation,
    EmpiricalQuantiles,
}

impl UncertaintyDistributionV1 {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::BoundedInterval => "bounded_interval",
            Self::NormalApproximation => "normal_approximation",
            Self::EmpiricalQuantiles => "empirical_quantiles",
        }
    }

    pub fn from_id(value: &str) -> Result<Self, ManifestContractErrorV1> {
        match value {
            "bounded_interval" => Ok(Self::BoundedInterval),
            "normal_approximation" => Ok(Self::NormalApproximation),
            "empirical_quantiles" => Ok(Self::EmpiricalQuantiles),
            _ => Err(ManifestContractErrorV1::InvalidEnum(
                "uncertainty_distribution",
            )),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SensorFailurePolicyV1 {
    Reject,
    Degrade,
    Abstain,
    ReflexStop,
}

impl SensorFailurePolicyV1 {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::Reject => "reject",
            Self::Degrade => "degrade",
            Self::Abstain => "abstain",
            Self::ReflexStop => "reflex_stop",
        }
    }

    pub fn from_id(value: &str) -> Result<Self, ManifestContractErrorV1> {
        match value {
            "reject" => Ok(Self::Reject),
            "degrade" => Ok(Self::Degrade),
            "abstain" => Ok(Self::Abstain),
            "reflex_stop" => Ok(Self::ReflexStop),
            _ => Err(ManifestContractErrorV1::InvalidEnum("failure_policy")),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct SensorUncertaintyProfileV1 {
    distribution_class: UncertaintyDistributionV1,
    lower_q32: i64,
    upper_q32: i64,
    confidence_ppm: u32,
}

impl SensorUncertaintyProfileV1 {
    pub fn new(
        distribution_class: UncertaintyDistributionV1,
        lower_q32: i64,
        upper_q32: i64,
        confidence_ppm: u32,
    ) -> Result<Self, ManifestContractErrorV1> {
        if lower_q32 > upper_q32 {
            return Err(ManifestContractErrorV1::InvalidUncertaintyRange);
        }
        if confidence_ppm == 0 || confidence_ppm > MAX_CONFIDENCE_PPM_V1 {
            return Err(ManifestContractErrorV1::InvalidConfidencePpm);
        }
        Ok(Self {
            distribution_class,
            lower_q32,
            upper_q32,
            confidence_ppm,
        })
    }

    #[must_use]
    pub const fn distribution_class(self) -> UncertaintyDistributionV1 {
        self.distribution_class
    }

    #[must_use]
    pub const fn lower_q32(self) -> i64 {
        self.lower_q32
    }

    #[must_use]
    pub const fn upper_q32(self) -> i64 {
        self.upper_q32
    }

    #[must_use]
    pub const fn confidence_ppm(self) -> u32 {
        self.confidence_ppm
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorOperatingRangeV1 {
    unit: BoundedText<MAX_OPERATING_UNIT_BYTES_V1>,
    minimum_q32: i64,
    maximum_q32: i64,
}

impl SensorOperatingRangeV1 {
    pub fn new(
        unit: &str,
        minimum_q32: i64,
        maximum_q32: i64,
    ) -> Result<Self, ManifestContractErrorV1> {
        if minimum_q32 > maximum_q32 {
            return Err(ManifestContractErrorV1::InvalidOperatingRange);
        }
        Ok(Self {
            unit: BoundedText::try_from_str(unit)
                .map_err(|_| ManifestContractErrorV1::InvalidText("operating_unit"))?,
            minimum_q32,
            maximum_q32,
        })
    }

    #[must_use]
    pub fn unit(&self) -> &str {
        self.unit.as_str()
    }

    #[must_use]
    pub const fn minimum_q32(&self) -> i64 {
        self.minimum_q32
    }

    #[must_use]
    pub const fn maximum_q32(&self) -> i64 {
        self.maximum_q32
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorCalibrationManifestV1 {
    sensor_id: StableId,
    sensor_class: SensorClassV1,
    hardware_or_adapter_digest: Digest32,
    calibration_generation: Generation,
    clock_domain: BoundedText<MAX_CLOCK_DOMAIN_BYTES_V1>,
    valid_from: UtcTimestampV1,
    valid_until: UtcTimestampV1,
    uncertainty_profile: SensorUncertaintyProfileV1,
    operating_range: SensorOperatingRangeV1,
    failure_policy: SensorFailurePolicyV1,
}

impl SensorCalibrationManifestV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        sensor_id: StableId,
        sensor_class: SensorClassV1,
        hardware_or_adapter_digest: Digest32,
        calibration_generation: Generation,
        clock_domain: &str,
        valid_from: &str,
        valid_until: &str,
        uncertainty_profile: SensorUncertaintyProfileV1,
        operating_range: SensorOperatingRangeV1,
        failure_policy: SensorFailurePolicyV1,
    ) -> Result<Self, ManifestContractErrorV1> {
        let value = Self {
            sensor_id,
            sensor_class,
            hardware_or_adapter_digest,
            calibration_generation,
            clock_domain: BoundedText::try_from_str(clock_domain)
                .map_err(|_| ManifestContractErrorV1::InvalidText("clock_domain"))?,
            valid_from: UtcTimestampV1::new(valid_from)
                .map_err(|_| ManifestContractErrorV1::InvalidTimestamp("valid_from"))?,
            valid_until: UtcTimestampV1::new(valid_until)
                .map_err(|_| ManifestContractErrorV1::InvalidTimestamp("valid_until"))?,
            uncertainty_profile,
            operating_range,
            failure_policy,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ManifestContractErrorV1> {
        require_digest(
            self.hardware_or_adapter_digest,
            "hardware_or_adapter_digest",
        )?;
        if !self.valid_from.is_before(&self.valid_until) {
            return Err(ManifestContractErrorV1::InvalidValidityWindow);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, ManifestContractErrorV1> {
        self.validate()?;
        let type_id = manifest_type_id("platform.types:sensor-calibration-manifest-v1")?;
        let uncertainty_entries = [
            CanonicalMapEntryV1 {
                key: "confidence_ppm",
                value: CanonicalValueV1::U64(u64::from(self.uncertainty_profile.confidence_ppm)),
            },
            CanonicalMapEntryV1 {
                key: "distribution_class",
                value: CanonicalValueV1::Text(self.uncertainty_profile.distribution_class.id()),
            },
            CanonicalMapEntryV1 {
                key: "lower_q32",
                value: CanonicalValueV1::I64(self.uncertainty_profile.lower_q32),
            },
            CanonicalMapEntryV1 {
                key: "upper_q32",
                value: CanonicalValueV1::I64(self.uncertainty_profile.upper_q32),
            },
        ];
        let operating_entries = [
            CanonicalMapEntryV1 {
                key: "maximum_q32",
                value: CanonicalValueV1::I64(self.operating_range.maximum_q32),
            },
            CanonicalMapEntryV1 {
                key: "minimum_q32",
                value: CanonicalValueV1::I64(self.operating_range.minimum_q32),
            },
            CanonicalMapEntryV1 {
                key: "unit",
                value: CanonicalValueV1::Text(self.operating_range.unit.as_str()),
            },
        ];
        let fields = [
            CanonicalFieldV1 {
                name: "calibration_generation",
                value: CanonicalValueV1::U64(self.calibration_generation.get()),
            },
            CanonicalFieldV1 {
                name: "clock_domain",
                value: CanonicalValueV1::Text(self.clock_domain.as_str()),
            },
            CanonicalFieldV1 {
                name: "failure_policy",
                value: CanonicalValueV1::Text(self.failure_policy.id()),
            },
            CanonicalFieldV1 {
                name: "hardware_or_adapter_digest",
                value: CanonicalValueV1::Digest(self.hardware_or_adapter_digest),
            },
            CanonicalFieldV1 {
                name: "operating_range",
                value: CanonicalValueV1::Map(&operating_entries),
            },
            CanonicalFieldV1 {
                name: "sensor_class",
                value: CanonicalValueV1::Text(self.sensor_class.id()),
            },
            CanonicalFieldV1 {
                name: "sensor_id",
                value: CanonicalValueV1::StableId(&self.sensor_id),
            },
            CanonicalFieldV1 {
                name: "uncertainty_profile",
                value: CanonicalValueV1::Map(&uncertainty_entries),
            },
            CanonicalFieldV1 {
                name: "valid_from",
                value: CanonicalValueV1::Text(self.valid_from.as_str()),
            },
            CanonicalFieldV1 {
                name: "valid_until",
                value: CanonicalValueV1::Text(self.valid_until.as_str()),
            },
        ];
        canonical_digest_v1(&type_id, 1, &fields).map_err(ManifestContractErrorV1::Canonical)
    }

    #[must_use]
    pub fn sensor_id(&self) -> &StableId {
        &self.sensor_id
    }

    #[must_use]
    pub const fn sensor_class(&self) -> SensorClassV1 {
        self.sensor_class
    }

    #[must_use]
    pub const fn hardware_or_adapter_digest(&self) -> Digest32 {
        self.hardware_or_adapter_digest
    }

    #[must_use]
    pub const fn calibration_generation(&self) -> Generation {
        self.calibration_generation
    }

    #[must_use]
    pub fn clock_domain(&self) -> &str {
        self.clock_domain.as_str()
    }

    #[must_use]
    pub fn valid_from(&self) -> &UtcTimestampV1 {
        &self.valid_from
    }

    #[must_use]
    pub fn valid_until(&self) -> &UtcTimestampV1 {
        &self.valid_until
    }

    #[must_use]
    pub const fn uncertainty_profile(&self) -> SensorUncertaintyProfileV1 {
        self.uncertainty_profile
    }

    #[must_use]
    pub fn operating_range(&self) -> &SensorOperatingRangeV1 {
        &self.operating_range
    }

    #[must_use]
    pub const fn failure_policy(&self) -> SensorFailurePolicyV1 {
        self.failure_policy
    }
}

fn manifest_type_id(value: &str) -> Result<StableId, ManifestContractErrorV1> {
    StableId::new(value).map_err(|_| ManifestContractErrorV1::InvalidTypeIdentity)
}

fn require_digest(digest: Digest32, field: &'static str) -> Result<(), ManifestContractErrorV1> {
    if digest.is_zero() {
        return Err(ManifestContractErrorV1::EmptyDigest(field));
    }
    Ok(())
}

fn bounded_enum(
    value: &str,
    field: &'static str,
) -> Result<BoundedText<MAX_MANIFEST_ENUM_BYTES_V1>, ManifestContractErrorV1> {
    let bytes = value.as_bytes();
    if bytes.is_empty()
        || !bytes[0].is_ascii_lowercase()
        || !bytes[bytes.len() - 1].is_ascii_alphanumeric()
        || bytes.iter().any(|byte| {
            !(byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(byte, b'.' | b'_' | b'-' | b':'))
        })
    {
        return Err(ManifestContractErrorV1::InvalidEnum(field));
    }
    BoundedText::try_from_str(value).map_err(|_| ManifestContractErrorV1::InvalidEnum(field))
}

fn parse_utc_timestamp(value: &str) -> Option<[u32; 7]> {
    let bytes = value.as_bytes();
    if !(20..=27).contains(&bytes.len()) || !bytes.is_ascii() {
        return None;
    }
    if bytes.get(4) != Some(&b'-')
        || bytes.get(7) != Some(&b'-')
        || bytes.get(10) != Some(&b'T')
        || bytes.get(13) != Some(&b':')
        || bytes.get(16) != Some(&b':')
        || bytes.last() != Some(&b'Z')
    {
        return None;
    }
    let year = parse_digits(bytes, 0, 4)?;
    let month = parse_digits(bytes, 5, 2)?;
    let day = parse_digits(bytes, 8, 2)?;
    let hour = parse_digits(bytes, 11, 2)?;
    let minute = parse_digits(bytes, 14, 2)?;
    let second = parse_digits(bytes, 17, 2)?;
    if year == 0
        || !(1..=12).contains(&month)
        || day == 0
        || day > days_in_month(year, month)
        || hour > 23
        || minute > 59
        || second > 59
    {
        return None;
    }
    let micros = if bytes.len() == 20 {
        0
    } else {
        if bytes.get(19) != Some(&b'.') {
            return None;
        }
        let digits = bytes.len() - 21;
        if !(1..=6).contains(&digits) {
            return None;
        }
        let fraction = parse_digits(bytes, 20, digits)?;
        fraction.checked_mul(10_u32.pow(u32::try_from(6 - digits).ok()?))?
    };
    Some([year, month, day, hour, minute, second, micros])
}

fn parse_digits(bytes: &[u8], start: usize, count: usize) -> Option<u32> {
    let mut value = 0_u32;
    for byte in bytes.get(start..start.checked_add(count)?)? {
        if !byte.is_ascii_digit() {
            return None;
        }
        value = value.checked_mul(10)?.checked_add(u32::from(byte - b'0'))?;
    }
    Some(value)
}

const fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if is_leap_year(year) => 29,
        2 => 28,
        _ => 0,
    }
}

const fn is_leap_year(year: u32) -> bool {
    year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400))
}

#[cfg(test)]
#[path = "manifests_tests.rs"]
mod tests;
