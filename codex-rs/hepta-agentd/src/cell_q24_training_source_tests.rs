//! Real Source/Ledger + original Material and native Training owners.
//! The evidence transport is an explicit same-UID fixture; this does not claim
//! an external role-host handoff, production StageOwner dispatch, or adoption.

use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;

use crate::CellQ24TrainingOwnerErrorV1;
use crate::OriginalCellQ24TrainingSourceConfigV1;
use crate::OriginalCellQ24TrainingSourceErrorV1;
use crate::OriginalCellQ24TrainingSourceOwnersV1;
use crate::OriginalCellQ24TrainingSourceV1;
use crate::SourceBoundCellQ24TrainingStageV1;
use crate::capture_original_cell_q24_training_source_v1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::WitnessStoreError;

use super::*;

type Peers = [std::thread::JoinHandle<anyhow::Result<usize>>; 2];

struct Harness {
    root: PathBuf,
    baseline: Arc<LoadedCellQ24ModelV1>,
    identity: AgentdIdentity,
    source: Arc<source::Source>,
    readback: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    ledger: Arc<Mutex<LedgerWriter>>,
    original: OriginalCellQ24MaterialReceiptConfigV1,
    config: OriginalCellQ24TrainingSourceConfigV1,
    generator: TrustedLearningSignerV1,
    material: OriginalCellQ24DatasetV1,
    _directory: tempfile::TempDir,
}

impl Harness {
    async fn new() -> anyhow::Result<Self> {
        let mut fixture = Fixture::new(false).await?;
        let initial = fixture.config.initial.clone();
        let mut owners = fixture.create()?;
        let experience = owners.attest_experience(fixture.sources(&initial))?;
        let prefix = binding::experience_prefix(&fixture.config, &experience.receipt)?;
        let dataset = owners.attest_dataset(fixture.sources(&prefix))?;
        let full = super::super::dataset_snapshot(&initial, &experience.receipt, &dataset.receipt)?;
        // Actual Material signatures are produced above. The transport fixture
        // below only replays those bytes; it has no production signer API.
        drop(owners);
        let config = OriginalCellQ24TrainingSourceConfigV1 {
            dataset: full,
            scope: fixture.config.scope.clone(),
            rule: fixture.config.rule,
            optimizer: fixture.optimizer,
            freeze_plan: fixture.config.freeze_plan.clone(),
            freeze_evidence: fixture.config.freeze_evidence.clone(),
            experience_evidence: experience.attestation,
            dataset_evidence: dataset.attestation,
            verifier: fixture.config.verifier.clone(),
        };
        let Fixture {
            root,
            baseline,
            identity,
            source,
            readback,
            writer,
            config: original,
            generator,
            _directory,
            ..
        } = fixture;
        Ok(Self {
            root,
            baseline,
            identity,
            source: Arc::new(source),
            readback,
            ledger: Arc::new(Mutex::new(writer)),
            original,
            config,
            generator,
            material: dataset.material,
            _directory,
        })
    }

    fn file(&self, name: &str, create: bool) -> anyhow::Result<File> {
        opened(&self.root, name, create)
    }

    fn witness(&self, name: &str, create: bool) -> anyhow::Result<FileAnchorWitnessStore> {
        Ok(FileAnchorWitnessStore::open(
            self.file(name, create)?,
            JournalScope {
                scope_digest: self.config.scope.binding(),
                objective_digest: self.config.dataset.request.envelope.objective_digest,
            },
            Generation::new(1)?,
            64,
        )?)
    }

    fn receipts(
        &self,
        create: bool,
    ) -> anyhow::Result<OriginalCellQ24TrainingReceiptOwnerV1<FileAnchorWitnessStore>> {
        let file = self.file("training-receipt", create)?;
        let witness = self.witness("training-receipt-witness", create)?;
        let config = OriginalCellQ24TrainingSigningConfigV1 {
            dataset: self.config.dataset.clone(),
            scope: self.config.scope.clone(),
            signer: self.generator.clone(),
            verifier: self.config.verifier.clone(),
            maximum_signature_lifetime_seconds: 300,
        };
        let key = SigningKey::from_bytes(&[1; 32]);
        Ok(if create {
            OriginalCellQ24TrainingReceiptOwnerV1::create(file, witness, config, key)?
        } else {
            OriginalCellQ24TrainingReceiptOwnerV1::recover(file, witness, config, key)?
        })
    }

