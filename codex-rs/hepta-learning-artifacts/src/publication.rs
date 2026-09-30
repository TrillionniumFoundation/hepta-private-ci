//! Crash-recoverable host publication contract for V2 artifact admission.
//!
//! The stable V1 registry remains a compatibility index. A V1 manifest cannot
//! represent every V2 lineage field, so this transaction keeps the complete
//! validated V2 admission as the authoritative sidecar and binds it to the exact
//! durable V1 registry snapshot and current-head witness. A host may acknowledge
//! publication only after all ordered durability phases have completed.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactEvent;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::validate_artifact_publication_v3;
use crate::validate_registry_head_witness;
use crate::verify_artifact_admission_v3;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationPhaseV1 {
    Prepared,
    PayloadDurable,
    RegistryDurable,
    WitnessDurable,
    Acknowledged,
}

impl ArtifactPublicationPhaseV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::PayloadDurable => 1,
            Self::RegistryDurable => 2,
            Self::WitnessDurable => 3,
            Self::Acknowledged => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationIntentV1 {
    pub operation_id: StableId,
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub expected_registry_predecessor_head: Digest32,
    pub intent_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationTransactionSnapshotV1 {
    pub intent: ArtifactPublicationIntentV1,
    pub phase: ArtifactPublicationPhaseV1,
    pub registry_receipt: Option<RegistrySnapshotReceipt>,
    pub witness_receipt: Option<RegistryHeadWitnessReceipt>,
    pub acknowledged_at: Option<u64>,
    pub state_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationReceiptV1 {
    pub operation_id: StableId,
    pub admission_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub witness_digest: Digest32,
    pub state_digest: Digest32,
    pub acknowledged_at: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationStatusV1 {
    pub operation_id: StableId,
    pub phase: ArtifactPublicationPhaseV1,
    pub admission_digest: Digest32,
    pub withdrawal_scope_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub registry_head_digest: Option<Digest32>,
    pub witness_digest: Option<Digest32>,
    pub acknowledged_at: Option<u64>,
    pub state_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug)]
pub struct ArtifactPublicationTransactionV1 {
    intent: ArtifactPublicationIntentV1,
    phase: ArtifactPublicationPhaseV1,
    registry_receipt: Option<RegistrySnapshotReceipt>,
    witness_receipt: Option<RegistryHeadWitnessReceipt>,
    acknowledged_at: Option<u64>,
    state_digest: Digest32,
}

impl ArtifactPublicationTransactionV1 {
    pub fn begin(
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        expected_registry_predecessor_head: Digest32,
        now: u64,
    ) -> Result<Self, ArtifactPublicationError> {
        validate_artifact_publication_v3(&admission, withdrawal_registry, now)?;
        if registry.head_digest() != expected_registry_predecessor_head {
            return Err(ArtifactPublicationError::RegistryPredecessorMismatch);
        }
        let intent_digest = digest_intent(
            &operation_id,
            &admission,
            expected_registry_predecessor_head,
        );
        let intent = ArtifactPublicationIntentV1 {
            operation_id,
            admission,
            expected_registry_predecessor_head,
            intent_digest,
        };
        let phase = ArtifactPublicationPhaseV1::Prepared;
        let state_digest = digest_state(&intent, phase, None, None, None);
        Ok(Self {
            intent,
            phase,
            registry_receipt: None,
            witness_receipt: None,
            acknowledged_at: None,
            state_digest,
        })
    }

    #[must_use]
    pub fn intent(&self) -> &ArtifactPublicationIntentV1 {
        &self.intent
    }

    #[must_use]
    pub const fn phase(&self) -> ArtifactPublicationPhaseV1 {
        self.phase
    }

    #[must_use]
    pub const fn state_digest(&self) -> Digest32 {
        self.state_digest
    }

    #[must_use]
    pub fn status(&self) -> ArtifactPublicationStatusV1 {
        ArtifactPublicationStatusV1 {
            operation_id: self.intent.operation_id.clone(),
            phase: self.phase,
            admission_digest: self.intent.admission.admission_digest,
            withdrawal_scope_digest: self.intent.admission.withdrawal_scope_digest,
            withdrawal_head_digest: self.intent.admission.withdrawal_head_digest,
            registry_head_digest: self.registry_receipt.map(|receipt| receipt.head_digest),
            witness_digest: self.witness_receipt.map(|receipt| receipt.witness_digest),
            acknowledged_at: self.acknowledged_at,
            state_digest: self.state_digest,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    pub fn record_payload_durable(
        &mut self,
        payload_digest: Digest32,
        encoded_bytes: u64,
    ) -> Result<(), ArtifactPublicationError> {
        self.require_phase(ArtifactPublicationPhaseV1::Prepared)?;
        let manifest = &self.intent.admission.validated_manifest.manifest;
        if payload_digest != manifest.bytes_digest || encoded_bytes != manifest.encoded_size_bytes {
            return Err(ArtifactPublicationError::PayloadMismatch);
        }
        self.phase = ArtifactPublicationPhaseV1::PayloadDurable;
        self.refresh_state_digest();
        Ok(())
    }

    pub fn record_registry_durable(
        &mut self,
        registry: &ArtifactRegistry,
        receipt: RegistrySnapshotReceipt,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), ArtifactPublicationError> {
        self.require_phase(ArtifactPublicationPhaseV1::PayloadDurable)?;
        self.revalidate_withdrawal_frontier(withdrawal_registry, now)?;
        if receipt.binding.is_zero()
            || receipt.file_digest.is_zero()
            || receipt.head_digest.is_zero()
            || receipt.records != registry.records().len()
            || receipt.head_digest != registry.head_digest()
        {
            return Err(ArtifactPublicationError::RegistryReceiptMismatch);
        }
        let record = registry
            .records()
            .last()
            .ok_or(ArtifactPublicationError::RegistryProjectionMismatch)?;
        if record.predecessor_chain_digest != self.intent.expected_registry_predecessor_head {
            return Err(ArtifactPublicationError::RegistryPredecessorMismatch);
        }
        let v2 = &self.intent.admission.validated_manifest.manifest;
        let ArtifactEvent::Register { manifest: v1, .. } = &record.event else {
            return Err(ArtifactPublicationError::RegistryProjectionMismatch);
        };
        if v1.artifact_id != v2.artifact_id
            || v1.kind != v2.kind
            || v1.generation != v2.generation
            || v1.content_digest != v2.bytes_digest
            || v1.producer_id != v2.producer_id
            || v1.compatibility_digest != v2.compatibility_digest
            || v1.encoded_size_bytes != v2.encoded_size_bytes
        {
            return Err(ArtifactPublicationError::RegistryProjectionMismatch);
        }

        self.registry_receipt = Some(receipt);
        self.phase = ArtifactPublicationPhaseV1::RegistryDurable;
        self.refresh_state_digest();
        Ok(())
    }

    pub fn record_witness_durable(
        &mut self,
        witness: &RegistryHeadWitnessV1,
        requirement: &RegistryHeadRequirementV1,
        receipt: RegistryHeadWitnessReceipt,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), ArtifactPublicationError> {
        self.require_phase(ArtifactPublicationPhaseV1::RegistryDurable)?;
        self.revalidate_withdrawal_frontier(withdrawal_registry, now)?;
        let registry_receipt = self
            .registry_receipt
            .ok_or(ArtifactPublicationError::InternalInvariant)?;
        let validated = validate_registry_head_witness(witness, requirement)
            .map_err(|_| ArtifactPublicationError::WitnessReceiptMismatch)?;
        if receipt.binding.is_zero()
            || receipt.file_digest.is_zero()
            || receipt.witness_digest != validated.witness_digest
            || witness.head_digest != registry_receipt.head_digest
            || witness.predecessor_head_digest != self.intent.expected_registry_predecessor_head
            || receipt.binding != registry_receipt.binding
        {
            return Err(ArtifactPublicationError::WitnessReceiptMismatch);
        }

        self.witness_receipt = Some(receipt);
        self.phase = ArtifactPublicationPhaseV1::WitnessDurable;
        self.refresh_state_digest();
        Ok(())
    }

    pub fn acknowledge(
        &mut self,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<ArtifactPublicationReceiptV1, ArtifactPublicationError> {
        self.require_phase(ArtifactPublicationPhaseV1::WitnessDurable)?;
        self.revalidate_withdrawal_frontier(withdrawal_registry, now)?;
        if now < self.intent.admission.admitted_at {
            return Err(ArtifactPublicationError::AcknowledgementTime);
        }
        let registry_receipt = self
            .registry_receipt
            .ok_or(ArtifactPublicationError::InternalInvariant)?;
        let witness_receipt = self
            .witness_receipt
            .ok_or(ArtifactPublicationError::InternalInvariant)?;
        self.acknowledged_at = Some(now);
        self.phase = ArtifactPublicationPhaseV1::Acknowledged;
        self.refresh_state_digest();
        Ok(ArtifactPublicationReceiptV1 {
            operation_id: self.intent.operation_id.clone(),
            admission_digest: self.intent.admission.admission_digest,
            registry_head_digest: registry_receipt.head_digest,
            witness_digest: witness_receipt.witness_digest,
            state_digest: self.state_digest,
            acknowledged_at: now,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> ArtifactPublicationTransactionSnapshotV1 {
        ArtifactPublicationTransactionSnapshotV1 {
            intent: self.intent.clone(),
            phase: self.phase,
            registry_receipt: self.registry_receipt,
            witness_receipt: self.witness_receipt,
            acknowledged_at: self.acknowledged_at,
            state_digest: self.state_digest,
        }
    }

    pub fn from_snapshot(
        snapshot: ArtifactPublicationTransactionSnapshotV1,
    ) -> Result<Self, ArtifactPublicationError> {
        verify_artifact_admission_v3(
            &snapshot.intent.admission,
            snapshot.intent.admission.withdrawal_head_digest,
            snapshot.intent.admission.admitted_at,
        )?;
        let expected_intent = digest_intent(
            &snapshot.intent.operation_id,
            &snapshot.intent.admission,
            snapshot.intent.expected_registry_predecessor_head,
        );
        if expected_intent != snapshot.intent.intent_digest {
            return Err(ArtifactPublicationError::SnapshotMismatch);
        }
        validate_snapshot_shape(&snapshot)?;
        let expected_state = digest_state(
            &snapshot.intent,
            snapshot.phase,
            snapshot.registry_receipt,
            snapshot.witness_receipt,
            snapshot.acknowledged_at,
        );
        if expected_state != snapshot.state_digest {
            return Err(ArtifactPublicationError::SnapshotMismatch);
        }
        Ok(Self {
            intent: snapshot.intent,
            phase: snapshot.phase,
            registry_receipt: snapshot.registry_receipt,
            witness_receipt: snapshot.witness_receipt,
            acknowledged_at: snapshot.acknowledged_at,
            state_digest: snapshot.state_digest,
        })
    }

    fn revalidate_withdrawal_frontier(
        &self,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<(), ArtifactPublicationError> {
        validate_artifact_publication_v3(&self.intent.admission, withdrawal_registry, now)?;
        Ok(())
    }

    fn require_phase(
        &self,
        expected: ArtifactPublicationPhaseV1,
    ) -> Result<(), ArtifactPublicationError> {
        if self.phase != expected {
            return Err(ArtifactPublicationError::InvalidPhase);
        }
        Ok(())
    }

    fn refresh_state_digest(&mut self) {
        self.state_digest = digest_state(
            &self.intent,
            self.phase,
            self.registry_receipt,
            self.witness_receipt,
            self.acknowledged_at,
        );
    }
}

fn validate_snapshot_shape(
    snapshot: &ArtifactPublicationTransactionSnapshotV1,
) -> Result<(), ArtifactPublicationError> {
    let shape_ok = match snapshot.phase {
        ArtifactPublicationPhaseV1::Prepared | ArtifactPublicationPhaseV1::PayloadDurable => {
            snapshot.registry_receipt.is_none()
                && snapshot.witness_receipt.is_none()
                && snapshot.acknowledged_at.is_none()
        }
        ArtifactPublicationPhaseV1::RegistryDurable => {
            snapshot.registry_receipt.is_some()
                && snapshot.witness_receipt.is_none()
                && snapshot.acknowledged_at.is_none()
        }
        ArtifactPublicationPhaseV1::WitnessDurable => {
            snapshot.registry_receipt.is_some()
                && snapshot.witness_receipt.is_some()
                && snapshot.acknowledged_at.is_none()
        }
        ArtifactPublicationPhaseV1::Acknowledged => {
            snapshot.registry_receipt.is_some()
                && snapshot.witness_receipt.is_some()
                && snapshot.acknowledged_at.is_some()
        }
    };
    if !shape_ok {
        return Err(ArtifactPublicationError::SnapshotMismatch);
    }
    Ok(())
}

fn digest_intent(
    operation_id: &StableId,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    expected_registry_predecessor_head: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-intent.v1".to_vec();
    push_id(&mut bytes, operation_id);
    bytes.extend_from_slice(admission.validated_manifest.manifest_digest.as_array());
    bytes.extend_from_slice(admission.withdrawal_scope_digest.as_array());
    bytes.extend_from_slice(admission.withdrawal_head_digest.as_array());
    bytes.extend_from_slice(admission.admission_digest.as_array());
    bytes.extend_from_slice(expected_registry_predecessor_head.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_state(
    intent: &ArtifactPublicationIntentV1,
    phase: ArtifactPublicationPhaseV1,
    registry_receipt: Option<RegistrySnapshotReceipt>,
    witness_receipt: Option<RegistryHeadWitnessReceipt>,
    acknowledged_at: Option<u64>,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-transaction.v1".to_vec();
    bytes.extend_from_slice(intent.intent_digest.as_array());
    bytes.push(phase.tag());
    match registry_receipt {
        Some(receipt) => {
            bytes.push(1);
            bytes.extend_from_slice(receipt.binding.as_array());
            bytes.extend_from_slice(receipt.head_digest.as_array());
            bytes.extend_from_slice(receipt.file_digest.as_array());
            push_usize(&mut bytes, receipt.records);
            push_usize(&mut bytes, receipt.encoded_bytes);
        }
        None => bytes.push(0),
    }
    match witness_receipt {
        Some(receipt) => {
            bytes.push(1);
            bytes.extend_from_slice(receipt.binding.as_array());
            bytes.extend_from_slice(receipt.witness_digest.as_array());
            bytes.extend_from_slice(receipt.file_digest.as_array());
            push_usize(&mut bytes, receipt.encoded_bytes);
        }
        None => bytes.push(0),
    }
    match acknowledged_at {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(value.as_str().as_bytes());
    bytes.push(0);
}

fn push_usize(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(value.to_string().as_bytes());
    bytes.push(0);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    InvalidPhase,
    PayloadMismatch,
    RegistryPredecessorMismatch,
    RegistryProjectionMismatch,
    RegistryReceiptMismatch,
    WitnessReceiptMismatch,
    AcknowledgementTime,
    SnapshotMismatch,
    InternalInvariant,
}

impl fmt::Display for ArtifactPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactPublicationError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::InvalidPhase
            | Self::PayloadMismatch
            | Self::RegistryPredecessorMismatch
            | Self::RegistryProjectionMismatch
            | Self::RegistryReceiptMismatch
            | Self::WitnessReceiptMismatch
            | Self::AcknowledgementTime
            | Self::SnapshotMismatch
            | Self::InternalInvariant => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

#[cfg(test)]
#[path = "publication_tests.rs"]
mod tests;
