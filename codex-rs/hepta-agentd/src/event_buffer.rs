use std::collections::VecDeque;

use crate::AgentdError;
use crate::AgentdEvent;
use crate::AgentdEventKind;
use crate::EventBatch;

pub(crate) struct EventBuffer {
    capacity: usize,
    next_cursor: u64,
    events: VecDeque<AgentdEvent>,
}

impl EventBuffer {
    pub(crate) fn new(capacity: usize) -> Result<Self, AgentdError> {
        if !(1..=4_096).contains(&capacity) {
            return Err(AgentdError::Invalid(
                "agentd event capacity must be between 1 and 4096".to_string(),
            ));
        }
        Ok(Self {
            capacity,
            next_cursor: 1,
            events: VecDeque::with_capacity(capacity),
        })
    }

    pub(crate) fn push(&mut self, kind: AgentdEventKind) {
        let cursor = self.next_cursor;
        self.next_cursor = self.next_cursor.saturating_add(1);
        if self.events.len() == self.capacity {
            self.events.pop_front();
        }
        self.events.push_back(AgentdEvent { cursor, kind });
    }

    pub(crate) fn batch(&self, after_cursor: u64, limit: usize) -> EventBatch {
        let oldest_cursor = self
            .events
            .front()
            .map_or(self.next_cursor, |event| event.cursor);
        let gap = after_cursor.saturating_add(1) < oldest_cursor;
        let floor = if gap {
            oldest_cursor.saturating_sub(1)
        } else {
            after_cursor
        };
        let events: Vec<_> = self
            .events
            .iter()
            .filter(|event| event.cursor > floor)
            .take(limit)
            .cloned()
            .collect();
        let next_cursor = events.last().map_or(floor, |event| event.cursor);
        EventBatch {
            events,
            gap,
            next_cursor,
            latest_cursor: self.next_cursor.saturating_sub(1),
        }
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_fleet::AgentLifecycle;

    use super::*;

    #[test]
    fn bounded_buffer_reports_cursor_gap_and_resumes() {
        let mut buffer = EventBuffer::new(2).expect("valid event buffer");
        for generation in 1..=3 {
            buffer.push(AgentdEventKind::Lifecycle {
                lifecycle: AgentLifecycle::Running,
                generation,
            });
        }

        let first = buffer.batch(0, 1);
        assert!(first.gap);
        assert_eq!(first.events.len(), 1);
        assert_eq!(first.events[0].cursor, 2);
        assert_eq!(first.next_cursor, 2);
        assert_eq!(first.latest_cursor, 3);

        let resumed = buffer.batch(first.next_cursor, 2);
        assert!(!resumed.gap);
        assert_eq!(resumed.events.len(), 1);
        assert_eq!(resumed.events[0].cursor, 3);
    }
}
