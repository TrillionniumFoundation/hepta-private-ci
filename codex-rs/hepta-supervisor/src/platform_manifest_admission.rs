//! Product-owner admission for external-system and sensor manifests.
//!
//! `platform.types` validates and commits the values. The supervisor supplies
//! the product-specific identity, hardware, authorization and generation pins
//! that turn a valid manifest into an owner-bound, still non-authorizing
//! admission receipt.

use std::error::Error;
use std::fmt;

use codex_hepta_types::CanonicalDigestError;
use codex_hepta_types::CanonicalFieldV1;
use codex_hepta_types::CanonicalValueV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ExternalSystemClassV1;
use codex_hepta_types::ExternalSystemManifestV1;
use codex_hepta_types::Generation;
use codex_hepta_types::ManifestContractErrorV1;
use codex_hepta_types::NonAuthorizingPosture;
use codex_hepta_types::SensorCalibrationManifestV1;
use codex_hepta_types::SensorClassV1;
use codex_hepta_types::SensorFailurePolicyV1;
use codex_hepta_types::StableId;
use codex_hepta_types::canonical_digest_v1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExternalSystemAdmissionPolicyV1 {
    system_id: StableId,
    system_class: ExternalSystemClassV1,
    host_identity_digest: Digest32,
    authorization_witness: Digest32,
    policy_digest: Digest32,
}

