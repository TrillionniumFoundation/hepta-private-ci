//! Original test custody only: files, witnesses and a genuinely unstarted pair.

use pretty_assertions::assert_eq;
use std::sync::Mutex;

use super::*;
use crate::OriginalCellQ24MaterialCommandOwnerV1;

pub(crate) type CommandHost = OriginalCellQ24MaterialCommandOwnerV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;

pub(crate) struct MaterialCommandFixture {
    pub(crate) host: Option<Arc<CommandHost>>,
    pub(crate) config: OriginalCellQ24MaterialReceiptConfigV1,
    pub(crate) ledger: Arc<Mutex<LedgerWriter>>,
    source: source::Source,
    identity: AgentdIdentity,
    baseline: Arc<LoadedCellQ24ModelV1>,
    optimizer: CellQ24SgdRuleV1,
    generator: TrustedLearningSignerV1,
    root: PathBuf,
    _directory: tempfile::TempDir,
}

impl MaterialCommandFixture {
    pub(crate) async fn new() -> anyhow::Result<Self> {
        Self::from_fixture(Fixture::new(/*expired_work*/ false).await?)
    }

    pub(crate) async fn candidate_pages() -> anyhow::Result<Self> {
        Self::from_fixture(Fixture::candidate_pages().await?)
    }

    fn from_fixture(f: Fixture) -> anyhow::Result<Self> {
        let owners = f.create()?;
        let ledger = Arc::new(Mutex::new(f.writer));
        let host = owners.into_command_owner(
            f.readback,
            f.identity.clone(),
            Arc::clone(&ledger),
            Arc::clone(&f.baseline),
        )?;
        Ok(Self {
            host: Some(Arc::new(host)),
            config: f.config,
            ledger,
            source: f.source,
            identity: f.identity,
            baseline: f.baseline,
            optimizer: f.optimizer,
            generator: f.generator,
            root: f.root,
            _directory: f._directory,
        })
    }

    pub(crate) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        // The enclosing module is Linux-only; retain every original byte.
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
            .withdraw_source(&self.config.initial.request.source_run_id)?;
        Ok(())
    }

    pub(crate) fn reopen(&mut self) -> anyhow::Result<()> {
        let host = self.host.take().expect("original command host");
        anyhow::ensure!(
            Arc::strong_count(&host) == 1,
            "drop all original connections first"
        );
        drop(host);
        let witness = |name: &str| -> anyhow::Result<FileAnchorWitnessStore> {
            Ok(FileAnchorWitnessStore::open(
                opened(&self.root, name, /*create*/ false)?,
                JournalScope {
                    scope_digest: self.config.scope.binding(),
                    objective_digest: self.config.initial.request.envelope.objective_digest,
                },
                Generation::new(1)?,
                64,
            )?)
        };
        let owners = Owners::recover(
            OriginalCellQ24MaterialReceiptFilesV1 {
                experience: opened(&self.root, "experience-journal", /*create*/ false)?,
                experience_witness: witness("experience-witness")?,
                dataset: opened(&self.root, "dataset-journal", /*create*/ false)?,
                dataset_witness: witness("dataset-witness")?,
            },
            self.config.clone(),
            SigningKey::from_bytes(&[4; 32]),
            SigningKey::from_bytes(&[5; 32]),
        )?;
        self.host = Some(Arc::new(owners.into_command_owner(
            self.source.readback(),
            self.identity.clone(),
            Arc::clone(&self.ledger),
            Arc::clone(&self.baseline),
        )?));
        Ok(())
    }
}

/// Fault injection after the real original claim and witness, before signing.
/// This creates no replacement receipt or attestation and is not a public seam.
pub(crate) fn interrupt_dataset_claim(
    owners: &mut Owners,
    config: &OriginalCellQ24MaterialReceiptConfigV1,
    sources: OriginalCellQ24MaterialReceiptSourcesV1<'_, FileAnchorWitnessStore>,
) -> anyhow::Result<ProductEvaluationExecutionKeyV1> {
    let experience = owners.readback_experience(sources)?;
    let saved = binding::dataset_saved(config, owners.dataset_binding, &experience)?;
    assert!(matches!(
        owners
            .dataset
            .commit_once(&saved, || Err(binding::owner_invalid(
                "explicit interruption after original Dataset claim"
            ))),
        Err(LearningOriginalOwnerErrorV1::Binding(
            "explicit interruption after original Dataset claim"
        ))
    ));
    assert_dataset_pending(owners, &saved)?;
    Ok(saved)
}

pub(crate) fn assert_dataset_pending(
    owners: &mut Owners,
    saved: &ProductEvaluationExecutionKeyV1,
) -> anyhow::Result<()> {
    assert!(matches!(
        owners.dataset.read(saved),
        Err(LearningOriginalOwnerErrorV1::Pending)
    ));
    let config = owners.config.clone();
    assert_eq!(saved.plan_id, config.initial.request.operation_id);
    Ok(())
}

#[path = "cell_q24_training_bootstrap_fixture_tests.rs"]
mod training_bootstrap;
