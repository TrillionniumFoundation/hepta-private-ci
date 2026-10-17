//! Generation-bound numeric registry admission and verifiable V2 receipts.
//!
//! The existing V1 registered receipt remains a content-addressed compatibility
//! receipt. V2 adds a caller-owned monotonic snapshot generation, explicit
//! definition digests and a full recomputation verifier without changing V1.

use std::error::Error;
use std::fmt;

use crate::CanonicalDigestError;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::ContractRegistryV1;
use crate::Digest32;
use crate::Generation;
use crate::NonAuthorizingPosture;
use crate::NumericConversionError;
use crate::NumericConversionReceiptV1;
use crate::NumericSignalSchemaV1;
use crate::NumericSignalV1;
use crate::RegisteredNumericConversionReceiptV1;
use crate::RegistryError;
use crate::StableId;
use crate::canonical_digest_v1;
use crate::rescale_signal;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RegistrySnapshotIdentityV1 {
    generation: Generation,
    registry_digest: Digest32,
}

impl RegistrySnapshotIdentityV1 {
    pub fn new(
        generation: Generation,
        registry_digest: Digest32,
    ) -> Result<Self, NumericRegistryV2Error> {
        if registry_digest.is_zero() {
            return Err(NumericRegistryV2Error::EmptyDigest("registry"));
        }
        Ok(Self {
            generation,
            registry_digest,
        })
    }

    pub fn from_registry(
        generation: Generation,
        registry: &ContractRegistryV1,
    ) -> Result<Self, NumericRegistryV2Error> {
        Self::new(generation, registry.registry_digest()?)
    }

