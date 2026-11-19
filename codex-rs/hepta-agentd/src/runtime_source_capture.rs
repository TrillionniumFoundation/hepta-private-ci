//! The source handoff requires an actual drain, successful control completion,
//! and release of the original State. A cancellation signal is not a receipt.

use std::future::Future;
use std::sync::Arc;
use std::sync::Weak;

use tokio::sync::oneshot;

use crate::AgentdError;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::control::source_capture::OriginalControlJoinV1;
use crate::control::source_capture::OriginalControlJoinedV1;

pub(crate) struct OriginalRuntimeDrainedV1 {
    state: Weak<AgentdState>,
    _control: OriginalControlJoinedV1,
}

pub(super) async fn run_until_original_source_drain(
    tasks: &mut RuntimeTasks,
    state: Arc<AgentdState>,
    shutdown: impl Future<Output = Result<(), AgentdError>>,
    control: OriginalControlJoinV1,
) -> Result<OriginalRuntimeDrainedV1, AgentdError> {
    let released_state = Arc::downgrade(&state);
    let (completed, mut observed) = oneshot::channel();
    tasks
        .run_until(async move {
            shutdown.await?;
            super::drain_runtime(state).await?;
            completed.send(()).map_err(|_| {
                AgentdError::Protocol("original runtime drain receiver was released".into())
            })
        })
        .await?;
    observed.try_recv().map_err(|_| {
        AgentdError::Protocol("original runtime returned without an actual drain".into())
    })?;
    let drained = OriginalRuntimeDrainedV1 {
        state: released_state,
        _control: control.require_original_control_join()?,
    };
    drained.require_released_state()?;
    Ok(drained)
}

impl OriginalRuntimeDrainedV1 {
    pub(crate) fn require_released_state(&self) -> Result<(), AgentdError> {
        if self.state.upgrade().is_some() {
            return Err(AgentdError::Protocol(
                "original runtime State is still retained".into(),
            ));
        }
        Ok(())
    }
}
