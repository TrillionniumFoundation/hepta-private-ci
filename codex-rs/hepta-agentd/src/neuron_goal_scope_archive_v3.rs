/// Bounded projection of the same sole archive owner. Each retired scope keeps
/// its full immutable identity/receipt; this frontier grants no current use.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronGoalScopeArchiveFrontierV3 {
    pub schema_version: u32,
    pub last_scope_ordinal: u64,
    pub scope_count: u64,
    pub total_bytes: u64,
    pub receipt_digest: String,
}
impl Default for AgentdNeuronGoalScopeArchiveFrontierV3 {
    fn default() -> Self {
        Self {
            schema_version: 3,
            last_scope_ordinal: 0,
            scope_count: 0,
            total_bytes: 0,
            receipt_digest: String::new(),
        }
    }
}
impl AgentdNeuronGoalScopeArchiveFrontierV3 {
    fn validate(&self) -> Result<(), AgentdNeuronControlErrorV2> {
        if self.schema_version != 3
            || self.last_scope_ordinal != self.scope_count
            || if self.scope_count == 0 {
                self.total_bytes != 0 || !self.receipt_digest.is_empty()
            } else {
                self.total_bytes == 0
                    || self
                        .receipt_digest
                        .parse::<Digest32>()
                        .map(codex_hepta_agent_components::types::Digest32::is_zero)
                        .unwrap_or(true)
            }
        {
            return Err(AgentdNeuronControlErrorV2::ControllerPoisoned);
        }
        Ok(())
    }
}

/// Complete topology is the bounded hot control record plus the cold frontier.
/// Cold identities remain individually queryable without reopening model owners.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronGoalScopeTopologyV3 {
    pub control: AgentdNeuronGoalScopeStateV3,
    pub cold: AgentdNeuronGoalScopeArchiveFrontierV3,
}

fn verify_complete_goal_scope_topology_v3(
    control: &AgentdNeuronGoalScopeStateV3,
    archives: &archive_store::GenerationArchiveStore,
) -> Result<(), AgentdNeuronControlErrorV2> {
    let cold = archives.goal_frontier_v3()?;
    cold.validate()?;
    if cold
        .scope_count
        .checked_add(control.retained_scopes.len() as u64)
        .and_then(|count| count.checked_add(1))
        != Some(control.active_scope.ordinal)
        || control
            .retained_scopes
            .iter()
            .enumerate()
            .any(|(index, scope)| {
                cold.last_scope_ordinal
                    .checked_add(index as u64)
                    .and_then(|value| value.checked_add(1))
                    != Some(scope.ordinal)
            })
    {
        return Err(AgentdNeuronControlErrorV2::GenerationConflict);
    }
    if let Some(last) = archives.archived_goal_scope_v3(cold.last_scope_ordinal)?
        && (last.identity.subject_scope_digest
            != control.active_scope.identity.subject_scope_digest
            || last.identity.model_generation > control.active_scope.identity.model_generation)
    {
        return Err(AgentdNeuronControlErrorV2::GenerationConflict);
    }
    Ok(())
}

impl AgentdNeuronGenerationControllerV2 {
    pub fn goal_scope_topology_v3(
        &self,
    ) -> Result<AgentdNeuronGoalScopeTopologyV3, AgentdNeuronControlErrorV2> {
        let state = self.lock_state()?;
        let control = state
            .goal_scope_state(state.lifecycle)
            .map_err(poison_control_state)?;
        let archives = state
            .archives
            .as_ref()
            .ok_or(AgentdNeuronControlErrorV2::ControllerPoisoned)?;
        verify_complete_goal_scope_topology_v3(&control, archives)?;
        Ok(AgentdNeuronGoalScopeTopologyV3 {
            control,
            cold: archives.goal_frontier_v3()?.clone(),
        })
    }
}

pub fn read_agentd_neuron_live_goal_scope_state_v3(
    path: &Path,
) -> Result<AgentdNeuronGoalScopeStateV3, AgentdNeuronControlErrorV2> {
    let persisted = read_agentd_neuron_goal_scope_state_v3(path).map_err(poison_control_state)?;
    let archives = archive_store::GenerationArchiveStore::open_goal_scopes_v3(
        path,
        archive_store::DEFAULT_MAX_TOTAL_BYTES,
    )?;
    let live = remove_cold_goal_scopes_v3(&persisted, &archives)?;
    verify_complete_goal_scope_topology_v3(&live, &archives)?;
    Ok(live)
}

fn remove_cold_goal_scopes_v3(
    state: &AgentdNeuronGoalScopeStateV3,
    archives: &archive_store::GenerationArchiveStore,
) -> Result<AgentdNeuronGoalScopeStateV3, AgentdNeuronControlErrorV2> {
    let mut hot = Vec::new();
    for scope in &state.retained_scopes {
        match archives.archived_goal_scope_v3(scope.ordinal)? {
            Some(cold) if cold == *scope => (),
            Some(_) => return Err(AgentdNeuronControlErrorV2::GenerationConflict),
            None => hot.push(scope.clone()),
        }
    }
    AgentdNeuronGoalScopeStateV3::new(
        state.lifecycle,
        state.active_scope.clone(),
        hot,
        state.reload_target_scope.clone(),
    )
    .map_err(poison_control_state)
}
