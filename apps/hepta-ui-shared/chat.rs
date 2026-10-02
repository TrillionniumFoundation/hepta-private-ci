//! Canonical, authority-free messaging presentation contract for every Rust host.
//! Hosts supply authenticated observations. Local drafts never imply delivery.

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum AppTab {
    #[default]
    Chat,
    Console,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ChatAvailability {
    #[default]
    Unavailable,
    Loading,
    Ready,
    Offline,
    Failed,
}

impl ChatAvailability {
    pub fn label(self) -> &'static str {
        match self {
            Self::Unavailable => "Messaging is not connected",
            Self::Loading => "Loading conversations…",
            Self::Ready => "Messaging connected",
            Self::Offline => "Messaging is offline",
            Self::Failed => "Conversations could not be loaded",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Conversation {
    pub id: String,
    pub title: String,
    pub preview: String,
    pub unread: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Message {
    pub id: String,
    pub sender: String,
    pub body: String,
    pub timestamp: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ChatState {
    pub tab: AppTab,
    pub availability: ChatAvailability,
    pub conversations: Vec<Conversation>,
    pub selected: Option<String>,
    pub messages: Vec<Message>,
    pub draft: String,
    pub filter: String,
    pub sending: bool,
    pub drafts: std::collections::BTreeMap<String, String>,
    pub selection_epoch: u64,
}

impl ChatState {
    pub fn select(&mut self, id: &str) -> bool {
        if !self.conversations.iter().any(|room| room.id == id) {
            return false;
        }
        if self.selected.as_deref() != Some(id) {
            if let Some(previous) = &self.selected {
                self.drafts.insert(previous.clone(), self.draft.clone());
            }
            self.selected = Some(id.to_owned());
            self.selection_epoch = self.selection_epoch.saturating_add(1);
            self.messages.clear();
            self.draft = self.drafts.get(id).cloned().unwrap_or_default();
        }
        self.tab = AppTab::Chat;
        true
    }

    pub fn visible_conversations(&self) -> impl Iterator<Item = &Conversation> {
        let filter = self.filter.trim().to_lowercase();
        self.conversations.iter().filter(move |room| {
            room.title.to_lowercase().contains(&filter) || room.id.to_lowercase().contains(&filter)
        })
    }

    /// Ignore late responses from a previous room or selection.
    pub fn observe_messages(&mut self, room: &str, epoch: u64, messages: Vec<Message>) -> bool {
        if self.selected.as_deref() != Some(room) || self.selection_epoch != epoch {
            return false;
        }
        self.messages = messages.into_iter().take(200).collect();
        true
    }

    pub fn can_send(&self) -> bool {
        self.availability == ChatAvailability::Ready
            && self
                .selected
                .as_ref()
                .is_some_and(|id| self.conversations.iter().any(|r| &r.id == id))
            && !self.sending
            && !self.draft.trim().is_empty()
            && self.draft.chars().count() <= 4096
    }

    /// Session replacement clears private content, selection, and unsent text together.
    pub fn reset_session(&mut self) {
        let tab = self.tab;
        *self = Self {
            tab,
            ..Self::default()
        };
    }
}

/// Shared geometry is in logical pixels; adapters may scale with user font size.
pub mod design {
    pub const RAIL_WIDTH: f32 = 64.0;
    pub const ROOMS_WIDTH: f32 = 280.0;
    pub const HEADER_HEIGHT: f32 = 64.0;
    pub const CONTROL_HEIGHT: f32 = 44.0;
    pub const COMPACT_WIDTH: f32 = 760.0;
    pub const BACKGROUND: [u8; 3] = [10, 15, 24];
    pub const SURFACE: [u8; 3] = [17, 25, 38];
    pub const BORDER: [u8; 3] = [53, 72, 96];
    pub const TEXT: [u8; 3] = [230, 237, 247];
    pub const MUTED: [u8; 3] = [166, 183, 205];
    pub const ACCENT: [u8; 3] = [105, 224, 232];
}
