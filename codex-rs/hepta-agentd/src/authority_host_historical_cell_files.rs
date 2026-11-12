//! Original Cell files held before A, then read without a writer or repair.
//! These are data inputs. Only the enclosing Root admission supplies a current
//! guard, and every physical operation belongs inside its durable refusal arm.

use super::super::*;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellJournalPartitionV1;
use codex_hepta_neuron::CellOriginalJournalFilesV1;
use codex_hepta_neuron::CellOwnerJournalReadbackV1;
use codex_hepta_neuron::CellOwnerSnapshotV1;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::SparseCheckpoint;
use codex_hepta_neuron::canonical_cell_step_request_digest_v1;
use codex_hepta_neuron::observe_original_file_anchor_v1;
use codex_hepta_neuron::observe_original_guarded_cell_v1;

pub(crate) struct RootHistoricalCellInputsV1 {
    pub(crate) journal: File,
    pub(crate) witness: File,
    pub(crate) witness_scope: JournalScope,
    pub(crate) witness_generation: Generation,
    pub(crate) witness_records: usize,
    pub(crate) maximum_records: usize,
}

pub(crate) struct OriginalCellFiles {
    inputs: RootHistoricalCellInputsV1,
    pins: [FilePin; 2],
    uid: u32,
    gid: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(super) struct OriginalCellObservation {
    pub(super) anchor: JournalAnchor,
    pub(super) snapshot: CellOwnerSnapshotV1,
    pub(super) decision: CellDecisionReceiptV1,
}

impl OriginalCellFiles {
    pub(crate) fn retain_original_cell(
        mut inputs: RootHistoricalCellInputsV1,
        uid: u32,
        gid: u32,
    ) -> io::Result<Self> {
        original_root()?;
        if uid == 0
            || gid == 0
            || inputs.witness_scope.scope_digest.is_zero()
            || inputs.witness_scope.objective_digest.is_zero()
            || inputs.witness_records == 0
            || !(3..=16).contains(&inputs.maximum_records)
        {
            return Err(io::Error::other(
                "original bounded Cell file context required",
            ));
        }
        let (journal, journal_pin) = FilePin::readonly(&inputs.journal, uid, gid)?;
        let (witness, witness_pin) = FilePin::readonly(&inputs.witness, uid, gid)?;
        if (journal_pin.device, journal_pin.inode) == (witness_pin.device, witness_pin.inode) {
            return Err(io::Error::other(
                "independent original Cell witness required",
            ));
        }
        inputs.journal = journal;
        inputs.witness = witness;
        let retained = Self {
            inputs,
            pins: [journal_pin, witness_pin],
            uid,
            gid,
        };
        retained.require_original_files()?;
        Ok(retained)
    }

    pub(super) fn file_pins(&self) -> &[FilePin; 2] {
        &self.pins
    }

