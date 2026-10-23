//! Frozen consumer-binding digest framing, without a concatenation buffer.
//!
//! This module hashes the supplied fields on every call. It does not cache a
//! binding, validate a migration posture, or authenticate a source observation.

use codex_hepta_types::Digest32;

use super::CONSUMER_BINDING_DOMAIN;
use super::CanonicalConsumerBindingError;
use super::CanonicalConsumerBindingV1;
use super::digest;
use crate::hnmf::ContractDigestV1;

pub(super) fn compute_binding_sha256_v1(
    binding: &CanonicalConsumerBindingV1,
) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
    let operation = binding.operation_id.as_str().as_bytes();
    let operation_length = u32::try_from(operation.len())
        .map_err(|_| CanonicalConsumerBindingError::Arithmetic)?
        .to_be_bytes();
    let tags = [binding.consumer.code(), binding.payload_kind.code()];
    let canonical = binding.canonical_payload_sha256.digest();
    let identity = binding.source_identity_sha256.digest();
    let snapshot = binding.source_snapshot_sha256.digest();
    let compatibility = binding
        .compatibility_payload_sha256
        .map(ContractDigestV1::digest);
    let compatibility_tag = [u8::from(compatibility.is_some())];
    let compatibility_bytes: &[u8] = match &compatibility {
        Some(value) => value.as_array(),
        None => &[],
    };
    let flags = [
        binding.migration_posture.code(),
        u8::from(binding.currentness_revalidation_required),
    ];

    // Preserve every byte of the V1 framing, including the optional-field tag,
    // operation byte length and final-use marker. Digest32::of_parts streams
    // these slices; it must not insert separators or change component order.
    digest(Digest32::of_parts(&[
        CONSUMER_BINDING_DOMAIN,
        &operation_length,
        operation,
        &tags,
        canonical.as_array(),
        identity.as_array(),
        snapshot.as_array(),
        &compatibility_tag,
        compatibility_bytes,
        &flags,
    ]))
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;

    use super::CONSUMER_BINDING_DOMAIN;
    use super::CanonicalConsumerBindingError;
    use super::CanonicalConsumerBindingV1;
    use super::ContractDigestV1;
    use super::compute_binding_sha256_v1;
    use super::digest;
    use crate::consumer::CanonicalConsumerV1;
    use crate::consumer::CanonicalMigrationPostureV1;
    use crate::consumer::CanonicalPayloadKindV1;
    use crate::hnmf::ContractIdV1;

    // Independent copy of the pre-refactor concatenate-and-hash framing. Do
    // not implement this reference in terms of the streaming helper.
    fn frozen_reference(
        binding: &CanonicalConsumerBindingV1,
    ) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
        let mut bytes = CONSUMER_BINDING_DOMAIN.to_vec();
        let operation = binding.operation_id.as_str().as_bytes();
        let length = u32::try_from(operation.len())
            .map_err(|_| CanonicalConsumerBindingError::Arithmetic)?;
        bytes.extend_from_slice(&length.to_be_bytes());
        bytes.extend_from_slice(operation);
        bytes.push(binding.consumer.code());
        bytes.push(binding.payload_kind.code());
        bytes.extend_from_slice(binding.canonical_payload_sha256.digest().as_array());
        bytes.extend_from_slice(binding.source_identity_sha256.digest().as_array());
        bytes.extend_from_slice(binding.source_snapshot_sha256.digest().as_array());
        match binding.compatibility_payload_sha256 {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(value.digest().as_array());
            }
            None => bytes.push(0),
        }
        bytes.push(binding.migration_posture.code());
        bytes.push(u8::from(binding.currentness_revalidation_required));
        digest(Digest32::of_bytes(&bytes))
    }

    fn sample_binding() -> Result<CanonicalConsumerBindingV1, Box<dyn std::error::Error>> {
        let canonical = digest(Digest32::of_bytes(b"canonical-payload"))?;
        let mut binding = CanonicalConsumerBindingV1 {
            operation_id: ContractIdV1::new("operation-1")?,
            consumer: CanonicalConsumerV1::CognitiveRead,
            payload_kind: CanonicalPayloadKindV1::MemoryEvent,
            canonical_payload_sha256: canonical,
            source_identity_sha256: digest(Digest32::of_bytes(b"root-identity"))?,
            source_snapshot_sha256: digest(Digest32::of_bytes(b"root-snapshot"))?,
            compatibility_payload_sha256: Some(digest(Digest32::of_bytes(b"legacy-payload"))?),
            migration_posture: CanonicalMigrationPostureV1::CompatibilityBound,
            currentness_revalidation_required: true,
            binding_sha256: canonical,
        };
        binding.binding_sha256 = frozen_reference(&binding)?;
        Ok(binding)
    }

    #[test]
    fn streamed_digest_matches_frozen_reference_for_all_tag_combinations()
    -> Result<(), Box<dyn std::error::Error>> {
        let payloads = [
            CanonicalPayloadKindV1::MemoryEvent,
            CanonicalPayloadKindV1::RecallPacket,
            CanonicalPayloadKindV1::ForgetPropagationReceipt,
        ];
        let postures = [
            CanonicalMigrationPostureV1::Native,
            CanonicalMigrationPostureV1::CompatibilityBound,
            CanonicalMigrationPostureV1::LegacyRetired,
        ];
        let sample = sample_binding()?;
        for operation in ["operation-1", "operation-10", "operation-100"] {
            for consumer in CanonicalConsumerV1::ALL {
                for payload in payloads {
                    for posture in postures {
                        for compatibility in [None, sample.compatibility_payload_sha256] {
                            for currentness in [false, true] {
                                let mut binding = sample.clone();
                                binding.operation_id = ContractIdV1::new(operation)?;
                                binding.consumer = consumer;
                                binding.payload_kind = payload;
                                binding.migration_posture = posture;
                                binding.compatibility_payload_sha256 = compatibility;
                                binding.currentness_revalidation_required = currentness;
                                assert_eq!(
                                    compute_binding_sha256_v1(&binding)?,
                                    frozen_reference(&binding)?
                                );
                                assert_eq!(
                                    binding.compute_binding_sha256()?,
                                    frozen_reference(&binding)?
                                );
                            }
                        }
                    }
                }
            }
        }
        Ok(())
    }

    #[test]
    fn frozen_digest_matches_independent_python_sha256_vector()
    -> Result<(), Box<dyn std::error::Error>> {
        let binding = sample_binding()?;
        let expected = ContractDigestV1::parse(
            "1b34018fdc4ea4353d65f798915dc54dc63d82cd750bc03ff3b5fd8d089b12e7",
        )?;
        assert_eq!(compute_binding_sha256_v1(&binding)?, expected);
        assert_eq!(binding.compute_binding_sha256()?, expected);
        Ok(())
    }

    #[test]
    fn changed_identity_output_or_marker_never_reuses_a_previous_digest()
    -> Result<(), Box<dyn std::error::Error>> {
        let original = sample_binding()?;
        original.validate_historical()?;
        let replacement = digest(Digest32::of_bytes(b"replacement"))?;
        for field in 0..10 {
            let mut changed = original.clone();
            match field {
                0 => changed.operation_id = ContractIdV1::new("operation-2")?,
                1 => changed.consumer = CanonicalConsumerV1::CognitiveStore,
                2 => changed.payload_kind = CanonicalPayloadKindV1::RecallPacket,
                3 => changed.canonical_payload_sha256 = replacement,
                4 => changed.source_identity_sha256 = replacement,
                5 => changed.source_snapshot_sha256 = replacement,
                6 => changed.compatibility_payload_sha256 = Some(replacement),
                7 => changed.compatibility_payload_sha256 = None,
                8 => changed.migration_posture = CanonicalMigrationPostureV1::Native,
                _ => changed.currentness_revalidation_required = false,
            }
            assert_ne!(changed.compute_binding_sha256()?, original.binding_sha256);
            assert!(changed.validate_historical().is_err());
        }
        Ok(())
    }
}
