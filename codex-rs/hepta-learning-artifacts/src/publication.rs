//! Crash-recoverable host publication contract for V2/V3 artifact admission.
//!
//! This module deliberately does not pretend that independent files are one
//! filesystem transaction. Instead it gives the host a closed publication
//! protocol: validate the withdrawal-bound admission, bind it to the exact
//! registry append, make the registry snapshot durable, publish the independently
//! authenticated current-head witness, and only then acknowledge the producer.
//! A restart reconstructs progress from an immutable publication contract plus
//! durable receipts. The contract's deterministic binding is carried by the
//! snapshot and witness receipts, so changed contract semantics fail closed.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactEvent;
use crate::ArtifactManifest;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryAppendReceipt;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::registry::digest_chain;
use crate::registry::digest_event;
use crate::validate_artifact_publication_v3;
use crate::validate_registry_head_witness;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationPhaseV1 {
    Prepared,
    SnapshotDurable,
    WitnessDurable,
    Acknowledged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationContractV1 {
    pub operation_id: StableId,
    pub registry_id: StableId,
    pub admission_digest: Digest32,
    pub manifest_digest: Digest32,
    pub withdrawal_domain_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub registry_predecessor_head_digest: Digest32,
    pub registry_successor_head_digest: Digest32,
    pub registry_sequence: LogicalSequence,
    pub registry_event_digest: Digest32,
    pub snapshot_binding: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationTransactionV1 {
    contract: ArtifactPublicationContractV1,
    phase: ArtifactPublicationPhaseV1,
    snapshot_file_digest: Option<Digest32>,
    witness_digest: Option<Digest32>,
}

impl ArtifactPublicationTransactionV1 {
    #[must_use]
    pub fn contract(&self) -> &ArtifactPublicationContractV1 {
        &self.contract
    }

    #[must_use]
    pub fn phase(&self) -> ArtifactPublicationPhaseV1 {
        self.phase
    }

    #[must_use]
    pub fn may_acknowledge_source(&self) -> bool {
        matches!(
            self.phase,
            ArtifactPublicationPhaseV1::WitnessDurable | ArtifactPublicationPhaseV1::Acknowledged
        )
    }

    pub fn observe_snapshot_durable(
        &mut self,
        receipt: RegistrySnapshotReceipt,
    ) -> Result<(), ArtifactPublicationError> {
        if receipt.binding != self.contract.snapshot_binding
            || receipt.head_digest != self.contract.registry_successor_head_digest
            || u64::try_from(receipt.records).ok() != Some(self.contract.registry_sequence.get())
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
        {
            return Err(ArtifactPublicationError::SnapshotReceiptMismatch);
        }
        match self.phase {
            ArtifactPublicationPhaseV1::Prepared => {
                self.snapshot_file_digest = Some(receipt.file_digest);
                self.phase = ArtifactPublicationPhaseV1::SnapshotDurable;
                Ok(())
            }
            ArtifactPublicationPhaseV1::SnapshotDurable
                if self.snapshot_file_digest == Some(receipt.file_digest) =>
            {
                Ok(())
            }
            ArtifactPublicationPhaseV1::WitnessDurable
            | ArtifactPublicationPhaseV1::Acknowledged
                if self.snapshot_file_digest == Some(receipt.file_digest) =>
            {
                Ok(())
            }
            ArtifactPublicationPhaseV1::SnapshotDurable
            | ArtifactPublicationPhaseV1::WitnessDurable
            | ArtifactPublicationPhaseV1::Acknowledged => {
                Err(ArtifactPublicationError::PhaseConflict)
            }
        }
    }

    pub fn observe_witness_durable(
        &mut self,
        witness: &RegistryHeadWitnessV1,
        receipt: RegistryHeadWitnessReceipt,
    ) -> Result<(), ArtifactPublicationError> {
        if self.snapshot_file_digest.is_none() {
            return Err(ArtifactPublicationError::SnapshotNotDurable);
        }
        if witness.registry_id != self.contract.registry_id
            || witness.head_digest != self.contract.registry_successor_head_digest
            || witness.predecessor_head_digest != self.contract.registry_predecessor_head_digest
            || receipt.binding != self.contract.snapshot_binding
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
        {
            return Err(ArtifactPublicationError::WitnessReceiptMismatch);
        }
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.contract.registry_id.clone(),
            minimum_generation: witness.generation,
            expected_predecessor_head_digest: self.contract.registry_predecessor_head_digest,
            minimum_authority_epoch: witness.authority_epoch,
            now: witness.issued_at,
        };
        let validated = validate_registry_head_witness(witness, &requirement)
            .map_err(|_| ArtifactPublicationError::WitnessReceiptMismatch)?;
        if validated.witness_digest != receipt.witness_digest {
            return Err(ArtifactPublicationError::WitnessReceiptMismatch);
        }
        match self.phase {
            ArtifactPublicationPhaseV1::SnapshotDurable => {
                self.witness_digest = Some(receipt.witness_digest);
                self.phase = ArtifactPublicationPhaseV1::WitnessDurable;
                Ok(())
            }
            ArtifactPublicationPhaseV1::WitnessDurable
            | ArtifactPublicationPhaseV1::Acknowledged
                if self.witness_digest == Some(receipt.witness_digest) =>
            {
                Ok(())
            }
            ArtifactPublicationPhaseV1::Prepared => {
                Err(ArtifactPublicationError::SnapshotNotDurable)
            }
            ArtifactPublicationPhaseV1::WitnessDurable
            | ArtifactPublicationPhaseV1::Acknowledged => {
                Err(ArtifactPublicationError::PhaseConflict)
            }
        }
    }

    pub fn acknowledge_source(&mut self) -> Result<(), ArtifactPublicationError> {
        match self.phase {
            ArtifactPublicationPhaseV1::WitnessDurable => {
                self.phase = ArtifactPublicationPhaseV1::Acknowledged;
                Ok(())
            }
            ArtifactPublicationPhaseV1::Acknowledged => Ok(()),
            ArtifactPublicationPhaseV1::Prepared | ArtifactPublicationPhaseV1::SnapshotDurable => {
                Err(ArtifactPublicationError::WitnessNotDurable)
            }
        }
    }
}

/// Deterministic V1 registry projection of an admitted V3 artifact.
///
/// The stable V1 registry cannot encode the complete V2 manifest shape. To keep
/// post-publication dataset revocation sound, a dataset-derived admission is
/// projectable only when it names exactly one source dataset; that exact digest
/// remains the V1 support digest. Dataset-independent admissions use the
/// admission digest as their non-dataset support witness. The V1 event ID stays
/// equal to the caller's exact operation ID, preserving ordinary registry
/// idempotency and identity-reuse conflict semantics.
///
/// The complete V3 admission cannot be embedded losslessly into stable V1 while
/// also preserving dataset revocation. The publication contract therefore derives
/// the snapshot/witness binding from the admission frontier and exact V1 append.
/// The stable V1 registry can enforce at most one artifact predecessor, so
/// publication rejects multi-dataset and multi-predecessor V2 manifests instead
/// of silently dropping revocation or eligibility edges.
pub fn artifact_registry_event_for_admission_v3(
    operation_id: StableId,
    admission: &WithdrawalBoundArtifactAdmissionV3,
) -> Result<ArtifactEvent, ArtifactPublicationError> {
    let manifest = &admission.validated_manifest.manifest;
    let predecessor_id = match manifest.predecessor_ids.as_slice() {
        [] => None,
        [only] => Some(only.clone()),
        _ => return Err(ArtifactPublicationError::MultiPredecessorProjectionUnsupported),
    };
    let support_digest = match (
        manifest.provenance_mode,
        manifest.source_dataset_digests.as_slice(),
    ) {
        (crate::ProvenanceModeV1::DatasetDerived, [only]) => *only,
        (crate::ProvenanceModeV1::DatasetDerived, _) => {
            return Err(ArtifactPublicationError::MultiDatasetProjectionUnsupported);
        }
        (crate::ProvenanceModeV1::DatasetIndependent, []) => admission.admission_digest,
        (crate::ProvenanceModeV1::DatasetIndependent, _) => {
            return Err(ArtifactPublicationError::InvalidBinding);
        }
    };
    Ok(ArtifactEvent::Register {
        event_id: operation_id,
        manifest: ArtifactManifest {
            artifact_id: manifest.artifact_id.clone(),
            kind: manifest.kind,
            generation: manifest.generation,
            predecessor_id,
            content_digest: manifest.bytes_digest,
            objective_digest: manifest.objective_class_digest,
            support_digest,
            producer_id: manifest.producer_id.clone(),
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
        },
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationRegistryBindingV1 {
    pub registry_id: StableId,
    pub predecessor_head_digest: Digest32,
}

pub fn prepare_artifact_publication_v1(
    operation_id: StableId,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    now: u64,
    append_receipt: &RegistryAppendReceipt,
    registry_binding: ArtifactPublicationRegistryBindingV1,
) -> Result<ArtifactPublicationTransactionV1, ArtifactPublicationError> {
    let ArtifactPublicationRegistryBindingV1 {
        registry_id,
        predecessor_head_digest: registry_predecessor_head_digest,
    } = registry_binding;
    validate_artifact_publication_v3(admission, withdrawal_registry, now)
        .map_err(ArtifactPublicationError::Admission)?;
    if append_receipt.event_digest.is_zero() || append_receipt.chain_digest.is_zero() {
        return Err(ArtifactPublicationError::InvalidBinding);
    }
    let expected_event = artifact_registry_event_for_admission_v3(operation_id.clone(), admission)?;
    let expected_event_digest = digest_event(&expected_event);
    if append_receipt.event_digest != expected_event_digest {
        return Err(ArtifactPublicationError::RegistryEventMismatch);
    }
    let expected_chain_digest = digest_chain(
        registry_predecessor_head_digest,
        append_receipt.sequence,
        expected_event_digest,
    );
    if append_receipt.chain_digest != expected_chain_digest {
        return Err(ArtifactPublicationError::RegistryChainMismatch);
    }
    let mut contract = ArtifactPublicationContractV1 {
        operation_id,
        registry_id,
        admission_digest: admission.admission_digest,
        manifest_digest: admission.validated_manifest.manifest_digest,
        withdrawal_domain_digest: admission.withdrawal_domain_digest,
        withdrawal_head_digest: admission.withdrawal_head_digest,
        registry_predecessor_head_digest,
        registry_successor_head_digest: append_receipt.chain_digest,
        registry_sequence: append_receipt.sequence,
        registry_event_digest: append_receipt.event_digest,
        snapshot_binding: Digest32::ZERO,
    };
    contract.snapshot_binding = publication_contract_binding(&contract);
    Ok(ArtifactPublicationTransactionV1 {
        contract,
        phase: ArtifactPublicationPhaseV1::Prepared,
        snapshot_file_digest: None,
        witness_digest: None,
    })
}

pub fn validate_artifact_publication_retry_v1(
    recorded: &ArtifactPublicationContractV1,
    candidate: &ArtifactPublicationContractV1,
) -> Result<(), ArtifactPublicationError> {
    if recorded.snapshot_binding != publication_contract_binding(recorded)
        || candidate.snapshot_binding != publication_contract_binding(candidate)
    {
        return Err(ArtifactPublicationError::ContractBindingMismatch);
    }
    if recorded.operation_id != candidate.operation_id {
        return Err(ArtifactPublicationError::OperationIdentityMismatch);
    }
    if recorded != candidate {
        return Err(ArtifactPublicationError::OperationIdentityConflict);
    }
    Ok(())
}

pub fn recover_artifact_publication_v1(
    contract: ArtifactPublicationContractV1,
    snapshot_receipt: Option<RegistrySnapshotReceipt>,
    witness: Option<(&RegistryHeadWitnessV1, RegistryHeadWitnessReceipt)>,
) -> Result<ArtifactPublicationTransactionV1, ArtifactPublicationError> {
    if contract.snapshot_binding != publication_contract_binding(&contract) {
        return Err(ArtifactPublicationError::ContractBindingMismatch);
    }
    let mut transaction = ArtifactPublicationTransactionV1 {
        contract,
        phase: ArtifactPublicationPhaseV1::Prepared,
        snapshot_file_digest: None,
        witness_digest: None,
    };
    if let Some(receipt) = snapshot_receipt {
        transaction.observe_snapshot_durable(receipt)?;
    }
    if let Some((witness, receipt)) = witness {
        transaction.observe_witness_durable(witness, receipt)?;
    }
    Ok(transaction)
}

fn publication_contract_binding(contract: &ArtifactPublicationContractV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-contract-binding.v1".to_vec();
    push_stable_id(&mut bytes, &contract.operation_id);
    push_stable_id(&mut bytes, &contract.registry_id);
    bytes.extend_from_slice(contract.admission_digest.as_array());
    bytes.extend_from_slice(contract.manifest_digest.as_array());
    bytes.extend_from_slice(contract.withdrawal_domain_digest.as_array());
    bytes.extend_from_slice(contract.withdrawal_head_digest.as_array());
    bytes.extend_from_slice(contract.registry_predecessor_head_digest.as_array());
    bytes.extend_from_slice(contract.registry_successor_head_digest.as_array());
    bytes.extend_from_slice(&contract.registry_sequence.get().to_be_bytes());
    bytes.extend_from_slice(contract.registry_event_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_stable_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let length = u64::try_from(raw.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    InvalidBinding,
    RegistryEventMismatch,
    RegistryChainMismatch,
    ContractBindingMismatch,
    OperationIdentityMismatch,
    OperationIdentityConflict,
    MultiDatasetProjectionUnsupported,
    MultiPredecessorProjectionUnsupported,
    SnapshotReceiptMismatch,
    WitnessReceiptMismatch,
    SnapshotNotDurable,
    WitnessNotDurable,
    PhaseConflict,
}

impl fmt::Display for ArtifactPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ArtifactPublicationError {}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::Generation;

    use crate::ArtifactKind;
    use crate::DatasetWithdrawalDomainV1;
    use crate::LearningArtifactManifestV2;
    use crate::ProvenanceModeV1;
    use crate::RegistryAppendDisposition;
    use crate::ValidatedArtifactManifestV2;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn admission() -> WithdrawalBoundArtifactAdmissionV3 {
        WithdrawalBoundArtifactAdmissionV3 {
            validated_manifest: ValidatedArtifactManifestV2 {
                manifest: LearningArtifactManifestV2 {
                    artifact_id: id("artifact"),
                    kind: ArtifactKind::Model,
                    generation: Generation::new(1).expect("generation"),
                    provenance_mode: ProvenanceModeV1::DatasetIndependent,
                    source_dataset_digests: Vec::new(),
                    lineage_digests: vec![digest("lineage")],
                    predecessor_ids: Vec::new(),
                    rollback_predecessor: None,
                    bytes_digest: digest("bytes"),
                    encoded_size_bytes: 32,
                    training_code_digest: digest("training"),
                    runtime_tuple_digest: digest("runtime"),
                    device_profile_digest: digest("device"),
                    objective_class_digest: digest("objective"),
                    compatibility_digest: digest("compatibility"),
                    schema_profile_digest: digest("schema"),
                    normalization_digest: digest("normalization"),
                    producer_id: id("producer"),
                    created_at: 10,
                    expires_at: 100,
                },
                manifest_digest: digest("manifest"),
                authority: AuthorityPosture::DENY_ALL,
            },
            withdrawal_domain_digest: digest("domain"),
            withdrawal_head_digest: Digest32::ZERO,
            admitted_at: 20,
            admission_digest: digest("admission"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn scoped_registry() -> DatasetWithdrawalRegistry {
        DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalDomainV1 {
            registry_id: id("withdrawals"),
            scope_digest: digest("scope"),
            authority_domain_digest: digest("authority"),
        })
        .expect("scoped registry")
    }

    fn append_receipt(
        operation_id: StableId,
        admission: &WithdrawalBoundArtifactAdmissionV3,
        predecessor: Digest32,
    ) -> RegistryAppendReceipt {
        let sequence = LogicalSequence::new(1).expect("sequence");
        let event =
            artifact_registry_event_for_admission_v3(operation_id, admission).expect("projection");
        let event_digest = digest_event(&event);
        RegistryAppendReceipt {
            disposition: RegistryAppendDisposition::Appended,
            sequence,
            event_digest,
            chain_digest: digest_chain(predecessor, sequence, event_digest),
        }
    }

    fn publication_binding(
        predecessor_head_digest: Digest32,
    ) -> ArtifactPublicationRegistryBindingV1 {
        ArtifactPublicationRegistryBindingV1 {
            registry_id: id("artifacts"),
            predecessor_head_digest,
        }
    }

    fn publication_contract() -> ArtifactPublicationContractV1 {
        let mut contract = ArtifactPublicationContractV1 {
            operation_id: id("operation"),
            registry_id: id("artifacts"),
            admission_digest: digest("admission"),
            manifest_digest: digest("manifest"),
            withdrawal_domain_digest: digest("domain"),
            withdrawal_head_digest: Digest32::ZERO,
            registry_predecessor_head_digest: digest("previous-head"),
            registry_successor_head_digest: digest("registry-head"),
            registry_sequence: LogicalSequence::new(1).expect("sequence"),
            registry_event_digest: digest("registry-event"),
            snapshot_binding: Digest32::ZERO,
        };
        contract.snapshot_binding = publication_contract_binding(&contract);
        contract
    }

    fn snapshot_receipt(binding: Digest32) -> RegistrySnapshotReceipt {
        RegistrySnapshotReceipt {
            binding,
            head_digest: digest("registry-head"),
            file_digest: digest("snapshot-file"),
            records: 1,
            encoded_bytes: 100,
        }
    }

    fn witness(binding: Digest32) -> (RegistryHeadWitnessV1, RegistryHeadWitnessReceipt) {
        let witness = RegistryHeadWitnessV1 {
            registry_id: id("artifacts"),
            generation: Generation::new(2).expect("generation"),
            head_digest: digest("registry-head"),
            predecessor_head_digest: digest("previous-head"),
            authority_epoch: 3,
            signer_id: id("owner"),
            signing_key_digest: digest("key"),
            issued_at: 20,
            expires_at: 100,
        };
        let validated = validate_registry_head_witness(
            &witness,
            &RegistryHeadRequirementV1 {
                registry_id: witness.registry_id.clone(),
                minimum_generation: witness.generation,
                expected_predecessor_head_digest: witness.predecessor_head_digest,
                minimum_authority_epoch: witness.authority_epoch,
                now: witness.issued_at,
            },
        )
        .expect("valid witness");
        (
            witness,
            RegistryHeadWitnessReceipt {
                binding,
                witness_digest: validated.witness_digest,
                file_digest: digest("witness-file"),
                encoded_bytes: 100,
            },
        )
    }

    #[test]
    fn crash_recovery_never_treats_snapshot_only_as_published() {
        let contract = publication_contract();
        let binding = contract.snapshot_binding;
        let mut prepared =
            recover_artifact_publication_v1(contract.clone(), None, None).expect("recover");
        assert_eq!(prepared.phase(), ArtifactPublicationPhaseV1::Prepared);
        assert_eq!(
            prepared.acknowledge_source(),
            Err(ArtifactPublicationError::WitnessNotDurable)
        );

        let mut snapshot_only = recover_artifact_publication_v1(
            contract.clone(),
            Some(snapshot_receipt(binding)),
            None,
        )
        .expect("recover snapshot");
        assert_eq!(
            snapshot_only.phase(),
            ArtifactPublicationPhaseV1::SnapshotDurable
        );
        assert_eq!(
            snapshot_only.acknowledge_source(),
            Err(ArtifactPublicationError::WitnessNotDurable)
        );

        let mut wrong_count = snapshot_receipt(binding);
        wrong_count.records = 2;
        assert_eq!(
            recover_artifact_publication_v1(contract.clone(), Some(wrong_count), None),
            Err(ArtifactPublicationError::SnapshotReceiptMismatch)
        );

        let (head, receipt) = witness(binding);
        let mut published = recover_artifact_publication_v1(
            contract,
            Some(snapshot_receipt(binding)),
            Some((&head, receipt)),
        )
        .expect("recover published");
        assert_eq!(
            published.phase(),
            ArtifactPublicationPhaseV1::WitnessDurable
        );
        published.acknowledge_source().expect("ack allowed");
        assert_eq!(published.phase(), ArtifactPublicationPhaseV1::Acknowledged);
    }

    #[test]
    fn durable_witness_from_wrong_registry_namespace_is_rejected() {
        let contract = publication_contract();
        let binding = contract.snapshot_binding;
        let mut transaction =
            recover_artifact_publication_v1(contract, Some(snapshot_receipt(binding)), None)
                .expect("snapshot recovery");

        let (mut wrong_registry, _) = witness(binding);
        wrong_registry.registry_id = id("other-artifacts");
        let validated = validate_registry_head_witness(
            &wrong_registry,
            &RegistryHeadRequirementV1 {
                registry_id: wrong_registry.registry_id.clone(),
                minimum_generation: wrong_registry.generation,
                expected_predecessor_head_digest: wrong_registry.predecessor_head_digest,
                minimum_authority_epoch: wrong_registry.authority_epoch,
                now: wrong_registry.issued_at,
            },
        )
        .expect("self-consistent witness for another registry");
        let wrong_receipt = RegistryHeadWitnessReceipt {
            binding,
            witness_digest: validated.witness_digest,
            file_digest: digest("other-witness-file"),
            encoded_bytes: 100,
        };
        assert_eq!(
            transaction.observe_witness_durable(&wrong_registry, wrong_receipt),
            Err(ArtifactPublicationError::WitnessReceiptMismatch)
        );
    }

    #[test]
    fn witness_without_snapshot_is_rejected_after_restart() {
        let contract = publication_contract();
        let binding = contract.snapshot_binding;
        let (head, receipt) = witness(binding);
        assert_eq!(
            recover_artifact_publication_v1(contract, None, Some((&head, receipt))),
            Err(ArtifactPublicationError::SnapshotNotDurable)
        );
    }

    #[test]
    fn prepare_binds_admission_to_exact_registry_event_and_chain() {
        let registry = scoped_registry();
        let head = registry.snapshot().head_digest;
        let admitted = crate::admit_manifest_at_withdrawal_head_v3(
            &registry,
            head,
            admission().validated_manifest.manifest,
            20,
        )
        .expect("admission");
        let operation_id = id("operation");
        let predecessor = digest("previous-head");
        let receipt = append_receipt(operation_id.clone(), &admitted, predecessor);
        let transaction = prepare_artifact_publication_v1(
            operation_id.clone(),
            &admitted,
            &registry,
            20,
            &receipt,
            publication_binding(predecessor),
        )
        .expect("publication contract");
        assert_eq!(transaction.contract().operation_id, operation_id);
        assert_eq!(transaction.contract().registry_id, id("artifacts"));
        assert_eq!(transaction.contract().registry_sequence, receipt.sequence);
        assert_eq!(
            transaction.contract().registry_event_digest,
            receipt.event_digest
        );

        let mut wrong_event = receipt.clone();
        wrong_event.event_digest = digest("other-event");
        assert_eq!(
            prepare_artifact_publication_v1(
                id("operation"),
                &admitted,
                &registry,
                20,
                &wrong_event,
                publication_binding(predecessor),
            ),
            Err(ArtifactPublicationError::RegistryEventMismatch)
        );

        let mut wrong_chain = receipt;
        wrong_chain.chain_digest = digest("other-chain");
        assert_eq!(
            prepare_artifact_publication_v1(
                id("operation"),
                &admitted,
                &registry,
                20,
                &wrong_chain,
                publication_binding(predecessor),
            ),
            Err(ArtifactPublicationError::RegistryChainMismatch)
        );
    }

    #[test]
    fn dataset_derived_publication_preserves_v1_revocation_support() {
        let withdrawal_registry = scoped_registry();
        let dataset = digest("dataset");
        let mut manifest = admission().validated_manifest.manifest;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = vec![dataset];
        let admitted = crate::admit_manifest_at_withdrawal_head_v3(
            &withdrawal_registry,
            withdrawal_registry.snapshot().head_digest,
            manifest,
            20,
        )
        .expect("dataset-bound admission");

        let operation_id = id("publication-operation");
        let event = artifact_registry_event_for_admission_v3(operation_id, &admitted)
            .expect("single-dataset projection");
        let ArtifactEvent::Register { manifest, .. } = &event else {
            panic!("publication must register");
        };
        assert_eq!(manifest.support_digest, dataset);

        let mut artifact_registry = crate::ArtifactRegistry::new();
        artifact_registry.append(event).expect("registry append");
        let prepared = crate::prepare_dataset_revocation(
            &artifact_registry,
            artifact_registry.snapshot().head_digest,
            &crate::DatasetRevocationRequest {
                operation_id: id("dataset-withdrawal-operation"),
                dataset_digest: dataset,
                source_revocation_digest: digest("source-withdrawal"),
                evaluator_id: id("independent-evaluator"),
            },
        )
        .expect("published dataset-derived artifact remains revocable");
        assert_eq!(prepared.summary().direct_artifacts, vec![id("artifact")]);
        assert_eq!(prepared.summary().appended, 1);
    }

    #[test]
    fn dataset_derived_publication_rejects_multi_dataset_v1_downgrade() {
        let mut multi = admission();
        multi.validated_manifest.manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        multi.validated_manifest.manifest.source_dataset_digests =
            vec![digest("dataset-a"), digest("dataset-b")];
        assert_eq!(
            artifact_registry_event_for_admission_v3(id("operation"), &multi),
            Err(ArtifactPublicationError::MultiDatasetProjectionUnsupported)
        );
    }

    #[test]
    fn publication_binding_commits_admission_frontier_without_rewriting_operation_identity() {
        let registry = scoped_registry();
        let head = registry.snapshot().head_digest;
        let mut manifest = admission().validated_manifest.manifest;
        manifest.provenance_mode = ProvenanceModeV1::DatasetDerived;
        manifest.source_dataset_digests = vec![digest("dataset")];
        let first =
            crate::admit_manifest_at_withdrawal_head_v3(&registry, head, manifest.clone(), 20)
                .expect("first admission");
        let second =
            crate::admit_manifest_at_withdrawal_head_v3(&registry, head, manifest, 21)
                .expect("second admission");
        let operation_id = id("operation");
        let predecessor = digest("previous-head");
        let first_event =
            artifact_registry_event_for_admission_v3(operation_id.clone(), &first)
                .expect("first projection");
        let second_event =
            artifact_registry_event_for_admission_v3(operation_id.clone(), &second)
                .expect("second projection");
        assert_eq!(digest_event(&first_event), digest_event(&second_event));
        assert_eq!(first_event.event_id(), &operation_id);
        assert_eq!(second_event.event_id(), &operation_id);

        let receipt = append_receipt(operation_id.clone(), &first, predecessor);
        let first_transaction = prepare_artifact_publication_v1(
            operation_id.clone(),
            &first,
            &registry,
            21,
            &receipt,
            publication_binding(predecessor),
        )
        .expect("first publication contract");
        let second_transaction = prepare_artifact_publication_v1(
            operation_id,
            &second,
            &registry,
            21,
            &receipt,
            publication_binding(predecessor),
        )
        .expect("second publication contract");
        assert_ne!(
            first_transaction.contract().snapshot_binding,
            second_transaction.contract().snapshot_binding
        );
    }

    #[test]
    fn recovery_rejects_contract_semantic_drift() {
        let mut contract = publication_contract();
        contract.admission_digest = digest("other-admission");
        assert_eq!(
            recover_artifact_publication_v1(contract, None, None),
            Err(ArtifactPublicationError::ContractBindingMismatch)
        );
    }

    #[test]
    fn publication_retry_requires_identical_operation_contract() {
        let recorded = publication_contract();
        let identical = recorded.clone();
        assert_eq!(
            validate_artifact_publication_retry_v1(&recorded, &identical),
            Ok(())
        );

        let mut changed = recorded.clone();
        changed.admission_digest = digest("changed-admission");
        changed.snapshot_binding = publication_contract_binding(&changed);
        assert_eq!(
            validate_artifact_publication_retry_v1(&recorded, &changed),
            Err(ArtifactPublicationError::OperationIdentityConflict)
        );

        let mut different_operation = recorded.clone();
        different_operation.operation_id = id("other-operation");
        different_operation.snapshot_binding = publication_contract_binding(&different_operation);
        assert_eq!(
            validate_artifact_publication_retry_v1(&recorded, &different_operation),
            Err(ArtifactPublicationError::OperationIdentityMismatch)
        );
    }

    #[test]
    fn multi_predecessor_manifest_is_not_silently_downgraded_to_v1_lineage() {
        let mut multi = admission();
        multi.validated_manifest.manifest.predecessor_ids = vec![id("parent-a"), id("parent-b")];
        multi.validated_manifest.manifest.rollback_predecessor = Some(id("parent-a"));
        assert_eq!(
            artifact_registry_event_for_admission_v3(id("operation"), &multi),
            Err(ArtifactPublicationError::MultiPredecessorProjectionUnsupported)
        );
    }

    #[test]
    fn prepare_requires_current_domain_bound_admission() {
        let registry = scoped_registry();
        let stale = admission();
        let operation_id = id("operation");
        let predecessor = digest("previous-head");
        let receipt = append_receipt(operation_id.clone(), &stale, predecessor);
        assert!(matches!(
            prepare_artifact_publication_v1(
                operation_id,
                &stale,
                &registry,
                20,
                &receipt,
                publication_binding(predecessor),
            ),
            Err(ArtifactPublicationError::Admission(_))
        ));
    }
}
