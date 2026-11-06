//! Explicit task-boundary generation replacement under existing authorities.
//!
//! The predecessor must already have a real STOP, no pending output and a
//! durable drain. This module never resets that journal, transfers its prefix,
//! invents a model proposal, or reuses an entered FinalUse token. The successor
//! starts a different task/run through the ordinary generation runtime.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;
use crate::neuron_generation_current::NeuronGenerationUpdateReadbackV1;
use crate::neuron_generation_current::PreparedNeuronGenerationUpdateV1;
use crate::neuron_generation_update_bootstrap::ReadyAgentdGenerationUpdateV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

/// Host-owned file and independent witness. Fresh preparation requires both
/// empty; recovery requires an existing guarded journal and never falls back
/// to creating one. The host retains responsibility for durable file placement.
pub struct AgentdGenerationUpdateTargetV1<W: AnchorWitnessStore> {
    pub file: File,
    pub witness: W,
    pub config: CellGenerationConfigV2,
    pub max_records: u64,
}

pub struct AgentdGenerationUpdateRequestV1 {
    pub operation_id: String,
}

/// Owns both real journal locks from preparation until the publication CAS.
/// It cannot be cloned or deserialized. After an uncertain result, callers
/// recover the original root operation instead of assuming it was not applied.
pub struct PreparedAgentdGenerationUpdateV1<Old: AnchorWitnessStore, New: AnchorWitnessStore> {
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    prepared: PreparedNeuronGenerationUpdateV1,
    old: CellGenerationJournalV2<Old>,
    new: CellGenerationJournalV2<New>,
    selected: AgentdSelectedGenerationV1,
}

pub fn prepare_agentd_generation_update_v1<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    StableId::new(&request.operation_id).map_err(invalid)?;
    // No artifact mutex is held while reading a predecessor that may already
    // carry a live guard. Its exclusive file lock remains owned throughout.
    let binding = validate_reset(&old, &selected, &target)?;
    let metadata = target.file.metadata()?;
    if !metadata.is_file()
        || metadata.len() != 0
        || target.witness.current().map_err(invalid)?.is_some()
    {
        return Err(invalid("fresh generation target is not empty"));
    }
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let old = old.rebind_current(guard).map_err(invalid)?;
    // The terminal predecessor is now private to this handoff. It cannot be
    // returned to a runtime, resumed, or admitted; the root floor still applies.
    let artifacts = authorities.artifacts.lock().map_err(invalid)?;
    selected.revalidate(&artifacts, authorities.now()?)?;
    let prepared = current.prepare(&old, request.operation_id, binding, &selected)?;
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let new = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    // Actual healthy header-only bytes, not a caller's asserted checkpoint.
    new.prepared_checkpoint().map_err(invalid)?;
    // Keep this guard until both preparation and its genesis are durable.
    // It serializes with publications/withdrawal updates by this concrete owner.
    drop(artifacts);
    Ok(PreparedAgentdGenerationUpdateV1 {
        current,
        authorities,
        prepared,
        old,
        new,
        selected,
    })
}

impl<Old: AnchorWitnessStore, New: AnchorWitnessStore> PreparedAgentdGenerationUpdateV1<Old, New> {
    pub(crate) fn from_parts(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        prepared: PreparedNeuronGenerationUpdateV1,
        old: CellGenerationJournalV2<Old>,
        new: CellGenerationJournalV2<New>,
        selected: AgentdSelectedGenerationV1,
    ) -> Self {
        Self {
            current,
            authorities,
            prepared,
            old,
            new,
            selected,
        }
    }

    #[must_use]
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    #[must_use]
    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    pub fn publish(
        mut self,
        signed: &SignedFinalUseGrant,
    ) -> Result<ReadyAgentdGenerationUpdateV1<New>, AgentdError> {
        let expected = self.prepared.final_use_binding().clone();
        let receipt = {
            let mut artifacts = self.authorities.artifacts.lock().map_err(invalid)?;
            self.current.publish(
                &self.prepared,
                &self.old,
                &self.new,
                &mut self.selected,
                NeuronGenerationUpdatePublicationV1 {
                    artifacts: &mut artifacts,
                    authority: &self.authorities.final_use,
                    signed,
                    clock: self.authorities.clock.as_ref(),
                },
            )?
        };
        // The old lock covers the actual CAS and readback. Its root floor has
        // now advanced; durable drain alone is never used as a writer fence.
        drop(self.old);
        let guard = LiveGenerationCurrent::new(
            self.current,
            self.authorities,
            self.selected,
            receipt.clone(),
            expected,
        )?;
        ReadyAgentdGenerationUpdateV1::new(self.new, receipt, guard)
    }
}

