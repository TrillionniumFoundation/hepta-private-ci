//! Validate each logical turn's original recovery chain while streaming the
//! original history. Completed predecessors cannot borrow the target's state.

use std::collections::HashSet;

use codex_history::{RolloutItem, TurnRecoveryRequestBinding};
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::{EventMsg, TurnRecoveryCandidateState};

use super::HostedRecoveryHistory;
use crate::hosted_turn::{HostedTurnProvenance, invalid};

// These bound this scan's identity bookkeeping, not model context. The
// original per-line 16 MiB reader bound remains independent and unchanged.
const MAX_SEEN_TURNS: usize = 262_144;
const MAX_SEEN_TURN_ID_BYTES: usize = 16 * 1024 * 1024;

fn additional_identity_bytes(turns: usize, bytes: usize, turn_id: &str) -> CodexResult<usize> {
    if turn_id.is_empty() || turns >= MAX_SEEN_TURNS {
        return Err(invalid("hosted history identity is empty or its turn-count bound is exhausted"));
    }
    bytes.checked_add(turn_id.len()).filter(|total| *total <= MAX_SEEN_TURN_ID_BYTES)
        .ok_or_else(|| invalid("hosted history turn identities exceed their byte bound"))
}

pub(super) struct HostedHistoryScan<'a> {
    requested: &'a str,
    // Ephemeral scan validation only: an unstarted cancellation cannot name
    // any logical turn already present in this original history.
    seen_turns: HashSet<String>,
    seen_turn_id_bytes: usize,
    tail: Option<String>,
    original: Option<TurnRecoveryRequestBinding>,
    hosted_route: Option<bool>,
    latest_generation: u64,
    pending_unready: Option<u64>,
    awaiting_start: bool,
    completed: bool,
    active: bool,
    preparation_interrupted: bool,
}

impl<'a> HostedHistoryScan<'a> {
    pub(super) fn new(requested: &'a str) -> Self {
        Self { requested, seen_turns: HashSet::new(), seen_turn_id_bytes: 0, tail: None, original: None, hosted_route: None,
            latest_generation: 0, pending_unready: None, awaiting_start: false,
            completed: false, active: false, preparation_interrupted: false }
    }

    fn record_new_identity(&mut self, turn_id: &str) -> CodexResult<bool> {
        if self.seen_turns.contains(turn_id) { return Ok(false); }
        let bytes = additional_identity_bytes(self.seen_turns.len(), self.seen_turn_id_bytes, turn_id)?;
        self.seen_turns.insert(turn_id.to_owned());
        self.seen_turn_id_bytes = bytes;
        Ok(true)
    }

