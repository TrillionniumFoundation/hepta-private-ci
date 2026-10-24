//! Disposable bounded views and FIFO actions for the original Notes UI wire.
//! This queue has no send permission, durable ledger or authority of its own.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use tokio::sync::Notify;

use crate::notes_ui_wire::*;

const ACTION_CAPACITY: usize = 8;
pub(crate) const ACTION_LIFETIME: Duration = Duration::from_secs(5);

pub(crate) struct QueuedCommand {
    pub(crate) command: ObjectiveCommand,
    pub(crate) end: Instant,
}

struct State {
    actions: VecDeque<QueuedCommand>,
    passive: VecDeque<QueuedCommand>,
    availability: ObjectiveObservation,
    intents: BTreeMap<String, ObjectiveObservation>,
}

pub(crate) struct NotesUiQueue {
    state: Mutex<State>,
    pub(crate) wake: Notify,
}

impl NotesUiQueue {
    pub(crate) fn new() -> Self {
        Self {
            state: Mutex::new(State {
                actions: VecDeque::new(),
                passive: VecDeque::new(),
                availability: ObjectiveObservation::new(None, ObjectiveStage::Unavailable),
                intents: BTreeMap::new(),
            }),
            wake: Notify::new(),
        }
    }

    /// A Session exchange never waits for an original owner operation. Passive
    /// refresh coalesces independently and cannot fill the eight action slots.
    pub(crate) fn request(&self, command: ObjectiveCommand) -> ObjectiveObservation {
        let mut unavailable = ObjectiveObservation::new(
            command.client_intent_id().map(str::to_owned), ObjectiveStage::Unavailable,
        );
        if let Err(issue) = command.validate() {
            unavailable.issue = Some(issue);
            return unavailable;
        }
        let Ok(mut state) = self.state.try_lock() else {
            unavailable.issue = Some(ObjectiveHostIssue::Capacity);
            return unavailable;
        };
        let mut view = if let Some(id) = command.client_intent_id() {
            if !state.intents.contains_key(id) && state.intents.len() == MAX_OBJECTIVE_VIEWS {
                unavailable.issue = Some(ObjectiveHostIssue::Capacity);
                return unavailable;
            }
            state.intents.entry(id.to_owned()).or_insert_with(|| {
                ObjectiveObservation::new(Some(id.to_owned()), ObjectiveStage::Queued)
            }).clone()
        } else { state.availability.clone() };
        let entry = QueuedCommand { command, end: Instant::now() + ACTION_LIFETIME };
        match &entry.command {
            ObjectiveCommand::Submit { .. } | ObjectiveCommand::Cancel { .. } => {
                if state.actions.len() == ACTION_CAPACITY {
                    view.issue = Some(ObjectiveHostIssue::Capacity);
                    return view;
                }
                state.actions.push_back(entry);
            }
            ObjectiveCommand::Availability {} | ObjectiveCommand::Status { .. } => {
                if let Some(existing) = state.passive.iter_mut().find(|existing| {
                    existing.command.client_intent_id() == entry.command.client_intent_id()
                }) {
                    *existing = entry;
                } else if state.passive.len() < MAX_OBJECTIVE_VIEWS + 1 {
                    state.passive.push_back(entry);
                } else {
                    view.issue = Some(ObjectiveHostIssue::Capacity);
                    return view;
                }
            }
        }
        self.wake.notify_one();
        view
    }

    /// One worker only. Expired queued actions never enter the original adapter.
    /// Expiration makes no statement about any earlier retained attempt.
    pub(crate) fn take(&self, now: Instant) -> Result<Option<QueuedCommand>, ()> {
        let mut state = self.state.lock().map_err(|_| ())?;
        loop {
            let entry = state.actions.pop_front().or_else(|| state.passive.pop_front());
            let Some(entry) = entry else { return Ok(None); };
            if now < entry.end { return Ok(Some(entry)); }
            let view = match entry.command.client_intent_id() {
                Some(id) => state.intents.get_mut(id).ok_or(())?,
                None => &mut state.availability,
            };
            if !view.request_retained { view.stage = ObjectiveStage::Unavailable; }
            view.issue = Some(ObjectiveHostIssue::Unavailable);
        }
    }

    pub(crate) fn update(&self, view: ObjectiveObservation) -> Result<(), ()> {
        let mut state = self.state.lock().map_err(|_| ())?;
        if let Some(id) = &view.client_intent_id {
            let previous = state.intents.get_mut(id).ok_or(())?;
            *previous = view;
        } else { state.availability = view; }
        Ok(())
    }
}

#[cfg(test)]
#[path = "notes_ui_queue_tests.rs"]
mod tests;
