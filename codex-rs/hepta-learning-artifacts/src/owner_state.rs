//! Fenced publication saga for registry restrictions and withdrawal frontiers.

use super::*;

use crate::DatasetWithdrawalSnapshotReceiptV1;
use crate::read_dataset_withdrawal_snapshot;
use crate::write_dataset_withdrawal_snapshot_beneath;

#[path = "owner_state_io.rs"]
mod io;
#[path = "owner_state_publication.rs"]
mod publication;
#[path = "owner_state_storage.rs"]
mod storage;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactOwnerStateTransitionV1 {
    InstallWithdrawalFrontier,
    Revoke { artifact_id: StableId },
    Quarantine { artifact_id: StableId },
}

#[derive(Clone, Debug)]
pub struct ArtifactOwnerStateIntentV1 {
    pub operation_id: StableId,
    pub transition: ArtifactOwnerStateTransitionV1,
    pub evaluator_id: StableId,
    pub reason_digest: Digest32,
    pub expected_registry_predecessor_head: Digest32,
    pub expected_withdrawal_predecessor_head: Digest32,
    pub next_withdrawal_registry: DatasetWithdrawalRegistry,
}

#[derive(Clone, Debug)]
pub struct LearningArtifactStatePublishRequestV1 {
    pub intent: ArtifactOwnerStateIntentV1,
    pub signed_current_head: SignedCurrentArtifactHeadV1,
    pub now: u64,
    pub authorized_at: u64,
    pub authorization_expires_at: u64,
    pub state_authorization_signature: [u8; 64],
}

