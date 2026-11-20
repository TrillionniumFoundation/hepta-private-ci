//! Non-authorizing typed receipt evidence retained by the original journal.
//! Parsing is always selected by its immutable topic, never response content.

use crate::LocalReconcileOutcome;
use crate::production_desktop::DesktopTerminalReceipt;
use crate::production_notes::NotesTerminalReceipt;

pub(crate) enum PrivateOrganTerminalReceipt {
    Notes(NotesTerminalReceipt),
    Desktop(DesktopTerminalReceipt),
}

impl PrivateOrganTerminalReceipt {
    pub(crate) fn from_json(topic: &str, payload: &str, evidence: &str) -> Result<Self, String> {
        match topic {
            crate::NOTES_REPLACE_TOPIC_V1 => {
                NotesTerminalReceipt::from_json(payload, evidence).map(Self::Notes)
            }
            crate::DESKTOP_INPUT_TOPIC_V1 => {
                DesktopTerminalReceipt::from_json(payload, evidence).map(Self::Desktop)
            }
            _ => Err("typed private organ receipt targets another topic".into()),
        }
    }
    pub(crate) fn outcome(&self) -> LocalReconcileOutcome {
        match self {
            Self::Notes(v) => v.outcome(),
            Self::Desktop(v) => v.outcome(),
        }
    }
    pub(crate) fn as_str(&self) -> &str {
        match self {
            Self::Notes(v) => v.as_str(),
            Self::Desktop(v) => v.as_str(),
        }
    }
    pub(crate) fn matches(&self, topic: &str, payload: &str) -> Result<(), String> {
        match (self, topic) {
            (Self::Notes(v), crate::NOTES_REPLACE_TOPIC_V1) => v.matches(payload),
            (Self::Desktop(v), crate::DESKTOP_INPUT_TOPIC_V1) => v.matches(payload),
            _ => Err("typed receipt family does not match immutable outbox".into()),
        }
    }
}
