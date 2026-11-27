//! Optional, typed composition into the actual Agentd startup and task host.
//! Default run() remains unchanged. A trusted Supervisor must supply already
//! verified model/qualification objects and current owner handles; request JSON
//! cannot deserialize this bootstrap or manufacture its independent authority.

use std::future::Future;
use std::time::Duration;

use codex_arg0::Arg0DispatchPaths;
use codex_hepta_control_plane::ActiveRuntimeModuleV1;
use codex_hepta_control_plane::RuntimeModuleAbiV1;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::SelectedMemoryServiceV1;

const MEMORY_STARTUP_DEADLINE: Duration = Duration::from_secs(10);
type OwnerCallback = Box<dyn FnOnce() -> Result<(), AgentdError> + Send>;

pub(super) struct MemoryRuntimeBootstrapV1 {
    service: SelectedMemoryServiceV1,
    active: ActiveRuntimeModuleV1,
    implementation: RuntimeModuleAbiV1,
    quarantine: OwnerCallback,
    retire: OwnerCallback,
}

// Deliberately NOT a child of the shutdown token. Cancellation propagation may
// visit readiness before the service's stop child; biased select alone cannot
// close that race. Only a successful startup may explicitly release this gate.
pub(super) fn startup_readiness_gate_v1() -> CancellationToken {
    CancellationToken::new()
}

impl SelectedMemoryServiceV1 {
    /// Start this explicitly selected service inside the SAME lifecycle host
    /// as control, App Server and generation monitoring. Nothing is enabled by
    /// ordinary Agentd startup. The caller must have completed the independent
    /// selection/rollback, citation and Supervisor handoff protocols first.
    /// A failed startup never falls back to an unqualified memory service.
    pub async fn run_agentd<Q, R>(
        self,
        config: AgentdConfig,
        arg0_paths: Arg0DispatchPaths,
        active: ActiveRuntimeModuleV1,
        implementation: RuntimeModuleAbiV1,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        let bootstrap = MemoryRuntimeBootstrapV1 {
            service: self,
            active,
            implementation,
            quarantine: Box::new(quarantine),
            retire: Box::new(retire),
        };
        super::run_composed(config, arg0_paths, Some(bootstrap)).await
    }
}

impl MemoryRuntimeBootstrapV1 {
    pub(super) async fn preflight(&mut self, state: &AgentdState) -> Result<(), AgentdError> {
        self.service
            .validate_startup_abi_v1(&self.active, &self.implementation)?;
        fenced_startup(
            || state.refresh_generation(),
            self.service
                .revalidate_agentd_startup_v1(&state.identity().agent_id),
            MEMORY_STARTUP_DEADLINE,
        )
        .await
    }

    pub(super) fn attach(
        self,
        tasks: &mut RuntimeTasks,
        ready: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.service.spawn_after_agentd_startup_v1(
            tasks,
            &self.active,
            &self.implementation,
            ready,
            self.quarantine,
            self.retire,
        )
    }
}

async fn fenced_startup<F, V>(
    mut fence: F,
    validate: V,
    deadline: Duration,
) -> Result<(), AgentdError>
where
    F: FnMut() -> Result<(), AgentdError>,
    V: Future<Output = Result<(), AgentdError>>,
{
    fence()?;
    timeout(deadline, validate)
        .await
        .map_err(|_| AgentdError::Protocol("memory startup owner check timed out".to_string()))??;
    fence()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;
    use std::cell::RefCell;

    use super::*;

    #[test]
    fn failed_parent_startup_cannot_release_the_readiness_gate() {
        let shutdown = CancellationToken::new();
        let service_stop = shutdown.child_token();
        let ready = startup_readiness_gate_v1();
        shutdown.cancel();
        assert!(service_stop.is_cancelled());
        assert!(!ready.is_cancelled());
        ready.cancel();
        assert!(ready.is_cancelled());
    }

    #[tokio::test]
    async fn initial_fence_rejects_without_polling_owner_validation() {
        let polled = Cell::new(false);
        let result = fenced_startup(
            || Err(rejected()),
            async {
                polled.set(true);
                Ok(())
            },
            MEMORY_STARTUP_DEADLINE,
        )
        .await;
        assert!(result.is_err());
        assert!(!polled.get());
    }

    fn rejected() -> AgentdError {
        AgentdError::GenerationFenced("test generation changed".to_string())
    }

    #[tokio::test]
    async fn owner_denial_never_becomes_startup_success() {
        let calls = Cell::new(0);
        let result = fenced_startup(
            || {
                calls.set(calls.get() + 1);
                Ok(())
            },
            async { Err(AgentdError::Protocol("owner unavailable".to_string())) },
            MEMORY_STARTUP_DEADLINE,
        )
        .await;
        assert!(result.is_err());
        assert_eq!(calls.get(), 1);
    }

    #[tokio::test]
    async fn generation_change_during_validation_rejects_before_attachment() {
        let calls = Cell::new(0);
        let result = fenced_startup(
            || {
                calls.set(calls.get() + 1);
                if calls.get() == 1 {
                    Ok(())
                } else {
                    Err(rejected())
                }
            },
            async { Ok(()) },
            MEMORY_STARTUP_DEADLINE,
        )
        .await;
        assert!(result.is_err());
        assert_eq!(calls.get(), 2);
    }

    #[tokio::test]
    async fn successful_validation_is_bracketed_by_both_generation_checks() {
        let events = RefCell::new(Vec::new());
        fenced_startup(
            || {
                events.borrow_mut().push("fence");
                Ok(())
            },
            async {
                events.borrow_mut().push("owner");
                Ok(())
            },
            MEMORY_STARTUP_DEADLINE,
        )
        .await
        .expect("ordered startup checks");
        assert_eq!(*events.borrow(), ["fence", "owner", "fence"]);
    }

    #[tokio::test]
    async fn unavailable_owner_times_out_without_a_post_validation_acknowledgement() {
        let calls = Cell::new(0);
        let result = fenced_startup(
            || {
                calls.set(calls.get() + 1);
                Ok(())
            },
            std::future::pending(),
            Duration::from_millis(1),
        )
        .await;
        assert!(matches!(result, Err(AgentdError::Protocol(_))));
        assert_eq!(calls.get(), 1);
    }
}