impl LearningArtifactStatePublishRequestV1 {
    /// Sign with the same externally trusted head signer; this binds the full
    /// intent and withdrawal frontier even when the registry has no state delta.
    pub fn authorization_signing_bytes(&self) -> Vec<u8> {
        authorization_bytes(
            &self.intent.operation_id,
            [
                LearningArtifactOwnerHost::state_request_digest(self),
                self.intent.expected_registry_predecessor_head,
                self.intent.expected_withdrawal_predecessor_head,
                self.signed_current_head.witness.head_digest,
                self.intent.next_withdrawal_registry.head_digest(),
            ],
            &self.signed_current_head,
            self.authorized_at,
            self.authorization_expires_at,
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerStatePublicationReceiptV1 {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub witness_digest: Digest32,
    pub state_digest: Digest32,
    pub acknowledged_at: u64,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum StatePhase {
    Prepared,
    SnapshotsDurable,
    WitnessDurable,
    Acknowledged,
}

impl StatePhase {
    const fn code(self) -> u8 {
        match self {
            Self::Prepared => 0,
            Self::SnapshotsDurable => 1,
            Self::WitnessDurable => 2,
            Self::Acknowledged => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct StateCheckpoint {
    pub operation_id: StableId,
    pub phase: StatePhase,
    pub request_digest: Digest32,
    pub expected_registry_predecessor_head: Digest32,
    pub expected_withdrawal_predecessor_head: Digest32,
    pub registry_receipt: RegistrySnapshotReceipt,
    pub withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    pub predecessor_withdrawal_receipt: DatasetWithdrawalSnapshotReceiptV1,
    pub witness_receipt: RegistryHeadWitnessReceipt,
    pub signed_head_digest: Digest32,
    pub original_writer_lease_digest: Digest32,
    pub acknowledged_at: Option<u64>,
    pub signed_head: SignedCurrentArtifactHeadV1,
    pub authorized_at: u64,
    pub authorization_expires_at: u64,
    pub state_authorization_signature: [u8; 64],
}

impl StateCheckpoint {
    pub(crate) fn is_acknowledged(&self) -> bool {
        self.phase == StatePhase::Acknowledged
    }

    fn receipt(&self) -> Result<ArtifactOwnerStatePublicationReceiptV1, ArtifactOwnerHostError> {
        Ok(ArtifactOwnerStatePublicationReceiptV1 {
            operation_id: self.operation_id.clone(),
            request_digest: self.request_digest,
            registry_head_digest: self.registry_receipt.head_digest,
            withdrawal_head_digest: self.withdrawal_receipt.head_digest,
            witness_digest: self.witness_receipt.witness_digest,
            state_digest: Digest32::of_bytes(&storage::encode(self)),
            acknowledged_at: self
                .acknowledged_at
                .ok_or(ArtifactOwnerHostError::CheckpointMismatch)?,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl LearningArtifactOwnerHost {
    pub(crate) fn state_request_digest(
        request: &LearningArtifactStatePublishRequestV1,
    ) -> Digest32 {
        let intent = &request.intent;
        let mut bytes = b"hepta.learning-artifacts.state-request.v1".to_vec();
        push_id(&mut bytes, &intent.operation_id);
        push_id(&mut bytes, &intent.evaluator_id);
        bytes.extend_from_slice(intent.reason_digest.as_array());
        bytes.extend_from_slice(intent.expected_registry_predecessor_head.as_array());
        bytes.extend_from_slice(intent.expected_withdrawal_predecessor_head.as_array());
        bytes.extend_from_slice(intent.next_withdrawal_registry.head_digest().as_array());
        match &intent.transition {
            ArtifactOwnerStateTransitionV1::InstallWithdrawalFrontier => bytes.push(0),
            ArtifactOwnerStateTransitionV1::Revoke { artifact_id } => {
                bytes.push(1);
                push_id(&mut bytes, artifact_id);
            }
            ArtifactOwnerStateTransitionV1::Quarantine { artifact_id } => {
                bytes.push(2);
                push_id(&mut bytes, artifact_id);
            }
        }
        bytes.extend_from_slice(&request.signed_current_head.signing_bytes());
        bytes.extend_from_slice(&request.signed_current_head.signature);
        bytes.extend_from_slice(&request.authorized_at.to_be_bytes());
        bytes.extend_from_slice(&request.authorization_expires_at.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    pub(crate) fn recover_state_publication(
        &self,
        operation: &StableId,
    ) -> Result<Option<StateCheckpoint>, ArtifactOwnerHostError> {
        storage::recover(self, operation)
    }

    pub(super) fn authenticate_state_checkpoint(
        &self,
        checkpoint: &StateCheckpoint,
        now: u64,
        require_current: bool,
    ) -> Result<(), ArtifactOwnerHostError> {
        let signed = &checkpoint.signed_head;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.verifier.trust.registry_id.clone(),
            minimum_generation: if require_current {
                self.verifier.trust.minimum_registry_generation
            } else {
                signed.witness.generation
            },
            expected_predecessor_head_digest: signed.witness.predecessor_head_digest,
            minimum_authority_epoch: if require_current {
                self.verifier.trust.minimum_authority_epoch
            } else {
                signed.witness.authority_epoch
            },
            now: signed.witness.issued_at,
        };
        self.verifier
            .verify_signed_head(signed, &requirement, false)?;
        if checkpoint.authorized_at > now
            || checkpoint.authorized_at > checkpoint.authorization_expires_at
            || require_current && now > checkpoint.authorization_expires_at
            || signed.witness.head_digest != checkpoint.registry_receipt.head_digest
            || signed.binding != checkpoint.registry_receipt.binding
            || signed.withdrawal_scope_digest != checkpoint.withdrawal_receipt.scope_digest
            || checkpoint.registry_receipt.binding != checkpoint.withdrawal_receipt.binding
            || checkpoint.predecessor_withdrawal_receipt.scope_digest
                != checkpoint.withdrawal_receipt.scope_digest
            || checkpoint.predecessor_withdrawal_receipt.binding
                != checkpoint.withdrawal_receipt.binding
            || checkpoint.predecessor_withdrawal_receipt.head_digest
                != checkpoint.expected_withdrawal_predecessor_head
        {
            return Err(ArtifactOwnerHostError::CurrentHeadContext);
        }
        let signer = self
            .verifier
            .head_signers
            .get(&signed.witness.signer_id)
            .ok_or(ArtifactOwnerHostError::UnknownSigner)?;
        verify_signer_context(
            signer,
            signed.witness.signing_key_digest,
            signed.witness.authority_epoch,
            checkpoint.authorized_at,
            now,
            require_current,
        )?;
        verify_signature(
            &signer.verifying_key,
            &authorization_bytes(
                &checkpoint.operation_id,
                [
                    checkpoint.request_digest,
                    checkpoint.expected_registry_predecessor_head,
                    checkpoint.expected_withdrawal_predecessor_head,
                    checkpoint.registry_receipt.head_digest,
                    checkpoint.withdrawal_receipt.head_digest,
                ],
                signed,
                checkpoint.authorized_at,
                checkpoint.authorization_expires_at,
            ),
            &checkpoint.state_authorization_signature,
        )
    }

    pub(crate) fn state_recovery_operations(
        &self,
    ) -> Result<Vec<StableId>, ArtifactOwnerHostError> {
        Ok(storage::all(self)?
            .into_iter()
            .filter(|checkpoint| !checkpoint.is_acknowledged())
            .map(|checkpoint| checkpoint.operation_id)
            .collect())
    }

    pub(super) fn state_registry_receipts_by_head(
        &self,
        head: Digest32,
    ) -> Result<Vec<RegistrySnapshotReceipt>, ArtifactOwnerHostError> {
        Ok(storage::all(self)?
            .into_iter()
            .filter(|checkpoint| {
                checkpoint.phase != StatePhase::Prepared
                    && checkpoint.registry_receipt.head_digest == head
            })
            .map(|checkpoint| checkpoint.registry_receipt)
            .collect())
    }

    pub(crate) fn recover_durable_withdrawal_frontier(
        &self,
        supplied: DatasetWithdrawalRegistry,
        binding: Digest32,
    ) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
        let mut frontier = supplied;
        for checkpoint in storage::all(self)? {
            if checkpoint.phase == StatePhase::Prepared {
                continue;
            }
            if checkpoint.withdrawal_receipt.binding != binding
                || checkpoint.withdrawal_receipt.scope_digest
                    != self.verifier.trust.withdrawal_scope_digest
            {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            let next = read_dataset_withdrawal_snapshot(
                File::open(
                    self.root
                        .join(storage::withdrawal_path(checkpoint.withdrawal_receipt)),
                )?,
                checkpoint.withdrawal_receipt,
            )?;
            let current_snapshot = frontier.snapshot();
            let next_snapshot = next.snapshot();
            let common = current_snapshot
                .records()
                .len()
                .min(next_snapshot.records().len());
            if current_snapshot.records()[..common] != next_snapshot.records()[..common] {
                return Err(ArtifactOwnerHostError::CheckpointMismatch);
            }
            if next_snapshot.records().len() > current_snapshot.records().len() {
                frontier = next;
            }
        }
        Ok(frontier)
    }

    pub(crate) fn recover_withdrawal_by_head(
        &self,
        head: Digest32,
        supplied: &DatasetWithdrawalRegistry,
    ) -> Result<DatasetWithdrawalRegistry, ArtifactOwnerHostError> {
        if supplied.head_digest() == head {
            return Ok(supplied.clone());
        }
        for checkpoint in storage::all(self)? {
            for receipt in [
                checkpoint.predecessor_withdrawal_receipt,
                checkpoint.withdrawal_receipt,
            ] {
                if receipt.head_digest != head {
                    continue;
                }
                match File::open(self.root.join(storage::withdrawal_path(receipt))) {
                    Ok(file) => return Ok(read_dataset_withdrawal_snapshot(file, receipt)?),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(error) => return Err(error.into()),
                }
            }
        }
        Err(ArtifactOwnerHostError::CheckpointMissing)
    }
}

fn authorization_bytes(
    operation: &StableId,
    digests: [Digest32; 5],
    signed: &SignedCurrentArtifactHeadV1,
    authorized_at: u64,
    expires_at: u64,
) -> Vec<u8> {
    let mut bytes = b"hepta.learning-artifacts.state-authorization.v1".to_vec();
    push_id(&mut bytes, operation);
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&signed.signing_bytes());
    bytes.extend_from_slice(&signed.signature);
    bytes.extend_from_slice(&authorized_at.to_be_bytes());
    bytes.extend_from_slice(&expires_at.to_be_bytes());
    bytes
}
