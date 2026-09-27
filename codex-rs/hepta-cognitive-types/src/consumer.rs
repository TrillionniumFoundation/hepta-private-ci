//! Exact, authority-free bindings between canonical cognitive contracts and their consumers.
//!
//! A registry row is not a runtime binding. These values bind one validated canonical
//! payload to one consumer operation, exact source identity, exact snapshot and an
//! explicit migration posture. They grant no read, write, model, tool or effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::MemoryEventV1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::RecallPacketV1;
use crate::wire::canonical_contract_digest_v1;

const CONSUMER_BINDING_DOMAIN: &[u8] = b"hepta.cognitive.consumer-binding.v1\0";

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CanonicalConsumerV1 {
    CognitiveRead,
    CognitiveStore,
    MemoryRetrieval,
    CompactEngine,
    IntelligenceControl,
}

impl CanonicalConsumerV1 {
    pub const ALL: [Self; 5] = [
        Self::CognitiveRead,
        Self::CognitiveStore,
        Self::MemoryRetrieval,
        Self::CompactEngine,
        Self::IntelligenceControl,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::CognitiveRead => "cognitive.read",
            Self::CognitiveStore => "cognitive.store",
            Self::MemoryRetrieval => "memory.retrieval",
            Self::CompactEngine => "compact.engine",
            Self::IntelligenceControl => "intelligence.control",
        }
    }

    const fn code(self) -> u8 {
        match self {
            Self::CognitiveRead => 0,
            Self::CognitiveStore => 1,
            Self::MemoryRetrieval => 2,
            Self::CompactEngine => 3,
            Self::IntelligenceControl => 4,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CanonicalPayloadKindV1 {
    MemoryEvent,
    RecallPacket,
    ForgetPropagationReceipt,
}

impl CanonicalPayloadKindV1 {
    pub const fn contract_id(self) -> &'static str {
        match self {
            Self::MemoryEvent => "MemoryEventV1",
            Self::RecallPacket => "RecallPacketV1",
            Self::ForgetPropagationReceipt => "ForgetPropagationReceiptV1",
        }
    }

    const fn code(self) -> u8 {
        match self {
            Self::MemoryEvent => 0,
            Self::RecallPacket => 1,
            Self::ForgetPropagationReceipt => 2,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum CanonicalMigrationPostureV1 {
    /// The canonical contract is the only accepted product surface.
    Native,
    /// A legacy payload remains accepted only when its exact digest is bound here.
    CompatibilityBound,
    /// The legacy surface is no longer accepted; its historical evidence remains readable.
    LegacyRetired,
}

impl CanonicalMigrationPostureV1 {
    const fn code(self) -> u8 {
        match self {
            Self::Native => 0,
            Self::CompatibilityBound => 1,
            Self::LegacyRetired => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalConsumerBindingV1 {
    pub operation_id: ContractIdV1,
    pub consumer: CanonicalConsumerV1,
    pub payload_kind: CanonicalPayloadKindV1,
    pub canonical_payload_sha256: ContractDigestV1,
    pub source_identity_sha256: ContractDigestV1,
    pub source_snapshot_sha256: ContractDigestV1,
    pub compatibility_payload_sha256: Option<ContractDigestV1>,
    pub migration_posture: CanonicalMigrationPostureV1,
    pub currentness_revalidation_required: bool,
    pub binding_sha256: ContractDigestV1,
}

impl CanonicalConsumerBindingV1 {
    fn seal(mut value: Self) -> Result<Self, CanonicalConsumerBindingError> {
        value.binding_sha256 = value.compute_binding_sha256()?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), CanonicalConsumerBindingError> {
        match self.migration_posture {
            CanonicalMigrationPostureV1::CompatibilityBound
                if self.compatibility_payload_sha256.is_none() =>
            {
                return Err(CanonicalConsumerBindingError::CompatibilityDigestRequired);
            }
            CanonicalMigrationPostureV1::Native | CanonicalMigrationPostureV1::LegacyRetired
                if self.compatibility_payload_sha256.is_some() =>
            {
                return Err(CanonicalConsumerBindingError::UnexpectedCompatibilityDigest);
            }
            _ => {}
        }
        if !self.currentness_revalidation_required {
            return Err(CanonicalConsumerBindingError::CurrentnessRevalidationRequired);
        }
        if !consumer_accepts(self.consumer, self.payload_kind) {
            return Err(CanonicalConsumerBindingError::ConsumerPayloadMismatch {
                consumer: self.consumer,
                payload: self.payload_kind,
            });
        }
        if self.binding_sha256 != self.compute_binding_sha256()? {
            return Err(CanonicalConsumerBindingError::BindingDigestMismatch);
        }
        Ok(())
    }

    pub fn compute_binding_sha256(
        &self,
    ) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
        let mut bytes = CONSUMER_BINDING_DOMAIN.to_vec();
        push_text(&mut bytes, self.operation_id.as_str())?;
        bytes.push(self.consumer.code());
        bytes.push(self.payload_kind.code());
        bytes.extend_from_slice(self.canonical_payload_sha256.digest().as_array());
        bytes.extend_from_slice(self.source_identity_sha256.digest().as_array());
        bytes.extend_from_slice(self.source_snapshot_sha256.digest().as_array());
        match self.compatibility_payload_sha256 {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(value.digest().as_array());
            }
            None => bytes.push(0),
        }
        bytes.push(self.migration_posture.code());
        bytes.push(u8::from(self.currentness_revalidation_required));
        digest(Digest32::of_bytes(&bytes))
    }
}

pub fn bind_memory_event_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    event: &MemoryEventV1,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    let payload = canonical_contract_digest_v1(event)
        .map_err(|error| CanonicalConsumerBindingError::CanonicalContract(error.to_string()))?;
    CanonicalConsumerBindingV1::seal(CanonicalConsumerBindingV1 {
        operation_id,
        consumer,
        payload_kind: CanonicalPayloadKindV1::MemoryEvent,
        canonical_payload_sha256: digest(payload)?,
        source_identity_sha256: digest(source_identity_sha256)?,
        source_snapshot_sha256: digest(source_snapshot_sha256)?,
        compatibility_payload_sha256: compatibility_payload_sha256.map(digest).transpose()?,
        migration_posture,
        currentness_revalidation_required: true,
        binding_sha256: digest(payload)?,
    })
}

pub fn bind_recall_packet_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    packet: &RecallPacketV1,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    let payload = canonical_contract_digest_v1(packet)
        .map_err(|error| CanonicalConsumerBindingError::CanonicalContract(error.to_string()))?;
    CanonicalConsumerBindingV1::seal(CanonicalConsumerBindingV1 {
        operation_id,
        consumer,
        payload_kind: CanonicalPayloadKindV1::RecallPacket,
        canonical_payload_sha256: digest(payload)?,
        source_identity_sha256: digest(source_identity_sha256)?,
        source_snapshot_sha256: digest(source_snapshot_sha256)?,
        compatibility_payload_sha256: compatibility_payload_sha256.map(digest).transpose()?,
        migration_posture,
        currentness_revalidation_required: true,
        binding_sha256: digest(payload)?,
    })
}

pub fn bind_forget_receipt_consumer_v1(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    receipt: &ForgetPropagationReceiptV1,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    let payload = canonical_contract_digest_v1(receipt)
        .map_err(|error| CanonicalConsumerBindingError::CanonicalContract(error.to_string()))?;
    CanonicalConsumerBindingV1::seal(CanonicalConsumerBindingV1 {
        operation_id,
        consumer,
        payload_kind: CanonicalPayloadKindV1::ForgetPropagationReceipt,
        canonical_payload_sha256: digest(payload)?,
        source_identity_sha256: digest(source_identity_sha256)?,
        source_snapshot_sha256: digest(source_snapshot_sha256)?,
        compatibility_payload_sha256: compatibility_payload_sha256.map(digest).transpose()?,
        migration_posture,
        currentness_revalidation_required: true,
        binding_sha256: digest(payload)?,
    })
}

fn consumer_accepts(consumer: CanonicalConsumerV1, payload: CanonicalPayloadKindV1) -> bool {
    match payload {
        CanonicalPayloadKindV1::MemoryEvent => true,
        CanonicalPayloadKindV1::RecallPacket => matches!(
            consumer,
            CanonicalConsumerV1::MemoryRetrieval | CanonicalConsumerV1::IntelligenceControl
        ),
        CanonicalPayloadKindV1::ForgetPropagationReceipt => matches!(
            consumer,
            CanonicalConsumerV1::CognitiveRead
                | CanonicalConsumerV1::CognitiveStore
                | CanonicalConsumerV1::CompactEngine
        ),
    }
}

fn digest(value: Digest32) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
    ContractDigestV1::from_digest(value).map_err(|_| CanonicalConsumerBindingError::ZeroDigest)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), CanonicalConsumerBindingError> {
    let len = u32::try_from(value.len()).map_err(|_| CanonicalConsumerBindingError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalConsumerBindingError {
    CanonicalContract(String),
    ZeroDigest,
    CompatibilityDigestRequired,
    UnexpectedCompatibilityDigest,
    CurrentnessRevalidationRequired,
    ConsumerPayloadMismatch {
        consumer: CanonicalConsumerV1,
        payload: CanonicalPayloadKindV1,
    },
    BindingDigestMismatch,
    Arithmetic,
}

impl fmt::Display for CanonicalConsumerBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CanonicalConsumerBindingError {}
