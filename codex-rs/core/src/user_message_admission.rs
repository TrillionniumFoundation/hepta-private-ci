use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::sync::oneshot;

use crate::session::turn_context::TurnContext;

/// The turn that accepted a submitted user message.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum UserMessageAdmission {
    /// Core installed a new turn for the submitted message.
    Started { turn_id: String },
    /// Core accepted the submitted message into an already-running turn.
    Steered { turn_id: String },
}

impl UserMessageAdmission {
    pub fn turn_id(&self) -> &str {
        match self {
            Self::Started { turn_id } | Self::Steered { turn_id } => turn_id,
        }
    }
}

/// Core-owned admission result retaining the exact turn that accepted a message.
///
/// Public callers continue to receive only [`UserMessageAdmission`]. Narrow
/// Core capabilities may retain this context without racing the active-turn
/// lifecycle after admission.
pub(crate) struct AdmittedUserMessage {
    admission: UserMessageAdmission,
    turn_context: Arc<TurnContext>,
}

impl AdmittedUserMessage {
    pub(crate) fn started(turn_context: Arc<TurnContext>) -> Self {
        Self {
            admission: UserMessageAdmission::Started {
                turn_id: turn_context.sub_id.clone(),
            },
            turn_context,
        }
    }

    pub(crate) fn steered(turn_context: Arc<TurnContext>) -> Self {
        Self {
            admission: UserMessageAdmission::Steered {
                turn_id: turn_context.sub_id.clone(),
            },
            turn_context,
        }
    }

    pub(crate) fn into_admission(self) -> UserMessageAdmission {
        let Self {
            admission,
            turn_context,
        } = self;
        drop(turn_context);
        admission
    }

    pub(crate) fn admission(&self) -> &UserMessageAdmission {
        &self.admission
    }

    pub(crate) fn into_parts(self) -> (UserMessageAdmission, Arc<TurnContext>) {
        (self.admission, self.turn_context)
    }
}

/// Explains why a submitted user message did not become durable.
#[derive(Debug)]
pub enum UserMessageAdmissionError {
    /// Core rejected the submission before admitting it to a turn.
    Admission(CodexErr),
    /// A user-prompt hook rejected the submitted message.
    RejectedByHook,
    /// The owning task finished before the submitted message was persisted.
    TaskEndedBeforePersistence,
    /// The admitted message could not be durably written to the rollout.
    PersistenceFailed(CodexErr),
}

impl From<UserMessageAdmissionError> for CodexErr {
    fn from(error: UserMessageAdmissionError) -> Self {
        match error {
            UserMessageAdmissionError::Admission(error) => error,
            UserMessageAdmissionError::RejectedByHook => {
                Self::InvalidRequest("user message was rejected by a hook".to_string())
            }
            UserMessageAdmissionError::TaskEndedBeforePersistence => Self::InternalAgentDied,
            UserMessageAdmissionError::PersistenceFailed(error) => error,
        }
    }
}

#[derive(Default)]
pub(crate) struct PendingUserMessageAdmissions {
    pending: Mutex<HashMap<String, PendingUserMessageAdmission>>,
}

struct PendingUserMessageAdmission {
    client_id: Option<String>,
    sender: oneshot::Sender<Result<AdmittedUserMessage, UserMessageAdmissionError>>,
    state: PendingUserMessageAdmissionState,
    hosted: Option<crate::hosted_turn::HostedTurnDispatch>,
    hosted_commit_pending: bool,
}

pub(crate) enum PendingUserMessageAdmissionState {
    Immediate,
    WaitingForAdmission,
    Admitted(AdmittedUserMessage),
    Persisted,
}

