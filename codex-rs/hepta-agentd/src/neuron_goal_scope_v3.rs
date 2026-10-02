/// Read-only identity of an actual serialized runtime owner. Model generation
/// and objective scope remain separate; this projection grants no admission.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronScopeIdentityV3 {
    pub model_generation: u64,
    #[serde(with = "scope_digest_v3")]
    pub subject_scope_digest: Digest32,
    #[serde(with = "scope_digest_v3")]
    pub objective_digest: Digest32,
    #[serde(with = "scope_digest_v3")]
    pub runtime_configuration_digest: Digest32,
    #[serde(with = "scope_digest_v3")]
    pub body_bundle_digest: Digest32,
}

impl AgentdNeuronHandleV2 {
    pub fn scope_identity(
        &self,
    ) -> Result<AgentdNeuronScopeIdentityV3, AgentdNeuronControlErrorV2> {
        let scope = self.owner.journal_scope_control()?;
        Ok(AgentdNeuronScopeIdentityV3 {
            model_generation: self.generation()?,
            subject_scope_digest: scope.scope_digest,
            objective_digest: scope.objective_digest,
            runtime_configuration_digest: self.configuration_digest(),
            body_bundle_digest: self
                .body_bundle_digest()
                .ok_or(AgentdNeuronControlErrorV2::GenerationConflict)?,
        })
    }
}

/// Monotonic journal ownership slot, independent of the actual model generation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronGoalScopeV3 {
    pub ordinal: u64,
    pub identity: AgentdNeuronScopeIdentityV3,
}

impl AgentdNeuronGoalScopeV3 {
    pub fn capture(
        ordinal: u64,
        owner: &AgentdNeuronHandleV2,
    ) -> Result<Self, AgentdNeuronControlErrorV2> {
        let value = Self {
            ordinal,
            identity: owner.scope_identity()?,
        };
        value.validate().map_err(poison_control_state)?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), AgentdNeuronControlStateErrorV2> {
        if self.ordinal == 0
            || self.identity.model_generation == 0
            || [
                self.identity.subject_scope_digest,
                self.identity.objective_digest,
                self.identity.runtime_configuration_digest,
                self.identity.body_bundle_digest,
            ]
            .into_iter()
            .any(codex_hepta_agent_components::types::Digest32::is_zero)
        {
            return Err(AgentdNeuronControlStateErrorV2::Invalid);
        }
        Ok(())
    }

    fn append_identity(&self, bytes: &mut Vec<u8>) {
        bytes.extend_from_slice(&self.ordinal.to_be_bytes());
        bytes.extend_from_slice(&self.identity.model_generation.to_be_bytes());
        for digest in [
            self.identity.subject_scope_digest,
            self.identity.objective_digest,
            self.identity.runtime_configuration_digest,
            self.identity.body_bundle_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
    }
}

/// Explicit V3 control topology. The original V2 codec and digest domain stay
/// unchanged. This checksummed projection is lifecycle state, not authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct AgentdNeuronGoalScopeStateV3 {
    pub schema_version: u32,
    pub lifecycle: AgentdNeuronLifecycleStateV2,
    pub active_scope: AgentdNeuronGoalScopeV3,
    pub retained_scopes: Vec<AgentdNeuronGoalScopeV3>,
    pub reload_target_scope: Option<AgentdNeuronGoalScopeV3>,
    pub state_digest: String,
}

