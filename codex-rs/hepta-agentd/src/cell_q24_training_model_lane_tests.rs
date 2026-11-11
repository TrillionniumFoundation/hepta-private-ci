//! Real Trainer and original Generator receipt ownership shared with Model.
//! Evaluation cohorts and credentials remain explicit fixtures; this is not
//! ordinary StageOwner assembly, independent B or a daemon cold restart.

use crate::OriginalCellQ24TrainingCompletionV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingStageErrorV1 as StageError;
use crate::OriginalCellQ24TrainingStageV1 as Stage;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use pretty_assertions::assert_eq;

use super::*;

struct LaneFixture {
    stage: Stage<FileAnchorWitnessStore, FileAnchorWitnessStore>,
    dataset: LearningIterationSnapshotV1,
    completed: OriginalCellQ24TrainingCompletionV1,
    evaluation: LearningFixture,
    _directory: tempfile::TempDir,
}

impl LaneFixture {
    async fn new() -> anyhow::Result<Self> {
        let disposition = IndependentEvaluationDispositionV1::EligibleForIndependentSelection;
        let ProposalFixture {
            mut trainer,
            dataset,
            evaluation,
            _directory: directory,
            ..
        } = ProposalFixture::new(disposition)?;
        let comparison = evaluation.receipt.plan().record();
        let manifests = [
            comparison.candidate.manifest.clone(),
            comparison.fixed_expert.manifest.clone(),
        ];
        let (_, _, metrics) = result_identity(&trainer.readback()?)?;
        let scope = FrozenLearningScopeV2::freeze(
            &dataset.request,
            &dataset.owners,
            LearningUpdateScopeV2::Cell,
            metrics.update_rule,
        )?;
        let key = SigningKey::from_bytes(&[41; 32]);
        let signer = TrustedLearningSignerV1 {
            principal: evaluation.context.generator.clone(),
            controller_id: evaluation.context.generator.principal_id.clone(),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![LearningEvidenceRoleV1::Generator],
            revoked_at: None,
        };
        let receipt_witness = FileAnchorWitnessStore::open(
            opened(directory.path(), "lane-receipt-witness")?,
            JournalScope {
                scope_digest: scope.binding(),
                objective_digest: dataset.request.envelope.objective_digest,
            },
            Generation::new(/*value*/ 1)?,
            /*max_records*/ 16,
        )?;
        let receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
            opened(directory.path(), "lane-receipts")?,
            receipt_witness,
            OriginalCellQ24TrainingSigningConfigV1 {
                dataset: dataset.clone(),
                scope,
                signer,
                verifier: evaluation.verifier.clone(),
                maximum_signature_lifetime_seconds: 300,
            },
            key,
        )?;
        let stage = Stage::from_original_owners(trainer, receipts).await?;
        // Native training already completed. Cancellation proves this path
        // retains that result while the original owner issues its first receipt.
        let completed = stage
            .execute_training(&dataset, Arc::new(AtomicBool::new(/*v*/ true)))
            .await?;
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset.clone())?;
        coordinator.record(
            completed.receipt.clone(),
            completed.receipt.observed_unix_seconds,
        )?;
        let evaluation =
            evaluation.with_training(coordinator.snapshot().clone(), manifests, disposition);
        Ok(Self {
            stage,
            dataset,
            completed,
            evaluation,
            _directory: directory,
        })
    }

    fn commit<W: AnchorWitnessStore>(
        &self,
        owner: &mut CellQ24ModelProposalOwnerV1<W>,
    ) -> Result<CellQ24ModelProposalReceiptV1, StageError> {
        let request = self
            .evaluation
            .request(self.completed.receipt.observed_unix_seconds);
        self.stage.commit_model_or_readback(
            owner,
            &CellQ24ModelProposalInputsV1 {
                training_cut: &self.evaluation.snapshot,
                training_attestation: &self.completed.attestation,
                runner: self.evaluation.runner(),
                evaluation: &self.evaluation.receipt,
                qualification: &self.evaluation.qualification,
                request: &request,
            },
        )
    }

    fn read<W: AnchorWitnessStore>(
        &self,
        owner: &mut CellQ24ModelProposalOwnerV1<W>,
    ) -> Result<CellQ24ModelProposalReceiptV1, StageError> {
        let request = self
            .evaluation
            .request(self.completed.receipt.observed_unix_seconds);
        self.stage.read_model_proposal(
            owner,
            &CellQ24ModelProposalInputsV1 {
                training_cut: &self.evaluation.snapshot,
                training_attestation: &self.completed.attestation,
                runner: self.evaluation.runner(),
                evaluation: &self.evaluation.receipt,
                qualification: &self.evaluation.qualification,
                request: &request,
            },
        )
    }
}

