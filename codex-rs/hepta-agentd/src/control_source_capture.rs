//! A receipt for the actual control supervisor's completed owned connections.
//! Cancellation, an aborted supervisor or a failed accepted connection cannot
//! create this receipt. It carries no publication or learning authority.

use tokio::sync::oneshot;

use crate::AgentdError;

pub(super) struct OriginalControlCompletionV1(oneshot::Sender<()>);
pub(crate) struct OriginalControlJoinV1(oneshot::Receiver<()>);
pub(crate) struct OriginalControlJoinedV1 {
    _private: (),
}

pub(super) fn original_control_join_v1() -> (
    OriginalControlCompletionV1,
    OriginalControlJoinV1,
) {
    let (sender, receiver) = oneshot::channel();
    (
        OriginalControlCompletionV1(sender),
        OriginalControlJoinV1(receiver),
    )
}

impl OriginalControlCompletionV1 {
    pub(super) fn complete(self) -> Result<(), AgentdError> {
        self.0.send(()).map_err(|_| {
            AgentdError::Protocol("original control join receiver was released".into())
        })
    }
}

impl OriginalControlJoinV1 {
    pub(crate) fn require_original_control_join(
        mut self,
    ) -> Result<OriginalControlJoinedV1, AgentdError> {
        self.0.try_recv().map_err(|_| {
            AgentdError::Protocol("original control connections did not complete".into())
        })?;
        Ok(OriginalControlJoinedV1 { _private: () })
    }
}
