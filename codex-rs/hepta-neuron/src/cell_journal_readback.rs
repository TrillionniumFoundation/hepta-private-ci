//! Existing, fully acknowledged guarded bytes only. This view has no writer,
//! recovery repair, append, witness CAS or fresh inference entry point.

use super::*;

pub struct CellOwnerJournalReadbackV1<W: AnchorWitnessStore>(CellOwnerJournalV1<W>);

impl<W: AnchorWitnessStore> CellOwnerJournalReadbackV1<W> {
    /// The host supplies its actual current owner or a sealed historical-read
    /// check derived from the original successor publication. No file creation,
    /// complete unwitnessed suffix or torn tail is accepted.
    pub fn open_guarded(file: File, witness: W, specs: Vec<CellJournalPartitionV1>, max_records: usize,
        binding: CellGenerationOwnerBindingV1, current: Arc<dyn CellGenerationCurrentV1>)
        -> Result<Self, CellExecutionError> {
        CellOwnerJournalV1::open_guarded_inner(file, witness, specs, max_records, binding, current,
            OpenMode::ReadOnlyAcknowledged).map(Self)
    }

    pub fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError> {
        let result = self.0.snapshot(scope)?;
        self.0.require_current()?;
        Ok(result)
    }

    pub fn lookup(&self, scope: &CellScopeV1, operation_id: &StableId, semantic_request_digest: Digest32)
        -> Result<Option<CellDecisionReceiptV1>, CellExecutionError> {
        let result = self.0.lookup(scope, operation_id, semantic_request_digest)?;
        self.0.require_current()?;
        Ok(result)
    }

    pub fn pending_inference(&self, scope: &CellScopeV1) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError> {
        let result = self.0.pending_inference(scope)?;
        self.0.require_current()?;
        Ok(result)
    }
}
