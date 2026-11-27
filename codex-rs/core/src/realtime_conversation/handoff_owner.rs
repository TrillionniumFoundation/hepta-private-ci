//! Binds a handoff conversation to the turn that actually accepts its input.

use super::RealtimeHandoffState;
use super::RealtimeHandoffStreamState;
use super::RealtimeOutbound;
use super::RealtimeSessionKind;
use crate::session::turn_context::TurnContext;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::sync::Mutex;
use tokio::sync::OwnedMutexGuard;
use tokio::sync::Semaphore;

/// Keep output coordination and retirement state inseparable for one owner.
/// The completion bit is accessed only while the single permit is held.
pub(super) struct RealtimeHandoffOutputGate {
    permit: Semaphore,
    complete: AtomicBool,
}

impl std::fmt::Debug for RealtimeHandoffOutputGate {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("RealtimeHandoffOutputGate")
            .finish_non_exhaustive()
    }
}

impl Default for RealtimeHandoffOutputGate {
    fn default() -> Self {
        Self {
            permit: Semaphore::new(/*permits*/ 1),
            complete: AtomicBool::new(/*v*/ false),
        }
    }
}

#[derive(Clone, Debug)]
pub(super) struct RealtimeTurnHandoff {
    pub(super) handoff: RealtimeHandoffState,
}

/// Retained with one submission through an exact Finish wait. Receipt of a
/// network handoff does not install this owner or change another turn's output.
pub(crate) struct RealtimeHandoffRequest {
    handoff: RealtimeHandoffState,
    handoff_id: String,
    admitted: OnceLock<Arc<RealtimeTurnHandoff>>,
}

pub(crate) struct PreparedRealtimeHandoff<'a> {
    request: &'a RealtimeHandoffRequest,
    turn: &'a TurnContext,
    owner: Arc<RealtimeTurnHandoff>,
    stream: Option<OwnedMutexGuard<RealtimeHandoffStreamState>>,
}

impl RealtimeHandoffRequest {
    pub(super) fn new(handoff: RealtimeHandoffState, handoff_id: String) -> Self {
        Self {
            handoff,
            handoff_id,
            admitted: OnceLock::new(),
        }
    }

    /// The caller holds the original admission owner. For steering, retain
    /// this stream guard until the input is appended and commit synchronously.
    pub(crate) async fn prepare<'a>(
        &'a self,
        turn: &'a TurnContext,
    ) -> PreparedRealtimeHandoff<'a> {
        let owner = turn
            .extension_data
            .get::<RealtimeTurnHandoff>()
            .filter(|owner| Arc::ptr_eq(&owner.handoff.identity, &self.handoff.identity))
            .unwrap_or_else(|| {
                let handoff = if self.handoff.client_managed_handoffs {
                    self.handoff.clone()
                } else {
                    RealtimeHandoffState {
                        last_output: Arc::new(Mutex::new(/*t*/ None)),
                        stream: Arc::new(Mutex::new(RealtimeHandoffStreamState::default())),
                        output_gate: Arc::new(RealtimeHandoffOutputGate::default()),
                        ..self.handoff.clone()
                    }
                };
                Arc::new(RealtimeTurnHandoff { handoff })
            });
        // Client-managed receipt already owns global activation and ACKs.
        // Bind its identity at admission without locking or mutating that stream.
        let stream = if self.handoff.client_managed_handoffs {
            None
        } else {
            Some(Arc::clone(&owner.handoff.stream).lock_owned().await)
        };
        PreparedRealtimeHandoff {
            request: self,
            turn,
            owner,
            stream,
        }
    }

    pub(crate) async fn flush_admitted(&self) -> CodexResult<()> {
        if self.handoff.client_managed_handoffs {
            return Ok(());
        }
        if let Some(owner) = self.admitted.get() {
            send_owned_handoff_output(
                &owner.handoff,
                /*output*/ None,
                /*complete*/ false,
            )
            .await?;
        }
        Ok(())
    }
}

impl PreparedRealtimeHandoff<'_> {
    pub(crate) fn commit(mut self) {
        if let Some(stream) = self.stream.as_mut() {
            match self.request.handoff.session_kind {
                RealtimeSessionKind::V1 => {
                    stream.items.clear();
                    stream.active_handoff = Some(self.request.handoff_id.clone());
                }
                RealtimeSessionKind::V2 if stream.active_handoff.is_some() => {
                    let previous = stream
                        .pending_steer_ack
                        .replace(self.request.handoff_id.clone());
                    assert!(
                        previous.is_none(),
                        "the previous steering acknowledgement must drain"
                    );
                }
                RealtimeSessionKind::V2 => {
                    stream.active_handoff = Some(self.request.handoff_id.clone());
                }
            }
        }
        let _ = self.turn.extension_data.insert(self.owner.as_ref().clone());
        self.request
            .admitted
            .set(Arc::clone(&self.owner))
            .unwrap_or_else(|_| panic!("one realtime submission may be admitted only once"));
    }
}

/// Serialize progress, accepted-steer acknowledgement and retirement for one
/// owner. Completion and abort mark it complete before releasing the turn fence;
/// a late timer cannot enqueue stale progress. Abort supplies no completion
/// output. The receiver therefore does not need a later arrival's global
/// handoff ID to classify an already-owned V2 output.
pub(super) async fn send_owned_handoff_output(
    handoff: &RealtimeHandoffState,
    output: Option<RealtimeOutbound>,
    complete: bool,
) -> CodexResult<()> {
    let gate = &handoff.output_gate;
    let _permit = gate
        .permit
        .acquire()
        .await
        .map_err(|_| CodexErr::InvalidRequest("conversation is not running".to_string()))?;
    if gate.complete.load(Ordering::Relaxed) {
        return Ok(());
    }
    if complete {
        gate.complete.store(/*val*/ true, Ordering::Relaxed);
    }
    let acknowledgement = handoff
        .stream
        .lock()
        .await
        .pending_steer_ack
        .take()
        .map(|handoff_id| RealtimeOutbound::HandoffSteerAck { handoff_id });
    for output in acknowledgement.into_iter().chain(output) {
        handoff
            .output_tx
            .send(output)
            .await
            .map_err(|_| CodexErr::InvalidRequest("conversation is not running".to_string()))?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "handoff_output_gate_tests.rs"]
mod output_gate_tests;

#[cfg(test)]
#[path = "handoff_owner_tests.rs"]
mod tests;
