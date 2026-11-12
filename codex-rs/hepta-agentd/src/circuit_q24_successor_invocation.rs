//! No task is buffered while the successor is pending. Once installed, every
//! operation delegates to the actual durable source, under the original state
//! RunStart and generation checks retained by the ordinary task path.

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_learning_ledger::RunStartRecordV1;

use super::*;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::AgentdIdentity;
use crate::CircuitTaskLearningPendingV1;
use crate::CircuitTaskLearningReadinessV1;
use crate::CircuitTaskReceiptV1;
use crate::CircuitTaskRequestV1;

pub(super) struct PendingSuccessorInvocation {
    pub(super) slot: Arc<SuccessorSlot>,
}

impl AgentdCircuitTaskInvocationProviderV1 for PendingSuccessorInvocation {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, AgentdError> {
        let source: Arc<OriginalQ24SuccessorInvocationV1> =
            self.slot.actual_invocation().map_err(refused)?;
        let result = source.build(identity, record)?;
        self.slot.require_open().map_err(refused)?;
        Ok(result)
    }
    fn publish_result(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), AgentdError> {
        let source: Arc<OriginalQ24SuccessorInvocationV1> =
            self.slot.actual_invocation().map_err(refused)?;
        source.publish_result(identity, record, receipt)?;
        self.slot.require_open().map_err(refused)
    }
    fn observe_learning(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        let readiness = match self.slot.actual_invocation() {
            Ok(source) => {
                let source: Arc<OriginalQ24SuccessorInvocationV1> = source;
                source.observe_learning(identity, record, trace)
            }
            Err(_) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::OwnerUnavailable,
            ),
        };
        // An in-flight original observation may finish durably after close, but
        // its Ready result cannot be returned through the closed successor slot.
        if self.slot.require_open().is_err() {
            return CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::OwnerUnavailable,
            );
        }
        readiness
    }
}
fn refused(error: crate::CircuitTaskErrorV1) -> AgentdError {
    AgentdError::GenerationFenced(error.to_string())
}
