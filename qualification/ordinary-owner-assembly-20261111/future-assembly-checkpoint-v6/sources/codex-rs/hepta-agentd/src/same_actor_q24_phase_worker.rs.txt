//! The actual required worker owns both the A loop and the later concrete
//! Learning/C worker. Host commands supply original material, never tasks or
//! Ready. Faults close the one phase. A normal return follows actual terminal
//! custody and the original Runtime shutdown; no failed phase is rearmed.

use std::os::unix::net::UnixDatagram;
use std::sync::Arc;
use std::sync::Weak;

use codex_hepta_automation::AutomationStore;
use tokio_util::sync::CancellationToken;

use super::OriginalSameActorAOwners;
use super::OriginalSameActorPhaseHostV1;
use super::phase_refused;
use crate::AgentdError;
use crate::AgentdGenerationUpdateAuthoritiesV1;
use crate::AgentdState;
use crate::circuit_task::OriginalCircuitOwnerCustody;
use crate::circuit_task::SameActorTaskRoute;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;

#[path = "same_actor_q24_phase_a.rs"]
mod original_a;
#[path = "same_actor_q24_phase_c.rs"]
mod original_c;

/// Constructed only by the real Initial publication/A installer. The close
/// guard exists before the owner closure or its future can ever be polled.
pub(crate) struct OriginalSameActorTaskWorker {
    context: Arc<OriginalSameActorRootContext>,
    route: Arc<SameActorTaskRoute>,
    owners: OriginalSameActorAOwners,
    authorities: AgentdGenerationUpdateAuthoritiesV1,
    scoped: UnixDatagram,
    host: OriginalSameActorPhaseHostV1,
    outer_custody: Option<Weak<OriginalCircuitOwnerCustody>>,
    _closing: CloseSameActorPhaseOnDrop,
}

struct OriginalPhaseExecution {
    context: Arc<OriginalSameActorRootContext>,
    route: Arc<SameActorTaskRoute>,
    store: AutomationStore,
    state: Arc<AgentdState>,
    cancellation: CancellationToken,
}

impl OriginalSameActorTaskWorker {
    pub(super) fn new(
        context: Arc<OriginalSameActorRootContext>,
        route: Arc<SameActorTaskRoute>,
        owners: OriginalSameActorAOwners,
        authorities: AgentdGenerationUpdateAuthoritiesV1,
        scoped: UnixDatagram,
        host: OriginalSameActorPhaseHostV1,
    ) -> Self {
        let closing = CloseSameActorPhaseOnDrop::new(context.gate());
        Self {
            context,
            route,
            owners,
            authorities,
            scoped,
            host,
            outer_custody: None,
            _closing: closing,
        }
    }

    pub(crate) fn with_original_outer_custody(
        mut self,
        custody: &Arc<OriginalCircuitOwnerCustody>,
    ) -> Result<Self, AgentdError> {
        OriginalCircuitOwnerCustody::require_original_origin(
            custody,
            self.context.identity(),
            self.context.gate(),
        )?;
        if self.outer_custody.is_some() {
            return Err(phase_refused("original Circuit worker custody was already bound"));
        }
        self.outer_custody = Some(Arc::downgrade(custody));
        Ok(self)
    }

    pub(crate) async fn run(
        self,
        store: AutomationStore,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        let Self {
            context,
            route,
            owners,
            authorities,
            scoped,
            mut host,
            outer_custody,
            _closing: mut closing,
        } = self;
        let execution = OriginalPhaseExecution {
            context,
            route,
            store,
            state,
            cancellation,
        };
        let custody = outer_custody.and_then(|original| original.upgrade()).ok_or_else(|| {
            phase_refused("original Circuit worker lost its external custody")
        })?;
        OriginalCircuitOwnerCustody::require_original_origin(
            &custody,
            execution.context.identity(),
            execution.context.gate(),
        )?;
        execution.require_original_execution()?;
        let original = execution.run_original_a(owners, &mut host).await?;
        execution.require_original_execution()?;
        let terminal = execution
            .run_original_scoped(original, authorities, scoped, &mut host)
            .await?;
        // Move the actual owners into external custody before notifying the
        // original Runtime. No await separates the move and notification.
        OriginalCircuitOwnerCustody::retain_original_normal_terminal(&custody, terminal)?;
        // A required worker does not return early merely because C finished.
        // The unchanged Runtime must first enter its real shutdown path.
        OriginalCircuitOwnerCustody::wait_original_runtime_shutdown(
            &custody,
            &execution.cancellation,
        )
        .await?;
        closing.disarm();
        Ok(())
    }
}

impl OriginalPhaseExecution {
    fn require_original_execution(&self) -> Result<(), AgentdError> {
        OriginalSameActorRootContext::require_current(self.context.as_ref())?;
        self.route.require_identity(self.context.identity())?;
        if self.cancellation.is_cancelled()
            || self.state.identity() != self.context.identity()
            || self.store.owner_agent_id() != &self.context.identity().agent_id
            || self.store.path().parent() != Some(self.context.identity().layout.automation_root())
        {
            self.close_original_execution();
            return Err(phase_refused(
                "original phase worker differs from its actual daemon owner",
            ));
        }
        Ok(())
    }

    fn close_original_execution(&self) {
        self.context.gate().close();
        self.route.close();
        self.cancellation.cancel();
    }
}