    #[must_use]
    pub const fn generation(self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn registry_digest(self) -> Digest32 {
        self.registry_digest
    }

    /// Verify that the supplied immutable registry is exactly the content
    /// snapshot named by this identity. Generation monotonicity remains an
    /// owner policy; callers must compare against their pinned current snapshot.
    pub fn verify_registry(
        self,
        registry: &ContractRegistryV1,
    ) -> Result<(), NumericRegistryV2Error> {
        if registry.registry_digest()? != self.registry_digest {
            return Err(NumericRegistryV2Error::ReceiptMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RegisteredNumericConversionReceiptV2 {
    conversion: NumericConversionReceiptV1,
    registry_snapshot: RegistrySnapshotIdentityV1,
    source_profile_definition_digest: Digest32,
    target_profile_definition_digest: Digest32,
    normalization_definition_digest: Digest32,
    conversion_receipt_digest: Digest32,
    admission_digest: Digest32,
    authority: NonAuthorizingPosture,
}

impl RegisteredNumericConversionReceiptV2 {
    #[must_use]
    pub fn conversion(&self) -> &NumericConversionReceiptV1 {
        &self.conversion
    }

    #[must_use]
    pub const fn registry_snapshot(&self) -> RegistrySnapshotIdentityV1 {
        self.registry_snapshot
    }

    #[must_use]
    pub const fn source_profile_definition_digest(&self) -> Digest32 {
        self.source_profile_definition_digest
    }

    #[must_use]
    pub const fn target_profile_definition_digest(&self) -> Digest32 {
        self.target_profile_definition_digest
    }

    #[must_use]
    pub const fn normalization_definition_digest(&self) -> Digest32 {
        self.normalization_definition_digest
    }

    #[must_use]
    pub const fn conversion_receipt_digest(&self) -> Digest32 {
        self.conversion_receipt_digest
    }

    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 {
        self.admission_digest
    }

    #[must_use]
    pub const fn authority(&self) -> NonAuthorizingPosture {
        self.authority
    }

    /// Recompute the receipt against the registry generation embedded in the
    /// receipt itself. This proves internal integrity, not freshness. Product
    /// owners that require anti-rollback must call `verify_for_snapshot` with
    /// their independently pinned current snapshot identity.
    pub fn verify(
        &self,
        source: &NumericSignalV1,
        target: &NumericSignalSchemaV1,
        registry: &ContractRegistryV1,
    ) -> Result<NumericSignalV1, NumericRegistryV2Error> {
        let (output, expected) = rescale_signal_registered_v2(
            source,
            target,
            registry,
            self.registry_snapshot.generation,
        )?;
        if &expected != self {
            return Err(NumericRegistryV2Error::ReceiptMismatch);
        }
        Ok(output)
    }

    /// Verify against an owner-pinned exact snapshot. This closes the replay
    /// gap left by self-contained verification: a valid receipt from an older
    /// generation or another registry digest cannot be accepted for the
    /// current owner generation. Snapshot mismatch intentionally reuses the
    /// existing V2 receipt-mismatch error to preserve exhaustive enum matches.
    pub fn verify_for_snapshot(
        &self,
        source: &NumericSignalV1,
        target: &NumericSignalSchemaV1,
        registry: &ContractRegistryV1,
        expected_snapshot: RegistrySnapshotIdentityV1,
    ) -> Result<NumericSignalV1, NumericRegistryV2Error> {
        expected_snapshot.verify_registry(registry)?;
        if self.registry_snapshot != expected_snapshot {
            return Err(NumericRegistryV2Error::ReceiptMismatch);
        }
        self.verify(source, target, registry)
    }
}

/// Additive V1 registry-evidence helper. The historical top-level
/// `rescale_signal_registered` signature remains unchanged for source
/// compatibility; consumers that require a distinct registry-admission receipt
/// opt into this explicitly named function.
pub fn rescale_signal_registered_receipt_v1(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, RegisteredNumericConversionReceiptV1), NumericConversionError> {
    source.schema.validate_with_registry(registry)?;
    target.validate_with_registry(registry)?;
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    let (output, conversion) = rescale_signal(source, target)?;
    let registry_digest = registry
        .registry_digest()
        .map_err(|_| NumericConversionError::CanonicalEncoding)?;
    let admission_digest = crate::numeric_conversion::registered_admission_digest(
        registry_digest,
        source.schema.normalization_digest,
        &conversion,
    )?;
    Ok((
        output,
        RegisteredNumericConversionReceiptV1 {
            conversion,
            registry_digest,
            admission_digest,
            authority: NonAuthorizingPosture::DENY_ALL,
        },
    ))
}

pub fn rescale_signal_registered_v2(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
    generation: Generation,
) -> Result<(NumericSignalV1, RegisteredNumericConversionReceiptV2), NumericRegistryV2Error> {
    let source_definition = registry.require_numeric_profile(source.schema.profile)?;
    let target_definition = registry.require_numeric_profile(target.profile)?;
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericRegistryV2Error::Numeric(
            NumericConversionError::NormalizationMismatch,
        ));
    }
    let normalization_definition =
        registry.require_normalization(source.schema.normalization_digest)?;
    // The immutable definitions above admit both profiles and the shared
    // normalization. The pure converter still validates both schemas, shape,
    // unit, bounds, rounding, and overflow. Avoid repeated registry lookups and
    // the unused V1 admission hash, not current authorization or snapshot checks.
    let (output, conversion) = rescale_signal(source, target)?;
    let registry_snapshot = RegistrySnapshotIdentityV1::from_registry(generation, registry)?;
    let conversion_receipt_digest = conversion_receipt_digest(&conversion)?;
    let source_profile_definition_digest = source_definition.digest();
    let target_profile_definition_digest = target_definition.digest();
    let normalization_definition_digest = normalization_definition.digest();
    let admission_digest = admission_digest_v2(
        registry_snapshot,
        source_profile_definition_digest,
        target_profile_definition_digest,
        normalization_definition_digest,
        conversion_receipt_digest,
    )?;
    Ok((
        output,
        RegisteredNumericConversionReceiptV2 {
            conversion,
            registry_snapshot,
            source_profile_definition_digest,
            target_profile_definition_digest,
            normalization_definition_digest,
            conversion_receipt_digest,
            admission_digest,
            authority: NonAuthorizingPosture::DENY_ALL,
        },
    ))
}

fn conversion_receipt_digest(
    receipt: &NumericConversionReceiptV1,
) -> Result<Digest32, NumericRegistryV2Error> {
    let type_id = StableId::new("platform.types:numeric-conversion-receipt-v1")
        .map_err(|_| NumericRegistryV2Error::InvalidTypeIdentity)?;
    let fields = [
        CanonicalFieldV1 {
            name: "error_denominator",
            value: CanonicalValueV1::U128(receipt.absolute_error_bound.denominator),
        },
        CanonicalFieldV1 {
            name: "error_numerator",
            value: CanonicalValueV1::U128(receipt.absolute_error_bound.numerator),
        },
        CanonicalFieldV1 {
            name: "evidence_digest",
            value: CanonicalValueV1::Digest(receipt.evidence_digest),
        },
        CanonicalFieldV1 {
            name: "output_digest",
            value: CanonicalValueV1::Digest(receipt.output_digest),
        },
        CanonicalFieldV1 {
            name: "source_digest",
            value: CanonicalValueV1::Digest(receipt.source_digest),
        },
        CanonicalFieldV1 {
            name: "source_profile",
            value: CanonicalValueV1::Text(receipt.source_profile.id()),
        },
        CanonicalFieldV1 {
            name: "target_profile",
            value: CanonicalValueV1::Text(receipt.target_profile.id()),
        },
    ];
    canonical_digest_v1(&type_id, 1, &fields).map_err(NumericRegistryV2Error::Canonical)
}

fn admission_digest_v2(
    snapshot: RegistrySnapshotIdentityV1,
    source_profile_definition_digest: Digest32,
    target_profile_definition_digest: Digest32,
    normalization_definition_digest: Digest32,
    conversion_receipt_digest: Digest32,
) -> Result<Digest32, NumericRegistryV2Error> {
    for (name, digest) in [
        (
            "source profile definition",
            source_profile_definition_digest,
        ),
        (
            "target profile definition",
            target_profile_definition_digest,
        ),
        ("normalization definition", normalization_definition_digest),
        ("conversion receipt", conversion_receipt_digest),
    ] {
        if digest.is_zero() {
            return Err(NumericRegistryV2Error::EmptyDigest(name));
        }
    }
    let type_id = StableId::new("platform.types:numeric-registry-admission-v2")
        .map_err(|_| NumericRegistryV2Error::InvalidTypeIdentity)?;
    let fields = [
        CanonicalFieldV1 {
            name: "conversion_receipt_digest",
            value: CanonicalValueV1::Digest(conversion_receipt_digest),
        },
        CanonicalFieldV1 {
            name: "normalization_definition_digest",
            value: CanonicalValueV1::Digest(normalization_definition_digest),
        },
        CanonicalFieldV1 {
            name: "registry_digest",
            value: CanonicalValueV1::Digest(snapshot.registry_digest),
        },
        CanonicalFieldV1 {
            name: "registry_generation",
            value: CanonicalValueV1::U64(snapshot.generation.get()),
        },
        CanonicalFieldV1 {
            name: "source_profile_definition_digest",
            value: CanonicalValueV1::Digest(source_profile_definition_digest),
        },
        CanonicalFieldV1 {
            name: "target_profile_definition_digest",
            value: CanonicalValueV1::Digest(target_profile_definition_digest),
        },
    ];
    canonical_digest_v1(&type_id, 2, &fields).map_err(NumericRegistryV2Error::Canonical)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NumericRegistryV2Error {
    Numeric(NumericConversionError),
    Registry(RegistryError),
    EmptyDigest(&'static str),
    InvalidTypeIdentity,
    ReceiptMismatch,
    Canonical(CanonicalDigestError),
}

impl From<NumericConversionError> for NumericRegistryV2Error {
    fn from(value: NumericConversionError) -> Self {
        Self::Numeric(value)
    }
}

impl From<RegistryError> for NumericRegistryV2Error {
    fn from(value: RegistryError) -> Self {
        Self::Registry(value)
    }
}

impl fmt::Display for NumericRegistryV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NumericRegistryV2Error {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IdProfileV1;
    use crate::NumericProfileDefinitionV1;
    use crate::NumericProfileV1;
    use crate::RegistryDefinitionV1;
    use crate::RegistryKindV1;
    use crate::SignalUnitV1;
    use crate::validate_id;

    fn fixture() -> (ContractRegistryV1, NumericSignalV1, NumericSignalSchemaV1) {
        let normalization = RegistryDefinitionV1::new(
            RegistryKindV1::Normalization,
            validate_id("normalization:identity", IdProfileV1::Normalization)
                .expect("normalization id"),
            1,
            "scale=identity;clamp=none",
        )
        .expect("normalization");
        let normalization_digest = normalization.digest();
        let registry = ContractRegistryV1::new_with_numeric_profiles(
            vec![normalization],
            vec![
                NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
                    .expect("source profile"),
                NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ24NearestTiesEven)
                    .expect("target profile"),
            ],
        )
        .expect("registry");
        let source = NumericSignalV1 {
            schema: NumericSignalSchemaV1 {
                profile: NumericProfileV1::HnmfPpmTowardZero,
                unit: SignalUnitV1::Utility,
                shape: vec![2],
                minimum_raw: -1_000_000,
                maximum_raw: 1_000_000,
                normalization_digest,
            },
            values: vec![250_000, -250_000],
        };
        let target = NumericSignalSchemaV1 {
            profile: NumericProfileV1::SignedQ24NearestTiesEven,
            minimum_raw: -(1_i64 << 24),
            maximum_raw: 1_i64 << 24,
            ..source.schema.clone()
        };
        (registry, source, target)
    }

    #[test]
    fn v2_binds_generation_and_every_definition_digest() {
        let (registry, source, target) = fixture();
        let generation = Generation::new(7).expect("generation");
        let (_, receipt) = rescale_signal_registered_v2(&source, &target, &registry, generation)
            .expect("registered conversion");
        assert_eq!(receipt.registry_snapshot().generation(), generation);
        assert!(!receipt.source_profile_definition_digest().is_zero());
        assert!(!receipt.target_profile_definition_digest().is_zero());
        assert!(!receipt.normalization_definition_digest().is_zero());
        assert!(!receipt.conversion_receipt_digest().is_zero());
        assert_eq!(receipt.authority(), NonAuthorizingPosture::DENY_ALL);
        receipt
            .verify(&source, &target, &registry)
            .expect("verified");

        let (_, later) = rescale_signal_registered_v2(
            &source,
            &target,
            &registry,
            Generation::new(8).expect("generation"),
        )
        .expect("later generation");
        assert_ne!(receipt.admission_digest(), later.admission_digest());
    }

    #[test]
    fn v2_verifier_rejects_tampered_receipt() {
        let (registry, source, target) = fixture();
        let (_, mut receipt) = rescale_signal_registered_v2(
            &source,
            &target,
            &registry,
            Generation::new(1).expect("generation"),
        )
        .expect("registered conversion");
        receipt.admission_digest = Digest32::of_bytes(b"tampered");
        assert_eq!(
            receipt.verify(&source, &target, &registry),
            Err(NumericRegistryV2Error::ReceiptMismatch)
        );
    }

    #[test]
    fn v2_owner_pinned_snapshot_rejects_generation_and_digest_rollback() {
        let (registry, source, target) = fixture();
        let generation = Generation::new(7).expect("generation");
        let (_, receipt) = rescale_signal_registered_v2(&source, &target, &registry, generation)
            .expect("registered conversion");
        let current = receipt.registry_snapshot();
        receipt
            .verify_for_snapshot(&source, &target, &registry, current)
            .expect("current snapshot");

        let later = RegistrySnapshotIdentityV1::from_registry(
            Generation::new(8).expect("generation"),
            &registry,
        )
        .expect("later snapshot");
        assert_eq!(
            receipt.verify_for_snapshot(&source, &target, &registry, later),
            Err(NumericRegistryV2Error::ReceiptMismatch)
        );

        let wrong_digest =
            RegistrySnapshotIdentityV1::new(generation, Digest32::of_bytes(b"different-registry"))
                .expect("snapshot");
        assert_eq!(
            receipt.verify_for_snapshot(&source, &target, &registry, wrong_digest),
            Err(NumericRegistryV2Error::ReceiptMismatch)
        );
    }

    #[test]
    fn optimized_v2_matches_the_previous_v1_intermediate_path() {
        let (registry, mut source, target) = fixture();
        for raw in [-1_000_000, -500_001, -1, 0, 1, 500_001, 1_000_000] {
            source.values = vec![raw, -raw];
            let (old_output, old) =
                rescale_signal_registered_receipt_v1(&source, &target, &registry)
                    .expect("old path");
            for generation in [1, 7, 8] {
                let generation = Generation::new(generation).expect("generation");
                let (output, receipt) =
                    rescale_signal_registered_v2(&source, &target, &registry, generation)
                        .expect("new path");
                let snapshot = RegistrySnapshotIdentityV1::from_registry(generation, &registry)
                    .expect("snapshot");
                let conversion_digest =
                    conversion_receipt_digest(&old.conversion).expect("conversion digest");
                let source_definition = registry
                    .require_numeric_profile(source.schema.profile)
                    .expect("source definition")
                    .digest();
                let target_definition = registry
                    .require_numeric_profile(target.profile)
                    .expect("target definition")
                    .digest();
                let expected = RegisteredNumericConversionReceiptV2 {
                    conversion: old.conversion.clone(),
                    registry_snapshot: snapshot,
                    source_profile_definition_digest: source_definition,
                    target_profile_definition_digest: target_definition,
                    normalization_definition_digest: source.schema.normalization_digest,
                    conversion_receipt_digest: conversion_digest,
                    admission_digest: admission_digest_v2(
                        snapshot,
                        source_definition,
                        target_definition,
                        source.schema.normalization_digest,
                        conversion_digest,
                    )
                    .expect("prior V2 digest"),
                    authority: NonAuthorizingPosture::DENY_ALL,
                };
                assert_eq!((output, receipt), (old_output.clone(), expected));
            }
        }
    }
}