    fn clients(
        &self,
        experience: SignedLearningEvidenceV1,
        dataset: SignedLearningEvidenceV1,
    ) -> anyhow::Result<(
        OriginalCellQ24TrainingSourceOwnersV1<FileAnchorWitnessStore>,
        Peers,
    )> {
        let (experience, first) = fixture_original_receipt_client_until_close(
            self.original.initial.clone(),
            self.config.dataset.receipts[0].clone(),
            self.config.verifier.clone(),
            experience,
        )?;
        let (dataset, second) = fixture_original_receipt_client_until_close(
            self.original.initial.clone(),
            self.config.dataset.receipts[1].clone(),
            self.config.verifier.clone(),
            dataset,
        )?;
        Ok((
            OriginalCellQ24TrainingSourceOwnersV1 {
                source: self.readback.clone(),
                identity: self.identity.clone(),
                ledger: Arc::clone(&self.ledger),
                baseline: Arc::clone(&self.baseline),
                experience,
                dataset,
            },
            [first, second],
        ))
    }

    async fn capture(&self) -> anyhow::Result<(OriginalCellQ24TrainingSourceV1, Peers)> {
        let (owners, peers) = self.clients(
            self.config.experience_evidence.clone(),
            self.config.dataset_evidence.clone(),
        )?;
        Ok((
            capture_original_cell_q24_training_source_v1(owners, self.config.clone()).await?,
            peers,
        ))
    }

    fn bytes(&self) -> anyhow::Result<[Vec<u8>; 4]> {
        // This entire fixture is Linux-only. Observation opens no production
        // writer, and never repairs or changes the original journal bytes.
        Ok([
            fs::read(self.root.join("native-training"))?,
            fs::read(self.root.join("native-witness"))?,
            fs::read(self.root.join("training-receipt"))?,
            fs::read(self.root.join("training-receipt-witness"))?,
        ])
    }
}

fn finish(peers: Peers) -> anyhow::Result<[usize; 2]> {
    let [first, second] = peers;
    Ok([
        first.join().expect("explicit Experience peer")?,
        second.join().expect("explicit Dataset peer")?,
    ])
}

#[tokio::test]
async fn source_bound_training_preserves_frozen_rule_and_recovers_exact_no_update()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let batch_before = fixture.material.batch().encoded().to_vec();
    let optimizer_before = fixture.config.optimizer.digest(fixture.material.batch())?;
    let frozen_before = fixture.config.scope.clone();
    let (capture, peers) = fixture.capture().await?;
    let (plan, batch, optimizer) = capture.native_inputs()?;
    assert_eq!(batch.encoded(), batch_before);
    assert_eq!(optimizer.digest(&batch)?, optimizer_before);
    // The same Root scope validates the exact capture-derived plan.
    let original_plan = fixture.material.training_plan(
        fixture.config.dataset.clone(),
        frozen_before.clone(),
        Arc::clone(&fixture.baseline),
        optimizer,
    )?;
    drop((plan, original_plan));
    assert_eq!(fixture.config.scope, frozen_before);
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
    let completed = stage
        .execute_training(&fixture.config.dataset, Arc::new(AtomicBool::new(false)))
        .await?;
    assert!(matches!(
        completed.outcome,
        CellQ24TrainingOutcomeV1::NoUpdate { .. }
    ));
    let repeated = stage.readback(&fixture.config.dataset).await?;
    assert_eq!(repeated.receipt, completed.receipt);
    assert_eq!(repeated.attestation, completed.attestation);
    drop(stage);
    assert!(finish(peers)?.into_iter().all(|count| count >= 2));
    let before = fixture.bytes()?;

    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::recover_from_original_source(
        fixture.file("native-training", false)?,
        fixture.witness("native-witness", false)?,
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(false)?)
            .await?;
    let recovered = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
    let retained = recovered.readback(&fixture.config.dataset).await?;
    assert_eq!(retained.receipt, completed.receipt);
    assert_eq!(retained.attestation, completed.attestation);
    drop(recovered);
    finish(peers)?;
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn source_bound_training_rejects_identical_legacy_batch_before_admission()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let plan = fixture.material.training_plan(
        fixture.config.dataset.clone(),
        fixture.config.scope.clone(),
        Arc::clone(&fixture.baseline),
        fixture.config.optimizer,
    )?;
    let training = CellQ24TrainingOwnerV1::create(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        plan,
        fixture.material.batch().clone(),
        fixture.config.optimizer,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let before = fixture.bytes()?;
    assert!(matches!(
        SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await,
        Err(crate::OriginalCellQ24TrainingStageErrorV1::Training(
            CellQ24TrainingOwnerErrorV1::Binding(
                "ordinary Training requires original source capture"
            )
        ))
    ));
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn source_bound_training_withdrawal_before_claim_fences_without_no_update()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
    let before = fixture.bytes()?;
    fixture
        .source
        .withdraw_source(&fixture.config.dataset.request.source_run_id)?;
    assert!(matches!(
        stage
            .execute_training(&fixture.config.dataset, Arc::new(AtomicBool::new(false)))
            .await,
        Err(crate::OriginalCellQ24TrainingStageErrorV1::Training(
            CellQ24TrainingOwnerErrorV1::Source(_)
        ))
    ));
    assert!(matches!(
        stage.readback(&fixture.config.dataset).await,
        Err(crate::OriginalCellQ24TrainingStageErrorV1::Training(
            CellQ24TrainingOwnerErrorV1::CommitUncertain
        ))
    ));
    drop(stage);
    finish(peers)?;
    assert_eq!(fixture.bytes()?, before);
    Ok(())
}

