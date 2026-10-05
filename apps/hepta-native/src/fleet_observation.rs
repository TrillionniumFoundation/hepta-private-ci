//! A bounded desktop projection of the authenticated Fleet observation.

use std::collections::BTreeSet;

use serde::Deserialize;

use crate::error::ShellError;

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FleetObservation {
    pub schema: String,
    pub observation_revision: u64,
    pub health: FleetHealth,
    pub agents: Vec<FleetAgent>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FleetHealth {
    pub ready: bool,
    pub supervisor_epoch: String,
    pub process_id: u32,
    pub registered_agents: u16,
    pub observed_faults: u64,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub(crate) enum AgentLifecycle {
    Stopped,
    Starting,
    Running,
    Draining,
    Failed,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct FleetAgent {
    pub agent_id: String,
    pub lifecycle: AgentLifecycle,
    pub lifecycle_generation: u64,
    pub active: bool,
    pub healthy: bool,
    pub process_id: Option<u64>,
    pub current_release: Option<String>,
    pub control_fence: AgentFence,
    pub matrix: AgentMatrix,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct AgentFence {
    pub supervisor_epoch: String,
}

#[derive(Debug, Clone, Deserialize)]
pub(crate) struct AgentMatrix {
    pub configured: bool,
    pub healthy: bool,
    pub degraded: bool,
    pub last_error: Option<String>,
}

impl FleetObservation {
    pub fn parse(value: &serde_json::Value) -> Result<Option<Self>, ShellError> {
        match value.get("schema").and_then(serde_json::Value::as_str) {
            Some("hepta_fleet_observation_v1") => {}
            Some(schema) if schema.starts_with("hepta_fleet_") => {
                return Err(ShellError::Backend(
                    "unsupported Fleet observation schema".into(),
                ));
            }
            _ => return Ok(None),
        }
        let observation: Self = serde_json::from_value(value.clone())
            .map_err(|error| ShellError::Backend(format!("invalid Fleet observation: {error}")))?;
        let mut identities = BTreeSet::new();
        if observation.schema != "hepta_fleet_observation_v1"
            || observation.observation_revision == 0
            || observation.health.process_id == 0
            || !uuid(&observation.health.supervisor_epoch)
            || observation.agents.len() > 256
            || usize::from(observation.health.registered_agents) != observation.agents.len()
        {
            return Err(ShellError::Backend(
                "invalid Fleet owner or complete roster".into(),
            ));
        }
        for agent in &observation.agents {
            if !uuid(&agent.agent_id)
                || !identities.insert(&agent.agent_id)
                || agent.control_fence.supervisor_epoch != observation.health.supervisor_epoch
                || agent.process_id == Some(0)
                || (agent.healthy && (!agent.active || agent.lifecycle != AgentLifecycle::Running))
                || (agent.matrix.healthy && (!agent.matrix.configured || agent.matrix.degraded))
                || agent
                    .current_release
                    .as_ref()
                    .is_some_and(|value| value.len() > 128)
                || agent
                    .matrix
                    .last_error
                    .as_ref()
                    .is_some_and(|value| value.len() > 4096)
            {
                return Err(ShellError::Backend("invalid Fleet agent projection".into()));
            }
        }
        Ok(Some(observation))
    }

    pub fn modules(&self) -> Vec<String> {
        let mut modules = vec!["ui.native".to_owned()];
        for agent in &self.agents {
            modules.push(format!("agent.{}", agent.agent_id));
            if agent.matrix.configured {
                modules.push(format!("matrix.{}", agent.agent_id));
            }
        }
        modules.sort();
        modules
    }
}

pub(crate) fn uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
            }
        })
}

#[derive(Debug, Clone)]
pub(crate) enum ObservationSource {
    Legacy,
    Fleet { epoch: String, process_id: u32 },
}

pub(crate) struct ViewMetadata {
    pub generation: u64,
    pub modules: Vec<String>,
    pub source: ObservationSource,
}

pub(crate) fn view_metadata(value: &serde_json::Value) -> Result<ViewMetadata, ShellError> {
    if let Some(fleet) = FleetObservation::parse(value)? {
        return Ok(ViewMetadata {
            generation: fleet.observation_revision,
            modules: fleet.modules(),
            source: ObservationSource::Fleet {
                epoch: fleet.health.supervisor_epoch,
                process_id: fleet.health.process_id,
            },
        });
    }
    let generation = value
        .pointer("/state/runtime_snapshot_generation")
        .and_then(serde_json::Value::as_u64)
        .ok_or_else(|| {
            ShellError::Backend("authenticated status lacks an observation identity".into())
        })?;
    Ok(ViewMetadata {
        generation,
        modules: vec!["runtime.legacy".to_owned(), "ui.native".to_owned()],
        source: ObservationSource::Legacy,
    })
}

#[cfg(test)]
#[path = "fleet_observation_tests.rs"]
mod tests;
