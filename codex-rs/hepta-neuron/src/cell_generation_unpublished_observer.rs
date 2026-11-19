//! Physical cost/state observation of an unpublished component journal. This
//! distinct type cannot be supplied where a guarded CURRENT observer is needed.
//! It grants no authority to execute, sign, publish or adopt the component.

use super::*;

pub struct CellGenerationUnpublishedObserverV1 {
    inner: CellGenerationJournalObserverV1,
}

impl CellGenerationUnpublishedObserverV1 {
    /// Reuse exactly the complete frame/state/witness reader, but bind the
    /// original unguarded journal format. Never accepts a guarded header.
    pub fn from_original_files(
        journal: File,
        witness: File,
        config: CellGenerationObserverConfigV1,
    ) -> Result<Self, CellGenerationErrorV2> {
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(&digest(
            b"hepta.cell.generation-owner.v2\0",
            &(&config.generation, config.journal_records),
        )?);
        let mut inner =
            CellGenerationJournalObserverV1::from_original_files(journal, witness, config)?;
        inner.header = header;
        Ok(Self { inner })
    }

    pub fn observe(&self) -> Result<CellGenerationJournalObservedV1, CellGenerationErrorV2> {
        self.inner.observe()
    }

    pub fn files_binding(&self) -> Digest32 {
        self.inner.files_binding()
    }

    pub fn owner_binding(&self) -> &CellGenerationOwnerBindingV1 {
        self.inner.owner_binding()
    }
}
