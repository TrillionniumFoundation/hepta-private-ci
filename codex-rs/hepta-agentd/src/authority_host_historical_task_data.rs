//! A retired publisher's Source and Cell data under both persistent arms.
//! The held physical readers outlive the complete recipient context. This
//! partial cut never grants historical learning or substitutes for RunStart,
//! Ledger, completed handoff or independent recipient admission.

use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_neuron::observe_original_file_anchor_v1;

use super::cell::OriginalRetainedCellReadV1;
use super::cell::RootRetainedCellDataV1;
use super::*;
use crate::HistoricalCircuitTaskSourceObservationV1;
use crate::RetiredCheckpointPublisher;

enum ReadState {
    Unobserved,
    Verifying,
    Complete(Box<HeldOriginalSourceCellDataV1>),
}

pub(super) struct OriginalHistoricalSourceCellReadV1<'a> {
    pin: &'a RootHistoricalSourcePinV1,
    cell: &'a OriginalRetainedCellReadV1<'a>,
    state: ReadState,
}

pub(super) struct OriginalHistoricalSourceCellObservationV1 {
    pub(super) source: HistoricalCircuitTaskSourceObservationV1,
    pub(super) definition: CellDefinitionV1,
    pub(super) cell: CellDecisionReceiptV1,
    pub(super) source_pin_digest: Digest32,
    pub(super) cell_cut_digest: Digest32,
}

struct HeldOriginalSourceCellDataV1 {
    inputs: RootHistoricalSourceInputsV1,
    source: HistoricalCircuitTaskSourceV1<FileAnchorWitnessStore>,
    observed: OriginalHistoricalSourceCellObservationV1,
    physical: [(u64, i64, i64, i64, i64); 2],
    _retired: RetiredCheckpointPublisher,
}

impl RootHistoricalSourcePinV1 {
    pub(super) fn with_original_source_cell_data<T>(
        &self,
        cell: &RootRetainedCellDataV1,
        action: impl FnOnce(&mut OriginalHistoricalSourceCellReadV1<'_>) -> io::Result<T>,
    ) -> io::Result<T> {
        cell.with_original_cell_data(|cell| {
            self.inspect_exact(|| {
                let mut pending = OriginalHistoricalSourceCellReadV1 {
                    pin: self,
                    cell,
                    state: ReadState::Unobserved,
                };
                let result = action(&mut pending)?;
                let ReadState::Complete(mut held) = pending.state else {
                    return Err(io::Error::other("original Source/Cell read unfinished"));
                };
                held.require_unchanged(self, cell)?;
                Ok(result)
            })
        })
    }
}

impl OriginalHistoricalSourceCellReadV1<'_> {
    pub(super) fn read_original_retired_source_cell(
        &mut self,
        inputs: RootHistoricalSourceInputsV1,
    ) -> io::Result<&OriginalHistoricalSourceCellObservationV1> {
        original_root()?;
        if !matches!(
            std::mem::replace(&mut self.state, ReadState::Verifying),
            ReadState::Unobserved
        ) {
            return Err(io::Error::other(
                "original Source/Cell read already attempted",
            ));
        }
        let pin = &self.pin.expected.pin;
        let identity = self.cell.original_cell_publisher_identity()?;
        let gid = self.cell.original_cell_peer_gid();
        if self.pin.expected.fenced
            || pin.schema != 1
            || pin.purpose != PIN_PURPOSE
            || pin.publisher.uid == 0
            || pin.publisher_epoch == 0
            || gid == 0
            || pin.identity
                != crate::neuron_generation_process_identity_digest_v1(&identity)
                    .map_err(io::Error::other)?
                    .to_string()
            || pin.spawn_generation != identity.spawn_generation
            || pin.target.scope().agent_id != identity.agent_id.as_str()
            || inputs.fence.owner_agent_id != identity.agent_id
            || identity.spawn_generation.checked_add(1) != Some(inputs.fence.generation)
        {
            return Err(io::Error::other(
                "original retired Source publisher differs",
            ));
        }
        let retired =
            RetiredCheckpointPublisher::observe(pin.publisher.clone()).map_err(io::Error::other)?;
        require_target(&pin.target, &inputs.definition, &inputs.source)?;
        if pin.witness_context
            != Digest32::of_parts(&[
                inputs.witness_scope.scope_digest.as_array(),
                inputs.witness_scope.objective_digest.as_array(),
                &inputs.witness_generation.get().to_be_bytes(),
                &(inputs.witness_records as u64).to_be_bytes(),
            ])
            .to_string()
            || pin.fence_digest
                != Digest32::of_parts(&[
                    b"hepta.root.historical-source-fence.v1\0",
                    &serde_json::to_vec(&inputs.fence).map_err(io::Error::other)?,
                ])
                .to_string()
        {
            return Err(io::Error::other("original Source witness or fence differs"));
        }
        let (journal, journal_pin) = FilePin::readonly(&inputs.journal, pin.publisher.uid, gid)?;
        let (witness, witness_pin) = FilePin::readonly(&inputs.witness, pin.publisher.uid, gid)?;
        if [journal_pin.clone(), witness_pin.clone()] != pin.source_files
            || (journal_pin.device, journal_pin.inode) == (witness_pin.device, witness_pin.inode)
            || witness.metadata()?.len() == 0
        {
            return Err(io::Error::other("original Source custody differs"));
        }
        let physical = physical_metadata(&inputs)?;
        let witness = FileAnchorWitnessStore::open(
            witness,
            inputs.witness_scope,
            inputs.witness_generation,
            inputs.witness_records,
        )
        .map_err(io::Error::other)?;
        let mut source = HistoricalCircuitTaskSourceV1::open(
            journal,
            witness,
            &identity,
            &inputs.fence,
            &inputs.registry,
            vec![inputs.source.clone()],
        )
        .map_err(io::Error::other)?;
        let observed = source
            .observe_run_publication(&inputs.source.scope.run_id)
            .map_err(io::Error::other)?;
        if observed.original_identity() != &identity
            || observed.original_fence() != &inputs.fence
            || observed.original_source() != &inputs.source
            || observed.binding_digest().to_string() != pin.source_configuration
            || observed.journal_anchor().sequence != pin.source_sequence
            || observed.journal_anchor().checkpoint_digest.to_string() != pin.source_checkpoint
            || observed.publication().publication_digest().to_string() != pin.publication
            || observed.publication().history_digest().as_str() != pin.completed_task
            || observed.publication().bundle_digest() != inputs.definition.bundle_digest
        {
            return Err(io::Error::other("original published Source cut differs"));
        }
        let cell = self.cell.read_original_cell_decision(
            &self.pin.expected,
            &inputs,
            observed.publication(),
        )?;
        let observation = OriginalHistoricalSourceCellObservationV1 {
            source: observed,
            definition: inputs.definition.clone(),
            cell,
            source_pin_digest: Digest32::of_parts(&[
                b"hepta.root.historical-source-pin.v1\0",
                &serde_json::to_vec(&self.pin.expected).map_err(io::Error::other)?,
            ]),
            cell_cut_digest: self.cell.retained_cell_data_digest()?,
        };
        let mut held = HeldOriginalSourceCellDataV1 {
            inputs,
            source,
            observed: observation,
            physical,
            _retired: retired,
        };
        held.require_unchanged(self.pin, self.cell)?;
        self.state = ReadState::Complete(Box::new(held));
        match &self.state {
            ReadState::Complete(held) => Ok(&held.observed),
            ReadState::Unobserved | ReadState::Verifying => {
                Err(io::Error::other("original Source/Cell cut missing"))
            }
        }
    }
}

