//! Complete the selected deployment only from its actual joined owners.
//! Root wire data, generic Runtime Ok, EOF and empty counts cannot construct
//! this private result. The daemon's own OS exit remains externally observed.

use std::io::Write;
use std::sync::Arc;

use super::super::owner::OriginalPhaseRunControl;
use super::super::refused;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::circuit_task::OriginalCircuitOwnerCustody;
use crate::production_launcher::OriginalRuntimeRootPurposesRetired;
use crate::production_launcher::OriginalSameActorRuntimeStopped;
use crate::root_authority_session::OriginalRootSessionCustodySlot;
use crate::root_authority_session::OriginalRootSessionFullyRetired;
use crate::root_authority_session::OriginalRootSessionPauseWaiter;
use crate::root_authority_session::OriginalRootSessionPaused;
use crate::root_production_inputs::same_actor_phase::OriginalSameActorRootContext;
use crate::same_actor_q24_deployment::OriginalDeploymentCoordinatorOwner;
use crate::same_actor_q24_deployment::OriginalDeploymentRetained;
use crate::same_actor_q24_deployment::OriginalRootProcessExited;
use crate::same_actor_q24_deployment::OriginalRootRetirementIntent;
use crate::same_actor_q24_deployment::OriginalRootWorkersJoined;
use crate::same_actor_q24_phase_gate::CloseSameActorPhaseOnDrop;
use crate::same_actor_q24_phase_gate::SameActorPhaseGate;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningJoined;

/// Only this module's actual finish function constructs the value. It holds
/// cleanup observations and the original pidfd, but no Session, writer File,
/// Context, business owner, live purpose or replaceable result callback.
pub(in super::super) struct OriginalPhaseCompletion {
    identity: AgentdIdentity,
    gate: Arc<SameActorPhaseGate>,
    exited: OriginalRootProcessExited,
    session: OriginalRootSessionFullyRetired,
    mcp: Arc<codex_app_server::OriginalMcpRuntimeShutdownObservation>,
    app_server: codex_app_server::OriginalAppServerJoined,
}

impl OriginalPhaseCompletion {
    pub(in super::super) fn require_original_complete(
        &self,
        control: &OriginalPhaseRunControl,
    ) -> Result<(), AgentdError> {
        OriginalRootProcessExited::require_original_cleanup_origin(
            &self.exited,
            &self.identity,
            &self.gate,
        )?;
        OriginalRootSessionFullyRetired::require_original_cleanup_origin(
            &self.session,
            &self.identity,
            &self.gate,
            &self.exited,
        )?;
        control.require_original_completed_owners(
            &self.identity,
            &self.gate,
            &self.mcp,
            &self.app_server,
        )
    }
}