    pub(super) fn observe(&mut self, item: RolloutItem) -> CodexResult<()> {
        let mut successor_start = false;
        if self.awaiting_start {
            match &item {
                RolloutItem::EventMsg(EventMsg::Warning(_)) => return Ok(()),
                RolloutItem::EventMsg(EventMsg::TurnStarted(event))
                    if self.tail.as_deref() == Some(event.turn_id.as_str()) => {
                        self.awaiting_start = false;
                        successor_start = true;
                    }
                _ => return Err(invalid("hosted Core recovery handoff lost its following turn start")),
            }
        }
        match item {
            RolloutItem::EventMsg(EventMsg::TurnStarted(event)) => {
                if !successor_start {
                    if self.active || !self.record_new_identity(&event.turn_id)? {
                        return Err(invalid("hosted logical turn restarted without its exact typed successor"));
                    }
                    self.tail = Some(event.turn_id);
                    self.original = None;
                    self.hosted_route = None;
                    self.latest_generation = 0;
                    self.preparation_interrupted = false;
                }
                self.completed = false;
                self.active = true;
                self.pending_unready = None;
            }
            RolloutItem::EventMsg(EventMsg::TurnComplete(event)) => {
                if !self.active || self.tail.as_deref() != Some(event.turn_id.as_str()) {
                    return Err(invalid("hosted history has an unmatched terminal turn"));
                }
                self.completed = true;
                self.active = false;
                self.pending_unready = None;
            }
            RolloutItem::EventMsg(EventMsg::TurnAborted(event)) => {
                if !self.active {
                    let turn_id = event.turn_id.filter(|turn_id| !turn_id.is_empty())
                        .ok_or_else(|| invalid("unstarted cancellation has no original turn identity"))?;
                    if !self.record_new_identity(&turn_id)? {
                        return Err(invalid("unstarted cancellation reopened an existing logical turn"));
                    }
                    // Core may cancel its reservation before TurnStarted or
                    // typed provenance exists. This closed prefix has no
                    // binding to recover and never releases an active turn.
                    self.tail = Some(turn_id);
                    self.original = None;
                    self.hosted_route = None;
                    self.latest_generation = 0;
                    self.completed = true;
                    self.preparation_interrupted = true;
                    self.pending_unready = None;
                    return Ok(());
                }
                if event.turn_id.as_deref() != self.tail.as_deref() {
                    return Err(invalid("hosted history has an unmatched interrupted turn"));
                }
                self.preparation_interrupted = true;
                self.active = false;
                self.pending_unready = None;
            }
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.state == TurnRecoveryCandidateState::Unready => {
                    if self.tail.as_deref() != Some(marker.turn_id.as_str()) || self.pending_unready.is_some() {
                        return Err(invalid("hosted history duplicated or crossed an Unready recovery marker"));
                    }
                    self.pending_unready = Some(marker.generation);
                }
            RolloutItem::EventMsg(EventMsg::Warning(_)) => {}
            RolloutItem::TurnRecoveryRequestBinding(binding) => {
                self.observe_binding(binding)?;
            }
            _ => { self.pending_unready = None; }
        }
        Ok(())
    }

    fn observe_binding(&mut self, binding: TurnRecoveryRequestBinding) -> CodexResult<()> {
        if self.tail.as_deref() != Some(binding.turn_id.as_str()) || self.completed {
            return Err(invalid("recovery binding crossed its original logical turn"));
        }
        let hosted = HostedTurnProvenance::from_recovery(&binding)?.is_some();
        if (!hosted && binding.turn_id == self.requested)
            || self.hosted_route.is_some_and(|original| original != hosted) {
            return Err(invalid("original hosted turn changed its recovery route"));
        }
        if let Some(first) = self.original.as_ref() {
            if hosted || binding.replay_applied_from_generation.is_some() {
                let next = self.latest_generation.checked_add(1)
                    .ok_or_else(|| invalid("hosted Core generation exhausted"))?;
                if binding.generation != next
                    || binding.replay_applied_from_generation != Some(self.latest_generation)
                    || self.pending_unready != Some(next)
                    || binding.fingerprint_sha256 != first.fingerprint_sha256
                    || binding.history_boundary != first.history_boundary || binding.replay != first.replay {
                    return Err(invalid("hosted Core recovery is not the exact original successor"));
                }
                self.awaiting_start = true;
            } else {
                // Ordinary completed prefixes can publish another model-call
                // Ready binding without restarting their logical turn. Only
                // an explicit replay successor may precede another start.
                self.original = Some(binding.clone());
            }
        } else if binding.replay_applied_from_generation.is_some() || !self.active {
            return Err(invalid("hosted Core recovery has no original binding"));
        } else {
            self.original = Some(binding.clone());
            self.hosted_route = Some(hosted);
        }
        self.latest_generation = binding.generation;
        self.pending_unready = None;
        Ok(())
    }

    pub(super) fn finish(self) -> CodexResult<HostedRecoveryHistory> {
        if self.tail.as_deref() != Some(self.requested) || self.completed
            || self.awaiting_start || self.pending_unready.is_some() || self.hosted_route != Some(true) {
            return Err(invalid("hosted recovery requires the exact unfinished logical tail"));
        }
        Ok(HostedRecoveryHistory {
            original: self.original.ok_or_else(|| invalid("original hosted recovery binding is missing"))?,
            latest_generation: self.latest_generation,
            preparation_interrupted: self.preparation_interrupted,
        })
    }
}

#[cfg(test)]
#[path = "hosted_turn_history_tests.rs"]
mod tests;
