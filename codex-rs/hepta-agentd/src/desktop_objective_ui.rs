//! Explicit desktop composition of the original sender, authenticated transport,
//! and bounded presentation callbacks. No default writer, issuer or trust source.

use crate::AgentRunPhase;
use crate::AgentRunReceipt;
use crate::AgentdClient;
use crate::AgentdObjectiveClient;
use crate::AgentdObjectiveClientError;
use crate::AgentdObjectivePeer;
use crate::AgentdObjectiveWindow;
use crate::AgentdProductionHostAttachment;
use crate::AuthBusObjectiveIngress;
use crate::ObjectiveAdmissionOutcome;
use crate::ObjectiveClientMode;
use crate::ObjectivePublicationOutcome;
use codex_hepta_memory::ObjectiveSenderCheckpoint;
use codex_hepta_memory::ObjectiveSenderRequest;
use hepta_control_core::chat::ChatWorkspace;
use hepta_control_core::objective_ui::ObjectiveUiBinding;
use hepta_control_core::objective_ui::ObjectiveUiCommand;
use hepta_control_core::objective_ui::ObjectiveUiError;
use hepta_control_core::objective_ui::ObjectiveUiObservation;
use hepta_control_core::objective_ui::ObjectiveUiPhase;
use hepta_control_core::objective_ui::ObjectiveUiPort;
use hepta_control_core::objective_ui::ObjectiveUiPublication;
use hepta_control_core::objective_ui::ObjectiveUiRequest;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::runtime::Handle;
use tokio::sync::mpsc;
use tokio::sync::watch;
use tokio::time::Instant;

const OBSERVATION_INTERVAL: Duration = Duration::from_secs(1);
const UNKNOWN_OBSERVATION_BACKOFF: Duration = Duration::from_secs(5);

/// The authenticated embedding supplies an existing production attachment and
/// already-signed request. Its run ID must bind the complete current UI scope;
/// its source digest must bind the displayed draft. This API never signs text.
pub struct AgentdObjectiveUiInputs<C: ObjectiveSenderCheckpoint> {
    pub attachment: AgentdProductionHostAttachment<C>,
    pub client: AgentdClient,
    pub original: ObjectiveSenderRequest,
    pub peer: AgentdObjectivePeer,
    pub binding: ObjectiveUiBinding,
    pub mode: ObjectiveClientMode,
    pub runtime: Handle,
}

#[derive(Debug, thiserror::Error)]
pub enum AgentdObjectiveUiError {
    #[error("the signed original request does not bind this UI owner, window and draft")]
    Binding,
    #[error("the current presentation cannot adopt the original owner: {0:?}")]
    Presentation(ObjectiveUiError),
    #[error(transparent)]
    Transport(#[from] AgentdObjectiveClientError),
}

/// Install in the actual workspace only after all exact bindings validate.
/// The renderer receives no signing key, raw signed envelope or database handle.
/// The worker uses the original host runtime and a one-command bounded queue.
pub fn install_original_objective_ui<C: ObjectiveSenderCheckpoint + 'static>(
    workspace: &mut ChatWorkspace,
    inputs: AgentdObjectiveUiInputs<C>,
) -> Result<(), AgentdObjectiveUiError> {
    let binding = inputs.binding;
    let ingress: AuthBusObjectiveIngress = serde_json::from_slice(inputs.original.exact_original())
        .map_err(|_| AgentdObjectiveUiError::Binding)?;
    let source = codex_hepta_objective::decode_source_envelope_json_v1(
        ingress.body.source_envelope_json.as_bytes(),
    )
    .map_err(|_| AgentdObjectiveUiError::Binding)?;
    if !binding.valid()
        || inputs.original.origin().agent_id.as_str() != binding.owner.agent_id
        || inputs.original.origin().spawn_generation != binding.owner.agent_generation
        || inputs.original.identity().run_id != binding.original_run_id()
        || inputs.original.identity().expires_at_ms > binding.owner_expires_at_ms
        || source.structured_intent.provenance.source_digest.as_array() != &binding.draft_sha256
    {
        return Err(AgentdObjectiveUiError::Binding);
    }
    let client = inputs.client.bind_original_objective(
        inputs.attachment.original_sender,
        inputs.original,
        inputs.peer,
        inputs.mode,
    )?;
    let initial = inputs.mode == ObjectiveClientMode::Initial;
    let observation = ObjectiveUiObservation {
        binding: binding.clone(),
        sequence: 1,
        phase: if initial {
            ObjectiveUiPhase::Prepared
        } else {
            ObjectiveUiPhase::Unknown
        },
        retained_publication: None,
        can_cancel: initial,
        can_refresh: !initial,
    };
    let (commands, receiver) = mpsc::channel(1);
    let (observations, updates) = watch::channel(observation);
    let window = client.window();
    let now_ms = now_ms().ok_or(AgentdObjectiveUiError::Binding)?;
    let port = OriginalObjectiveUiPort {
        binding,
        window,
        commands,
        updates,
        first_poll: true,
        submit_claimed: !initial,
        cancel_claimed: false,
        last_sequence: 0,
        last_now_ms: now_ms,
        closed_reported: false,
    };
    workspace
        .install_objective_owner(Box::new(port), now_ms)
        .map_err(AgentdObjectiveUiError::Presentation)?;
    inputs
        .runtime
        .spawn(run_owner(client, receiver, observations, initial));
    Ok(())
}

