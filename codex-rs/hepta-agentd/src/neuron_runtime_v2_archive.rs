/// Keep only recent physical owners resident. Cold history is queried through
/// immutable blobs; retirement never grants an execution or result-use gate.
pub const MAX_RETAINED_NEURON_GENERATION_OWNERS_V2: usize = 2;

impl AgentdNeuronGenerationControllerV2 {
    pub fn archive_retained_generations(
        &self,
        budget: std::time::Duration,
    ) -> Result<usize, AgentdNeuronControlErrorV2> {
        self.archive_retained_generations_to(MAX_RETAINED_NEURON_GENERATION_OWNERS_V2, budget)
    }

    fn archive_retained_generations_to(
        &self,
        maximum: usize,
        budget: std::time::Duration,
    ) -> Result<usize, AgentdNeuronControlErrorV2> {
        let deadline = Instant::now()
            .checked_add(budget)
            .ok_or(AgentdNeuronControlErrorV2::PendingRecovery)?;
        let mut state = self.lock_state()?;
        let mut archived = 0;
        while state.retained.len() > maximum {
            if Instant::now() >= deadline || state.archives.is_none() {
                return Err(AgentdNeuronControlErrorV2::PendingRecovery);
            }
            let (generation, handle) = state
                .retained
                .first_key_value()
                .map(|(generation, handle)| (*generation, handle.clone()))
                .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?;
            handle.close_lifecycle_gate()?;
            let _drain = handle.try_drain_lifecycle_gate()?;
            let archive = handle.owner.export_archive_control()?;
            state
                .archives
                .as_mut()
                .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?
                .commit(&archive)?;
            // Commit the archive frontier first. A crash before the following
            // hot-topology publication recovers this same archive, never a model.
            let retained = state
                .retained
                .keys()
                .copied()
                .filter(|value| *value != generation)
                .collect();
            persist_generation_state(
                state.state_path.as_deref(),
                state.lifecycle,
                state.active.generation()?,
                retained,
                state.reload_target_generation,
            )
            .map_err(poison_control_state)?;
            handle.owner.retire_control()?;
            state.retained.remove(&generation);
            archived += 1;
        }
        Ok(archived)
    }
}

/// Installer recovery uses this bounded hot topology to reopen only physical
/// owners still required by control state. Archived generations stay cold.
pub fn read_agentd_neuron_live_generation_state_v2(
    path: &Path,
) -> Result<AgentdNeuronGenerationStateV2, AgentdNeuronControlErrorV2> {
    let mut state = read_agentd_neuron_generation_state_v2(path).map_err(poison_control_state)?;
    let archives =
        archive_store::GenerationArchiveStore::open(path, archive_store::DEFAULT_MAX_TOTAL_BYTES)?;
    let mut retained = Vec::new();
    for generation in &state.retained_generations {
        if !archives.contains(*generation)? {
            retained.push(*generation);
        }
    }
    state.retained_generations = retained;
    state.state_digest = state
        .expected_digest()
        .map_err(poison_control_state)?
        .to_string();
    state.validate().map_err(poison_control_state)?;
    Ok(state)
}

/// A host storage budget, independent of model or qualification policy. Full
/// cold storage applies backpressure and retains all committed truth.
#[derive(Clone, Copy, Debug)]
pub struct AgentdNeuronArchivePolicyV1 {
    pub maximum_total_bytes: u64,
}
impl Default for AgentdNeuronArchivePolicyV1 {
    fn default() -> Self {
        Self {
            maximum_total_bytes: archive_store::DEFAULT_MAX_TOTAL_BYTES,
        }
    }
}
