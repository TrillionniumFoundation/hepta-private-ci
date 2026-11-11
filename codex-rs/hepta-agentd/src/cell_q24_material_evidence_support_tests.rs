//! Test-only original files, signed Material completions and source capabilities.
//! The enclosing fixture owns its directory; no production visibility is widened.

use pretty_assertions::assert_eq;
use std::sync::Mutex;

use super::*;
use crate::OriginalCellQ24MaterialEvidenceOwnerV1;

pub(crate) type Service = OriginalCellQ24MaterialEvidenceOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

pub(crate) struct ReadbackServiceFixture {
    pub(crate) service: Option<Arc<Service>>,
    pub(crate) initial: LearningIterationSnapshotV1,
    pub(crate) dataset: LearningIterationSnapshotV1,
    pub(crate) experience_receipt: LearningIterationReceiptV1,
    pub(crate) experience_attestation: SignedLearningEvidenceV1,
    pub(crate) dataset_attestation: Option<SignedLearningEvidenceV1>,
    pub(crate) config: OriginalCellQ24MaterialReceiptConfigV1,
    pub(crate) ledger: Arc<Mutex<LedgerWriter>>,
    source: source::Source,
    identity: AgentdIdentity,
    baseline: Arc<LoadedCellQ24ModelV1>,
    optimizer: CellQ24SgdRuleV1,
    root: PathBuf,
    _directory: tempfile::TempDir,
}

impl ReadbackServiceFixture {
    pub(crate) async fn new(complete_dataset: bool) -> anyhow::Result<Self> {
        let mut f = Fixture::new(false).await?;
        let initial = f.config.initial.clone();
        let mut owners = f.create()?;
        let experience = owners.attest_experience(f.sources(&initial))?;
        let prefix = binding::experience_prefix(&f.config, &experience.receipt)?;
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(prefix.clone())?;
        let dataset_attestation = if complete_dataset {
            let dataset = owners.attest_dataset(f.sources(&prefix))?;
            assert_eq!(dataset.receipt.actor_id, initial.owners.dataset);
            coordinator.record(
                dataset.receipt.clone(),
                dataset.receipt.observed_unix_seconds,
            )?;
            Some(dataset.attestation)
        } else {
            None
        };
        let ledger = Arc::new(Mutex::new(f.writer));
        let service = owners.into_evidence_readback_owner(
            f.readback,
            f.identity.clone(),
            Arc::clone(&ledger),
            Arc::clone(&f.baseline),
        )?;
        Ok(Self {
            service: Some(Arc::new(service)),
            initial,
            dataset: coordinator.snapshot().clone(),
            experience_receipt: experience.receipt,
            experience_attestation: experience.attestation,
            dataset_attestation,
            config: f.config,
            ledger,
            source: f.source,
            identity: f.identity,
            baseline: f.baseline,
            optimizer: f.optimizer,
            root: f.root,
            _directory: f._directory,
        })
    }

    pub(crate) fn source_config(
        &self,
    ) -> anyhow::Result<crate::OriginalCellQ24TrainingSourceConfigV1> {
        anyhow::ensure!(self.dataset.receipts.len() == 2, "original Dataset is completed");
        Ok(crate::OriginalCellQ24TrainingSourceConfigV1 {
            dataset: self.dataset.clone(),
            scope: self.config.scope.clone(),
            rule: self.config.rule,
            optimizer: self.optimizer,
            freeze_plan: self.config.freeze_plan.clone(),
            freeze_evidence: self.config.freeze_evidence.clone(),
            experience_evidence: self.experience_attestation.clone(),
            dataset_evidence: self.dataset_attestation.clone()
                .ok_or_else(|| anyhow::anyhow!("original Dataset signature is completed"))?,
            verifier: self.config.verifier.clone(),
        })
    }

    pub(crate) fn baseline(&self) -> Arc<LoadedCellQ24ModelV1> {
        Arc::clone(&self.baseline)
    }

    pub(crate) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        // This entire module is Linux-only. These qualification observations
        // retain the complete files, including each original witness.
        [
            "experience-journal",
            "experience-witness",
            "dataset-journal",
            "dataset-witness",
            "ledger",
            "ledger-witness",
        ]
        .into_iter()
        .map(|name| Ok(fs::read(self.root.join(name))?))
        .collect()
    }

    pub(crate) fn withdraw(&mut self) -> anyhow::Result<()> {
        self.source
            .withdraw_source(&self.initial.request.source_run_id)?;
        Ok(())
    }

    pub(crate) fn reopen(&mut self) -> anyhow::Result<()> {
        let owner = self
            .service
            .take()
            .expect("fixture retained original service");
        anyhow::ensure!(
            Arc::strong_count(&owner) == 1,
            "drop every original service peer first"
        );
        drop(owner);
        let witness = |name: &str| -> anyhow::Result<FileAnchorWitnessStore> {
            Ok(FileAnchorWitnessStore::open(
                opened(&self.root, name, false)?,
                JournalScope {
                    scope_digest: self.config.scope.binding(),
                    objective_digest: self.initial.request.envelope.objective_digest,
                },
                Generation::new(1)?,
                64,
            )?)
        };
        let owners = Owners::recover(
            OriginalCellQ24MaterialReceiptFilesV1 {
                experience: opened(&self.root, "experience-journal", false)?,
                experience_witness: witness("experience-witness")?,
                dataset: opened(&self.root, "dataset-journal", false)?,
                dataset_witness: witness("dataset-witness")?,
            },
            self.config.clone(),
            SigningKey::from_bytes(&[4; 32]),
            SigningKey::from_bytes(&[5; 32]),
        )?;
        self.service = Some(Arc::new(owners.into_evidence_readback_owner(
            self.source.readback(),
            self.identity.clone(),
            Arc::clone(&self.ledger),
            Arc::clone(&self.baseline),
        )?));
        Ok(())
    }
}
