//! Ordinary-finish admission is a separate, positively proved boundary from
//! completion of the callbacks that shutdown and residency must still drain.

use std::sync::Arc;
use std::sync::atomic::Ordering;

use codex_extension_api::ThreadIdleCause;

use super::TaskFinishHandoff;
use crate::session::session::Session;
use crate::state::DurableRecoveryState;
use crate::state::TaskTerminalizationKind;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum RecoveryPreparation {
    NotRequired,
    Revoked(u64),
    SeedPrepared(u64),
    Invalid,
    Tombstoned,
    TombstoneFailed,
}

impl RecoveryPreparation {
    pub(super) fn from_tombstone_result(persisted: bool) -> Self {
        if persisted {
            Self::Tombstoned
        } else {
            Self::TombstoneFailed
        }
    }

    pub(super) fn can_prove_ordinary_finish(self) -> bool {
        matches!(self, Self::NotRequired | Self::Revoked(_))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum RecoveryPublication {
    NoSeed,
    Confirmed(u64),
    Invalid,
    Tombstoned,
    TombstoneFailed,
}

impl RecoveryPublication {
    pub(super) fn from_tombstone_result(persisted: bool) -> Self {
        if persisted {
            Self::Tombstoned
        } else {
            Self::TombstoneFailed
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum FinishTerminalPublication {
    NotDeferred,
    Published,
    Undelivered,
    StaleOwner,
}

impl Session {
    /// Lock order is active turn -> recovery authority -> admission gate ->
    /// short registry/candidate locks. No caller holds authority while waiting
    /// for active turn. All async acquisition precedes final revalidation.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active-turn ownership and recovery authority must be checked in their established lock order"
    )]
    pub(super) async fn publish_ordinary_finish_terminal(
        &self,
        handoff: &mut TaskFinishHandoff,
        task_epoch: u64,
        cause: &ThreadIdleCause,
        terminal_generation: Option<u64>,
        preparation: RecoveryPreparation,
        publication: RecoveryPublication,
    ) -> FinishTerminalPublication {
        if handoff.prepared_terminal_event.is_none() {
            return FinishTerminalPublication::NotDeferred;
        }
        let authority = handoff.recovery_authority.clone();
        let active_turn = self.active_turn.lock().await;
        let authority_state = match authority.as_ref() {
            Some(authority) => Some(authority.state.lock().await),
            None => None,
        };
        // begin_shutdown uses this gate without awaiting any other lock.
        // Keep shutdown, event enqueue and admission release in one transition.
        let _admission_gate = self
            .start_admission_gate
            .lock()
            .unwrap_or_else(|error| panic!("start admission gate mutex poisoned: {error:?}"));
        let exact_owner = self
            .pending_task_terminalization_completions
            .lock()
            .unwrap_or_else(|error| {
                panic!("task terminalization completion registry mutex poisoned: {error:?}")
            })
            .iter()
            .any(|(identity, completion, kind, _, _, _)| {
                Arc::ptr_eq(identity, &handoff.terminalization_identity)
                    && Arc::ptr_eq(completion, &handoff.completion)
                    && *kind == TaskTerminalizationKind::Finish
            });
        let exact_task = handoff.task.as_ref().is_some_and(|task| {
            task.attach_epoch == task_epoch
                && Arc::ptr_eq(&task.turn_context, &handoff.turn_context)
        });
        if !exact_owner
            || !exact_task
            || active_turn.is_some()
            || self.turn_epoch.load(Ordering::Acquire) != task_epoch
            || handoff.completion.is_complete()
            || !handoff.completion.blocks_admission()
        {
            return FinishTerminalPublication::StaleOwner;
        }

        let candidate = self
            .recovery_candidate
            .lock()
            .unwrap_or_else(|error| panic!("recovery candidate mutex poisoned: {error:?}"));
        let recovery_proven = match preparation {
            RecoveryPreparation::NotRequired => {
                publication == RecoveryPublication::NoSeed
                    && authority.is_none()
                    && candidate.is_none()
            }
            RecoveryPreparation::Revoked(generation) => {
                publication == RecoveryPublication::NoSeed
                    && candidate.is_none()
                    && authority
                        .as_ref()
                        .is_some_and(|authority| !authority.ready.load(Ordering::Acquire))
                    && authority_state.as_ref().is_some_and(|state| {
                        !state.poisoned
                            && state.durable_state == DurableRecoveryState::Unready
                            && state.generation == generation
                            && state.ready_persistence_failure_generation.is_none()
                            && state.request_fingerprint_sha256.is_none()
                            && state.replay.is_none()
                    })
            }
            // Ok task results never create an interrupt seed. Keep this new
            // permission limited to ordinary completion even if a future caller
            // accidentally supplies an interrupted-recovery outcome.
            RecoveryPreparation::SeedPrepared(_)
            | RecoveryPreparation::Invalid
            | RecoveryPreparation::Tombstoned
            | RecoveryPreparation::TombstoneFailed => false,
        };
        let release_admission = *cause == ThreadIdleCause::Completed
            && self.live_thread().is_some()
            && recovery_proven
            && !self.shutdown_started()
            && !self.has_pending_admission_fence_except(Some(&handoff.terminalization_identity))
            && terminal_generation.is_some_and(|generation| {
                self.rollout_persistence_failure_generation() == generation
            });
        drop(candidate);

        // No await below: final generation/owner checks, terminal enqueue,
        // old execution-slot release and admission release are one transition.
        // Starts must reacquire active_turn, so TurnStarted cannot overtake it.
        if !self.enqueue_prepared_terminal_event(&mut handoff.prepared_terminal_event) {
            // Retain both the event and task/capacity witness. Ordinary callback
            // and completion cleanup keep their old timing, without early admission.
            return FinishTerminalPublication::Undelivered;
        }
        if release_admission {
            handoff.task.take();
            handoff.completion.release_admission();
        }
        // On an unproved boundary the notification is delivered, but the old
        // fence still rejects callback admission until normal completion.
        FinishTerminalPublication::Published
    }
}
