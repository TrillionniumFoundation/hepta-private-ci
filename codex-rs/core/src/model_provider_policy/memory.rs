use std::sync::Arc;

use codex_extension_api::ModelProviderRequestKind;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnInputRequest;
use codex_protocol::turn_input::TurnInputSubmission;

use crate::CodexThread;
use crate::UserMessageAdmission;
use crate::model_provider_policy::ModelProviderPolicyContext;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::user_message_admission::AdmittedUserMessage;
use crate::user_message_admission::PendingUserMessageAdmissionState;

/// Opaque capability for provider-governed detached Memory requests.
///
/// The handle retains the exact session and admitted parent turn. Callers
/// cannot substitute extension stores, admitted turn identity, or request kind.
pub struct MemoryModelProviderPolicyHandle {
    session: Arc<Session>,
    parent_turn: Arc<TurnContext>,
}

/// Start-or-Steer result that only grants detached Memory authority for a
/// newly started turn.
pub enum MemoryTurnInputSubmission {
    Started {
        turn_id: String,
        provider_policy: MemoryModelProviderPolicyHandle,
    },
    Steered {
        turn_id: String,
    },
    NotSubmitted {
        reason: NotSubmittedReason,
    },
}

impl MemoryModelProviderPolicyHandle {
    fn new(session: Arc<Session>, parent_turn: Arc<TurnContext>) -> Self {
        Self {
            session,
            parent_turn,
        }
    }

    pub(crate) fn context(&self) -> ModelProviderPolicyContext<'_> {
        ModelProviderPolicyContext {
            registry: self.session.services.extensions.as_ref(),
            session_store: &self.session.services.session_extension_data,
            thread_store: &self.session.services.thread_extension_data,
            turn_store: self.parent_turn.extension_data.as_ref(),
            thread_id: self.session.thread_id().to_string(),
            turn_id: self.parent_turn.sub_id.clone(),
            request_kind: ModelProviderRequestKind::Memory,
            ephemeral_input_cwd: None,
        }
    }

    pub(crate) fn thread_id(&self) -> codex_protocol::ThreadId {
        self.session.thread_id()
    }

    pub(crate) fn session_id(&self) -> codex_protocol::SessionId {
        self.session.session_id()
    }
}

impl CodexThread {
    /// Submits ordered turn input and captures an exact provider-policy
    /// capability only when this submission starts a new turn.
    ///
    /// Steered input cannot start Memory again for the active turn, and idle
    /// queue or recovery operations use separate APIs that never call this
    /// method.
    pub async fn start_or_steer_turn_and_capture_memory_policy(
        &self,
        request: TurnInputRequest,
    ) -> CodexResult<MemoryTurnInputSubmission> {
        let (submission, admitted) = self
            .submit_turn_input_and_wait_for_exact_admission(
                request,
                PendingUserMessageAdmissionState::Immediate,
            )
            .await
            .map_err(codex_protocol::error::CodexErr::from)?;
        match (submission, admitted) {
            (TurnInputSubmission::Started { turn_id }, Some(admitted)) => {
                let (admission, parent_turn) = AdmittedUserMessage::into_parts(admitted);
                if !matches!(
                    admission,
                    UserMessageAdmission::Started {
                        turn_id: ref admitted_turn_id
                    } if admitted_turn_id == &turn_id
                ) {
                    return Err(codex_protocol::error::CodexErr::InvalidRequest(
                        "started turn did not retain its exact Hepta admission".to_string(),
                    ));
                }
                let provider_policy =
                    MemoryModelProviderPolicyHandle::new(Arc::clone(&self.session), parent_turn);
                Ok(MemoryTurnInputSubmission::Started {
                    turn_id,
                    provider_policy,
                })
            }
            (TurnInputSubmission::Steered { turn_id }, Some(admitted)) => {
                let (admission, parent_turn) = AdmittedUserMessage::into_parts(admitted);
                drop(parent_turn);
                if !matches!(
                    admission,
                    UserMessageAdmission::Steered {
                        turn_id: ref admitted_turn_id
                    } if admitted_turn_id == &turn_id
                ) {
                    return Err(codex_protocol::error::CodexErr::InvalidRequest(
                        "steered turn did not retain its exact Hepta admission".to_string(),
                    ));
                }
                Ok(MemoryTurnInputSubmission::Steered { turn_id })
            }
            (TurnInputSubmission::NotSubmitted { reason }, None) => {
                Ok(MemoryTurnInputSubmission::NotSubmitted { reason })
            }
            _ => Err(codex_protocol::error::CodexErr::InvalidRequest(
                "turn-input routing completed without exact Hepta admission".to_string(),
            )),
        }
    }
}
