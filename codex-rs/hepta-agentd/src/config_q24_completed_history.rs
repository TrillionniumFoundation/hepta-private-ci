//! Transfer only the actual completed-history capability to daemon runtime.
//! Neither decoded DATA nor a caller-supplied terminal snapshot can enter it.

use std::sync::Arc;

use super::AgentdConfig;
use crate::AgentdError;
use crate::root_completed_learning_history::OriginalCompletedLearningHistoryV1;

impl AgentdConfig {
    pub(crate) fn with_original_q24_completed_history(
        mut self,
        completed: Arc<OriginalCompletedLearningHistoryV1>,
    ) -> Result<Self, AgentdError> {
        if self.original_q24_completed_history.is_some() {
            return Err(AgentdError::Invalid(
                "original completed history already installed".into(),
            ));
        }
        OriginalCompletedLearningHistoryV1::require_original_current(&completed, self.identity())?;
        let result = completed
            .data()
            .validate_data()
            .map_err(AgentdError::Protocol);
        OriginalCompletedLearningHistoryV1::require_original_current(&completed, self.identity())?;
        result?;
        self.original_q24_completed_history = Some(completed);
        Ok(self)
    }

    pub(crate) fn take_original_q24_completed_history(
        &mut self,
    ) -> Option<Arc<OriginalCompletedLearningHistoryV1>> {
        self.original_q24_completed_history.take()
    }
}
