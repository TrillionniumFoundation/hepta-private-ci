//! Composition-bound admission for canonical Agentd runs.
//!
//! The legacy `start_run` entry remains for compatibility callers. Canonical
//! intelligence uses `start_bound_run`, which proves the snapshot belongs to
//! this process launch and the unique Running lifecycle generation before
//! mutating the coordinator.

use crate::AgentRunCoordinator;
use crate::AgentRunError;
use crate::RunReceipt;
use crate::RunSnapshot;
use crate::objective_run_fence_digest_v1;

impl AgentRunCoordinator {
    pub fn start_bound_run(
        &mut self,
        now_ms: u64,
        snapshot: RunSnapshot,
    ) -> Result<RunReceipt, AgentRunError> {
        let composition = self.composition();
        let running_generation = composition
            .supervisor_generation
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        if snapshot.generation != running_generation {
            return Err(AgentRunError::InvalidGeneration);
        }
        let expected_fence = objective_run_fence_digest_v1(
            &composition.agent_id,
            composition.supervisor_generation,
            running_generation,
        )
        .to_string();
        if snapshot.fence_digest != expected_fence {
            return Err(AgentRunError::InvalidRunStart("composition identity"));
        }
        self.start_run(now_ms, snapshot)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(value: &str) -> String {
        codex_hepta_types::Digest32::of_bytes(value.as_bytes()).to_string()
    }

    fn composition() -> crate::RuntimeComposition {
        crate::RuntimeComposition {
            agent_id: "agent.bound".to_string(),
            supervisor_generation: 41,
            agentd_generation: 42,
            configuration_digest: digest("configuration"),
            ports_digest: digest("ports"),
            max_active_runs: 2,
        }
    }

    fn snapshot() -> RunSnapshot {
        RunSnapshot {
            run_id: "run.bound".to_string(),
            request_digest: digest("request"),
            objective_digest: digest("objective"),
            body_digest: digest("body"),
            artifact_set_digest: digest("artifacts"),
            authority_epoch: 7,
            generation: 42,
            fence_digest: objective_run_fence_digest_v1("agent.bound", 41, 42).to_string(),
            deadline_ms: 10_000,
        }
    }

    #[test]
    fn running_generation_differs_from_spawn_and_is_admitted() {
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition()).expect("composition");
        let receipt = coordinator
            .start_bound_run(100, snapshot())
            .expect("bound run");
        assert_eq!(receipt.generation, 42);
    }

    #[test]
    fn forged_generation_or_fence_is_rejected_before_mutation() {
        let mut coordinator =
            AgentRunCoordinator::compose_runtime(composition()).expect("composition");

        let mut starting_generation = snapshot();
        starting_generation.generation = 41;
        starting_generation.fence_digest =
            objective_run_fence_digest_v1("agent.bound", 41, 41).to_string();
        assert_eq!(
            coordinator.start_bound_run(100, starting_generation),
            Err(AgentRunError::InvalidGeneration)
        );

        let mut draining_generation = snapshot();
        draining_generation.generation = 43;
        draining_generation.fence_digest =
            objective_run_fence_digest_v1("agent.bound", 41, 43).to_string();
        assert_eq!(
            coordinator.start_bound_run(100, draining_generation),
            Err(AgentRunError::InvalidGeneration)
        );

        let mut wrong_fence = snapshot();
        wrong_fence.fence_digest = digest("foreign-fence");
        assert_eq!(
            coordinator.start_bound_run(100, wrong_fence),
            Err(AgentRunError::InvalidRunStart("composition identity"))
        );
        assert_eq!(coordinator.run("run.bound"), None);
    }
}
