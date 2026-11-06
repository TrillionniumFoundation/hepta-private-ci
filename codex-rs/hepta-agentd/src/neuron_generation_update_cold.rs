//! Cold takeover of an already completed task for the next explicit reset.
//!
//! The host finishes STOP, delivery ACK and drain while the predecessor's live
//! CURRENT/selection remain valid, then shuts down that runtime. After CURRENT
//! advances, this path replays the existing guarded file under the concrete
//! Control floor solely to prove that terminal boundary. It never returns a
//! journal or permits the predecessor to resume, admit work or deliver output.

use std::fs::File;
use std::sync::Arc;

use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationConfigV2;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update::PreparedAgentdGenerationUpdateV1;
use crate::neuron_generation_update::prepare_agentd_generation_update_v1;
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
    if !observation.is_terminal() || !old.is_drained().map_err(invalid)? {
        return Err(invalid(
            "cold predecessor requires STOP, exact output ACK and drain",
        ));
    }
    prepare_agentd_generation_update_v1(current, authorities, old, selected, target, request)
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