struct OriginalObjectiveUiPort {
    binding: ObjectiveUiBinding,
    window: AgentdObjectiveWindow,
    commands: mpsc::Sender<ObjectiveUiCommand>,
    updates: watch::Receiver<ObjectiveUiObservation>,
    first_poll: bool,
    submit_claimed: bool,
    cancel_claimed: bool,
    last_sequence: u64,
    last_now_ms: u64,
    closed_reported: bool,
}

impl OriginalObjectiveUiPort {
    fn require_current(&mut self) -> Result<(), ObjectiveUiError> {
        let current = now_ms().ok_or(ObjectiveUiError::Retired)?;
        if current < self.last_now_ms
            || current >= self.binding.owner_expires_at_ms
            || !self.window.is_live()
            || self.commands.is_closed()
        {
            self.window.close();
            return Err(ObjectiveUiError::Retired);
        }
        self.last_now_ms = current;
        Ok(())
    }
}

impl ObjectiveUiPort for OriginalObjectiveUiPort {
    fn binding(&self) -> &ObjectiveUiBinding {
        &self.binding
    }

    fn request(
        &mut self,
        command: ObjectiveUiCommand,
        presentation_epoch: u64,
        room: u64,
        draft: &str,
    ) -> Result<ObjectiveUiRequest, ObjectiveUiError> {
        self.require_current()?;
        if presentation_epoch != self.binding.presentation_epoch || room != self.binding.room {
            return Err(ObjectiveUiError::Binding);
        }
        match command {
            ObjectiveUiCommand::Submit if !self.binding.matches_draft(draft) => {
                return Err(ObjectiveUiError::DraftChanged);
            }
            ObjectiveUiCommand::Submit if self.submit_claimed => {
                return Ok(ObjectiveUiRequest::Existing);
            }
            ObjectiveUiCommand::Cancel if self.cancel_claimed => {
                return Ok(ObjectiveUiRequest::Existing);
            }
            ObjectiveUiCommand::Refresh if !self.submit_claimed => {
                return Err(ObjectiveUiError::Unavailable);
            }
            ObjectiveUiCommand::Cancel if !self.updates.borrow().can_cancel => {
                return Err(ObjectiveUiError::Busy);
            }
            ObjectiveUiCommand::Submit
            | ObjectiveUiCommand::Cancel
            | ObjectiveUiCommand::Refresh => {}
        }
        let permit = self.commands.try_reserve().map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => ObjectiveUiError::Busy,
            mpsc::error::TrySendError::Closed(_) => ObjectiveUiError::Unavailable,
        })?;
        match command {
            ObjectiveUiCommand::Submit => self.submit_claimed = true,
            ObjectiveUiCommand::Cancel => {
                self.submit_claimed = true;
                self.cancel_claimed = true;
            }
            ObjectiveUiCommand::Refresh => {}
        }
        permit.send(command);
        Ok(ObjectiveUiRequest::Queued)
    }

    fn poll(&mut self) -> Option<ObjectiveUiObservation> {
        if self.require_current().is_err() {
            if self.closed_reported {
                return None;
            }
            self.closed_reported = true;
            let mut closed = self.updates.borrow().clone();
            closed.sequence = closed.sequence.max(self.last_sequence).saturating_add(1);
            closed.phase = ObjectiveUiPhase::Closed;
            closed.can_cancel = false;
            closed.can_refresh = false;
            return Some(closed);
        }
        if !self.first_poll && !self.updates.has_changed().unwrap_or(false) {
            return None;
        }
        self.first_poll = false;
        let observed = self.updates.borrow_and_update().clone();
        if observed.sequence <= self.last_sequence {
            return None;
        }
        self.last_sequence = observed.sequence;
        Some(observed)
    }

    fn close(&mut self) {
        self.window.close();
    }
}

