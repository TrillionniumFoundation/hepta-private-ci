//! Bounded, opt-in observations for the recovery integration fixtures.
//!
//! No observer strongly owns a Session, RunningTask, execution lease, or
//! admission guard. The weak session identity prevents address reuse without
//! retaining its resources. Reads never wait for a lock. Observations are not
//! recovery authority, and their absence is not proof that a branch was unused.

use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use serde_json::Value;
use serde_json::json;

use crate::CodexThread;
use crate::session::session::Session;
use crate::state::TurnRecoveryAuthority;

const MAX_OBSERVERS: usize = 8;
const MAX_EVENTS: usize = 8;
static OBSERVERS: Mutex<Vec<Weak<Observer>>> = Mutex::new(Vec::new());

struct Observer {
    session: Weak<Session>,
    events: Mutex<Vec<Value>>,
    dropped_events: AtomicUsize,
}

/// Read-only fixture handle. Keeping the original authority alive does not
/// keep its task, thread, environment, or execution guard alive.
pub struct RecoveryDiagnostics {
    observer: Arc<Observer>,
    authority: Option<Arc<TurnRecoveryAuthority>>,
    capture_status: &'static str,
    registered: bool,
    turn_id: String,
}

impl RecoveryDiagnostics {
    /// Registers bounded observations and tries once to retain this turn's
    /// existing recovery authority. An unavailable capture is explicit.
    pub fn capture(thread: &CodexThread, turn_id: &str) -> Self {
        let session = thread.session.as_ref();
        let observer = Arc::new(Observer {
            session: Arc::downgrade(&thread.session),
            events: Mutex::new(Vec::new()),
            dropped_events: AtomicUsize::new(0),
        });
        let registered = OBSERVERS.try_lock().is_ok_and(|mut observers| {
            observers.retain(|item| item.strong_count() != 0);
            if observers.len() == MAX_OBSERVERS {
                return false;
            }
            observers.push(Arc::downgrade(&observer));
            true
        });
        let (authority, capture_status) = match session.active_turn.try_lock() {
            Ok(active) => match active.as_ref().and_then(|turn| turn.task.as_ref()) {
                Some(task) if task.turn_context.sub_id == turn_id => {
                    (task.recovery_authority.clone(), "matched_task")
                }
                Some(_) => (None, "different_task"),
                None => (None, "no_task"),
            },
            Err(_) => (None, "active_lock_busy"),
        };
        Self {
            observer,
            authority,
            capture_status,
            registered,
            turn_id: turn_id.to_string(),
        }
    }

