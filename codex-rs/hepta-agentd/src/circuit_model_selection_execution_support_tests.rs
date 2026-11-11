//! Test-only original Evaluator host custody for the raw execution file.
//! The witness is initialized before runner admission and advances with each
//! real store mutation. This is not a production host installation.
use codex_hepta_intelligence_eval::{
    LockedFileProductEvaluationExecutionStoreV1, ProductEvaluationExecutionClaimV1,
    ProductEvaluationExecutionKeyV1, ProductEvaluationExecutionStateV1,
    ProductEvaluationExecutionStoreErrorV1, ProductEvaluationExecutionStoreV1,
};
use codex_hepta_neuron::{AnchorWitnessStore, FileAnchorWitnessStore, JournalAnchor};
use pretty_assertions::assert_eq;

type Error = ProductEvaluationExecutionStoreErrorV1;

pub(super) struct WitnessedExecutions {
    pub(super) store: LockedFileProductEvaluationExecutionStoreV1,
    pub(super) witness: FileAnchorWitnessStore,
    fenced: bool,
}

impl WitnessedExecutions {
    pub(super) fn initialize(
        mut store: LockedFileProductEvaluationExecutionStoreV1,
        mut witness: FileAnchorWitnessStore,
    ) -> anyhow::Result<Self> {
        // An empty, independently opened witness is supplied by this explicit
        // test host before it gives the runner either claim or signing port.
        anyhow::ensure!(witness.current()?.is_none(), "fresh execution witness");
        let physical = store.read_current_anchor()?;
        assert_eq!(physical.sequence, 0);
        witness.compare_and_swap(
            None,
            JournalAnchor {
                sequence: 1,
                checkpoint_digest: physical.history_digest,
            },
        )?;
        Ok(Self { store, witness, fenced: false })
    }

    fn current(&mut self) -> Result<JournalAnchor, Error> {
        if self.fenced {
            return Err(Error::Indeterminate);
        }
        let observed = (|| {
            let before = self.witness.current().map_err(|_| Error::Indeterminate)?;
            let physical = self.store.read_current_anchor().map_err(|_| Error::Indeterminate)?;
            let current = JournalAnchor {
                sequence: physical.sequence.checked_add(1).ok_or(Error::Indeterminate)?,
                checkpoint_digest: physical.history_digest,
            };
            let after = self.witness.current().map_err(|_| Error::Indeterminate)?;
            if before != Some(current) || after != Some(current) {
                return Err(Error::Indeterminate);
            }
            Ok(current)
        })();
        if observed.is_err() { self.fenced = true; }
        observed
    }

    fn anchor_after(&mut self, previous: JournalAnchor) -> Result<(), Error> {
        let result = (|| {
            let physical = self.store.read_current_anchor().map_err(|_| Error::Indeterminate)?;
            let next = JournalAnchor {
                sequence: physical.sequence.checked_add(1).ok_or(Error::Indeterminate)?,
                checkpoint_digest: physical.history_digest,
            };
            if next != previous {
                self.witness.compare_and_swap(Some(previous), next)
                    .map_err(|_| Error::Indeterminate)?;
            }
            self.current()?;
            Ok(())
        })();
        if result.is_err() { self.fenced = true; }
        result
    }
}

impl ProductEvaluationExecutionStoreV1 for WitnessedExecutions {
    fn claim(&mut self, key: &ProductEvaluationExecutionKeyV1)
        -> Result<ProductEvaluationExecutionClaimV1, Error>
    {
        let before = self.current()?;
        let result = self.store.claim(key);
        if result.is_err() { self.fenced = true; return result; }
        self.anchor_after(before)?;
        result
    }

    fn complete(&mut self, key: &ProductEvaluationExecutionKeyV1, bytes: &[u8])
        -> Result<(), Error>
    {
        let before = self.current()?;
        if let Err(error) = self.store.complete(key, bytes) {
            self.fenced = true;
            return Err(error);
        }
        self.anchor_after(before)
    }

    fn readback(&mut self, key: &ProductEvaluationExecutionKeyV1)
        -> Result<ProductEvaluationExecutionStateV1, Error>
    {
        let before = self.current()?;
        let result = self.store.readback(key);
        if self.current()? != before {
            self.fenced = true;
            return Err(Error::Indeterminate);
        }
        result
    }
}
