//! Guarded V13 task-boundary assembly over the original update coordinator.
//!
//! The checked files stay inside this module through publication. Callers
//! supply existing CURRENT/selection/FinalUse owners; this adapter cannot mint
//! authority, expose a raw journal, choose a replacement clock or run a model.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update::PreparedAgentdGenerationUpdateV1;
use crate::neuron_generation_update::prepare_agentd_generation_drained_update_v1;
use crate::neuron_generation_update::prepare_agentd_generation_same_model_task_v1;
use crate::neuron_generation_update::prepare_agentd_generation_update_v1;
use crate::neuron_generation_update::recover_agentd_generation_update_v1;
use crate::neuron_generation_update_cold::AgentdGenerationUpdatePredecessorFilesV1;
use crate::neuron_generation_update_cold::prepare_agentd_generation_cold_drained_update_v1;
use crate::neuron_generation_update_cold::prepare_agentd_generation_cold_same_model_task_v1;
use crate::neuron_generation_update_cold::prepare_agentd_generation_cold_update_v1;
use crate::neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
use crate::neuron_generation_update_forward::prepare_agentd_generation_forward_recovery_v1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;
use crate::neuron_v13_generation_bootstrap::AgentdV13GenerationBootstrapConfigV1;
use crate::neuron_v13_generation_bootstrap::AgentdV13GenerationWorkerV1;
use crate::neuron_v13_generation_bootstrap::V13GenerationOwnerFilesV1;
use crate::neuron_v13_generation_bootstrap::V13GenerationOwnerModeV1;
use crate::neuron_v13_generation_bootstrap::owners;
use crate::neuron_v13_generation_bootstrap::owners::V13BackendOwner;
use crate::neuron_v13_generation_update_runtime::ReadyAgentdV13GenerationUpdateV1;

/// Actual host identity, already-opened owner files and the prepared Linux
/// worker. Fresh/reopen mode is fixed by the chosen operation, never a fallback.
pub struct AgentdV13GenerationUpdateInputsV1<'a> {
    pub identity: &'a AgentdIdentity,
    pub config: AgentdV13GenerationBootstrapConfigV1,
    pub files: V13GenerationOwnerFilesV1,
    pub prepared: &'a AgentdV13GenerationWorkerV1,
}

impl AgentdV13GenerationUpdateInputsV1<'_> {
    pub(crate) fn open(
        self,
        mode: V13GenerationOwnerModeV1,
    ) -> Result<
        (
            AgentdGenerationUpdateTargetV1<FileAnchorWitnessStore>,
            V13BackendOwner,
        ),
        AgentdError,
    > {
        let opened =
            owners::open_owners(self.identity, self.config, self.files, mode, self.prepared)?;
        let target = AgentdGenerationUpdateTargetV1 {
            file: opened.journal,
            witness: opened.witness,
            config: opened.backend.configuration().generation.clone(),
            max_records: opened.backend.configuration().max_records,
        };
        Ok((target, opened.backend))
    }

    pub(crate) fn revalidate_selection(
        &self,
        authorities: &AgentdGenerationUpdateAuthoritiesV1,
        selected: &mut AgentdSelectedGenerationV1,
    ) -> Result<(), AgentdError> {
        if selected.manifest() != &self.config.generation.manifest {
            return Err(AgentdError::Invalid(
                "V13 selection differs from the requested successor manifest".into(),
            ));
        }
        let artifacts = authorities
            .artifacts
            .lock()
            .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        selected.revalidate(&artifacts, authorities.now()?)
    }
}

/// The actual old/new journal locks and lower control owner remain private.
/// Preparing retains empty successor genesis; no preparation cost is appended
/// until the original signed publication has made that owner current.
pub struct PreparedAgentdV13GenerationUpdateV1<Old: AnchorWitnessStore> {
    update: PreparedAgentdGenerationUpdateV1<Old, FileAnchorWitnessStore>,
    backend: V13BackendOwner,
}

impl<Old: AnchorWitnessStore> PreparedAgentdV13GenerationUpdateV1<Old> {
    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.update.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.update.intent_digest()
    }

    pub fn publish(
        self,
        signed: &SignedFinalUseGrant,
    ) -> Result<ReadyAgentdV13GenerationUpdateV1, AgentdError> {
        let ready = self.update.publish(signed)?;
        Ok(ReadyAgentdV13GenerationUpdateV1::new(ready, self.backend))
    }
}

/// Prepare one new V13 task using the actual stopped, acknowledged and drained
/// predecessor. The ordinary coordinator rechecks the exact selection and cut
/// before any protected publication.
pub fn prepare_agentd_v13_generation_update_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update =
        prepare_agentd_generation_update_v1(current, authorities, old, selected, target, request)?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Cold terminal takeover keeps the original strict STOP/ACK/drain proof and
/// never exposes the predecessor under a weaker guard to a running service.
pub fn prepare_agentd_v13_generation_cold_update_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update = prepare_agentd_generation_cold_update_v1(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Operator-only forward preparation uses the original files and selection and
/// requires a different externally signed operation. It never retries a claim
/// or interprets an unresolved previous publication as not applied.
pub fn prepare_agentd_v13_generation_forward_recovery_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationForwardRecoveryV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::Reopen)?;
    let update = prepare_agentd_generation_forward_recovery_v1(
        current,
        authorities,
        old,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Reopen an actual published successor with the original operation readback.
/// Missing owner files, different boot/selection or uncertain publication stay
/// errors; neither this path nor the control owner recreates a dispatch token.
pub fn recover_agentd_v13_generation_update_v1(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    expected: AgentdGenerationUpdateRecoveryV1,
) -> Result<ReadyAgentdV13GenerationUpdateV1, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::Reopen)?;
    let ready =
        recover_agentd_generation_update_v1(current, authorities, selected, target, expected)?;
    Ok(ReadyAgentdV13GenerationUpdateV1::new(ready, backend))
}

/// Explicitly retire a task whose owner has durably drained and whose output
/// is fully acknowledged. The old snapshot remains unchanged, including its
/// non-STOP status; the distinct signed Control publication fences that writer.
pub fn prepare_agentd_v13_generation_drained_update_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update = prepare_agentd_generation_drained_update_v1(
        current,
        authorities,
        old,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Cold explicit retirement uses the original drained predecessor files.
/// It does not claim a model STOP or produce terminal learning/eval evidence.
pub fn prepare_agentd_v13_generation_cold_drained_update_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update = prepare_agentd_generation_cold_drained_update_v1(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Carry the exact V13 manifest into a new task after the actual ACK and drain.
/// Independent evaluation's no-update outcome needs no fabricated model change;
/// this operation still requires current selection and its own FinalUse grant.
pub fn prepare_agentd_v13_generation_same_model_task_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    old: CellGenerationJournalV2<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update = prepare_agentd_generation_same_model_task_v1(
        current,
        authorities,
        old,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}

/// Reopen the drained predecessor only for same-model task handoff. The closed
/// old owner is never exposed to a worker or resumed under a weaker guard.
pub fn prepare_agentd_v13_generation_cold_same_model_task_v1<Old: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    mut selected: AgentdSelectedGenerationV1,
    inputs: AgentdV13GenerationUpdateInputsV1<'_>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdV13GenerationUpdateV1<Old>, AgentdError> {
    inputs.revalidate_selection(&authorities, &mut selected)?;
    let (target, backend) = inputs.open(V13GenerationOwnerModeV1::InitializeEmpty)?;
    let update = prepare_agentd_generation_cold_same_model_task_v1(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
    )?;
    Ok(PreparedAgentdV13GenerationUpdateV1 { update, backend })
}
