//! Cold takeover of a drained task boundary for the next explicit reset.
//!
//! The original entry requires STOP; the distinct retirement entry requires
//! persistent drain without inventing a model STOP. The host finishes delivery
//! ACK and drain while the predecessor's live CURRENT/selection remain valid,
//! then shuts down that runtime. After CURRENT
//! advances, this path replays the existing guarded file under the concrete
//! Control floor solely to prove that recorded boundary. It never returns a
//! journal or permits the predecessor to resume, admit work or deliver output.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update::PreparedAgentdGenerationUpdateV1;
use crate::neuron_generation_update::prepare_with_completion;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

/// Existing predecessor file and its independent witness. No missing or empty
/// file is created here. Ordinary V2 journals cannot enter the guarded domain.
pub struct AgentdGenerationUpdatePredecessorFilesV1<W: AnchorWitnessStore> {
    pub file: File,
    pub witness: W,
    pub config: CellGenerationConfigV2,
    pub max_records: u64,
}

/// Prepare a new task after the preceding guarded runtime has fully stopped.
///
/// The exclusive predecessor lock remains inside the returned preparation
/// until the publication CAS/readback. Advancing Artifact CURRENT therefore
/// does not require weakening the previous runtime's live guard. The selected
/// successor and FinalUse are still checked by the ordinary coordinator.
pub fn prepare_agentd_generation_cold_update_v1<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    prepare_cold_with_completion(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
        NeuronGenerationPredecessorCompletionV1::ModelStopped,
    )
}

/// Reopen a stopped runtime's drained journal only for explicit retirement.
/// It retains the old snapshot, including stopped=false, and never resumes it.
pub fn prepare_agentd_generation_cold_drained_update_v1<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    prepare_cold_with_completion(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
        NeuronGenerationPredecessorCompletionV1::OwnerDrained,
    )
}

/// Continue with the identical model after a closed runtime's actual drain.
/// No prior request or output is replayed, and no model adoption is implied.
pub fn prepare_agentd_generation_cold_same_model_task_v1<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    prepare_cold_with_completion(
        current,
        authorities,
        predecessor,
        selected,
        target,
        request,
        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel,
    )
}

fn prepare_cold_with_completion<Old, New>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    predecessor: AgentdGenerationUpdatePredecessorFilesV1<Old>,
    selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<New>,
    request: AgentdGenerationUpdateRequestV1,
    completion: NeuronGenerationPredecessorCompletionV1,
) -> Result<PreparedAgentdGenerationUpdateV1<Old, New>, AgentdError>
where
    Old: AnchorWitnessStore,
    New: AnchorWitnessStore,
{
    let metadata = predecessor.file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid(
            "cold predecessor requires an existing guarded journal",
        ));
    }
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let old = CellGenerationJournalV2::open_guarded(
        predecessor.file,
        predecessor.witness,
        predecessor.config,
        predecessor.max_records,
        guard,
    )
    .map_err(invalid)?;
    let observation = old.observe_generation().map_err(invalid)?;
    if !old.is_drained().map_err(invalid)?
        || (completion == NeuronGenerationPredecessorCompletionV1::ModelStopped
            && !observation.is_terminal())
    {
        return Err(invalid(match completion {
            NeuronGenerationPredecessorCompletionV1::ModelStopped => {
                "cold predecessor requires STOP, exact output ACK and drain"
            }
            NeuronGenerationPredecessorCompletionV1::OwnerDrained
            | NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel => {
                "cold predecessor requires exact output ACK and durable drain"
            }
        }));
    }
    prepare_with_completion(
        current,
        authorities,
        old,
        selected,
        target,
        request,
        completion,
    )
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
