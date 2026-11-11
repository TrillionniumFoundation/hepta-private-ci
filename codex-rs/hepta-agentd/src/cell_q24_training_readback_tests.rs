//! Real original Dataset and native Trainer mechanics with fixture custody.
//! These checks establish the readback connection, not independent B results,
//! Root export qualification, ordinary adoption, or a deployed learning loop.

use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationTrainerV1;
use crate::OriginalCellQ24SourceReceiptOwnerV1;
use crate::OriginalCellQ24SourceSigningConfigV1;
use crate::OriginalCellQ24SourceStageV1;
use crate::OriginalCellQ24TrainingReadbackV1;
use crate::OriginalCellQ24TrainingReceiptOwnerV1;
use crate::OriginalCellQ24TrainingSigningConfigV1;
use crate::OriginalCellQ24TrainingStageV1;
use crate::LearningIterationRuntimeErrorV1 as Error;

struct Fixture {
    root: tempfile::TempDir,
    session: support::Session,
    dataset: Dataset,
    prepared: Arc<crate::CellQ24PreparedLearningV1>,
    stage: Arc<OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
    dataset_cut: LearningIterationSnapshotV1,
    _current: VersionFixture,
    _experience: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
    _dataset_owner: OriginalCellQ24SourceReceiptOwnerV1<FileAnchorWitnessStore>,
}

fn original_witness(
    root: &Path,
    cut: &LearningIterationSnapshotV1,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(root, "witness")?,
        codex_hepta_neuron::JournalScope {
            scope_digest: cut.head_digest,
            objective_digest: cut.request.envelope.objective_digest,
        },
        Generation::new(/*value*/ 1)?, /*max_records*/ 64,
    )?)
}

impl Fixture {
    async fn new(run: &str) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let (session, baseline, bundle, current) = ordinary(
            root.path(), run, /*source_envelope*/ None,
        ).await?;
        let publication = execute(&session, /*request_id*/ 1).await?;
        for path in ["ledger", "experience", "dataset", "native", "generator"] {
            fs::create_dir(root.path().join(path))?;
        }
        let dataset = Dataset::new(
            &root.path().join("ledger"),
            &[(&session, &publication, Some(2_i64 << 32))],
            OutcomeTerminalityV1::Terminal,
        )?;
        let mut config = preparation::config(&dataset, &publication, baseline, bundle)?;
        let verifier = dataset.ledger.lock().unwrap().verifier().clone();
        config.owners.evidence_trust_digest = verifier.trust_digest();
        config.owners.experience = dataset.signers[1].principal.principal_id.clone();
        config.owners.dataset = dataset.signers[1].principal.principal_id.clone();
        config.owners.trainer = dataset.signers[0].principal.principal_id.clone();
        config.owners.evaluator = dataset.signers[2].principal.principal_id.clone();
        let prepared = Arc::new(preparation::prepare(config, &dataset)?);
        let source_owner = |directory: &str, stage| -> anyhow::Result<_> {
            let directory = root.path().join(directory);
            Ok(OriginalCellQ24SourceReceiptOwnerV1::create(
                file(&directory, "source")?, original_witness(&directory, prepared.initial())?,
                Arc::clone(&prepared), OriginalCellQ24SourceSigningConfigV1 {
                    stage, signer: dataset.signers[1].clone(), verifier: verifier.clone(),
                    maximum_signature_lifetime_seconds: 600,
                }, SigningKey::from_bytes(&[2; 32]),
            )?)
        };
        let mut experience = source_owner("experience", OriginalCellQ24SourceStageV1::Experience)?;
        let mut dataset_owner = source_owner("dataset", OriginalCellQ24SourceStageV1::Dataset)?;
        experience.attest_experience()?;
        let dataset_cut = dataset_owner.attest_dataset(&mut experience)?.snapshot().clone();
        let material = prepared.training_material(dataset_cut.clone(), prepared.scope().clone())?;
        let training = crate::CellQ24TrainingOwnerV1::create(
            file(&root.path().join("native"), "training")?,
            original_witness(&root.path().join("native"), &dataset_cut)?,
            material.plan, material.batch, material.rule,
        )?;
        training.require_original_dataset_provenance()?;
        let receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
            file(&root.path().join("generator"), "receipt")?,
            original_witness(&root.path().join("generator"), &dataset_cut)?,
            OriginalCellQ24TrainingSigningConfigV1 {
                dataset: dataset_cut.clone(), scope: prepared.scope().clone(),
                signer: dataset.signers[0].clone(), verifier,
                maximum_signature_lifetime_seconds: 600,
            }, SigningKey::from_bytes(&[1; 32]),
        )?;
        let stage = Arc::new(OriginalCellQ24TrainingStageV1::from_original_owners(training, receipts).await?);
        Ok(Self { root, session, dataset, prepared, stage, dataset_cut, _current: current, _experience: experience, _dataset_owner: dataset_owner })
    }

    async fn train(&self) -> anyhow::Result<LearningIterationSnapshotV1> {
        let completed = self.stage.execute_training(
            &self.dataset_cut, Arc::new(AtomicBool::new(/*val*/ false)),
        ).await?;
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(self.dataset_cut.clone())?;
        coordinator.record(completed.receipt.clone(), completed.receipt.observed_unix_seconds)?;
        Ok(coordinator.snapshot().clone())
    }

    async fn readback_cap(
        &self,
        snapshot: LearningIterationSnapshotV1,
        cancelled: Arc<AtomicBool>,
    ) -> Result<OriginalCellQ24TrainingReadbackV1, Error> {
        OriginalCellQ24TrainingReadbackV1::from_component_owners(
            Arc::clone(&self.prepared), Arc::clone(&self.stage), self.dataset_cut.clone(), snapshot, cancelled,
        ).await
    }

    fn original_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        ["native/training", "native/witness", "generator/receipt", "generator/witness"]
            .map(|path| fs::read(self.root.path().join(path)))
            .into_iter().collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }
}

