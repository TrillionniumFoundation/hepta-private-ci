//! Bounded owner-observation projection. These values are not grants or execution receipts.
use std::collections::BTreeSet;

pub const MAX_MESSAGES: usize = 512;
pub const MAX_MESSAGE_BYTES: usize = 64 * 1024;
pub const MAX_TIMELINE_BYTES: usize = 2 * 1024 * 1024;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ViewFence {
    pub owner_session: String,
    pub generation: u64,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Role {
    User,
    Assistant,
    System,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MessagePhase {
    Observed,
    Streaming,
    Completed,
    Failed,
    Interrupted,
    Indeterminate,
}
impl MessagePhase {
    pub fn label(self) -> &'static str {
        match self {
            Self::Observed => "Observed",
            Self::Streaming => "Receiving",
            Self::Completed => "Response complete",
            Self::Failed => "Failed",
            Self::Interrupted => "Interrupted",
            Self::Indeterminate => "Outcome unknown",
        }
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Message {
    pub id: String,
    pub turn_id: String,
    pub role: Role,
    pub text: String,
    pub phase: MessagePhase,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct History {
    pub thread_id: String,
    pub title: String,
    pub revision: u64,
    pub event_sequence: u64,
    pub messages: Vec<Message>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectionError {
    Invalid,
    Limit,
    Stale,
    WrongOwner,
    WrongThread,
    Gap,
    UnknownItem,
    Conflict,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ScrollPosition {
    pub at_end: bool,
    pub new_activity: bool,
}
impl Default for ScrollPosition {
    fn default() -> Self {
        Self {
            at_end: true,
            new_activity: false,
        }
    }
}
#[derive(Clone, Debug, Default)]
pub struct Timeline {
    pub scroll: ScrollPosition,
    pub needs_resync: bool,
    fence: Option<ViewFence>,
    history: Option<History>,
    last_event: Option<(u64, String, String)>,
}
fn identifier(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}
impl Timeline {
    pub fn history(&self) -> Option<&History> {
        self.history.as_ref()
    }
    pub fn bind(&mut self, fence: ViewFence) -> Result<(), ProjectionError> {
        if !identifier(&fence.owner_session) || fence.generation == 0 {
            return Err(ProjectionError::Invalid);
        }
        if self.fence.as_ref() != Some(&fence) {
            self.history = None;
            self.last_event = None;
            self.needs_resync = false;
            self.scroll = ScrollPosition::default();
        }
        self.fence = Some(fence);
        Ok(())
    }
    pub fn replace_history(
        &mut self,
        fence: &ViewFence,
        value: History,
    ) -> Result<(), ProjectionError> {
        if self.fence.as_ref() != Some(fence) {
            return Err(ProjectionError::WrongOwner);
        }
        if !identifier(&value.thread_id) || value.title.len() > 512 || value.title.contains('\0') {
            return Err(ProjectionError::Invalid);
        }
        if value.messages.len() > MAX_MESSAGES {
            return Err(ProjectionError::Limit);
        }
        if let Some(previous) = &self.history {
            if previous.thread_id != value.thread_id {
                return Err(ProjectionError::WrongThread);
            }
            if value.revision < previous.revision || value.event_sequence < previous.event_sequence
            {
                return Err(ProjectionError::Stale);
            }
            if value.revision == previous.revision && &value != previous {
                return Err(ProjectionError::Conflict);
            }
        }
        let mut ids = BTreeSet::new();
        let mut bytes = 0usize;
        for message in &value.messages {
            if !identifier(&message.id)
                || !identifier(&message.turn_id)
                || message.text.contains('\0')
                || !ids.insert(&message.id)
            {
                return Err(ProjectionError::Invalid);
            }
            bytes = bytes
                .checked_add(message.text.len())
                .ok_or(ProjectionError::Limit)?;
            if message.text.len() > MAX_MESSAGE_BYTES || bytes > MAX_TIMELINE_BYTES {
                return Err(ProjectionError::Limit);
            }
        }
        if !self.scroll.at_end
            && self
                .history
                .as_ref()
                .is_some_and(|old| old.messages != value.messages)
        {
            self.scroll.new_activity = true;
        }
        self.history = Some(value);
        self.last_event = None;
        self.needs_resync = false;
        Ok(())
    }
    /// A delta may only extend an item previously observed from this owner/thread.
    /// A sequence gap requests authoritative history; it never silently drops data.
    pub fn delta(
        &mut self,
        fence: &ViewFence,
        thread: &str,
        item: &str,
        sequence: u64,
        delta: &str,
    ) -> Result<bool, ProjectionError> {
        if self.fence.as_ref() != Some(fence) {
            return Err(ProjectionError::WrongOwner);
        }
        let history = self.history.as_mut().ok_or(ProjectionError::UnknownItem)?;
        if history.thread_id != thread {
            return Err(ProjectionError::WrongThread);
        }
        if sequence == history.event_sequence {
            return if self
                .last_event
                .as_ref()
                .is_some_and(|last| last.0 == sequence && last.1 == item && last.2 == delta)
            {
                Ok(false)
            } else {
                Err(ProjectionError::Conflict)
            };
        }
        if sequence < history.event_sequence {
            return Err(ProjectionError::Stale);
        }
        if history.event_sequence.checked_add(1) != Some(sequence) {
            self.needs_resync = true;
            return Err(ProjectionError::Gap);
        }
        if delta.contains('\0') {
            return Err(ProjectionError::Invalid);
        }
        let total: usize = history
            .messages
            .iter()
            .map(|message| message.text.len())
            .sum();
        if total.saturating_add(delta.len()) > MAX_TIMELINE_BYTES {
            return Err(ProjectionError::Limit);
        }
        let message = history
            .messages
            .iter_mut()
            .find(|message| message.id == item)
            .ok_or(ProjectionError::UnknownItem)?;
        if message.phase != MessagePhase::Streaming {
            return Err(ProjectionError::Conflict);
        }
        if message.text.len().saturating_add(delta.len()) > MAX_MESSAGE_BYTES {
            return Err(ProjectionError::Limit);
        }
        message.text.push_str(delta);
        history.event_sequence = sequence;
        self.last_event = Some((sequence, item.into(), delta.into()));
        if !self.scroll.at_end {
            self.scroll.new_activity = true;
        }
        Ok(true)
    }
    pub fn user_scrolled(&mut self, at_end: bool) {
        self.scroll.at_end = at_end;
        if at_end {
            self.scroll.new_activity = false;
        }
    }
    pub fn jump_to_latest(&mut self) {
        self.scroll = ScrollPosition::default();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (Timeline, ViewFence, History) {
        let fence = ViewFence {
            owner_session: "fixture-owner".into(),
            generation: 7,
        };
        let history = History {
            thread_id: "fixture-thread".into(),
            title: "Fixture conversation".into(),
            revision: 1,
            event_sequence: 10,
            messages: vec![Message {
                id: "item-1".into(),
                turn_id: "turn-1".into(),
                role: Role::Assistant,
                text: "Hello".into(),
                phase: MessagePhase::Streaming,
            }],
        };
        let mut timeline = Timeline::default();
        timeline.bind(fence.clone()).unwrap();
        timeline.replace_history(&fence, history.clone()).unwrap();
        (timeline, fence, history)
    }
    #[test]
    fn streamed_unicode_is_exact_deduplicated_and_gap_requires_resync() {
        let (mut t, f, _) = fixture();
        t.user_scrolled(false);
        assert_eq!(
            t.delta(&f, "fixture-thread", "item-1", 11, " 世界"),
            Ok(true)
        );
        assert_eq!(
            t.delta(&f, "fixture-thread", "item-1", 11, " 世界"),
            Ok(false)
        );
        assert_eq!(t.history().unwrap().messages[0].text, "Hello 世界");
        assert!(t.scroll.new_activity);
        assert_eq!(
            t.delta(&f, "fixture-thread", "item-1", 11, "changed"),
            Err(ProjectionError::Conflict)
        );
        assert_eq!(
            t.delta(&f, "fixture-thread", "item-1", 13, "gap"),
            Err(ProjectionError::Gap)
        );
        assert!(t.needs_resync);
        assert_eq!(t.history().unwrap().messages[0].text, "Hello 世界");
        t.jump_to_latest();
        assert!(!t.scroll.new_activity);
    }
    #[test]
    fn stale_or_cross_owner_history_cannot_replace_observed_transcript() {
        let (mut t, f, h) = fixture();
        let original = t.history().cloned();
        let wrong = ViewFence {
            owner_session: "another".into(),
            generation: 7,
        };
        assert_eq!(
            t.replace_history(&wrong, h.clone()),
            Err(ProjectionError::WrongOwner)
        );
        let mut changed = h.clone();
        changed.messages[0].text = "different".into();
        assert_eq!(
            t.replace_history(&f, changed),
            Err(ProjectionError::Conflict)
        );
        assert_eq!(t.history().cloned(), original);
        t.bind(ViewFence {
            owner_session: f.owner_session,
            generation: 8,
        })
        .unwrap();
        assert!(t.history().is_none());
        assert_eq!(
            t.delta(&wrong, "fixture-thread", "item-1", 11, "late"),
            Err(ProjectionError::WrongOwner)
        );
    }
    #[test]
    fn oversized_history_and_unknown_delta_are_atomic_rejections() {
        let (mut t, f, mut h) = fixture();
        h.revision = 2;
        h.messages[0].text = "界".repeat(MAX_MESSAGE_BYTES);
        assert_eq!(t.replace_history(&f, h), Err(ProjectionError::Limit));
        assert_eq!(t.history().unwrap().messages[0].text, "Hello");
        assert_eq!(
            t.delta(&f, "fixture-thread", "not-started", 11, "x"),
            Err(ProjectionError::UnknownItem)
        );
        assert_eq!(t.history().unwrap().event_sequence, 10);
    }
}
