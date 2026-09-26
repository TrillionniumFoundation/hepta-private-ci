//! One identity grammar for authenticated Objective and canonical run admission.
//! A process is launched at `spawn`; its ready Running lifecycle is `spawn + 1`.
//! Body/model generation continues to refer to `spawn`, not the lifecycle epoch.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentRunError;
use crate::RunSnapshot;
use crate::RuntimeComposition;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct AgentdRunEpochV1 {
    agent_id: String,
    spawn_generation: u64,
    current_generation: u64,
    fence_digest: Digest32,
}

impl AgentdRunEpochV1 {
    pub(crate) fn running(
        agent_id: &str,
        spawn_generation: u64,
        current_generation: u64,
    ) -> Result<Self, AgentRunError> {
        StableId::new(agent_id).map_err(|_| AgentRunError::InvalidIdentity("agent"))?;
        if spawn_generation == 0 || spawn_generation.checked_add(1) != Some(current_generation) {
            return Err(AgentRunError::InvalidGeneration);
        }
        Ok(Self {
            agent_id: agent_id.to_string(),
            spawn_generation,
            current_generation,
            fence_digest: objective_run_fence_digest(
                agent_id,
                spawn_generation,
                current_generation,
            ),
        })
    }

    pub(crate) const fn fence_digest(&self) -> Digest32 {
        self.fence_digest
    }

    pub(crate) fn validate_composition(
        &self,
        composition: &RuntimeComposition,
    ) -> Result<(), AgentRunError> {
        if composition.agent_id != self.agent_id
            || composition.agentd_generation != self.spawn_generation
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        Ok(())
    }

    pub(crate) fn validate_snapshot(&self, snapshot: &RunSnapshot) -> Result<(), AgentRunError> {
        if snapshot.generation != self.current_generation
            || snapshot.fence_digest != self.fence_digest.to_string()
        {
            return Err(AgentRunError::MixedSnapshot);
        }
        Ok(())
    }
}

pub(crate) fn objective_run_fence_digest(
    agent_id: &str,
    spawn_generation: u64,
    current_generation: u64,
) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\0".to_vec();
    bytes.extend_from_slice(agent_id.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "intelligence_identity_tests.rs"]
mod tests;