impl Drop for OriginalObjectiveUiPort {
    fn drop(&mut self) {
        self.window.close();
    }
}

async fn run_owner<C: ObjectiveSenderCheckpoint + 'static>(
    mut client: AgentdObjectiveClient<C>,
    mut commands: mpsc::Receiver<ObjectiveUiCommand>,
    observations: watch::Sender<ObjectiveUiObservation>,
    initial: bool,
) {
    let window = client.window();
    let mut started = !initial;
    let mut cancelled = false;
    let mut view = observations.borrow().clone();
    let mut delay = OBSERVATION_INTERVAL;
    let mut next_observation = Instant::now() + delay;
    loop {
        let Some(remaining) = now_ms()
            .and_then(|now| view.binding.owner_expires_at_ms.checked_sub(now))
            .filter(|remaining| *remaining > 0)
        else {
            window.close();
            break;
        };
        let expires = Instant::now() + Duration::from_millis(remaining);
        let follow = (started || cancelled)
            && matches!(
                view.phase,
                ObjectiveUiPhase::Unknown
                    | ObjectiveUiPhase::Published
                    | ObjectiveUiPhase::Cancelling
            );
        let command = tokio::select! {
            biased;
            _ = window.cancelled() => break,
            _ = tokio::time::sleep_until(expires) => {
                window.close();
                break;
            },
            command = commands.recv() => match command { Some(command) => command, None => break },
            _ = tokio::time::sleep_until(next_observation), if follow => ObjectiveUiCommand::Refresh,
        };
        if now_ms().is_none_or(|now| now >= view.binding.owner_expires_at_ms) {
            window.close();
            break;
        }
        if command != ObjectiveUiCommand::Refresh {
            view.phase = match command {
                ObjectiveUiCommand::Submit => ObjectiveUiPhase::Submitting,
                ObjectiveUiCommand::Cancel => ObjectiveUiPhase::Cancelling,
                ObjectiveUiCommand::Refresh => view.phase,
            };
            view.can_cancel = false;
            view.can_refresh = false;
            publish(&observations, &mut view);
        }
        let before = view.clone();
        let operation = async {
            match command {
                ObjectiveUiCommand::Submit => {
                    started = true;
                    client.submit_once().await?;
                    refresh(&mut client, &mut view).await
                }
                ObjectiveUiCommand::Cancel => {
                    cancelled = true;
                    if !started {
                        client.cancel_local().await?;
                        view.phase = ObjectiveUiPhase::LocalCancelled;
                    } else {
                        let result = client
                            .cancel_current("Desktop owner requested cancellation".to_string())
                            .await?;
                        view.phase = match result.disposition {
                            crate::AgentCancellationDisposition::CancelledBeforeDispatch => {
                                ObjectiveUiPhase::CancelledBeforeDispatch
                            }
                            crate::AgentCancellationDisposition::CancellingAfterDispatch => {
                                ObjectiveUiPhase::Cancelling
                            }
                            crate::AgentCancellationDisposition::AlreadyTerminal => {
                                run_phase(&result.receipt)
                            }
                        };
                    }
                    Ok(())
                }
                ObjectiveUiCommand::Refresh => refresh(&mut client, &mut view).await,
            }
        };
        let result = tokio::select! {
            biased;
            _ = window.cancelled() => break,
            _ = tokio::time::sleep_until(expires) => {
                window.close();
                break;
            },
            result = operation => result,
        };
        if result.is_err() {
            view.phase = ObjectiveUiPhase::Unknown;
        }
        view.can_refresh = true;
        view.can_cancel = !cancelled && matches!(view.phase, ObjectiveUiPhase::Published);
        if view != before {
            publish(&observations, &mut view);
        }
        // This one worker only observes the retained original request. A lost
        // submit/cancel ACK never creates another effectful command. Delay from
        // completion prevents catch-up bursts after slow I/O; unchanged reads do
        // not redraw, and terminal phases stop automatic polling altogether.
        delay = if view.phase == ObjectiveUiPhase::Unknown {
            delay.saturating_mul(2).min(UNKNOWN_OBSERVATION_BACKOFF)
        } else {
            OBSERVATION_INTERVAL
        };
        next_observation = Instant::now() + delay;
    }
}

