//! Crash-recoverable host publication contract for V2/V3 artifact admission.
//!
//! This module deliberately does not pretend that independent files are one
//! filesystem transaction. Instead it gives the host a closed publication
//! protocol: validate the withdrawal-bound admission, bind it to the exact
//! registry append, make the registry snapshot durable, publish the independently
//! authenticated current-head witness, and only then acknowledge the producer.
//! A restart reconstructs progress exclusively from durable receipts.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryAppendReceipt;
use crate::RegistryHeadRequirementV1;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistryHeadWitnessV1;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
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
    pub admission_digest: Digest32,
    pub manifest_digest: Digest32,
    pub withdrawal_domain_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub registry_predecessor_head_digest: Digest32,
    pub registry_successor_head_digest: Digest32,
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
            ArtifactPublicationPhaseV1::WitnessDurable
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
        if witness.head_digest != self.contract.registry_successor_head_digest
            || witness.predecessor_head_digest != self.contract.registry_predecessor_head_digest
            || receipt.binding != self.contract.snapshot_binding
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
        {
            return Err(ArtifactPublicationError::WitnessReceiptMismatch);
        }
        let requirement = RegistryHeadRequirementV1 {
            registry_id: witness.registry_id.clone(),
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
            ArtifactPublicationPhaseV1::SnapshotDurable
            | ArtifactPublicationPhaseV1::WitnessDurable
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

pub fn prepare_artifact_publication_v1(
    operation_id: StableId,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    now: u64,
    registry_predecessor_head_digest: Digest32,
    append_receipt: &RegistryAppendReceipt,
    snapshot_binding: Digest32,
) -> Result<ArtifactPublicationTransactionV1, ArtifactPublicationError> {
    validate_artifact_publication_v3(admission, withdrawal_registry, now)
        .map_err(ArtifactPublicationError::Admission)?;
    if append_receipt.event_digest.is_zero()
        || append_receipt.chain_digest.is_zero()
        || snapshot_binding.is_zero()
    {
        return Err(ArtifactPublicationError::InvalidBinding);
    }
    Ok(ArtifactPublicationTransactionV1 {
        contract: ArtifactPublicationContractV1 {
            operation_id,
            admission_digest: admission.admission_digest,
            manifest_digest: admission.validated_manifest.manifest_digest,
            withdrawal_domain_digest: admission.withdrawal_domain_digest,
            withdrawal_head_digest: admission.withdrawal_head_digest,
            registry_predecessor_head_digest,
            registry_successor_head_digest: append_receipt.chain_digest,
            registry_event_digest: append_receipt.event_digest,
            snapshot_binding,
        },
        phase: ArtifactPublicationPhaseV1::Prepared,
        snapshot_file_digest: None,
        witness_digest: None,
    })
}

pub fn recover_artifact_publication_v1(
    contract: ArtifactPublicationContractV1,
    snapshot_receipt: Option<RegistrySnapshotReceipt>,
    witness: Option<(&RegistryHeadWitnessV1, RegistryHeadWitnessReceipt)>,
) -> Result<ArtifactPublicationTransactionV1, ArtifactPublicationError> {
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    InvalidBinding,
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
    use codex_hepta_types::LogicalSequence;

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

    fn append_receipt() -> RegistryAppendReceipt {
        RegistryAppendReceipt {
            disposition: RegistryAppendDisposition::Appended,
            sequence: LogicalSequence::new(1).expect("sequence"),
            event_digest: digest("registry-event"),
            chain_digest: digest("registry-head"),
        }
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
        let binding = digest("binding");
        let contract = ArtifactPublicationContractV1 {
            operation_id: id("operation"),
            admission_digest: digest("admission"),
            manifest_digest: digest("manifest"),
            withdrawal_domain_digest: digest("domain"),
            withdrawal_head_digest: Digest32::ZERO,
            registry_predecessor_head_digest: digest("previous-head"),
            registry_successor_head_digest: digest("registry-head"),
            registry_event_digest: digest("registry-event"),
            snapshot_binding: binding,
        };
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
    fn witness_without_snapshot_is_rejected_after_restart() {
        let binding = digest("binding");
        let (head, receipt) = witness(binding);
        let contract = ArtifactPublicationContractV1 {
            operation_id: id("operation"),
            admission_digest: digest("admission"),
            manifest_digest: digest("manifest"),
            withdrawal_domain_digest: digest("domain"),
            withdrawal_head_digest: Digest32::ZERO,
            registry_predecessor_head_digest: digest("previous-head"),
            registry_successor_head_digest: digest("registry-head"),
            registry_event_digest: digest("registry-event"),
            snapshot_binding: binding,
        };
        assert_eq!(
            recover_artifact_publication_v1(contract, None, Some((&head, receipt))),
            Err(ArtifactPublicationError::SnapshotNotDurable)
        );
    }

    #[test]
    fn prepare_requires_current_domain_bound_admission() {
        let binding = digest("binding");
        let registry = scoped_registry();
        let stale = admission();
        assert!(matches!(
            prepare_artifact_publication_v1(
                id("operation"),
                &stale,
                &registry,
                20,
                digest("previous-head"),
                &append_receipt(),
                binding,
            ),
            Err(ArtifactPublicationError::Admission(_))
        ));
    }
}
