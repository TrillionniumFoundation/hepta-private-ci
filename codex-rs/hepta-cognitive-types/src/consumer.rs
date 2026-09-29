//! Exact, authority-free bindings between canonical cognitive contracts and their consumers.
//!
//! A registry row is not a runtime binding. These values bind one validated canonical
//! payload to one consumer operation, exact source identity, exact snapshot and an
//! explicit migration posture. They grant no read, write, model, tool or effect authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::consumer_adapters::ConsumerConvergenceStateV1;
use crate::consumer_adapters::registered_consumer_v1;
use crate::hnmf::ContractDigestV1;
use crate::hnmf::ContractIdV1;
use crate::hnmf::MemoryEventV1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::RecallPacketV1;
use crate::wire::ContractDigestProfileV1;
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
        authorize_migration_posture_v1(value.consumer, value.migration_posture)?;
        value.binding_sha256 = value.compute_binding_sha256()?;
        value.validate_historical()?;
        Ok(value)
    }

    /// Validate this binding for a current product use.
    ///
    /// In addition to frozen structural and digest checks, this consults the
    /// current migration registry. A historical receipt must not call this
    /// method after the owning consumer has retired its compatibility surface;
    /// use [`Self::validate_historical`] for immutable audit evidence instead.
    pub fn validate(&self) -> Result<(), CanonicalConsumerBindingError> {
        self.validate_historical()?;
        authorize_migration_posture_v1(self.consumer, self.migration_posture)
    }

    /// Validate immutable historical evidence without reinterpreting it through
    /// today's migration registry.
    ///
    /// This still checks the frozen digest, payload/consumer matrix, migration
    /// field shape and mandatory final-use revalidation marker. It deliberately
    /// does not authorize a new use and therefore cannot revive a retired legacy
    /// path or replace the current owner observation required by `validate()`.
    pub fn validate_historical(&self) -> Result<(), CanonicalConsumerBindingError> {
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

    /// The digest stored in a V1 consumer binding is intentionally the frozen
    /// historical profile. Current semantic parity is checked separately with
    /// the schema-bound profile by `CanonicalHandoffV1`.
    #[must_use]
    pub const fn payload_digest_profile(&self) -> ContractDigestProfileV1 {
        ContractDigestProfileV1::FrozenCanonicalJsonV1
    }

    /// Hash the exact current fields without allocating a concatenated payload.
    /// This recomputes the frozen digest; it does not establish source freshness
    /// or replace the registry and owner checks performed at a current use.
    pub fn compute_binding_sha256(&self) -> Result<ContractDigestV1, CanonicalConsumerBindingError> {
        digest_encoding::compute_binding_sha256_v1(self)
    }
}

/// Return whether the current reviewed registry state permits a newly created
/// or newly used binding with `posture`. Historical evidence uses its frozen
/// posture and is checked by `CanonicalConsumerBindingV1::validate_historical`.
#[must_use]
pub const fn migration_posture_authorized_for_state_v1(
    state: ConsumerConvergenceStateV1,
    posture: CanonicalMigrationPostureV1,
) -> bool {
    match state {
        ConsumerConvergenceStateV1::CanonicalShadow
        | ConsumerConvergenceStateV1::RegisteredPendingCutover => {
            matches!(posture, CanonicalMigrationPostureV1::CompatibilityBound)
        }
        ConsumerConvergenceStateV1::CanonicalAuthoritative => matches!(
            posture,
            CanonicalMigrationPostureV1::Native
                | CanonicalMigrationPostureV1::CompatibilityBound
        ),
        ConsumerConvergenceStateV1::LegacyRetired => matches!(
            posture,
            CanonicalMigrationPostureV1::Native | CanonicalMigrationPostureV1::LegacyRetired
        ),
    }
}