#[tokio::test]
async fn original_training_model_lane_retains_custody_and_exact_generator_evidence()
-> anyhow::Result<()> {
    let mut f = LaneFixture::new().await?;
    let directory = tempfile::tempdir()?;
    let mut model = f.stage.create_model_owner(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
    )?;
    assert!(matches!(
        f.read(&mut model),
        Err(StageError::ModelProposal(ProposalError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    let original = f.completed.attestation.clone();
    f.completed.attestation.evidence_id = StableId::new("substitute-generator-evidence")?;
    f.completed.attestation.signature = SigningKey::from_bytes(&[41; 32])
        .sign(&f.completed.attestation.signing_bytes())
        .to_bytes();
    // A valid same-key signature is still not the original retained receipt.
    f.evaluation.verifier.verify(
        LearningEvidenceRoleV1::Generator,
        &f.completed.attestation,
        &codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1(
            &f.completed.receipt,
        )?,
        f.completed.receipt.observed_unix_seconds,
    )?;
    assert!(matches!(
        f.commit(&mut model),
        Err(StageError::Binding(
            "exact retained Training receipt and attestation"
        ))
    ));
    f.completed.attestation = original;
    assert!(matches!(
        f.read(&mut model),
        Err(StageError::ModelProposal(ProposalError::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        )))
    ));
    let proposal = f.commit(&mut model)?;
    assert_eq!(f.read(&mut model)?, proposal);
    assert_eq!(f.commit(&mut model)?, proposal);
    drop(model);
    // Only Model is reopened. The exact Trainer and Generator owners remain
    // inside the same stage throughout creation, commit and recovery.
    let mut recovered = f.stage.recover_model_owner(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
    )?;
    assert_eq!(f.read(&mut recovered)?, proposal);
    let retained = f.stage.readback(&f.dataset).await?;
    assert_eq!(retained.receipt, f.completed.receipt);
    assert_eq!(retained.attestation, f.completed.attestation);
    assert_eq!(
        result_identity(&retained.outcome)?,
        result_identity(&f.completed.outcome)?
    );
    Ok(())
}

#[tokio::test]
async fn original_training_model_lane_preserves_pending_and_lost_ack() -> anyhow::Result<()> {
    let f = LaneFixture::new().await?;
    for sequence in [2, 3] {
        for fault in [LostAck::BeforeWrite, LostAck::AfterWrite] {
            let directory = tempfile::tempdir()?;
            let mut model = f.stage.create_model_owner(
                opened(directory.path(), "proposal")?,
                FaultWitness {
                    inner: witness(directory.path())?,
                    sequence,
                    fault,
                },
            )?;
            assert!(matches!(
                f.commit(&mut model),
                Err(StageError::ModelProposal(ProposalError::CommitUncertain))
            ));
            assert!(matches!(
                f.read(&mut model),
                Err(StageError::ModelProposal(ProposalError::CommitUncertain))
            ));
            drop(model);
            let mut recovered = f.stage.recover_model_owner(
                opened(directory.path(), "proposal")?,
                witness(directory.path())?,
            )?;
            if sequence == 2 {
                assert!(matches!(
                    f.read(&mut recovered),
                    Err(StageError::ModelProposal(ProposalError::Pending))
                ));
                assert!(matches!(
                    f.commit(&mut recovered),
                    Err(StageError::ModelProposal(ProposalError::Pending))
                ));
            } else {
                let original = f.read(&mut recovered)?;
                assert_eq!(f.commit(&mut recovered)?, original);
            }
        }
    }
    let retained = f.stage.readback(&f.dataset).await?;
    assert_eq!(retained.receipt, f.completed.receipt);
    assert_eq!(retained.attestation, f.completed.attestation);
    Ok(())
}

#[cfg(unix)]
fn write_same_length(path: &Path, bytes: &[u8]) -> anyhow::Result<()> {
    use std::io::Write as _;
    assert_eq!(fs::metadata(path)?.len(), bytes.len() as u64);
    let mut file = OpenOptions::new().write(true).open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

#[cfg(unix)]
#[tokio::test]
async fn original_training_model_lane_fences_physical_mutation_after_bytes_restore()
-> anyhow::Result<()> {
    let f = LaneFixture::new().await?;
    let directory = tempfile::tempdir()?;
    let proposal_path = directory.path().join("proposal");
    let training_path = f._directory.path().join("job");
    let mut model = f.stage.create_model_owner(
        opened(directory.path(), "proposal")?,
        witness(directory.path())?,
    )?;
    f.commit(&mut model)?;
    // POSIX advisory locks permit this controlled hostile mutation fixture.
    // The production owner keeps its original locked descriptor throughout.
    let original = fs::read(&proposal_path)?;
    let mut mutated = original.clone();
    mutated[0] ^= 1;
    write_same_length(&proposal_path, &mutated)?;
    assert!(matches!(
        f.read(&mut model),
        Err(StageError::ModelProposal(ProposalError::File(_)))
    ));
    write_same_length(&proposal_path, &original)?;
    assert!(matches!(
        f.read(&mut model),
        Err(StageError::ModelProposal(ProposalError::CommitUncertain))
    ));
    let original = fs::read(&training_path)?;
    let mut mutated = original.clone();
    mutated[0] ^= 1;
    write_same_length(&training_path, &mutated)?;
    assert!(matches!(
        f.stage.readback(&f.dataset).await,
        Err(StageError::Training(OwnerError::File(_)))
    ));
    write_same_length(&training_path, &original)?;
    assert!(matches!(
        f.stage.readback(&f.dataset).await,
        Err(StageError::Training(OwnerError::CommitUncertain))
    ));
    Ok(())
}
