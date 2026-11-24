//! Publishes terminal readiness while preserving the shutdown completion fence.

use super::TerminalizationAdmission;
use crate::session::session::Session;
use crate::session::terminal_event::PreparedTerminalEvent;
use crate::state::StartTransitionCompletion;
use std::sync::Arc;

pub(super) enum TerminalEventOwner<'a> {
    Task {
        identity: &'a Arc<()>,
        completion: &'a Arc<StartTransitionCompletion>,
    },
    StartTransition {
        identity: &'a Arc<()>,
        completion: &'a Arc<StartTransitionCompletion>,
    },
}

impl Session {
    /// All durable/stateful cleanup has completed before this call. Serialize
    /// readiness with new reservations and the shutdown seal. Registry readers
    /// cannot observe the queued event with Closed admission: delivery and the
    /// Closed -> Open transition hold that same registry mutex, without awaits.
    /// The completion entry remains registered through parent notification and
    /// pending-work admission so shutdown still drains the entire owner.
    pub(super) async fn publish_terminal_readiness(
        &self,
        owner: TerminalEventOwner<'_>,
        terminal: &PreparedTerminalEvent,
    ) -> bool {
        let active = self.active_turn.lock().await;
        if active.is_some() {
            return false;
        }
        let _admission_gate = self
            .start_admission_gate
            .lock()
            .unwrap_or_else(|error| panic!("start admission gate mutex poisoned: {error:?}"));
        match owner {
            TerminalEventOwner::Task {
                identity,
                completion,
            } => {
                let mut pending = self
                    .pending_task_terminalization_completions
                    .lock()
                    .unwrap_or_else(|error| {
                        panic!("task terminalization completion registry mutex poisoned: {error:?}")
                    });
                let Some((_, _, _, _, _, _, admission)) =
                    pending
                        .iter_mut()
                        .find(|(current, current_completion, _, _, _, _, _)| {
                            Arc::ptr_eq(current, identity)
                                && Arc::ptr_eq(current_completion, completion)
                        })
                else {
                    return false;
                };
                if *admission != TerminalizationAdmission::Closed
                    || !self.deliver_prepared_terminal_event(terminal)
                {
                    return false;
                }
                *admission = TerminalizationAdmission::Open;
            }
            TerminalEventOwner::StartTransition {
                identity,
                completion,
            } => {
                let mut pending = self
                    .pending_start_transition_completions
                    .lock()
                    .unwrap_or_else(|error| {
                        panic!("start transition completion registry mutex poisoned: {error:?}")
                    });
                let Some((_, _, _, admission)) =
                    pending
                        .iter_mut()
                        .find(|(current, current_completion, _, _)| {
                            Arc::ptr_eq(current, identity)
                                && Arc::ptr_eq(current_completion, completion)
                        })
                else {
                    return false;
                };
                if *admission != TerminalizationAdmission::Closed
                    || !self.deliver_prepared_terminal_event(terminal)
                {
                    return false;
                }
                *admission = TerminalizationAdmission::Open;
            }
        }
        true
    }
}