impl ExternalSystemAdmissionPolicyV1 {
    pub fn new(
        system_id: StableId,
        system_class: ExternalSystemClassV1,
        host_identity_digest: Digest32,
        authorization_witness: Digest32,
    ) -> Result<Self, PlatformManifestAdmissionErrorV1> {
        require_digest(host_identity_digest, "host identity")?;
        require_digest(authorization_witness, "authorization witness")?;
        let type_id = policy_type("runtime.supervisor:external-system-admission-policy-v1")?;
        let fields = [
            CanonicalFieldV1 {
                name: "authorization_witness",
                value: CanonicalValueV1::Digest(authorization_witness),
            },
            CanonicalFieldV1 {
                name: "host_identity_digest",
                value: CanonicalValueV1::Digest(host_identity_digest),
            },
            CanonicalFieldV1 {
                name: "system_class",
                value: CanonicalValueV1::Text(system_class.id()),
            },
            CanonicalFieldV1 {
                name: "system_id",
                value: CanonicalValueV1::StableId(&system_id),
            },
        ];
        let policy_digest = canonical_digest_v1(&type_id, 1, &fields)
            .map_err(PlatformManifestAdmissionErrorV1::Canonical)?;
        Ok(Self {
            system_id,
            system_class,
            host_identity_digest,
            authorization_witness,
            policy_digest,
        })
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExternalSystemAdmissionV1 {
    manifest_digest: Digest32,
    policy_digest: Digest32,
    system_id: StableId,
    host_identity_digest: Digest32,
    observed_at: String,
    authority: NonAuthorizingPosture,
}

impl ExternalSystemAdmissionV1 {
    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub fn system_id(&self) -> &StableId {
        &self.system_id
    }

    #[must_use]
    pub const fn host_identity_digest(&self) -> Digest32 {
        self.host_identity_digest
    }

    #[must_use]
    pub fn observed_at(&self) -> &str {
        &self.observed_at
    }

    #[must_use]
    pub const fn authority(&self) -> NonAuthorizingPosture {
        self.authority
    }
}

pub fn admit_external_system_manifest_v1(
    policy: &ExternalSystemAdmissionPolicyV1,
    manifest: &ExternalSystemManifestV1,
) -> Result<ExternalSystemAdmissionV1, PlatformManifestAdmissionErrorV1> {
    manifest
        .validate()
        .map_err(PlatformManifestAdmissionErrorV1::Manifest)?;
    if manifest.system_id() != &policy.system_id {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "system id",
        ));
    }
    if manifest.system_class() != policy.system_class {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "system class",
        ));
    }
    if manifest.host_identity_digest() != policy.host_identity_digest {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "host identity",
        ));
    }
    if manifest.authorization_witness() != policy.authorization_witness {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "authorization witness",
        ));
    }
    let manifest_digest = manifest
        .semantic_digest()
        .map_err(PlatformManifestAdmissionErrorV1::Manifest)?;
    Ok(ExternalSystemAdmissionV1 {
        manifest_digest,
        policy_digest: policy.policy_digest,
        system_id: manifest.system_id().clone(),
        host_identity_digest: manifest.host_identity_digest(),
        observed_at: manifest.observed_at().as_str().to_owned(),
        authority: NonAuthorizingPosture::DENY_ALL,
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorCalibrationAdmissionPolicyV1 {
    sensor_id: StableId,
    sensor_class: SensorClassV1,
    hardware_or_adapter_digest: Digest32,
    calibration_generation: Generation,
    clock_domain: String,
    failure_policy: SensorFailurePolicyV1,
    policy_digest: Digest32,
}

impl SensorCalibrationAdmissionPolicyV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        sensor_id: StableId,
        sensor_class: SensorClassV1,
        hardware_or_adapter_digest: Digest32,
        calibration_generation: Generation,
        clock_domain: &str,
        failure_policy: SensorFailurePolicyV1,
    ) -> Result<Self, PlatformManifestAdmissionErrorV1> {
        require_digest(hardware_or_adapter_digest, "hardware or adapter")?;
        if clock_domain.is_empty() || clock_domain.len() > 128 || clock_domain.contains('\0') {
            return Err(PlatformManifestAdmissionErrorV1::InvalidPolicy(
                "clock domain",
            ));
        }
        let type_id = policy_type("runtime.supervisor:sensor-admission-policy-v1")?;
        let fields = [
            CanonicalFieldV1 {
                name: "calibration_generation",
                value: CanonicalValueV1::U64(calibration_generation.get()),
            },
            CanonicalFieldV1 {
                name: "clock_domain",
                value: CanonicalValueV1::Text(clock_domain),
            },
            CanonicalFieldV1 {
                name: "failure_policy",
                value: CanonicalValueV1::Text(failure_policy.id()),
            },
            CanonicalFieldV1 {
                name: "hardware_or_adapter_digest",
                value: CanonicalValueV1::Digest(hardware_or_adapter_digest),
            },
            CanonicalFieldV1 {
                name: "sensor_class",
                value: CanonicalValueV1::Text(sensor_class.id()),
            },
            CanonicalFieldV1 {
                name: "sensor_id",
                value: CanonicalValueV1::StableId(&sensor_id),
            },
        ];
        let policy_digest = canonical_digest_v1(&type_id, 1, &fields)
            .map_err(PlatformManifestAdmissionErrorV1::Canonical)?;
        Ok(Self {
            sensor_id,
            sensor_class,
            hardware_or_adapter_digest,
            calibration_generation,
            clock_domain: clock_domain.to_owned(),
            failure_policy,
            policy_digest,
        })
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SensorCalibrationAdmissionV1 {
    manifest_digest: Digest32,
    policy_digest: Digest32,
    sensor_id: StableId,
    calibration_generation: Generation,
    valid_from: String,
    valid_until: String,
    authority: NonAuthorizingPosture,
}

impl SensorCalibrationAdmissionV1 {
    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    #[must_use]
    pub fn sensor_id(&self) -> &StableId {
        &self.sensor_id
    }

    #[must_use]
    pub const fn calibration_generation(&self) -> Generation {
        self.calibration_generation
    }

    #[must_use]
    pub fn valid_from(&self) -> &str {
        &self.valid_from
    }

    #[must_use]
    pub fn valid_until(&self) -> &str {
        &self.valid_until
    }

    #[must_use]
    pub const fn authority(&self) -> NonAuthorizingPosture {
        self.authority
    }
}

pub fn admit_sensor_calibration_manifest_v1(
    policy: &SensorCalibrationAdmissionPolicyV1,
    manifest: &SensorCalibrationManifestV1,
) -> Result<SensorCalibrationAdmissionV1, PlatformManifestAdmissionErrorV1> {
    manifest
        .validate()
        .map_err(PlatformManifestAdmissionErrorV1::Manifest)?;
    if manifest.sensor_id() != &policy.sensor_id {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "sensor id",
        ));
    }
    if manifest.sensor_class() != policy.sensor_class {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "sensor class",
        ));
    }
    if manifest.hardware_or_adapter_digest() != policy.hardware_or_adapter_digest {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "hardware or adapter",
        ));
    }
    if manifest.calibration_generation() != policy.calibration_generation {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "calibration generation",
        ));
    }
    if manifest.clock_domain() != policy.clock_domain.as_str() {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "clock domain",
        ));
    }
    if manifest.failure_policy() != policy.failure_policy {
        return Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
            "failure policy",
        ));
    }
    let manifest_digest = manifest
        .semantic_digest()
        .map_err(PlatformManifestAdmissionErrorV1::Manifest)?;
    Ok(SensorCalibrationAdmissionV1 {
        manifest_digest,
        policy_digest: policy.policy_digest,
        sensor_id: manifest.sensor_id().clone(),
        calibration_generation: manifest.calibration_generation(),
        valid_from: manifest.valid_from().as_str().to_owned(),
        valid_until: manifest.valid_until().as_str().to_owned(),
        authority: NonAuthorizingPosture::DENY_ALL,
    })
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), PlatformManifestAdmissionErrorV1> {
    if value.is_zero() {
        return Err(PlatformManifestAdmissionErrorV1::InvalidPolicy(field));
    }
    Ok(())
}