impl PendingUserMessageAdmissions {
    pub(crate) fn register_hosted_recovery(
        &self,
        submission_id: String,
        dispatch: crate::hosted_turn::HostedTurnDispatch,
    ) -> CodexResult<(
        PendingUserMessageAdmissionGuard<'_>,
        oneshot::Receiver<Result<AdmittedUserMessage, UserMessageAdmissionError>>,
    )> {
        let mut pending = self.pending.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        if pending.contains_key(&submission_id)
            || pending.values().any(|entry| entry.client_id.as_deref() == Some(dispatch.queue.client_id.as_str()))
        {
            return Err(CodexErr::InvalidRequest("original hosted admission is still owned".to_owned()));
        }
        let (sender, receiver) = oneshot::channel();
        pending.insert(submission_id.clone(), PendingUserMessageAdmission {
            client_id: Some(dispatch.queue.client_id.clone()), sender,
            state: PendingUserMessageAdmissionState::WaitingForAdmission,
            hosted: Some(dispatch), hosted_commit_pending: true,
        });
        Ok((PendingUserMessageAdmissionGuard { admissions: self, submission_id }, receiver))
    }

    pub(crate) fn register(
        &self,
        submission_id: String,
        client_id: Option<String>,
        state: PendingUserMessageAdmissionState,
    ) -> (
        PendingUserMessageAdmissionGuard<'_>,
        oneshot::Receiver<Result<AdmittedUserMessage, UserMessageAdmissionError>>,
    ) {
        let (sender, receiver) = oneshot::channel();
        self.pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(
                submission_id.clone(),
                PendingUserMessageAdmission {
                    client_id,
                    sender,
                    state,
                    hosted: None,
                    hosted_commit_pending: false,
                },
            );
        (
            PendingUserMessageAdmissionGuard {
                admissions: self,
                submission_id,
            },
            receiver,
        )
    }

    pub(crate) fn attach_hosted(&self, submission_id: &str, dispatch: crate::hosted_turn::HostedTurnDispatch) -> CodexResult<()> {
        let mut pending = self.pending.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        let entry = pending.get_mut(submission_id).ok_or_else(|| {
            CodexErr::InvalidRequest("original hosted admission is missing".to_string())
        })?;
        if entry.hosted_commit_pending || entry.client_id.as_deref() != Some(dispatch.queue.client_id.as_str()) {
            return Err(CodexErr::InvalidRequest("hosted admission identity changed".to_string()));
        }
        entry.hosted = Some(dispatch);
        entry.hosted_commit_pending = true;
        Ok(())
    }

    pub(crate) fn is_hosted(&self, submission_id: &str) -> bool {
        self.pending.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(submission_id).is_some_and(|entry| entry.hosted_commit_pending)
    }

    pub(crate) fn take_hosted(&self, submission_id: &str) -> Option<crate::hosted_turn::HostedTurnDispatch> {
        self.pending.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
            .get_mut(submission_id).and_then(|entry| entry.hosted.take())
    }

    pub(crate) fn confirm_hosted_persistence(&self, submission_id: &str) {
        let client_id = {
            let mut pending = self.pending.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
            let Some(entry) = pending.get_mut(submission_id) else { return; };
            entry.hosted_commit_pending = false;
            entry.client_id.clone()
        };
        if let Some(client_id) = client_id {
            self.complete_persistence(&client_id, Ok(()));
        }
    }

    pub(crate) fn complete(
        &self,
        submission_id: &str,
        admission: CodexResult<AdmittedUserMessage>,
    ) {
        let mut pending = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(entry) = pending.get_mut(submission_id) else {
            return;
        };

        match admission {
            Ok(admission) => match &entry.state {
                PendingUserMessageAdmissionState::WaitingForAdmission => {
                    entry.state = PendingUserMessageAdmissionState::Admitted(admission);
                }
                PendingUserMessageAdmissionState::Immediate
                | PendingUserMessageAdmissionState::Persisted => {
                    if let Some(entry) = pending.remove(submission_id) {
                        let _ = entry.sender.send(Ok(admission));
                    }
                }
                PendingUserMessageAdmissionState::Admitted(_) => {}
            },
            Err(error) => {
                if let Some(entry) = pending.remove(submission_id) {
                    let _ = entry
                        .sender
                        .send(Err(UserMessageAdmissionError::Admission(error)));
                }
            }
        }
    }