impl HeldOriginalSourceCellDataV1 {
    fn require_unchanged(
        &mut self,
        pin: &RootHistoricalSourcePinV1,
        cell: &OriginalRetainedCellReadV1<'_>,
    ) -> io::Result<()> {
        original_root()?;
        let original = &pin.expected.pin;
        let inputs = &self.inputs;
        let witness = observe_original_file_anchor_v1(
            &inputs.witness,
            inputs.witness_scope,
            inputs.witness_generation,
            inputs.witness_records,
        )
        .map_err(io::Error::other)?;
        if witness != Some(self.observed.source.journal_anchor())
            || self
                .source
                .observe_run_publication(&inputs.source.scope.run_id)
                .map_err(io::Error::other)?
                != self.observed.source
            || cell.read_original_cell_decision(
                &pin.expected,
                inputs,
                self.observed.source.publication(),
            )? != self.observed.cell
            || [
                FilePin::read(
                    &inputs.journal,
                    original.publisher.uid,
                    cell.original_cell_peer_gid(),
                )?,
                FilePin::read(
                    &inputs.witness,
                    original.publisher.uid,
                    cell.original_cell_peer_gid(),
                )?,
            ] != original.source_files
            || observe_original_file_anchor_v1(
                &inputs.witness,
                inputs.witness_scope,
                inputs.witness_generation,
                inputs.witness_records,
            )
            .map_err(io::Error::other)?
                != witness
            || physical_metadata(inputs)? != self.physical
        {
            return Err(io::Error::other(
                "original Source/Cell data changed during context",
            ));
        }
        RetiredCheckpointPublisher::observe(original.publisher.clone())
            .map_err(io::Error::other)?;
        Ok(())
    }
}

fn physical_metadata(
    inputs: &RootHistoricalSourceInputsV1,
) -> io::Result<[(u64, i64, i64, i64, i64); 2]> {
    let journal = inputs.journal.metadata()?;
    let witness = inputs.witness.metadata()?;
    Ok([journal, witness].map(|metadata| {
        (
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    }))
}