/// Fail closed when a caller tries to promote or retire a consumer by choosing
/// a posture in the request. The reviewed registry state, not the payload
/// producer, authorizes migration. Current shadow and pending-cutover consumers
/// therefore require an exact compatibility digest.
pub fn authorize_migration_posture_v1(
    consumer: CanonicalConsumerV1,
    posture: CanonicalMigrationPostureV1,
) -> Result<(), CanonicalConsumerBindingError> {
    let registration = registered_consumer_v1(consumer.as_str()).ok_or(
        CanonicalConsumerBindingError::ConsumerNotRegistered { consumer },
    )?;
    if migration_posture_authorized_for_state_v1(registration.state, posture) {
        Ok(())
    } else {
        Err(CanonicalConsumerBindingError::MigrationPostureNotAuthorized {
            consumer,
            posture,
            state: registration.state,
        })
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
    bind_consumer_v1(
        operation_id,
        consumer,
        event,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
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
    bind_consumer_v1(
        operation_id,
        consumer,
        packet,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
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
    bind_consumer_v1(
        operation_id,
        consumer,
        receipt,
        source_identity_sha256,
        source_snapshot_sha256,
        compatibility_payload_sha256,
        migration_posture,
    )
}

// Private family mapping keeps the three public constructors on one checked
// field-construction path. It is not a new wire contract or consumer registry.
trait ConsumerPayloadV1: crate::wire::CognitiveContractV1 {
    const KIND: CanonicalPayloadKindV1;
}

impl ConsumerPayloadV1 for MemoryEventV1 {
    const KIND: CanonicalPayloadKindV1 = CanonicalPayloadKindV1::MemoryEvent;
}

impl ConsumerPayloadV1 for RecallPacketV1 {
    const KIND: CanonicalPayloadKindV1 = CanonicalPayloadKindV1::RecallPacket;
}

impl ConsumerPayloadV1 for ForgetPropagationReceiptV1 {
    const KIND: CanonicalPayloadKindV1 = CanonicalPayloadKindV1::ForgetPropagationReceipt;
}

fn bind_consumer_v1<T: ConsumerPayloadV1>(
    operation_id: ContractIdV1,
    consumer: CanonicalConsumerV1,
    value: &T,
    source_identity_sha256: Digest32,
    source_snapshot_sha256: Digest32,
    compatibility_payload_sha256: Option<Digest32>,
    migration_posture: CanonicalMigrationPostureV1,
) -> Result<CanonicalConsumerBindingV1, CanonicalConsumerBindingError> {
    // Retain the existing validation order and frozen digest profile. Only
    // immutable per-call work is reused; current migration checks still run.
    let payload = canonical_contract_digest_v1(value)
        .map_err(|error| CanonicalConsumerBindingError::CanonicalContract(error.to_string()))?;
    let canonical_payload_sha256 = digest(payload)?;
    CanonicalConsumerBindingV1::seal(CanonicalConsumerBindingV1 {
        operation_id,
        consumer,
        payload_kind: T::KIND,
        canonical_payload_sha256,
        source_identity_sha256: digest(source_identity_sha256)?,
        source_snapshot_sha256: digest(source_snapshot_sha256)?,
        compatibility_payload_sha256: compatibility_payload_sha256.map(digest).transpose()?,
        migration_posture,
        currentness_revalidation_required: true,
        binding_sha256: canonical_payload_sha256,
    })
}

fn consumer_accepts(consumer: CanonicalConsumerV1, payload: CanonicalPayloadKindV1) -> bool {
    match payload {
        CanonicalPayloadKindV1::MemoryEvent => matches!(
            consumer,
            CanonicalConsumerV1::CognitiveRead
                | CanonicalConsumerV1::CognitiveStore
                | CanonicalConsumerV1::CompactEngine
        ),
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalConsumerBindingError {
    CanonicalContract(String),
    ZeroDigest,
    CompatibilityDigestRequired,
    UnexpectedCompatibilityDigest,
    CurrentnessRevalidationRequired,
    ConsumerNotRegistered {
        consumer: CanonicalConsumerV1,
    },
    MigrationPostureNotAuthorized {
        consumer: CanonicalConsumerV1,
        posture: CanonicalMigrationPostureV1,
        state: ConsumerConvergenceStateV1,
    },
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

#[path = "consumer_error.rs"]
mod error_mapping;
#[path = "consumer_digest.rs"]
mod digest_encoding;