    /// Completes one registered submission with the exact context that Core
    /// installed for a newly started turn.
    pub(crate) fn complete_started(&self, submission_id: &str, turn_context: Arc<TurnContext>) {
        self.complete(
            submission_id,
            Ok(AdmittedUserMessage::started(turn_context)),
        );
    }

    /// Completes one registered submission with the exact active context that
    /// accepted steered input.
    pub(crate) fn complete_steered(&self, submission_id: &str, turn_context: Arc<TurnContext>) {
        self.complete(
            submission_id,
            Ok(AdmittedUserMessage::steered(turn_context)),
        );
    }

    pub(crate) fn contains_client_id(&self, client_id: &str) -> bool {
        self.pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .values()
            .any(|entry| {
                !matches!(&entry.state, PendingUserMessageAdmissionState::Immediate)
                    && entry.client_id.as_deref() == Some(client_id)
            })
    }

    pub(crate) fn complete_persistence(
        &self,
        client_id: &str,
        result: Result<(), UserMessageAdmissionError>,
    ) {
        let mut pending = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(submission_id) = pending.iter().find_map(|(submission_id, entry)| {
            (!matches!(&entry.state, PendingUserMessageAdmissionState::Immediate)
                && entry.client_id.as_deref() == Some(client_id))
            .then(|| submission_id.clone())
        }) else {
            return;
        };

        if let Err(error) = result {
            if let Some(entry) = pending.remove(&submission_id) {
                let _ = entry.sender.send(Err(error));
            }
            return;
        }

        let Some(entry) = pending.get_mut(&submission_id) else {
            return;
        };
        // The user input flush is only the first half of hosted admission.
        // The host's checkpoint/history must become durable before queue ACK.
        if entry.hosted_commit_pending {
            return;
        }
        match std::mem::replace(
            &mut entry.state,
            PendingUserMessageAdmissionState::Persisted,
        ) {
            PendingUserMessageAdmissionState::Admitted(admission) => {
                if let Some(entry) = pending.remove(&submission_id) {
                    let _ = entry.sender.send(Ok(admission));
                }
            }
            PendingUserMessageAdmissionState::Immediate
            | PendingUserMessageAdmissionState::WaitingForAdmission
            | PendingUserMessageAdmissionState::Persisted => {}
        }
    }

    pub(crate) fn complete_task_end(&self, turn_id: &str) -> bool {
        let mut pending = self
            .pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let submission_ids = pending
            .iter()
            .filter_map(|(submission_id, entry)| {
                let belongs_to_turn = match &entry.state {
                    PendingUserMessageAdmissionState::WaitingForAdmission => {
                        submission_id == turn_id
                    }
                    PendingUserMessageAdmissionState::Admitted(AdmittedUserMessage {
                        admission:
                            UserMessageAdmission::Started {
                                turn_id: admission_turn_id,
                            }
                            | UserMessageAdmission::Steered {
                                turn_id: admission_turn_id,
                            },
                        ..
                    }) => admission_turn_id == turn_id,
                    PendingUserMessageAdmissionState::Immediate
                    | PendingUserMessageAdmissionState::Persisted => false,
                };
                belongs_to_turn.then(|| submission_id.clone())
            })
            .collect::<Vec<_>>();

        let had_pending_admissions = !submission_ids.is_empty();
        for submission_id in submission_ids {
            if let Some(entry) = pending.remove(&submission_id) {
                let _ = entry
                    .sender
                    .send(Err(UserMessageAdmissionError::TaskEndedBeforePersistence));
            }
        }
        had_pending_admissions
    }

    fn remove(&self, submission_id: &str) {
        self.pending
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .remove(submission_id);
    }
}

pub(crate) struct PendingUserMessageAdmissionGuard<'a> {
    admissions: &'a PendingUserMessageAdmissions,
    submission_id: String,
}

impl Drop for PendingUserMessageAdmissionGuard<'_> {
    fn drop(&mut self) {
        self.admissions.remove(&self.submission_id);
    }
}