    pub(super) fn context_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.root.historical-cell-files.v1\0",
            self.inputs.witness_scope.scope_digest.as_array(),
            self.inputs.witness_scope.objective_digest.as_array(),
            &self.inputs.witness_generation.get().to_be_bytes(),
            &(self.inputs.witness_records as u64).to_be_bytes(),
            &(self.inputs.maximum_records as u64).to_be_bytes(),
        ])
    }

    /// Called before Root acknowledges Initial enrollment. An empty original
    /// Cell journal and an existing empty witness are observed twice; no owner
    /// is initialized, advanced or repaired by this read.
    pub(crate) fn require_original_cell_baseline(&self) -> io::Result<()> {
        original_root()?;
        for _ in 0..2 {
            self.require_original_files()?;
            if self.inputs.journal.metadata()?.len() != 0 {
                return Err(io::Error::other(
                    "original Initial Cell journal is not empty",
                ));
            }
            let observed = observe_original_file_anchor_v1(
                &self.inputs.witness,
                self.inputs.witness_scope,
                self.inputs.witness_generation,
                self.inputs.witness_records,
            )
            .map_err(io::Error::other)?;
            if observed.is_some() {
                return Err(io::Error::other(
                    "original Initial Cell witness is not empty",
                ));
            }
            self.require_original_files()?;
        }
        Ok(())
    }

    /// Data-only read of the actual Cell for the separately registered
    /// successor. The Root publication caller supplies its complete context.
    pub(crate) fn read_original_successor_cell(
        &self,
        definition: &CellDefinitionV1,
        source: &CircuitTaskSourceInputV1,
        publication: &crate::CircuitTaskSourcePublicationV1,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<(JournalAnchor, CellDecisionReceiptV1)> {
        let before = self.read_original_cell_data(definition, source, publication, target)?;
        let after = self.read_original_cell_data(definition, source, publication, target)?;
        if before != after {
            return Err(io::Error::other(
                "original successor Cell changed during readback",
            ));
        }
        Ok((after.anchor, after.decision))
    }

    pub(super) fn observe_original_cell(
        &self,
        definition: &CellDefinitionV1,
        source: &CircuitTaskSourceInputV1,
        publication: &crate::CircuitTaskSourcePublicationV1,
        target: &CellGenerationOwnerBindingV1,
        current: Arc<dyn CellGenerationCurrentV1>,
    ) -> io::Result<OriginalCellObservation> {
        original_root()?;
        require_target(target, definition, source)?;
        let before = self.read_original_cell_once(
            definition,
            source,
            publication,
            target,
            Arc::clone(&current),
        )?;
        let after = self.read_original_cell_once(
            definition,
            source,
            publication,
            target,
            Arc::clone(&current),
        )?;
        let physical = self.read_original_cell_data(definition, source, publication, target)?;
        if before != after || physical != after {
            return Err(io::Error::other(
                "original Cell changed across physical readback",
            ));
        }
        current.check_current(target).map_err(io::Error::other)?;
        self.require_original_files()?;
        Ok(after)
    }

    /// Data-only readback, also usable after the original CURRENT advances.
    /// Its caller must retain the independent Root cut and current admission;
    /// no implementation of a live-current guard is constructed from data.
    pub(super) fn read_original_cell_data(
        &self,
        definition: &CellDefinitionV1,
        source: &CircuitTaskSourceInputV1,
        publication: &crate::CircuitTaskSourcePublicationV1,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<OriginalCellObservation> {
        original_root()?;
        self.require_original_files()?;
        require_target(target, definition, source)?;
        let input = publication.input();
        if input != &source.input(input.operation_id.clone())
            || publication.bundle_digest() != definition.bundle_digest
        {
            return Err(io::Error::other("original Cell and Source inputs differ"));
        }
        let request =
            canonical_cell_step_request_digest_v1(definition, input).map_err(io::Error::other)?;
        let (journal, _) = FilePin::readonly(&self.inputs.journal, self.uid, self.gid)?;
        let (witness, _) = FilePin::readonly(&self.inputs.witness, self.uid, self.gid)?;
        let observed = observe_original_guarded_cell_v1(
            CellOriginalJournalFilesV1 {
                journal,
                witness,
                witness_scope: self.inputs.witness_scope,
                witness_generation: self.inputs.witness_generation,
                witness_records: self.inputs.witness_records,
            },
            CellJournalPartitionV1 {
                scope: source.scope.clone(),
                definition: definition.clone(),
                source_frontier: source.source_frontier,
                writer_epoch: target.writer_epoch(),
            },
            self.inputs.maximum_records,
            target,
            &input.operation_id,
            request,
        )
        .map_err(io::Error::other)?;
        publication
            .require_decision(&observed.decision)
            .map_err(io::Error::other)?;
        if observed.snapshot.revision != 1
            || observed.snapshot.writer_epoch != target.writer_epoch()
            || observed
                .snapshot
                .checkpoint
                .as_ref()
                .map(SparseCheckpoint::digest)
                != Some(observed.decision.checkpoint_after)
            || observed.decision.checkpoint_after != publication.checkpoint_digest()
        {
            return Err(io::Error::other(
                "original Cell checkpoint differs from Source",
            ));
        }
        self.require_original_files()?;
        Ok(OriginalCellObservation {
            anchor: observed.anchor,
            snapshot: observed.snapshot,
            decision: observed.decision,
        })
    }

    fn read_original_cell_once(
        &self,
        definition: &CellDefinitionV1,
        source: &CircuitTaskSourceInputV1,
        publication: &crate::CircuitTaskSourcePublicationV1,
        target: &CellGenerationOwnerBindingV1,
        current: Arc<dyn CellGenerationCurrentV1>,
    ) -> io::Result<OriginalCellObservation> {
        self.require_original_files()?;
        let input = publication.input();
        if input != &source.input(input.operation_id.clone())
            || publication.bundle_digest() != definition.bundle_digest
        {
            return Err(io::Error::other("original Cell and Source inputs differ"));
        }
        let request =
            canonical_cell_step_request_digest_v1(definition, input).map_err(io::Error::other)?;
        let (journal, _) = FilePin::readonly(&self.inputs.journal, self.uid, self.gid)?;
        let (witness, _) = FilePin::readonly(&self.inputs.witness, self.uid, self.gid)?;
        let witness = FileAnchorWitnessStore::open(
            witness,
            self.inputs.witness_scope,
            self.inputs.witness_generation,
            self.inputs.witness_records,
        )
        .map_err(io::Error::other)?;
        let anchor = witness
            .current()
            .map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("original committed Cell witness missing"))?;
        let reader = CellOwnerJournalReadbackV1::open_guarded(
            journal,
            witness,
            vec![CellJournalPartitionV1 {
                scope: source.scope.clone(),
                definition: definition.clone(),
                source_frontier: source.source_frontier,
                writer_epoch: target.writer_epoch(),
            }],
            self.inputs.maximum_records,
            target.clone(),
            current,
        )
        .map_err(io::Error::other)?;
        if reader
            .pending_inference(&input.scope)
            .map_err(io::Error::other)?
            .is_some()
        {
            return Err(io::Error::other(
                "original Cell has an unresolved inference",
            ));
        }
        let decision = reader
            .lookup(&input.scope, &input.operation_id, request)
            .map_err(io::Error::other)?
            .ok_or_else(|| io::Error::other("original Cell decision missing"))?;
        publication
            .require_decision(&decision)
            .map_err(io::Error::other)?;
        let snapshot = reader.snapshot(&input.scope).map_err(io::Error::other)?;
        if snapshot.revision != 1
            || snapshot.writer_epoch != target.writer_epoch()
            || snapshot.checkpoint.as_ref().map(SparseCheckpoint::digest)
                != Some(decision.checkpoint_after)
            || decision.checkpoint_after != publication.checkpoint_digest()
        {
            return Err(io::Error::other(
                "original Cell checkpoint differs from Source",
            ));
        }
        self.require_original_files()?;
        Ok(OriginalCellObservation {
            anchor,
            snapshot,
            decision,
        })
    }

    fn require_original_files(&self) -> io::Result<()> {
        if self.inputs.witness.metadata()?.len() == 0
            || self.pins
                != [
                    FilePin::read(&self.inputs.journal, self.uid, self.gid)?,
                    FilePin::read(&self.inputs.witness, self.uid, self.gid)?,
                ]
        {
            return Err(io::Error::other("original Cell descriptor custody changed"));
        }
        Ok(())
    }
}