#[tokio::test]
async fn original_q24_training_readback_uses_same_hq2_owners_and_rejects_substitution()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("b-original-training-readback").await?;
    let training = fixture.train().await?;
    let fence = Arc::new(AtomicBool::new(/*val*/ false));
    let cap = fixture.readback_cap(training.clone(), Arc::clone(&fence)).await?;
    let trainer = OriginalCellEvaluationTrainerV1::OriginalQ24(cap);
    trainer.require_original_owner(&fixture.prepared, &fixture.stage, &fixture.dataset_cut, &fence)?;
    assert!(trainer.require_original_owner(&fixture.prepared, &fixture.stage, &fixture.dataset_cut,
        &Arc::new(AtomicBool::new(/*val*/ false))).is_err());
    trainer.require_training(&training, fixture.prepared.scope())?;
    let receipt = training.receipts.last().expect("actual Training");
    let original = fixture.original_bytes()?;
    let signed = trainer.borrow().readback(&training, receipt).await?;
    assert_eq!(signed, fixture.stage.receipt_attestation(&fixture.dataset_cut, receipt).await?);
    let mut changed = receipt.clone();
    changed.evidence_digest = cell::d("copied-training-is-not-original");
    assert!(trainer.borrow().readback(&training, &changed).await.is_err());
    let mut changed = training.clone();
    changed.request.source_run_id = cell::id("different-original-source");
    assert!(trainer.borrow().readback(&changed, receipt).await.is_err());
    assert!(trainer.require_training(&fixture.dataset_cut, fixture.prepared.scope()).is_err());
    let payload = learning_iteration_receipt_signing_bytes_v1(receipt)?;
    let verifier = fixture.dataset.ledger.lock().unwrap().verifier().clone();
    let generator = verifier.verify(LearningEvidenceRoleV1::Generator, &signed, &payload, now())?;
    let evaluator_signature = sign(&fixture.dataset.ledger.lock().unwrap(), LearningEvidenceRoleV1::Evaluator, &payload);
    let evaluator = verifier.verify(LearningEvidenceRoleV1::Evaluator, &evaluator_signature, &payload, now())?;
    verify_signed_actor_separation(&generator, &evaluator, now())?;
    assert!(verify_signed_actor_separation(&generator, &generator, now()).is_err());
    assert_eq!(fixture.original_bytes()?, original);
    fixture.session.stop().await
}

#[tokio::test]
async fn original_q24_training_readback_never_fits_missing_owner_and_observes_withdrawal()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("b-original-training-missing").await?;
    let empty = fixture.original_bytes()?;
    assert!(fixture.readback_cap(
        fixture.dataset_cut.clone(), Arc::new(AtomicBool::new(/*val*/ false)),
    ).await.is_err());
    assert_eq!(fixture.original_bytes()?, empty);
    let training = fixture.train().await?;
    let cap = fixture.readback_cap(training.clone(), Arc::new(AtomicBool::new(/*val*/ false))).await?;
    let original = fixture.original_bytes()?;
    fixture.session.source.withdraw_for_dataset_test(&training.request.source_run_id)?;
    assert!(cap.readback(&training, training.receipts.last().expect("actual Training")).await.is_err());
    assert_eq!(fixture.original_bytes()?, original);
    fixture.session.stop().await
}

#[tokio::test]
async fn original_q24_training_readback_keeps_aggregate_fence_and_current_dataset()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("b-original-training-fenced").await?;
    let training = fixture.train().await?;
    let cancelled = Arc::new(AtomicBool::new(/*val*/ false));
    let cap = fixture.readback_cap(training.clone(), Arc::clone(&cancelled)).await?;
    let other = fixture.readback_cap(training.clone(), Arc::new(AtomicBool::new(/*val*/ false))).await?;
    let original = fixture.original_bytes()?;
    cancelled.store(/*val*/ true, Ordering::Release);
    assert!(matches!(cap.readback(&training, training.receipts.last().expect("actual Training")).await,
        Err(Error::CommitUncertain)));
    assert!(matches!(fixture.readback_cap(training.clone(), cancelled).await, Err(Error::CommitUncertain)));
    fixture.dataset.correct()?;
    assert!(other.readback(&training, training.receipts.last().expect("actual Training")).await.is_err());
    assert_eq!(fixture.original_bytes()?, original);
    fixture.session.stop().await
}
