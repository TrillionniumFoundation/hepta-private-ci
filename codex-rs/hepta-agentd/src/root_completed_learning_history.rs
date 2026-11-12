//! Only actual same-session Root exchanges construct this completed history.
//! No non-Send Root context, original writer, or serialized grant is retained.

use codex_hepta_agent_protocol::OriginalQ24CompletedHistoryDataV1;

use super::*;
use crate::AgentdIdentity;
pub(crate) use crate::root_historical_task_read_protocol::CompletedHistoryModeV1;

pub(crate) struct OriginalCompletedLearningHistoryV1 {
    client: Arc<RootHistoricalTaskReadClientV1>,
    data_cut: String,
    data: OriginalQ24CompletedHistoryDataV1,
}

impl RootHistoricalTaskReadClientV1 {
    /// First acceptance is an explicit one-shot request on the existing lane.
    /// An uncertain response never permits another attempt by this client.
    pub(crate) fn accept_original_completed_learning(
        self: &Arc<Self>,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
    ) -> Result<CompletedLearningAcceptanceResponseV1, AgentdError> {
        let mut fence = FenceReadOnDrop {
            client: self,
            armed: true,
        };
        RootHistoricalTaskReadClientV1::require_same_original_session(self, session)?;
        self.require_completed_identity(identity)?;
        if self.completed_attempted.swap(true, Ordering::AcqRel) {
            return Err(AgentdError::Io(refused()));
        }
        let result = (|| {
            let response = match RootHistoricalTaskReadClientV1::exchange(
                self,
                HistoricalReadOperationV1::AcceptCompletedLearning,
            )? {
                Reply::Acceptance(response) => response,
                Reply::Task(_)
                | Reply::LearningTrust(_)
                | Reply::PostAFrozenLearning(_)
                | Reply::History(_) => return Err(refused()),
            };
            if response.initial != self.initial.head_digest.to_string() {
                return Err(refused());
            }
            Ok(response)
        })();
        let identity_after = self.require_completed_identity(identity);
        let session_after =
            RootHistoricalTaskReadClientV1::require_same_original_session(self, session);
        identity_after?;
        session_after?;
        let response = result?;
        fence.armed = false;
        Ok(response)
    }

    pub(crate) fn read_original_completed_history(
        self: &Arc<Self>,
        session: &AgentdRootAuthoritySession,
        identity: &AgentdIdentity,
        mode: CompletedHistoryModeV1,
    ) -> Result<OriginalCompletedLearningHistoryV1, AgentdError> {
        let mut fence = FenceReadOnDrop {
            client: self,
            armed: true,
        };
        RootHistoricalTaskReadClientV1::require_same_original_session(self, session)?;
        self.require_completed_identity(identity)?;
        let result = (|| {
            let captured = match mode {
                CompletedHistoryModeV1::CaptureRetired => {
                    if self.completed_attempted.swap(true, Ordering::AcqRel) {
                        return Err(AgentdError::Io(refused()));
                    }
                    Some(self.read_completed_response(
                        identity,
                        HistoricalReadOperationV1::CaptureCompletedHistory,
                    )?)
                }
                CompletedHistoryModeV1::ReadFinalized => None,
            };
            let response = self.read_completed_response(
                identity,
                HistoricalReadOperationV1::ReadCompletedHistory,
            )?;
            if let Some(captured) = captured
                && (captured.data_cut != response.data_cut
                    || captured.completion != response.completion)
            {
                return Err(AgentdError::Io(refused()));
            }
            Ok(response)
        })();
        let identity_after = self.require_completed_identity(identity);
        let session_after =
            RootHistoricalTaskReadClientV1::require_same_original_session(self, session);
        identity_after?;
        session_after?;
        let response = result?;
        fence.armed = false;
        Ok(OriginalCompletedLearningHistoryV1 {
            client: Arc::clone(self),
            data_cut: response.data_cut,
            data: response.completion,
        })
    }

    fn require_completed_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        RootHistoricalTaskReadConnectionV1::require_original_session(&self.connection)?;
        let (_, original) = RootHistoricalTaskReadConnectionV1::original_binding(&self.connection);
        if self.fenced.load(Ordering::Acquire) || original != identity {
            return Err(AgentdError::Io(refused()));
        }
        RootHistoricalTaskReadConnectionV1::require_original_session(&self.connection)
    }

    fn read_completed_response(
        &self,
        identity: &AgentdIdentity,
        operation: HistoricalReadOperationV1,
    ) -> Result<CompletedLearningHistoryResponseV1, AgentdError> {
        let mut fence = FenceReadOnDrop {
            client: self,
            armed: true,
        };
        self.require_completed_identity(identity)?;
        let result = (|| {
            let response = match RootHistoricalTaskReadClientV1::exchange(self, operation)? {
                Reply::History(response) => response,
                Reply::Task(_)
                | Reply::LearningTrust(_)
                | Reply::PostAFrozenLearning(_)
                | Reply::Acceptance(_) => return Err(AgentdError::Io(refused())),
            };
            if response.completion.initial != self.initial.head_digest.to_string()
                || response.completion.identity_digest
                    != crate::neuron_generation_process_identity_digest_v1(identity)?.to_string()
            {
                return Err(AgentdError::Io(refused()));
            }
            Ok(response)
        })();
        let after = self.require_completed_identity(identity);
        after?;
        let response = result?;
        fence.armed = false;
        Ok(response)
    }
}

impl OriginalCompletedLearningHistoryV1 {
    pub(crate) fn data(&self) -> &OriginalQ24CompletedHistoryDataV1 {
        &self.data
    }

    pub(crate) fn require_original_current(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        let mut fence = FenceReadOnDrop {
            client: &self.client,
            armed: true,
        };
        let observed = self
            .client
            .read_completed_response(identity, HistoricalReadOperationV1::ReadCompletedHistory)?;
        if observed.data_cut != self.data_cut || observed.completion != self.data {
            return Err(AgentdError::Io(refused()));
        }
        self.client.require_completed_identity(identity)?;
        fence.armed = false;
        Ok(())
    }
}