/// Recover only a root operation that actually published. Prepared/claimed
/// uncertainty stays pending; this path cannot claim or dispatch any grant.
pub fn recover_agentd_generation_update_v1<W: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<W>,
    expected: AgentdGenerationUpdateRecoveryV1,
) -> Result<ReadyAgentdGenerationUpdateV1<W>, AgentdError> {
    let prepared = current.recover_operation(&expected.operation_id, expected.intent_digest)?;
    if selected.observation().digest() != prepared.selection_observation_digest() {
        return Err(invalid(
            "recovery selection differs from the original operation",
        ));
    }
    let receipt = match current.read_operation(&prepared)? {
        NeuronGenerationUpdateReadbackV1::Prepared => {
            return Err(invalid("generation update remains pending; no redispatch"));
        }
        NeuronGenerationUpdateReadbackV1::Published(receipt) => receipt,
    };
    let binding =
        CellGenerationOwnerBindingV1::new(&target.config, target.max_records).map_err(invalid)?;
    if &binding != receipt.target() || selected.manifest() != &target.config.manifest {
        return Err(invalid(
            "recovery target differs from the original publication",
        ));
    }
    let metadata = target.file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid("published generation journal is missing"));
    }
    {
        let artifacts = authorities.artifacts.lock().map_err(invalid)?;
        selected.revalidate(&artifacts, authorities.now()?)?;
    }
    let live = LiveGenerationCurrent::new(
        current.clone(),
        authorities,
        selected,
        receipt.clone(),
        prepared.final_use_binding().clone(),
    )?;
    let guard: Arc<dyn CellGenerationCurrentV1> = live.clone();
    let new = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    // Ordinary recovery retains state/cost/output. No absent file or damaged
    // history is repaired by replacing the published task with fresh genesis.
    let observed = match current.read_operation(&prepared)? {
        NeuronGenerationUpdateReadbackV1::Prepared => {
            return Err(invalid("published generation regressed to preparation"));
        }
        NeuronGenerationUpdateReadbackV1::Published(observed) => observed,
    };
    if observed != receipt || new.owner_binding() != Some(observed.target()) {
        return Err(invalid("generation publication changed during recovery"));
    }
    ReadyAgentdGenerationUpdateV1::new(new, observed, live)
}

pub struct AgentdGenerationUpdateRecoveryV1 {
    pub operation_id: String,
    pub intent_digest: Digest32,
}

pub(super) fn validate_reset<Old: AnchorWitnessStore, New: AnchorWitnessStore>(
    old: &CellGenerationJournalV2<Old>,
    selected: &AgentdSelectedGenerationV1,
    target: &AgentdGenerationUpdateTargetV1<New>,
) -> Result<CellGenerationOwnerBindingV1, AgentdError> {
    if old.owner_binding().is_none() {
        return Err(invalid(
            "legacy generation journals cannot enter guarded updates",
        ));
    }
    let observation = old.observe_generation().map_err(invalid)?;
    if !observation.is_terminal() || !old.is_drained().map_err(invalid)? {
        return Err(invalid(
            "predecessor requires STOP, exact output ACK and drain",
        ));
    }
    let predecessor = observation.snapshot();
    let successor = &target.config.initial;
    if selected.manifest() != &target.config.manifest
        || successor.scope.principal_digest != predecessor.scope.principal_digest
        || successor.scope.agent_id != predecessor.scope.agent_id
        || successor.scope.cell_id != predecessor.scope.cell_id
        || successor.scope.run_id == predecessor.scope.run_id
        || target.config.task_digest == observation.task_digest()
        || successor.manifest_digest == predecessor.manifest_digest
        || successor.generation <= predecessor.generation
        || successor.writer_epoch <= predecessor.writer_epoch
        || successor.revision != 0
        || !successor.prefix.is_empty()
        || successor.stopped
    {
        return Err(invalid(
            "generation update must be a new-task explicit reset",
        ));
    }
    CellGenerationOwnerBindingV1::new(&target.config, target.max_records).map_err(invalid)
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
