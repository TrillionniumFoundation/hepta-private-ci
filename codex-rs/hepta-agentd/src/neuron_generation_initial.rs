//! First guarded generation admission through an explicit signed publication.
//!
//! A root-owned Preparing record and actual empty genesis precede the original
//! FinalUse boundary. No predecessor execution, STOP, output or grant is
//! invented to turn an ordinary journal into a guarded owner.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationCurrentOwnerV1;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;
use crate::neuron_generation_current::PreparedNeuronGenerationInitialV1;
use crate::neuron_generation_initial_bootstrap::ReadyAgentdGenerationInitialV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update::AgentdGenerationUpdateTargetV1;
use crate::neuron_generation_update_live::AgentdGenerationUpdateAuthoritiesV1;
use crate::neuron_generation_update_live::LiveGenerationCurrent;
use crate::neuron_generation_update_selection::AgentdSelectedGenerationV1;

/// Owns the exact root preparation and actual successor lock until publication.
/// Neither the prepared journal nor a raw runtime endpoint can be extracted.
pub struct PreparedAgentdGenerationInitialV1<W: AnchorWitnessStore> {
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    prepared: PreparedNeuronGenerationInitialV1,
    journal: CellGenerationJournalV2<W>,
    selected: AgentdSelectedGenerationV1,
}

/// Create the root Preparing record once. Existing root history is never reset
/// or treated as an absent owner. File placement and independent root custody
/// remain the trusted host's responsibility.
pub fn prepare_agentd_generation_initial_v1<W: AnchorWitnessStore>(
    root: Arc<RootAuthorityDirectory>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<W>,
    request: AgentdGenerationUpdateRequestV1,
) -> Result<PreparedAgentdGenerationInitialV1<W>, AgentdError> {
    StableId::new(&request.operation_id).map_err(invalid)?;
    let binding = validate_initial_target(&selected, &target)?;
    let metadata = target.file.metadata()?;
    if !metadata.is_file()
        || metadata.len() != 0
        || target.witness.current().map_err(invalid)?.is_some()
    {
        return Err(invalid("initial generation requires an empty target"));
    }
    let artifacts = authorities.artifacts.lock().map_err(invalid)?;
    selected.revalidate(&artifacts, authorities.now()?)?;
    let (current, prepared) = NeuronGenerationCurrentOwnerV1::prepare_initial(
        root,
        request.operation_id,
        binding,
        &selected,
    )?;
    let current = Arc::new(current);
    let guard: Arc<dyn CellGenerationCurrentV1> = current.clone();
    let journal = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    journal.prepared_checkpoint().map_err(invalid)?;
    drop(artifacts);
    Ok(PreparedAgentdGenerationInitialV1::from_parts(
        current,
        authorities,
        prepared,
        journal,
        selected,
    ))
}

impl<W: AnchorWitnessStore> PreparedAgentdGenerationInitialV1<W> {
    pub(crate) fn from_parts(
        current: Arc<NeuronGenerationCurrentOwnerV1>,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        prepared: PreparedNeuronGenerationInitialV1,
        journal: CellGenerationJournalV2<W>,
        selected: AgentdSelectedGenerationV1,
    ) -> Self {
        Self {
            current,
            authorities,
            prepared,
            journal,
            selected,
        }
    }

    pub fn final_use_binding(&self) -> &FinalUseBinding {
        self.prepared.final_use_binding()
    }

    pub fn intent_digest(&self) -> Digest32 {
        self.prepared.intent_digest()
    }

    /// Enter the original signed boundary once and retain its actual witness.
    /// An unknown acknowledgement is recovered by the original operation ID.
    pub fn publish(
        mut self,
        signed: &SignedFinalUseGrant,
    ) -> Result<ReadyAgentdGenerationInitialV1<W>, AgentdError> {
        let expected = self.prepared.final_use_binding().clone();
        let receipt = {
            let mut artifacts = self.authorities.artifacts.lock().map_err(invalid)?;
            self.current.publish_initial(
                &self.prepared,
                &self.journal,
                &mut self.selected,
                NeuronGenerationUpdatePublicationV1 {
                    artifacts: &mut artifacts,
                    authority: &self.authorities.final_use,
                    signed,
                    clock: self.authorities.clock.as_ref(),
                },
            )?
        };
        let guard = LiveGenerationCurrent::new_initial(
            self.current,
            self.authorities,
            self.selected,
            receipt.clone(),
            expected,
        )?;
        ReadyAgentdGenerationInitialV1::new(self.journal, receipt, guard)
    }
}

/// Recover only an actual initial publication. A pending or missing original
/// record is not permission to claim another token or recreate empty history.
pub fn recover_agentd_generation_initial_v1<W: AnchorWitnessStore>(
    current: Arc<NeuronGenerationCurrentOwnerV1>,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    mut selected: AgentdSelectedGenerationV1,
    target: AgentdGenerationUpdateTargetV1<W>,
    expected: AgentdGenerationUpdateRecoveryV1,
) -> Result<ReadyAgentdGenerationInitialV1<W>, AgentdError> {
    let prepared =
        current.recover_initial_operation(&expected.operation_id, expected.intent_digest)?;
    if selected.observation().digest() != prepared.selection_observation_digest()
        || &validate_initial_target(&selected, &target)? != prepared.target()
    {
        return Err(invalid("initial recovery target or selection differs"));
    }
    let receipt = match current.read_initial_operation(&prepared)? {
        NeuronGenerationInitialReadbackV1::Prepared => {
            return Err(invalid("initial generation remains pending; no redispatch"));
        }
        NeuronGenerationInitialReadbackV1::Published(receipt) => receipt,
    };
    let metadata = target.file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 {
        return Err(invalid("published initial journal is missing"));
    }
    {
        let artifacts = authorities.artifacts.lock().map_err(invalid)?;
        selected.revalidate(&artifacts, authorities.now()?)?;
    }
    let live = LiveGenerationCurrent::new_initial(
        current.clone(),
        authorities,
        selected,
        receipt.clone(),
        prepared.final_use_binding().clone(),
    )?;
    let guard: Arc<dyn CellGenerationCurrentV1> = live.clone();
    let journal = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        guard,
    )
    .map_err(invalid)?;
    let observed = match current.read_initial_operation(&prepared)? {
        NeuronGenerationInitialReadbackV1::Prepared => {
            return Err(invalid("initial publication regressed to preparation"));
        }
        NeuronGenerationInitialReadbackV1::Published(observed) => observed,
    };
    if observed != receipt || journal.owner_binding() != Some(observed.target()) {
        return Err(invalid("initial publication changed during recovery"));
    }
    ReadyAgentdGenerationInitialV1::new(journal, observed, live)
}

pub(crate) fn validate_initial_target<W: AnchorWitnessStore>(
    selected: &AgentdSelectedGenerationV1,
    target: &AgentdGenerationUpdateTargetV1<W>,
) -> Result<CellGenerationOwnerBindingV1, AgentdError> {
    if selected.manifest() != &target.config.manifest
        || target.config.initial.revision != 0
        || !target.config.initial.prefix.is_empty()
        || target.config.initial.stopped
    {
        return Err(invalid("initial generation requires its selected genesis"));
    }
    CellGenerationOwnerBindingV1::new(&target.config, target.max_records).map_err(invalid)
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