    /// Best-effort snapshot, not an atomic cut. Busy or poisoned locks are
    /// reported, never waited on or recovered. No history or payload is emitted.
    pub fn snapshot(&self, thread: &CodexThread) -> Value {
        let session = thread.session.as_ref();
        if std::ptr::from_ref(session) != self.observer.session.as_ptr() {
            return json!({"session_changed": true});
        }
        let active = session.active_turn.try_lock().map_or_else(
            |_| json!({"lock": "busy"}),
            |active| json!({
                "present": active.is_some(),
                "task": active.as_ref().and_then(|turn| turn.task.as_ref()).map(|task| json!({
                    "turn_matches": task.turn_context.sub_id == self.turn_id,
                    "attach_epoch": task.attach_epoch,
                    "recovery_eligible": task.recovery_eligible_model_turn,
                    "cancelled": task.cancellation_token.is_cancelled(),
                })),
                "terminalization": active.as_ref().and_then(|turn| turn.task_terminalization.as_ref()).map(|marker| json!({
                    "kind": format!("{:?}", marker.kind),
                    "phase": format!("{:?}", marker.phase),
                    "attach_epoch": marker.attach_epoch,
                    "complete": marker.completion.is_complete(),
                })),
                "reservation": active.as_ref().is_some_and(|turn| turn.start_reservation.is_some()),
                "transition": active.as_ref().is_some_and(|turn| turn.start_transition.is_some()),
            }),
        );
        let candidate =
            session.recovery_candidate.try_lock().map_or_else(
                |_| json!({"lock": "busy_or_poisoned"}),
                |candidate| {
                    candidate.as_ref().map_or(Value::Null, |candidate| json!({
                "turn_matches": candidate.turn_id == self.turn_id,
                "epoch": candidate.epoch,
                "marker_generation": candidate.marker_generation,
                "persistence_failure_generation": candidate.persistence_failure_generation,
                "request_sha256": candidate.request_fingerprint_sha256,
                "context_sha256": candidate.replay.turn_context_sha256,
                "history_boundary_sha256": digest(&candidate.replay.history_boundary),
            }))
                },
            );
        let authority = self.authority.as_ref().map(|authority| {
            let state = authority.state.try_lock().map_or_else(
                |_| json!({"lock": "busy"}),
                |state| json!({
                    "generation": state.generation,
                    "durable_state": format!("{:?}", state.durable_state),
                    "poisoned": state.poisoned,
                    "ready_persistence_failure_generation": state.ready_persistence_failure_generation,
                    "request_sha256": state.request_fingerprint_sha256,
                    "has_replay": state.replay.is_some(),
                }),
            );
            json!({"ready": authority.ready.load(Ordering::Acquire), "state": state})
        });
        let pending = session.pending_task_terminalization_completions.try_lock().map_or_else(
            |_| json!({"lock": "busy_or_poisoned"}),
            |entries| json!({
                "count": entries.len(),
                "entries": entries.iter().take(MAX_EVENTS).map(|(_, completion, kind, _, abort, finish, admission)| {
                    let abort = abort.as_ref().map(|slot| slot.try_lock().map_or_else(
                        |_| json!({"lock": "busy_or_poisoned"}),
                        |slot| slot.as_ref().map_or(Value::Null, |handoff| json!({
                            "phase": format!("{:?}", handoff.phase),
                            "failed_closed": handoff.failed_closed,
                            "task_quiesced": handoff.task_quiesced,
                            "terminal_persistence_generation": handoff.terminal_persistence_generation,
                            "has_recovery_seed": handoff.recovery_seed.is_some(),
                        })),
                    ));
                    let finish = finish.as_ref().map(|slot| slot.try_lock().map_or_else(
                        |_| json!({"lock": "busy_or_poisoned"}),
                        |slot| slot.as_ref().map_or(Value::Null, |handoff| json!({
                            "phase": format!("{:?}", handoff.phase),
                            "failed_closed": handoff.failed_closed,
                            "has_recovery_seed": handoff.recovery_seed.is_some(),
                        })),
                    ));
                    json!({"kind": format!("{kind:?}"), "admission": format!("{admission:?}"),
                           "complete": completion.is_complete(), "abort": abort, "finish": finish})
                }).collect::<Vec<_>>(),
            }),
        );
        let start_fences = session.pending_start_transition_completions.try_lock().map_or_else(
            |_| json!({"lock": "busy_or_poisoned"}),
            |entries| json!({"count": entries.len(), "closed": entries.iter().filter(|(_, _, _, admission)|
                *admission == super::TerminalizationAdmission::Closed).count()}),
        );
        let events = self.observer.events.try_lock().map_or_else(
            |_| json!({"lock": "busy_or_poisoned"}),
            |events| json!(&*events),
        );
        json!({
            "diagnostic_only": true, "atomic_snapshot": false, "observation_complete": false,
            "observer_registered": self.registered, "capture_status": self.capture_status,
            "epoch": session.turn_epoch.load(Ordering::Acquire),
            "persistence_failure_generation": session.rollout_persistence_failure_generation.load(Ordering::Acquire),
            "shutdown": session.shutdown_started.load(Ordering::Acquire),
            "active": active, "candidate": candidate, "original_authority": authority,
            "pending_terminalizations": pending, "pending_start_fences": start_fences,
            "rejections": events,
            "dropped_events": self.observer.dropped_events.load(Ordering::Acquire),
        })
    }
}

/// Records only when an integration fixture registered this exact session.
/// Contended observation is discarded; it cannot delay or authorize recovery.
pub(crate) fn record(session: &Session, code: &'static str, details: impl FnOnce() -> Value) {
    let observer = OBSERVERS.try_lock().ok().and_then(|observers| {
        observers
            .iter()
            .filter_map(Weak::upgrade)
            .find(|observer| observer.session.as_ptr() == std::ptr::from_ref(session))
    });
    let Some(observer) = observer else { return };
    let Ok(mut events) = observer.events.try_lock() else {
        observer.dropped_events.fetch_add(1, Ordering::AcqRel);
        return;
    };
    if events.len() == MAX_EVENTS {
        observer.dropped_events.fetch_add(1, Ordering::AcqRel);
        return;
    }
    events.push(json!({"code": code, "details": details()}));
}

pub(crate) fn digest(value: &impl serde::Serialize) -> Option<String> {
    crate::model_provider_policy::canonical_sha256(value)
        .ok()
        .map(|digest| digest.as_str().to_string())
}

pub(crate) fn context_comparison(
    expected: &codex_protocol::protocol::TurnContextItem,
    current: &codex_protocol::protocol::TurnContextItem,
) -> Value {
    let fields = serde_json::to_value(expected)
        .ok()
        .zip(serde_json::to_value(current).ok())
        .and_then(|(expected, current)| {
            Some((expected.as_object()?.clone(), current.as_object()?.clone()))
        })
        .map(|(expected, current)| {
            expected
                .keys()
                .chain(current.keys())
                .collect::<BTreeSet<_>>()
                .into_iter()
                .filter(|key| expected.get(*key) != current.get(*key))
                .cloned()
                .collect::<Vec<_>>()
        });
    json!({"equal": expected == current, "expected_sha256": digest(expected),
           "current_sha256": digest(current), "different_field_names": fields})
}