async fn refresh<C: ObjectiveSenderCheckpoint>(
    client: &mut AgentdObjectiveClient<C>,
    view: &mut ObjectiveUiObservation,
) -> Result<(), AgentdObjectiveClientError> {
    if client.acknowledged_local_cancellation().await? {
        view.phase = ObjectiveUiPhase::LocalCancelled;
        return Ok(());
    }
    let (history, run) = client.observe_current().await?;
    if let Some(publication) = history.retained_publication {
        view.retained_publication = Some(match publication.outcome {
            ObjectivePublicationOutcome::Compiled { .. } => ObjectiveUiPublication::Compiled,
            ObjectivePublicationOutcome::ExplicitAbstain { .. } => {
                ObjectiveUiPublication::Abstained
            }
            ObjectivePublicationOutcome::Conflict { .. } => ObjectiveUiPublication::Conflict,
        });
    }
    view.phase = match history.latest {
        ObjectiveAdmissionOutcome::Unknown { .. } => ObjectiveUiPhase::Unknown,
        ObjectiveAdmissionOutcome::Published { publication } => match publication.outcome {
            ObjectivePublicationOutcome::Compiled { .. } => {
                run.as_ref().map_or(ObjectiveUiPhase::Unknown, run_phase)
            }
            ObjectivePublicationOutcome::ExplicitAbstain { .. } => ObjectiveUiPhase::Abstained,
            ObjectivePublicationOutcome::Conflict { .. } => ObjectiveUiPhase::Conflict,
        },
    };
    Ok(())
}

fn run_phase(run: &AgentRunReceipt) -> ObjectiveUiPhase {
    match run.phase {
        AgentRunPhase::Admitted | AgentRunPhase::ContextAttached | AgentRunPhase::Dispatched => {
            ObjectiveUiPhase::Published
        }
        AgentRunPhase::Cancelling => ObjectiveUiPhase::Cancelling,
        AgentRunPhase::Succeeded if run.terminal_observed => ObjectiveUiPhase::Succeeded,
        AgentRunPhase::Failed if run.terminal_observed => ObjectiveUiPhase::Failed,
        AgentRunPhase::Cancelled if run.terminal_observed => ObjectiveUiPhase::Cancelled,
        AgentRunPhase::Indeterminate if run.terminal_observed => ObjectiveUiPhase::Indeterminate,
        AgentRunPhase::Succeeded
        | AgentRunPhase::Failed
        | AgentRunPhase::Cancelled
        | AgentRunPhase::Indeterminate => ObjectiveUiPhase::Unknown,
    }
}

fn publish(sender: &watch::Sender<ObjectiveUiObservation>, view: &mut ObjectiveUiObservation) {
    view.sequence = view.sequence.saturating_add(1);
    sender.send_replace(view.clone());
}

fn now_ms() -> Option<u64> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()?
            .as_millis(),
    )
    .ok()
}