struct WithdrawAfterClaim {
    witness: FileAnchorWitnessStore,
    source: Arc<source::Source>,
    run: StableId,
}

impl AnchorWitnessStore for WithdrawAfterClaim {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.witness.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.witness.compare_and_swap(expected, next)?;
        if next.sequence == 2 {
            self.source
                .withdraw_source(&self.run)
                .expect("explicit withdrawal after original native claim");
        }
        Ok(())
    }
}

#[tokio::test]
async fn source_bound_training_withdrawal_after_claim_preserves_pending_without_signature()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        WithdrawAfterClaim {
            witness: fixture.witness("native-witness", true)?,
            source: Arc::clone(&fixture.source),
            run: fixture.config.dataset.request.source_run_id.clone(),
        },
        capture,
    )?;
    let original =
        OriginalCellQ24TrainingStageV1::from_original_owners(training, fixture.receipts(true)?)
            .await?;
    let stage = SourceBoundCellQ24TrainingStageV1::from_original_stage(original).await?;
    let before = fixture.bytes()?;
    let (recovery_capture, recovery_peers) = fixture.capture().await?;
    assert!(
        stage
            .execute_training(&fixture.config.dataset, Arc::new(AtomicBool::new(false)),)
            .await
            .is_err()
    );
    drop(stage);
    finish(peers)?;
    let after = fixture.bytes()?;
    assert_ne!(before[0], after[0], "the actual native claim is durable");
    assert_ne!(before[1], after[1], "its independent witness did advance");
    assert_eq!(
        before[2..],
        after[2..],
        "the Generator never claimed or signed"
    );

    // A previously observed capture may bind recovery, but does not authorize
    // work. The actual original journal remains Pending, never Missing/NoUpdate.
    let mut recovered = CellQ24TrainingOwnerV1::recover_from_original_source(
        fixture.file("native-training", false)?,
        fixture.witness("native-witness", false)?,
        recovery_capture,
    )?;
    assert!(matches!(
        recovered.readback(),
        Err(CellQ24TrainingOwnerErrorV1::Pending)
    ));
    drop(recovered);
    finish(recovery_peers)?;
    let (owners, peers) = fixture.clients(
        fixture.config.experience_evidence.clone(),
        fixture.config.dataset_evidence.clone(),
    )?;
    assert!(
        capture_original_cell_q24_training_source_v1(owners, fixture.config.clone())
            .await
            .is_err()
    );
    finish(peers)?;
    assert_eq!(fixture.bytes()?, after);
    Ok(())
}

