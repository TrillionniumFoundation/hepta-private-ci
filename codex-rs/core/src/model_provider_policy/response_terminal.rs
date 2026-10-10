use codex_extension_api::ModelProviderPolicyError;
use codex_extension_api::ModelProviderTerminal;
use codex_protocol::models::ResponseItem;
use serde::Serialize;

use super::attempt_owner::ProviderAttemptOwner;
use super::binding::bytes_sha256;
use super::binding::canonical_sha256;

pub(crate) struct ProviderResponseTerminal {
    state: TerminalState,
}

impl ProviderResponseTerminal {
    pub(crate) fn new(owner: Option<ProviderAttemptOwner>) -> Self {
        Self {
            state: match owner {
                Some(owner) => TerminalState::Pending(owner),
                None => TerminalState::Inactive,
            },
        }
    }

    pub(crate) fn is_pending(&self) -> bool {
        matches!(self.state, TerminalState::Pending(_))
    }

    pub(crate) async fn finish_completed<T: Serialize>(
        &mut self,
        response_id: &str,
        response_items: &[ResponseItem],
        token_usage: &T,
        end_turn: Option<bool>,
    ) -> Result<bool, ModelProviderPolicyError> {
        if !self.is_pending() {
            return self.inactive_or_finished();
        }
        self.finish(ModelProviderTerminal::Completed {
            response_id_sha256: bytes_sha256(response_id.as_bytes())?,
            response_items_sha256: canonical_sha256(&response_items)?,
            token_usage_sha256: canonical_sha256(token_usage)?,
            end_turn,
        })
        .await
    }

    pub(crate) async fn finish_completed_unary(
        &mut self,
        response_items: &[ResponseItem],
    ) -> Result<bool, ModelProviderPolicyError> {
        if !self.is_pending() {
            return self.inactive_or_finished();
        }
        self.finish(ModelProviderTerminal::CompletedUnary {
            response_items_sha256: canonical_sha256(&response_items)?,
        })
        .await
    }

    pub(crate) async fn finish_rejected(
        &mut self,
        reason_code: &'static str,
    ) -> Result<bool, ModelProviderPolicyError> {
        self.finish(ModelProviderTerminal::Rejected {
            reason_code: reason_code.to_string(),
        })
        .await
    }

    pub(crate) async fn finish_not_dispatched(
        &mut self,
        reason_code: &'static str,
    ) -> Result<bool, ModelProviderPolicyError> {
        self.finish(ModelProviderTerminal::NotDispatched {
            reason_code: reason_code.to_string(),
        })
        .await
    }

    pub(crate) async fn finish_indeterminate(
        &mut self,
        reason_code: &'static str,
        response_items: &[ResponseItem],
    ) -> Result<bool, ModelProviderPolicyError> {
        if !self.is_pending() {
            return self.inactive_or_finished();
        }
        let partial_response_sha256 = if response_items.is_empty() {
            None
        } else {
            Some(canonical_sha256(&response_items)?)
        };
        self.finish(ModelProviderTerminal::Indeterminate {
            reason_code: reason_code.to_string(),
            partial_response_sha256,
        })
        .await
    }

    async fn finish(
        &mut self,
        terminal: ModelProviderTerminal,
    ) -> Result<bool, ModelProviderPolicyError> {
        let previous = std::mem::replace(&mut self.state, TerminalState::CommitFailed);
        match previous {
            TerminalState::Inactive => {
                self.state = TerminalState::Inactive;
                Ok(false)
            }
            TerminalState::Pending(owner) => match owner.finish(terminal).await {
                Ok(()) => {
                    self.state = TerminalState::Committed;
                    Ok(true)
                }
                Err(error) => Err(error),
            },
            TerminalState::Committed => {
                self.state = TerminalState::Committed;
                Err(already_finished_error())
            }
            TerminalState::CommitFailed => Err(commit_failed_error()),
        }
    }

    fn inactive_or_finished(&self) -> Result<bool, ModelProviderPolicyError> {
        match self.state {
            TerminalState::Inactive => Ok(false),
            TerminalState::Pending(_) => unreachable!("pending state was checked by caller"),
            TerminalState::Committed => Err(already_finished_error()),
            TerminalState::CommitFailed => Err(commit_failed_error()),
        }
    }
}

enum TerminalState {
    Inactive,
    Pending(ProviderAttemptOwner),
    Committed,
    CommitFailed,
}

fn already_finished_error() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_policy_terminal_already_committed",
        "provider attempt terminal was already committed",
    )
}

fn commit_failed_error() -> ModelProviderPolicyError {
    ModelProviderPolicyError::new(
        "model_provider_policy_terminal_commit_failed",
        "provider attempt terminal commit already failed",
    )
}

#[cfg(test)]
#[path = "response_terminal_tests.rs"]
mod tests;
