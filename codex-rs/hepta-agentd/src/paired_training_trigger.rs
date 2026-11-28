//! A one-use hint from the retained original Core connection. Notifications
//! cannot prove persistence, human consent or permission to read material.
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::UserInput;
use codex_hepta_types::Digest32;
use tokio::sync::oneshot;

use crate::AgentdError;
use crate::PairedPreparationRequest;
use crate::PairedTrainingPlanV1;
use crate::notes_literal_adapter::invalid;

pub(super) struct OriginalTrainingTrigger {
    plan: PairedTrainingPlanV1,
    thread_id: String,
    consent_text: String,
    request: Option<oneshot::Sender<PairedPreparationRequest>>,
}

impl OriginalTrainingTrigger {
    pub(super) fn new(
        plan: PairedTrainingPlanV1,
        thread_id: String,
    ) -> Result<(Self, oneshot::Receiver<PairedPreparationRequest>), AgentdError> {
        let consent_text = plan.consent_text()?;
        let (request, receiver) = oneshot::channel();
        Ok((
            Self {
                plan,
                thread_id,
                consent_text,
                request: Some(request),
            },
            receiver,
        ))
    }

    /// Only the original owner calls this for a completed Core user item.
    /// The separate consumer must still use the original read_training lane,
    /// including its Core ReconcileOnly/Persisted, AuthBus, Root and journal checks.
    pub(super) fn observe_completed(
        &mut self,
        thread_id: &str,
        turn_id: &str,
        item: &ThreadItem,
    ) -> Result<(), AgentdError> {
        if self.request.is_none() || thread_id != self.thread_id {
            return Ok(());
        }
        let ThreadItem::UserMessage { content, .. } = item else {
            return Ok(());
        };
        if !matches!(content.as_slice(), [UserInput::Text { text, text_elements }]
            if text == &self.consent_text && text_elements.is_empty())
        {
            return Ok(());
        }
        let Ok(client_id) = super::human::original_client_id(item) else {
            return Ok(());
        };
        let delivery: Digest32 = client_id
            .trim_start_matches("hepta.authbus:")
            .parse()
            .map_err(|_| invalid("original paired delivery reference changed"))?;
        let request = self
            .plan
            .request_for_original(turn_id.to_owned(), delivery)?;
        self.request
            .take()
            .ok_or_else(|| invalid("original paired trigger already consumed"))?
            .send(request)
            .map_err(|_| invalid("original paired consumer ended before its hint"))
    }
}

#[cfg(test)]
#[path = "paired_training_trigger_tests.rs"]
mod tests;
