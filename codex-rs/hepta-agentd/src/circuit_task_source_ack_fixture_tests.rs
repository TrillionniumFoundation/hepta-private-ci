//! Original Source Missing/Pending facts for the real Root-lane mechanism
//! component. No Feature completion, task authority or model is manufactured.

use super::*;
use pretty_assertions::assert_eq;

pub(crate) enum AckSourceStage {
    Missing,
    Pending,
}

pub(crate) struct AckSourceFixture {
    root: tempfile::TempDir,
    identity: AgentdIdentity,
    readback: CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>,
    before: (Vec<u8>, Vec<u8>),
}

impl AckSourceFixture {
    pub(crate) fn new(stage: AckSourceStage) -> anyhow::Result<Self> {
        let root = tempfile::tempdir()?;
        let identity = identity(root.path())?;
        let fence = fence(&identity)?;
        let sources = vec![source("A", b"original ACK mechanism source")];
        let owner = match stage {
            AckSourceStage::Missing => Source::create(
                opened(root.path(), "source-journal")?,
                witness(root.path(), "source-witness")?,
                &identity,
                &fence,
                &registry()?,
                sources,
            )?,
            AckSourceStage::Pending => {
                let claim_sequence = 2;
                let original = DurableCircuitTaskSourceV1::create(
                    opened(root.path(), "source-journal")?,
                    LostAckWitness {
                        original: witness(root.path(), "source-witness")?,
                        fail_sequence: Arc::new(AtomicU64::new(claim_sequence)),
                        failure: WitnessFailure::AfterWrite,
                    },
                    &identity,
                    &fence,
                    &registry()?,
                    sources.clone(),
                )?;
                // The actual request claim and witness are durable. Losing
                // that witness ACK prevents completion; reopen must preserve
                // the genuine Pending claim rather than repair or replay it.
                let error = original.build(&identity, &record("A")).unwrap_err();
                assert_eq!(
                    error.to_string(),
                    agent_error(Error::CommitUncertain).to_string()
                );
                drop(original);
                Source::recover(
                    opened(root.path(), "source-journal")?,
                    witness(root.path(), "source-witness")?,
                    &identity,
                    &fence,
                    &registry()?,
                    sources,
                )?
            }
        };
        let readback = owner.readback();
        let before = (
            fs::read(root.path().join("source-journal"))?,
            fs::read(root.path().join("source-witness"))?,
        );
        let result = Self {
            root,
            identity,
            readback,
            before,
        };
        assert_eq!(
            result.read_publication().err(),
            Some(Error::ReconciliationRequired)
        );
        Ok(result)
    }

    pub(crate) fn read_publication(&self) -> Result<CircuitTaskSourcePublicationV1, Error> {
        self.readback
            .read_run_publication(&self.identity, &cell::id("A"))
    }

    pub(crate) fn require_unchanged(&self) -> anyhow::Result<()> {
        assert_eq!(
            (
                fs::read(self.root.path().join("source-journal"))?,
                fs::read(self.root.path().join("source-witness"))?,
            ),
            self.before
        );
        Ok(())
    }
}
