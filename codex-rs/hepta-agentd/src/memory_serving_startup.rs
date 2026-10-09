//! Revalidate existing capabilities before the real Agentd task host starts.
//! This module issues no keys, selection, time observations or final-use grants.

use std::future::Future;

use codex_hepta_contracts::AgentId;
use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use codex_hepta_control_plane::RuntimeModuleStateClassV1;
use tokio_util::sync::CancellationToken;

use super::super::SelectedMemoryServiceV1;
use super::require_current_memory_fleet_v1;
use crate::AgentdError;
use crate::RuntimeTasks;
use crate::SharedMemoryTrainingError;

impl SelectedMemoryServiceV1 {
    pub(crate) fn validate_startup_abi_v1(
        &self,
        active: &ActiveRuntimeModuleV1,
        implementation: &RuntimeModuleAbiV1,
    ) -> Result<(), AgentdError> {
        implementation
            .validate()
            .map_err(|error| AgentdError::Protocol(format!("invalid memory startup ABI: {error}")))?;
        let compiled = ActiveRuntimeModuleV1 {
            module_id: implementation.module_id.clone(),
            generation: implementation.generation,
            implementation_digest: implementation.implementation_digest,
            candidate_artifact_digest: implementation.candidate_artifact_digest,
            owner_id: implementation.owner_id.clone(),
            state_class: implementation.state_class,
            dependencies: implementation.dependencies.clone(),
            input_ports: implementation.input_ports.clone(),
            output_ports: implementation.output_ports.clone(),
            authoritative_domains: implementation.authoritative_domains.clone(),
            effect_scope: implementation.effect_scope.clone(),
        };
        let manifest = self.model.pinned.manifest();
        if active != &compiled
            || self.model.unavailable
            || implementation.state_class != RuntimeModuleStateClassV1::Stateless
            || !implementation.authoritative_domains.is_empty()
            || implementation.implementation_digest != self.process.runtime_digest()
            || implementation.candidate_artifact_digest != manifest.content_digest
            || implementation.generation != self.qualification.route_generation()
            || !self.qualification.matches(manifest)
        {
            return Err(AgentdError::Protocol(
                "selected memory startup does not match its admitted ABI".to_string(),
            ));
        }
        // A fresh process cannot pretend to have observed retirement in a
        // prior host. Cross-process handoff remains the Supervisor's durable
        // generation fence, never a locally reset predecessor map.
        if implementation.predecessor_generation.is_some() {
            return Err(AgentdError::Protocol(
                "fresh Agentd host cannot acknowledge a predecessor's retirement".to_string(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn revalidate_agentd_startup_v1(
        &mut self,
        agent: &AgentId,
    ) -> Result<(), AgentdError> {
        if self.owners.replay.consumer.agent_id() != agent {
            self.model.unavailable = true;
            return Err(AgentdError::Protocol(
                "selected memory source consumer differs from the starting Agentd".to_string(),
            ));
        }
        let checked: Result<(), SharedMemoryTrainingError> = async {
            // Identical lock ordering to the actual final-use path. No worker
            // is launched and no response/authority is issued by this check.
            let fleet = self.owners.fleet.lock().await;
            require_current_memory_fleet_v1(&fleet, self.node.as_str())?;
            let ledger = self.owners.ledger.lock().await;
            let artifacts = self.owners.artifacts.lock().await;
            let selector = self.owners.selector.read().await;
            let evidence = self.owners.evidence.read().await;
            self.qualification
                .revalidate_current(
                    &evidence,
                    &(self.owners.audit_withdrawals)()?,
                    (self.owners.clock)()?,
                )
                .map_err(|_| SharedMemoryTrainingError::Invalid("stale startup qualification"))?;
            self.owners
                .replay
                .with_current_selected_memory_tensor_v1(
                    &mut self.model,
                    &ledger,
                    &artifacts,
                    &selector,
                    || (self.owners.clock)(),
                    |_| (),
                )
                .await?;
            // Re-sample trust lifetimes and withdrawals after the asynchronous
            // source/current-registry checks, not only before them.
            self.qualification
                .revalidate_current(
                    &evidence,
                    &(self.owners.audit_withdrawals)()?,
                    (self.owners.clock)()?,
                )
                .map_err(|_| SharedMemoryTrainingError::Invalid("startup qualification changed"))?;
            require_current_memory_fleet_v1(&fleet, self.node.as_str())?;
            Ok(())
        }
        .await;
        if checked.is_err() {
            self.model.unavailable = true;
        }
        checked.map_err(|error| AgentdError::Protocol(format!("memory startup rejected: {error}")))
    }

    pub(crate) fn spawn_after_agentd_startup_v1<Q, R>(
        self,
        tasks: &mut RuntimeTasks,
        active: &ActiveRuntimeModuleV1,
        implementation: &RuntimeModuleAbiV1,
        ready: CancellationToken,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        self.validate_startup_abi_v1(active, implementation)?;
        tasks.spawn_bound_optional_service(
            active,
            implementation,
            move |stop| run_after_ready(stop, ready, move |stop| self.run(stop)),
            quarantine,
            retire,
        )
    }
}

async fn run_after_ready<S, F>(
    stop: CancellationToken,
    ready: CancellationToken,
    start: S,
) -> Result<(), AgentdError>
where
    S: FnOnce(CancellationToken) -> F,
    F: Future<Output = Result<(), AgentdError>>,
{
    tokio::select! {
        biased;
        _ = stop.cancelled() => Ok(()),
        _ = ready.cancelled() => start(stop).await,
    }
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;

    use super::*;

    #[tokio::test]
    async fn ready_gate_executes_the_factory_only_after_release() {
        let stop = CancellationToken::new();
        let ready = CancellationToken::new();
        let calls = Cell::new(0);
        let work = run_after_ready(stop, ready.clone(), |_| async {
            calls.set(calls.get() + 1);
            Ok(())
        });
        tokio::pin!(work);
        tokio::select! {
            biased;
            _ = &mut work => panic!("factory ran before Agentd startup completed"),
            _ = tokio::task::yield_now() => {},
        }
        assert_eq!(calls.get(), 0);
        ready.cancel();
        work.await.expect("released service");
        assert_eq!(calls.get(), 1);
    }

    #[tokio::test]
    async fn failed_startup_drops_the_factory_without_execution() {
        let stop = CancellationToken::new();
        stop.cancel();
        let calls = Cell::new(0);
        run_after_ready(stop, CancellationToken::new(), |_| async {
            calls.set(calls.get() + 1);
            Ok(())
        })
        .await
        .expect("cancelled unopened service");
        assert_eq!(calls.get(), 0);
    }

    #[tokio::test]
    async fn stop_takes_precedence_when_release_and_shutdown_are_both_ready() {
        let stop = CancellationToken::new();
        let ready = CancellationToken::new();
        stop.cancel();
        ready.cancel();
        let calls = Cell::new(0);
        run_after_ready(stop, ready, |_| async {
            calls.set(calls.get() + 1);
            Ok(())
        })
        .await
        .expect("shutdown wins");
        assert_eq!(calls.get(), 0);
    }
}