impl AgentdNeuronGoalScopeStateV3 {
    pub fn new(
        lifecycle: AgentdNeuronLifecycleStateV2,
        active_scope: AgentdNeuronGoalScopeV3,
        mut retained_scopes: Vec<AgentdNeuronGoalScopeV3>,
        reload_target_scope: Option<AgentdNeuronGoalScopeV3>,
    ) -> Result<Self, AgentdNeuronControlStateErrorV2> {
        retained_scopes.sort_by_key(|scope| scope.ordinal);
        let mut value = Self {
            schema_version: 3,
            lifecycle,
            active_scope,
            retained_scopes,
            reload_target_scope,
            state_digest: String::new(),
        };
        value.state_digest = value.expected_digest()?.to_string();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), AgentdNeuronControlStateErrorV2> {
        self.active_scope.validate()?;
        if self.schema_version != 3
            || self
                .retained_scopes
                .windows(2)
                .any(|pair| pair[0].ordinal >= pair[1].ordinal)
        {
            return Err(AgentdNeuronControlStateErrorV2::Invalid);
        }
        for scope in &self.retained_scopes {
            scope.validate()?;
            if scope.ordinal >= self.active_scope.ordinal
                || scope.identity.subject_scope_digest
                    != self.active_scope.identity.subject_scope_digest
                || scope.identity.model_generation > self.active_scope.identity.model_generation
            {
                return Err(AgentdNeuronControlStateErrorV2::Invalid);
            }
        }
        match (self.lifecycle, &self.reload_target_scope) {
            (AgentdNeuronLifecycleStateV2::Reloading, Some(next)) => {
                next.validate()?;
                if next.ordinal
                    != self
                        .active_scope
                        .ordinal
                        .checked_add(1)
                        .ok_or(AgentdNeuronControlStateErrorV2::Invalid)?
                    || next.identity.subject_scope_digest
                        != self.active_scope.identity.subject_scope_digest
                    || next.identity.model_generation < self.active_scope.identity.model_generation
                    || next.identity == self.active_scope.identity
                {
                    return Err(AgentdNeuronControlStateErrorV2::Invalid);
                }
            }
            (AgentdNeuronLifecycleStateV2::Reloading, None) => {
                return Err(AgentdNeuronControlStateErrorV2::Invalid);
            }
            (_, None) => {}
            (_, Some(_)) => return Err(AgentdNeuronControlStateErrorV2::Invalid),
        }
        if self.state_digest.is_empty() || self.state_digest != self.expected_digest()?.to_string()
        {
            return Err(AgentdNeuronControlStateErrorV2::Corrupt);
        }
        Ok(())
    }

    fn expected_digest(&self) -> Result<Digest32, AgentdNeuronControlStateErrorV2> {
        let mut bytes = b"hepta.agentd.neuron-goal-scope-state.v3".to_vec();
        bytes.extend_from_slice(&self.schema_version.to_be_bytes());
        bytes.push(lifecycle_code(self.lifecycle));
        self.active_scope.append_identity(&mut bytes);
        bytes.extend_from_slice(
            &u32::try_from(self.retained_scopes.len())
                .map_err(|_| AgentdNeuronControlStateErrorV2::Invalid)?
                .to_be_bytes(),
        );
        for scope in &self.retained_scopes {
            scope.append_identity(&mut bytes);
        }
        match &self.reload_target_scope {
            Some(scope) => {
                bytes.push(1);
                scope.append_identity(&mut bytes);
            }
            None => bytes.push(0),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn write_agentd_neuron_goal_scope_state_v3(
    path: &Path,
    state: &AgentdNeuronGoalScopeStateV3,
) -> Result<(), AgentdNeuronControlStateErrorV2> {
    state.validate()?;
    let encoded =
        serde_json::to_vec_pretty(state).map_err(|_| AgentdNeuronControlStateErrorV2::Corrupt)?;
    write_generation_state_encoded(path, &encoded)
}

pub fn read_agentd_neuron_goal_scope_state_v3(
    path: &Path,
) -> Result<AgentdNeuronGoalScopeStateV3, AgentdNeuronControlStateErrorV2> {
    let state: AgentdNeuronGoalScopeStateV3 =
        serde_json::from_slice(&read_generation_state_bytes(path)?)
            .map_err(|_| AgentdNeuronControlStateErrorV2::Corrupt)?;
    state.validate()?;
    Ok(state)
}

mod scope_digest_v3 {
    use super::Digest32;
    pub(super) fn serialize<S: serde::Serializer>(
        digest: &Digest32,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&digest.to_string())
    }
    pub(super) fn deserialize<'de, D: serde::Deserializer<'de>>(
        decoder: D,
    ) -> Result<Digest32, D::Error> {
        let text = <String as serde::Deserialize>::deserialize(decoder)?;
        text.parse()
            .map_err(|_| serde::de::Error::custom("invalid scope digest"))
    }
}
