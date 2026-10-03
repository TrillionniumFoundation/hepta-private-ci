//! Request-scoped consumer bindings for already validated canonical payloads.
//!
//! These constructors reuse the exact payload bytes and frozen digest held by
//! [`ValidatedCanonicalPayload`]. They do not cache or establish owner
//! currentness, source freshness, authorization, promotion, activation, or
//! release state. Product owners must still perform their final current-binding
//! observation immediately before use.

use codex_hepta_types::Digest32;

use crate::consumer::CanonicalConsumerBindingError;
use crate::consumer::CanonicalConsumerBindingV1;
use crate::consumer::CanonicalConsumerV1;
use crate::consumer::CanonicalMigrationPostureV1;
use crate::consumer::CanonicalPayloadKindV1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::MemoryEventV1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::RecallPacketV1;
use crate::wire::CognitiveContractV1;
use crate::wire::ValidatedCanonicalPayload;

pub fn bind_prepared_memory_event_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    payload: &ValidatedCanonicalPayload<MemoryEventV1>,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    bind_prepared_consumer_v1(
        operation_id,
        consumer,
        CanonicalPayloadKindV1::MemoryEvent,
        payload,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
}

pub fn bind_prepared_recall_packet_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    payload: &ValidatedCanonicalPayload<RecallPacketV1>,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    bind_prepared_consumer_v1(
        operation_id,
        consumer,
        CanonicalPayloadKindV1::RecallPacket,
        payload,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
}

pub fn bind_prepared_forget_receipt_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    payload: &ValidatedCanonicalPayload<ForgetPropagationReceiptV1>,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    bind_prepared_consumer_v1(
        operation_id,
        consumer,
        CanonicalPayloadKindV1::ForgetPropagationReceipt,
        payload,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
}

#[allow(clippy::too_many_arguments)]
fn bind_prepared_consumer_v1<T: CognitiveContractV1>(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    payload_kind: CanonicalPayloadKindV1,
    payload: &ValidatedCanonicalPayload<T>,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    let canonical_payload_sha256 = checked_digest(payload.frozen_digest().digest())?;
    let mut binding = CanonicalConsumerBindingV1 {
        operation_id,
        consumer,
        payload_kind,
        canonical_payload_sha256,
        source_identity_sha256: checked_digest(source_identity_sha256)?,
        source_snapshot_sha256: checked_digest(source_snapshot_sha256)?,
        compatibility_payload_sha256: compatibility_payload_sha256
            .map(checked_digest)
            .transpose()?,
        migration_posture,
        currentness_revalidation_required: true,
        binding_sha256: canonical_payload_sha256,
    };
    binding.binding_sha256 = binding.compute_binding_sha256()?;
    binding.validate()?;
    Ok(binding)
}

fn checked_digest(value: Digest32) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
    ContractDigestV1::from_digest(value).map_err(|_| CanonicalConsumerBindingError::ZeroDigest)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use super::*;
    use crate::consumer::bind_memory_event_consumer_v1;
    use crate::hnmf::MemoryLifecycleV1;
    use crate::hnmf::MemoryScopeV1;
    use crate::hnmf::MemoryVerificationStateV1;
    use crate::hnmf::ModalityKindV1;
    use crate::hnmf::ModalitySpanRefV1;
    use crate::hnmf::ObservedIntervalV1;
    use crate::hnmf::PrivacyClassV1;
    use crate::hnmf::ProvenanceRefV1;
    use crate::hnmf::RetentionPolicyV1;
    use crate::hnmf::SpanRangeV1;
    use crate::wire::canonical_contract_digest_v1;

    fn id(value: &str) -> ContractIdV1 {
        ContractIdV1::new(value).expect("valid static id")
    }

    fn digest(character: char) -> ContractDigestV1 {
        ContractDigestV1::parse(&std::iter::repeat_n(character, 64).collect::<String>())
            .expect("valid digest")
    }

    fn event() -> MemoryEventV1 {
        MemoryEventV1 {
            event_id: id("event:prepared"),
            episode_id: id("episode:prepared"),
            scope: MemoryScopeV1::AgentPrivate {
                agent_id: id("agent:prepared"),
            },
            observed_interval: ObservedIntervalV1 {
                start_unix_ms: 1,
                end_unix_ms: None,
            },
            modality_spans: vec![ModalitySpanRefV1 {
                span_id: id("span:prepared"),
                modality: ModalityKindV1::Text,
                asset_sha256: digest('a'),
                range: SpanRangeV1::ByteRange { start: 0, end: 1 },
                preprocessor_manifest_sha256: digest('b'),
                feature_blob_sha256: None,
                symbolic_projection_sha256: None,
                uncertainty_ppm: 0,
                privacy_class: PrivacyClassV1::AgentPrivate,
                redaction_mask_sha256: None,
            }],
            cross_modal_bindings: Vec::new(),
            semantic_keys: BTreeSet::from(["prepared".to_string()]),
            provenance: vec![ProvenanceRefV1 {
                source_id: id("source:prepared"),
                source_revision: 1,
                source_sha256: digest('c'),
                observed_at_unix_ms: 1,
            }],
            verification: MemoryVerificationStateV1::Verified,
            retention_policy: RetentionPolicyV1::Persistent {
                retain_until_unix_ms: None,
            },
            objective_digest: digest('d'),
            ndu_state_digest: digest('e'),
            causal_parents: BTreeSet::new(),
            temporal_neighbors: BTreeSet::new(),
            behavior_propensity_ppm: None,
            lifecycle: MemoryLifecycleV1::Active,
        }
    }

    #[test]
    fn prepared_binding_matches_legacy_constructor_without_reserializing() {
        let event = event();
        let prepared = ValidatedCanonicalPayload::new(event.clone()).expect("prepared event");
        let source_identity = digest('5').digest();
        let source_snapshot = digest('6').digest();
        let compatibility = Some(digest('7').digest());
        let expected = bind_memory_event_consumer_v1(
            id("operation:prepared"),
            CanonicalConsumerV1::CognitiveRead,
            &event,
            source_identity,
            source_snapshot,
            compatibility,
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
        .expect("legacy constructor");
        let actual = bind_prepared_memory_event_consumer_v1(
            id("operation:prepared"),
            CanonicalConsumerV1::CognitiveRead,
            &prepared,
            source_identity,
            source_snapshot,
            compatibility,
            CanonicalMigrationPostureV1::CompatibilityBound,
        )
        .expect("prepared constructor");
        assert_eq!(actual, expected);
        assert_eq!(
            actual.canonical_payload_sha256.digest(),
            prepared.frozen_digest().digest()
        );
    }

    #[test]
    fn prepared_payload_digest_is_the_existing_frozen_profile() {
        let event = event();
        let prepared = ValidatedCanonicalPayload::new(event.clone()).expect("prepared event");
        assert_eq!(
            prepared.frozen_digest().digest(),
            canonical_contract_digest_v1(&event).expect("historical frozen digest")
        );
    }
}
