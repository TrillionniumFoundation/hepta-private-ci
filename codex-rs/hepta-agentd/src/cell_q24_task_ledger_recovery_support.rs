//! Close only the original owners, then reopen their exact files and witnesses.
//! The source/Cell read capabilities stay original; this is not daemon restart
//! qualification. A readonly witness descriptor injects one real write failure.

use std::fs::File;
use std::sync::Mutex;

use super::*;
use super::fixture::file;
use super::fixture::witness;

pub(super) struct Recovered {
    pub(super) producer: Arc<crate::OriginalCellQ24TaskLedgerProducerV1>,
    pub(super) ledger: Arc<Mutex<LedgerWriter>>,
    pub(super) context: Context,
}

pub(super) struct Context {
    pub(super) root: tempfile::TempDir,
    pub(super) publication: CircuitTaskSourcePublicationV1,
    pub(super) identity: crate::AgentdIdentity,
    pub(super) source: Arc<support::Source>,
    pub(super) cell: support::Cell,
    published: crate::PublishedCircuitFeatureTaskV1,
    config: crate::OriginalCellQ24TaskLedgerConfigV1,
    trust: ActivatedLearningTrustV1,
    _runtime_directory: tempfile::TempDir,
    _version: VersionFixture,
}

impl fixture::Fixture {
    pub(super) async fn reopen(mut self, read_only_witness: bool) -> anyhow::Result<Recovered> {
        self.session.stop().await?;
        let identity = self.session.runtime.identity.clone();
        let source = Arc::clone(&self.session.source);
        let cell = self.session.cell.clone();
        let published = self.session.retirement.clone();
        let runtime_directory = std::mem::replace(
            &mut self.session.runtime._temp, tempfile::tempdir()?,
        );
        let fixture::Fixture { session, root, ledger, producer, config, signers: _,
            publication, baseline: _, bundle: _, _version, trust } = self;
        drop(session);
        drop(producer);
        drop(ledger);
        Context { root, publication, identity, source, cell, published, config, trust,
            _runtime_directory: runtime_directory, _version }.open(read_only_witness)
    }
}

impl Recovered {
    pub(super) fn reopen(self, read_only_witness: bool) -> anyhow::Result<Self> {
        let Self { producer, ledger, context } = self;
        drop(producer);
        drop(ledger);
        context.open(read_only_witness)
    }
}

impl Context {
    fn open(self, read_only_witness: bool) -> anyhow::Result<Recovered> {
        let binding = cell::d("original-task-ledger-fixture");
        let descriptor = if read_only_witness {
            File::open(self.root.path().join("ledger.witness"))?
        } else {
            file(self.root.path(), "ledger.witness")?
        };
        let witness_owner = LedgerWitnessStore::recover(descriptor, binding)?;
        let frontier = witness_owner.frontier()?;
        let recovery = if frontier.anchor.sequence == 0 {
            assert!(frontier.anchor.chain_digest.is_zero());
            LedgerRecovery::Unacknowledged
        } else {
            LedgerRecovery::Acknowledged(frontier.anchor)
        };
        let ledger = DurableLedger::recover(
            file(self.root.path(), "ledger")?, binding, /*max_records*/ 64, recovery,
        )?;
        let directory = File::open(self.root.path())?;
        let ledger = Arc::new(Mutex::new(LedgerWriter::from_durable(
            ledger, witness_owner, self.trust.clone(), &directory, &directory,
        )?));
        let producer = Arc::new(crate::OriginalCellQ24TaskLedgerProducerV1::open_original(
            crate::OriginalCellQ24TaskLedgerInputsV1 {
                ledger: Arc::clone(&ledger),
                signature_journal: file(self.root.path(), "signatures")?,
                signature_witness: witness(
                    self.root.path(), "signatures.witness", self.publication.input().objective_digest,
                )?,
                open_mode: crate::CircuitQ24TaskOpenModeV1::Recover,
                config: self.config.clone(),
                generator_key: SigningKey::from_bytes(&[1; 32]),
            },
            Arc::clone(&self.source), self.cell.clone(), self.published.clone(), self.identity.clone(),
        )?);
        Ok(Recovered { producer, ledger, context: self })
    }

    pub(super) fn bytes(&self, name: &str) -> anyhow::Result<Vec<u8>> {
        Ok(fs::read(self.root.path().join(name))?)
    }

    pub(super) fn require_original_source(&self) -> anyhow::Result<()> {
        assert!(self.source.read_run_publication(
            &self.identity, &self.publication.original_record().snapshot.run_id,
        )? == self.publication);
        let _same_cell = self.cell.committed(&self.publication)?;
        Ok(())
    }
}