fn policy_type(value: &str) -> Result<StableId, PlatformManifestAdmissionErrorV1> {
    StableId::new(value).map_err(|_| PlatformManifestAdmissionErrorV1::InvalidTypeIdentity)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlatformManifestAdmissionErrorV1 {
    InvalidPolicy(&'static str),
    InvalidTypeIdentity,
    PolicyMismatch(&'static str),
    Manifest(ManifestContractErrorV1),
    Canonical(CanonicalDigestError),
}

impl fmt::Display for PlatformManifestAdmissionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for PlatformManifestAdmissionErrorV1 {}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::SensorOperatingRangeV1;
    use codex_hepta_types::SensorUncertaintyProfileV1;
    use codex_hepta_types::UncertaintyDistributionV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn external_system_owner_binds_host_and_authorization() {
        let policy = ExternalSystemAdmissionPolicyV1::new(
            id("host-1"),
            ExternalSystemClassV1::DebianHost,
            digest("host identity"),
            digest("authorization"),
        )
        .expect("policy");
        let manifest = ExternalSystemManifestV1::new(
            id("host-1"),
            ExternalSystemClassV1::DebianHost,
            digest("host identity"),
            digest("os"),
            digest("packages"),
            digest("services"),
            digest("filesystem"),
            digest("identities"),
            digest("network"),
            digest("secrets"),
            "2026-09-27T00:00:00Z",
            digest("authorization"),
        )
        .expect("manifest");
        let receipt = admit_external_system_manifest_v1(&policy, &manifest).expect("admission");
        assert_eq!(
            receipt.manifest_digest(),
            manifest.semantic_digest().expect("digest")
        );
        assert_eq!(receipt.authority(), NonAuthorizingPosture::DENY_ALL);
    }

    #[test]
    fn sensor_owner_binds_hardware_clock_generation_and_failure_policy() {
        let generation = Generation::new(4).expect("generation");
        let policy = SensorCalibrationAdmissionPolicyV1::new(
            id("sensor-1"),
            SensorClassV1::ProviderRuntime,
            digest("adapter"),
            generation,
            "provider-monotonic-clock",
            SensorFailurePolicyV1::Abstain,
        )
        .expect("policy");
        let manifest = SensorCalibrationManifestV1::new(
            id("sensor-1"),
            SensorClassV1::ProviderRuntime,
            digest("adapter"),
            generation,
            "provider-monotonic-clock",
            "2026-09-27T00:00:00Z",
            "2026-10-27T00:00:00Z",
            SensorUncertaintyProfileV1::new(
                UncertaintyDistributionV1::EmpiricalQuantiles,
                -10,
                10,
                990_000,
            )
            .expect("uncertainty"),
            SensorOperatingRangeV1::new("utility", -100, 100).expect("range"),
            SensorFailurePolicyV1::Abstain,
        )
        .expect("manifest");
        let receipt = admit_sensor_calibration_manifest_v1(&policy, &manifest).expect("admission");
        assert_eq!(receipt.calibration_generation(), generation);
        assert_eq!(
            receipt.manifest_digest(),
            manifest.semantic_digest().expect("digest")
        );
    }

    #[test]
    fn sensor_owner_rejects_generation_replay() {
        let policy = SensorCalibrationAdmissionPolicyV1::new(
            id("sensor"),
            SensorClassV1::Simulator,
            digest("adapter"),
            Generation::new(2).expect("generation"),
            "clock",
            SensorFailurePolicyV1::Reject,
        )
        .expect("policy");
        let manifest = SensorCalibrationManifestV1::new(
            id("sensor"),
            SensorClassV1::Simulator,
            digest("adapter"),
            Generation::new(1).expect("generation"),
            "clock",
            "2026-09-27T00:00:00Z",
            "2026-09-28T00:00:00Z",
            SensorUncertaintyProfileV1::new(
                UncertaintyDistributionV1::BoundedInterval,
                0,
                1,
                1_000_000,
            )
            .expect("uncertainty"),
            SensorOperatingRangeV1::new("count", 0, 1).expect("range"),
            SensorFailurePolicyV1::Reject,
        )
        .expect("manifest");
        assert_eq!(
            admit_sensor_calibration_manifest_v1(&policy, &manifest),
            Err(PlatformManifestAdmissionErrorV1::PolicyMismatch(
                "calibration generation"
            ))
        );
    }
}
