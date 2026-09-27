//! Canonical Agentd run-generation and fence identity.
//!
//! The process spawn generation and the live Fleet lifecycle generation are
//! deliberately distinct.  Product run admission must bind both values through
//! one digest grammar; callers may not synthesize an alternative fence.

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::RunStartRecordV1;

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::RunReceipt;
use crate::RunSnapshot;
use crate::RuntimeComposition;

const OBJECTIVE_FENCE_DOMAIN: &[u8] = b"hepta:agentd:objective-fence:v1\0";

/// Compute the sole canonical Objective/run fence.
///
/// `spawn_generation` identifies the daemon process. `current_generation`
/// identifies the live Fleet lifecycle epoch admitted by that process.
pub fn agentd_objective_fence(
    agent_id: &str,
    spawn_generation: u64,
    current_generation: u64,
) -> Result<String, AgentRunError> {
    if agent_id.is_empty()
        || agent_id.len() > 128
        || !agent_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(AgentRunError::InvalidIdentity("agent"));
    }
    if spawn_generation == 0
        || current_generation == 0
        || current_generation < spawn_generation
    {
        return Err(AgentRunError::InvalidGeneration);
    }
    let mut bytes = OBJECTIVE_FENCE_DOMAIN.to_vec();
    bytes.extend_from_slice(agent_id.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Ok(Sha256Digest::for_bytes(&bytes).as_str().to_string())
}

impl RuntimeComposition {
    /// Resolve the lifecycle generation accepted by this frozen composition.
    ///
    /// Historical compositions recorded identical supervisor/Agentd values at
    /// process start.  Such a composition admits work only after the Fleet
    /// advances to Running (`spawn + 1`).  Newer compositions may already carry
    /// the distinct live Agentd generation and use it directly.
    pub fn current_run_generation(&self) -> Result<u64, AgentRunError> {
        if self.supervisor_generation == 0 || self.agentd_generation == 0 {
            return Err(AgentRunError::InvalidGeneration);
        }
        if self.agentd_generation < self.supervisor_generation {
            return Err(AgentRunError::InvalidGeneration);
        }
        if self.agentd_generation == self.supervisor_generation {
            self.agentd_generation
                .checked_add(1)
                .ok_or(AgentRunError::ArithmeticOverflow)
        } else {
            Ok(self.agentd_generation)
        }
    }

    pub fn objective_fence_for(&self, generation: u64) -> Result<String, AgentRunError> {
        let current = self.current_run_generation()?;
        if generation != current {
            return Err(AgentRunError::InvalidGeneration);
        }
        agentd_objective_fence(
            &self.agent_id,
            self.supervisor_generation,
            generation,
        )
    }
}

impl AgentRunCoordinator {
    /// Admit a run only when generation and fence match the frozen Agentd
    /// composition.  Compatibility callers may retain `start_run`; canonical
    /// product callers must use this stricter boundary.
    pub fn start_bound_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        let expected_fence = self.composition().objective_fence_for(snapshot.generation)?;
        if snapshot.fence_digest != expected_fence {
            return Err(AgentRunError::MixedSnapshot);
        }
        self.start_run(now_ms, snapshot)
    }

    /// Project an already authenticated durable RunStart through the same
    /// composition fence used by canonical intelligence admission.
    pub(crate) fn start_revalidated_bound_run_start(
        &mut self,
        now_ms: u64,
        record: &RunStartRecordV1,
    ) -> Result<RunReceipt, AgentRunError> {
        let deadline_ms = record
            .admission
            .deadline_unix_micros
            .checked_add(999)
            .map(|value| value / 1_000)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        let snapshot = RunSnapshot {
            run_id: record.snapshot.run_id.to_string(),
            request_digest: record.admission.admitted_source_digest.to_string(),
            objective_digest: record.snapshot.objective_digest.to_string(),
            body_digest: record.runtime_body_digest.to_string(),
            artifact_set_digest: record.snapshot.artifact_set_digest.to_string(),
            authority_epoch: record.snapshot.authority_epoch,
            generation: record.snapshot.generation,
            fence_digest: record.snapshot.fence_digest.to_string(),
            deadline_ms,
        };
        let expected_fence = self.composition().objective_fence_for(snapshot.generation)?;
        if snapshot.fence_digest != expected_fence {
            return Err(AgentRunError::MixedSnapshot);
        }
        self.start_revalidated_run_start(now_ms, record)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(byte: char) -> String {
        byte.to_string().repeat(64)
    }

    fn composition(spawn: u64, current: u64) -> RuntimeComposition {
        RuntimeComposition {
            agent_id: "agent.identity".to_string(),
            supervisor_generation: spawn,
            agentd_generation: current,
            configuration_digest: digest('1'),
            ports_digest: digest('2'),
            max_active_runs: 2,
        }
    }

    fn snapshot(composition: &RuntimeComposition, generation: u64) -> RunSnapshot {
        RunSnapshot {
            run_id: "run.identity".to_string(),
            request_digest: digest('3'),
            objective_digest: digest('4'),
            body_digest: digest('5'),
            artifact_set_digest: digest('6'),
            authority_epoch: 7,
            generation,
            fence_digest: agentd_objective_fence(
                &composition.agent_id,
                composition.supervisor_generation,
                generation,
            )
            .expect("fence"),
            deadline_ms: 10_000,
        }
    }

    #[test]
    fn starting_composition_admits_distinct_running_generation() {
        let composition = composition(41, 41);
        assert_eq!(composition.current_run_generation().unwrap(), 42);
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition.clone()).expect("coordinator");
        let receipt = coordinator
            .start_bound_run(100, snapshot(&composition, 42))
            .expect("bound run");
        assert_eq!(receipt.generation, 42);
    }

    #[test]
    fn bound_admission_rejects_generation_or_fence_substitution() {
        let composition = composition(41, 42);
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition.clone()).expect("coordinator");
        let mut wrong_generation = snapshot(&composition, 42);
        wrong_generation.generation = 43;
        assert_eq!(
            coordinator.start_bound_run(100, wrong_generation),
            Err(AgentRunError::InvalidGeneration)
        );

        let mut wrong_fence = snapshot(&composition, 42);
        wrong_fence.fence_digest = digest('f');
        assert_eq!(
            coordinator.start_bound_run(100, wrong_fence),
            Err(AgentRunError::MixedSnapshot)
        );
    }
}