#[tokio::test]
async fn source_bound_capture_rejects_valid_freeze_resigning_with_identical_training_bytes()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let mut changed = fixture.config.clone();
    changed.freeze_evidence.expires_at -= 1;
    changed.freeze_evidence.signature = SigningKey::from_bytes(&[3; 32])
        .sign(&changed.freeze_evidence.signing_bytes())
        .to_bytes();
    let alternative = {
        let mut ledger = fixture
            .ledger
            .lock()
            .expect("original ledger fixture mutex");
        CellQ24DatasetReaderV1::new(&fixture.readback, &fixture.identity, &mut ledger)
            .read_current(
                &fixture.original.initial,
                &fixture.baseline,
                changed.rule,
                changed.freeze_plan.clone(),
                &changed.freeze_evidence,
            )?
    };
    assert_eq!(
        alternative.batch().encoded(),
        fixture.material.batch().encoded()
    );
    assert_eq!(
        alternative.dataset_observation(),
        fixture.material.dataset_observation()
    );
    assert_ne!(
        alternative.provenance_digest(),
        fixture.material.provenance_digest()
    );
    let (owners, peers) = fixture.clients(
        fixture.config.experience_evidence.clone(),
        fixture.config.dataset_evidence.clone(),
    )?;
    assert!(matches!(
        capture_original_cell_q24_training_source_v1(owners, changed).await,
        Err(OriginalCellQ24TrainingSourceErrorV1::Binding(
            "original Material observations and live data"
        ))
    ));
    assert_eq!(finish(peers)?, [1, 1]);
    Ok(())
}

#[tokio::test]
async fn source_bound_training_cold_identity_rejects_valid_material_signature_renewal()
-> anyhow::Result<()> {
    let fixture = Harness::new().await?;
    let (capture, peers) = fixture.capture().await?;
    let training = CellQ24TrainingOwnerV1::create_from_original_source(
        fixture.file("native-training", true)?,
        fixture.witness("native-witness", true)?,
        capture,
    )?;
    drop(training);
    finish(peers)?;
    let before = fs::read(fixture.root.join("native-training"))?;
    let mut renewed = fixture.config.clone();
    renewed.dataset_evidence.expires_at -= 1;
    renewed.dataset_evidence.signature = SigningKey::from_bytes(&[5; 32])
        .sign(&renewed.dataset_evidence.signing_bytes())
        .to_bytes();
    // Valid same-payload signature, with unchanged original issued_at. The
    // fixture can assert this new signature, but cold identity must still fail.
    renewed.verifier.verify(
        LearningEvidenceRoleV1::Observer,
        &renewed.dataset_evidence,
        &learning_iteration_receipt_signing_bytes_v1(&renewed.dataset.receipts[1])?,
        binding::now()?,
    )?;
    let (owners, peers) = fixture.clients(
        fixture.config.experience_evidence.clone(),
        fixture.config.dataset_evidence.clone(),
    )?;
    assert!(matches!(
        capture_original_cell_q24_training_source_v1(owners, renewed.clone()).await,
        Err(OriginalCellQ24TrainingSourceErrorV1::Binding(
            "complete original Material signatures"
        ))
    ));
    finish(peers)?;
    let (owners, peers) = fixture.clients(
        renewed.experience_evidence.clone(),
        renewed.dataset_evidence.clone(),
    )?;
    let capture = capture_original_cell_q24_training_source_v1(owners, renewed).await?;
    assert!(
        CellQ24TrainingOwnerV1::recover_from_original_source(
            fixture.file("native-training", false)?,
            fixture.witness("native-witness", false)?,
            capture,
        )
        .is_err()
    );
    finish(peers)?;
    assert_eq!(fs::read(fixture.root.join("native-training"))?, before);

    let (capture, peers) = fixture.capture().await?;
    let mut original = CellQ24TrainingOwnerV1::recover_from_original_source(
        fixture.file("native-training", false)?,
        fixture.witness("native-witness", false)?,
        capture,
    )?;
    assert!(matches!(
        original.readback(),
        Err(CellQ24TrainingOwnerErrorV1::Store(
            ProductEvaluationExecutionStoreErrorV1::Missing
        ))
    ));
    drop(original);
    finish(peers)?;
    assert_eq!(fs::read(fixture.root.join("native-training"))?, before);
    Ok(())
}