/// Own every non-Sync bundle across waits. Synchronous cap checks borrow the
/// actual objects only until their concrete owned waiter has been obtained.
pub(super) async fn finish_original_phase(
    stopped: OriginalSameActorRuntimeStopped,
    context: Arc<OriginalSameActorRootContext>,
    control: Arc<OriginalPhaseRunControl>,
    coordinator: Option<OriginalDeploymentCoordinatorOwner>,
) -> Result<OriginalPhaseCompletion, AgentdError> {
    let _closing = CloseSameActorPhaseOnDrop::new(context.gate());
    let identity = context.identity().clone();
    let gate = Arc::clone(context.gate());
    let circuit = control.original_circuit_custody(&context)?;
    let (stopped, learning, natural) =
        OriginalCircuitOwnerCustody::take_original_natural_join(&circuit, stopped).await?;
    let mut coordinator = coordinator.ok_or_else(|| {
        refused("normal retirement requires the actual joined deployment coordinator")
    })?;
    let coordinator_retained = OriginalDeploymentCoordinatorOwner::take_original_after_c_join(
        &mut coordinator,
        &stopped,
        &learning,
        &natural,
    )?;
    // The real thread was joined and its result transferred above. Remove
    // the now-empty joining owner, including its extra Context reference.
    drop(coordinator);

    let pause = OriginalRootSessionCustodySlot::request_original_normal_pause(
        control.session_slot(),
        &identity,
        &gate,
        OriginalSameActorLearningJoined::original_c_joined(&learning),
        &natural,
    )?;
    let paused = OriginalRootSessionPauseWaiter::join_original_paused(pause).await?;
    let (intent, coordinator_retained) =
        OriginalDeploymentRetained::authorize_original_root_retirement(
            coordinator_retained,
            &stopped,
            &learning,
            &natural,
            &paused,
        )?;

    // The actual seq1 postchecks have completed. Each method consumes its
    // own real owner, closes only its proven purpose, and retains all armed
    // guards, Files and Session references through the second acknowledgement.
    let runtime = OriginalSameActorRuntimeStopped::retire_original_root_purposes(stopped, &intent)?;
    let learning =
        OriginalSameActorLearningJoined::retire_original_root_purposes(learning, &intent)?;
    let session = OriginalRootSessionPaused::retire_original_observation_purpose(paused, &intent)?;
    let joined = OriginalRootRetirementIntent::observe_original_root_workers_joined(
        intent,
        &runtime,
        &learning,
        &session,
        &coordinator_retained,
    )?;
    // This consumes the same ACK2, performs its complete original postchecks,
    // shuts the actual final socket and aliases, then observes the ORIGINAL
    // held Root pidfd. It does not wait for Root before sending its EOF.
    let exited = OriginalRootWorkersJoined::wait_original_root_process_exit(joined).await?;

    // Root's kernel exit is now proven. Fault guards may close the already
    // retired Gate; all checks below are cleanup-only, never fresh Current.
    let mut failure = None;
    if let Err(error) =
        OriginalSameActorRootContext::finish_original_deadline_watch(&context, &exited)
    {
        preserve_original_cleanup_failure(&mut failure, error);
    }
    drop(learning);
    drop(natural);
    drop(coordinator_retained);
    if let Err(error) =
        control.release_original_circuit_after_root_exit(&circuit, &exited, &identity, &gate)
    {
        preserve_original_cleanup_failure(&mut failure, error);
    }
    drop(circuit);
    if let Err(error) =
        OriginalRuntimeRootPurposesRetired::release_original_after_root_exit(runtime, &exited).await
    {
        preserve_original_cleanup_failure(&mut failure, error);
    }
    let components = match control
        .finish_original_component_owners_after_root_exit(&exited, &identity, &gate)
        .await
    {
        Ok(observed) => Some(observed),
        Err(error) => {
            preserve_original_cleanup_failure(&mut failure, error);
            None
        }
    };
    // The closed C/Learning owners, actual coordinator, Runtime attachment,
    // Device/MCP owner and explicit deadline watcher have now been released.
    // This last Context Arc must go BEFORE the Session's final-field/File cut.
    drop(context);
    let session =
        match OriginalRootSessionCustodySlot::finish_original_retired_session_after_root_exit(
            control.session_slot(),
            session,
            &exited,
        ) {
            Ok(retired) => Some(retired),
            Err(error) => {
                preserve_original_cleanup_failure(&mut failure, error);
                None
            }
        };
    if let Some(error) = failure {
        return Err(error);
    }
    let (mcp, app_server) =
        components.ok_or_else(|| refused("actual component owner joins are missing"))?;
    let session = session.ok_or_else(|| refused("actual Session final retirement is missing"))?;
    let complete = OriginalPhaseCompletion {
        identity,
        gate,
        exited,
        session,
        mcp,
        app_server,
    };
    OriginalPhaseCompletion::require_original_complete(&complete, &control)?;
    Ok(complete)
}

fn preserve_original_cleanup_failure(first: &mut Option<AgentdError>, error: AgentdError) {
    if first.is_none() {
        *first = Some(error);
    } else {
        let _ = writeln!(
            std::io::stderr().lock(),
            "hepta-agentd level=error error={error}: additional original terminal cleanup failure",
        );
    }
}
