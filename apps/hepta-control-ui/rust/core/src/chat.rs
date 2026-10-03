//! Authority-free chat presentation. A local draft is never a sent message.
use std::collections::BTreeMap;

pub const MAX_DRAFT_BYTES: usize = 16 * 1024;
pub const MAX_LOCAL_DRAFTS: usize = 16;
pub const COMPACT_WIDTH: f32 = 760.0;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum WorkspaceTab {
    #[default]
    Conversations,
    Console,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Appearance {
    #[default]
    Dark,
    Light,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ComposeStatus {
    LocalDraft,
    InputLimit,
    TransportUnavailable,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Draft {
    pub title: String,
    pub text: String,
    pub status: ComposeStatus,
}

/// Host-independent transient presentation, never a transport/recovery owner.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HistoryTicket {
    room: u64,
    thread: String,
    fence: crate::chat_timeline::ViewFence,
    serial: u64,
}

#[derive(Default)]
struct DraftPartition {
    active: u64,
    next: u64,
    drafts: BTreeMap<u64, Draft>,
}

pub struct ChatWorkspace {
    pub tab: WorkspaceTab,
    pub appearance: Appearance,
    pub navigation_open: bool,
    pub filter: String,
    pub composing: bool,
    pub presentation_note: Option<String>,
    active: u64,
    next: u64,
    drafts: BTreeMap<u64, Draft>,
    timelines: BTreeMap<u64, crate::chat_timeline::Timeline>,
    bindings: BTreeMap<u64, HistoryTicket>,
    request_serial: u64,
    owner: crate::chat_owner::ChatOwnerAdapter,
    authorized: BTreeMap<u64, crate::chat_owner::SignedTextRef>,
    draft_principal: Option<String>,
    parked_drafts: BTreeMap<Option<String>, DraftPartition>,
    presentation_epoch: u64,
}

impl Default for ChatWorkspace {
    fn default() -> Self {
        let mut value = Self {
            tab: WorkspaceTab::Conversations,
            appearance: Appearance::Dark,
            navigation_open: false,
            filter: String::new(),
            composing: false,
            presentation_note: None,
            active: 0,
            next: 1,
            drafts: BTreeMap::new(),
            timelines: BTreeMap::new(),
            bindings: BTreeMap::new(),
            request_serial: 0,
            owner: crate::chat_owner::ChatOwnerAdapter::default(),
            authorized: BTreeMap::new(),
            draft_principal: None,
            parked_drafts: BTreeMap::new(),
            presentation_epoch: 0,
        };
        value.drafts.insert(
            0,
            Draft {
                title: "New conversation".into(),
                text: String::new(),
                status: ComposeStatus::LocalDraft,
            },
        );
        value
    }
}

impl ChatWorkspace {
    /// Both host renderers consume this real adapter availability. A prepared
    /// envelope still requires a configured independent host to dispatch it.
    pub fn owner_status(&self, now_ms: u64) -> &'static str {
        use crate::chat_owner::{ChatCapability, ChatOwnerError, DeliveryState};
        if let Some(delivery) = self.delivery_for(self.active, now_ms) {
            if !delivery.fresh
                && delivery.state != DeliveryState::Sending
                && delivery.state != DeliveryState::Unknown
            {
                return "Last owner delivery observation is stale; current outcome is unconfirmed";
            }
            return match delivery.state {
                DeliveryState::Sending => "Waiting for owner admission; not delivered",
                DeliveryState::Unknown => {
                    "Outcome unknown; recover with the original owner identity"
                }
                DeliveryState::Queued => "Queued by owner; no model completion observed",
                DeliveryState::Leased => "Owner relay in progress; no model completion observed",
                DeliveryState::QueueAccepted => "Accepted by owner queue; not a completed response",
                DeliveryState::Expired => "Owner delivery expired; no target absence inferred",
                DeliveryState::Quarantined => {
                    "Owner quarantined delivery; target acceptance may be unknown"
                }
            };
        }
        match self
            .owner
            .require_capability(ChatCapability::SubmitSignedText, now_ms)
        {
            Err(ChatOwnerError::Unavailable) => "Local draft · chat owner unavailable",
            Err(ChatOwnerError::Expired) => {
                "Chat owner session expired; re-authentication is required"
            }
            Err(_) => "Current owner does not authorize this chat action",
            Ok(_) if !self.authorized.contains_key(&self.active) => {
                "Independent message authorization is required before dispatch"
            }
            Ok(_) => "Authorized envelope prepared; an independent host must dispatch it",
        }
    }

    /// Host-injected authenticated context; never derived from Console credentials.
    pub fn install_owner(
        &mut self,
        session: crate::chat_owner::OwnerSession,
        now_ms: u64,
    ) -> Result<(), crate::chat_owner::ChatOwnerError> {
        let principal = session.scope.principal_id.clone();
        self.authorized.clear();
        self.timelines.clear();
        self.bindings.clear();
        self.presentation_epoch = self.presentation_epoch.saturating_add(1);
        self.composing = false;
        if let Err(error) = self.owner.install_owner(session, now_ms) {
            let _ = self.activate_draft_principal(None);
            return Err(error);
        }
        if let Err(error) = self.activate_draft_principal(Some(principal)) {
            self.owner.disconnect();
            let _ = self.activate_draft_principal(None);
            return Err(error);
        }
        Ok(())
    }
    pub fn presentation_epoch(&self) -> u64 {
        self.presentation_epoch
    }
    pub fn disconnect_owner(&mut self) {
        self.presentation_epoch = self.presentation_epoch.saturating_add(1);
        self.composing = false;
        self.authorized.clear();
        self.timelines.clear();
        self.bindings.clear();
        self.owner.disconnect();
        let _ = self.activate_draft_principal(None);
    }
    fn activate_draft_principal(
        &mut self,
        principal: Option<String>,
    ) -> Result<(), crate::chat_owner::ChatOwnerError> {
        if self.draft_principal == principal {
            return Ok(());
        }
        if !self.parked_drafts.contains_key(&principal) && self.parked_drafts.len() >= 4 {
            return Err(crate::chat_owner::ChatOwnerError::Capacity);
        }
        let current = DraftPartition {
            active: self.active,
            next: self.next,
            drafts: std::mem::take(&mut self.drafts),
        };
        self.parked_drafts
            .insert(self.draft_principal.clone(), current);
        let mut next = self.parked_drafts.remove(&principal).unwrap_or_default();
        if next.drafts.is_empty() {
            next.next = 1;
            next.active = 0;
            next.drafts.insert(
                0,
                Draft {
                    title: "New conversation".into(),
                    text: String::new(),
                    status: ComposeStatus::LocalDraft,
                },
            );
        }
        self.active = next.active;
        self.next = next.next;
        self.drafts = next.drafts;
        self.draft_principal = principal;
        self.filter.clear();
        self.presentation_note = None;
        self.navigation_open = false;
        self.composing = false;
        Ok(())
    }

    /// The host retains the actual independently signed envelope. Only its opaque
    /// exact-text reference enters shared presentation; no key or signature does.
    pub fn stage_authorized_text(
        &mut self,
        room: u64,
        envelope: crate::chat_owner::SignedTextRef,
    ) -> Result<(), crate::chat_owner::ChatOwnerError> {
        use crate::chat_owner::ChatOwnerError as E;
        let draft = self.drafts.get(&room).ok_or(E::InvalidInput)?;
        let binding = self.bindings.get(&room).ok_or(E::Unavailable)?;
        if draft.text != envelope.text()
            || binding.thread != envelope.scope().thread_id
            || binding.fence.owner_session != envelope.scope().session_id
            || binding.fence.generation != envelope.scope().connection_generation
        {
            return Err(E::BindingMismatch);
        }
        self.authorized.insert(room, envelope);
        Ok(())
    }
    pub fn begin_authorized_submit(
        &mut self,
        room: u64,
        now_ms: u64,
    ) -> Result<crate::chat_owner::SubmissionAdmission, crate::chat_owner::ChatOwnerError> {
        use crate::chat_owner::ChatOwnerError as E;
        let envelope = self.authorized.get(&room).ok_or(E::Unavailable)?;
        if self
            .drafts
            .get(&room)
            .is_none_or(|draft| draft.text != envelope.text())
        {
            return Err(E::BindingMismatch);
        }
        self.owner.begin_submit(envelope.clone(), now_ms)
    }
    pub fn observe_delivery(
        &mut self,
        ticket: &crate::chat_owner::DispatchTicket,
        response: crate::chat_owner::OwnerDeliveryObservation,
        now_ms: u64,
    ) -> Result<crate::chat_owner::DeliveryView, crate::chat_owner::ChatOwnerError> {
        self.owner.observe_response(ticket, response, now_ms)
    }
    pub fn delivery_unknown(
        &mut self,
        ticket: &crate::chat_owner::DispatchTicket,
    ) -> Result<(), crate::chat_owner::ChatOwnerError> {
        self.owner.mark_unknown(ticket)
    }
    pub fn retry_exact_initial(
        &mut self,
        message_id: &str,
        now_ms: u64,
    ) -> Result<crate::chat_owner::SubmissionAdmission, crate::chat_owner::ChatOwnerError> {
        self.owner.retry_same_envelope(message_id, now_ms)
    }
    pub fn delivery_for(&self, room: u64, now_ms: u64) -> Option<&crate::chat_owner::DeliveryView> {
        let reference = self.authorized.get(&room)?;
        self.owner.view(&reference.metadata().message_id, now_ms)
    }

    pub fn timeline(&self) -> Option<&crate::chat_timeline::Timeline> {
        self.timelines.get(&self.active)
    }
    pub fn begin_history(
        &mut self,
        room: u64,
        thread: &str,
        fence: crate::chat_timeline::ViewFence,
    ) -> Result<HistoryTicket, crate::chat_timeline::ProjectionError> {
        use crate::chat_timeline::ProjectionError as E;
        if !self.drafts.contains_key(&room)
            || thread.is_empty()
            || thread.len() > 256
            || thread.chars().any(char::is_control)
        {
            return Err(E::Invalid);
        }
        if self
            .bindings
            .get(&room)
            .is_some_and(|old| old.thread != thread)
        {
            return Err(E::WrongThread);
        }
        self.request_serial = self.request_serial.checked_add(1).ok_or(E::Limit)?;
        let ticket = HistoryTicket {
            room,
            thread: thread.into(),
            fence: fence.clone(),
            serial: self.request_serial,
        };
        self.timelines.entry(room).or_default().bind(fence)?;
        self.bindings.insert(room, ticket.clone());
        Ok(ticket)
    }
    pub fn receive_history(
        &mut self,
        ticket: &HistoryTicket,
        history: crate::chat_timeline::History,
    ) -> Result<(), crate::chat_timeline::ProjectionError> {
        use crate::chat_timeline::ProjectionError as E;
        if self.bindings.get(&ticket.room) != Some(ticket) {
            return Err(E::Stale);
        }
        if history.thread_id != ticket.thread {
            return Err(E::WrongThread);
        }
        self.timelines
            .get_mut(&ticket.room)
            .ok_or(E::UnknownItem)?
            .replace_history(&ticket.fence, history)
    }
    pub fn receive_delta(
        &mut self,
        ticket: &HistoryTicket,
        item: &str,
        sequence: u64,
        delta: &str,
    ) -> Result<bool, crate::chat_timeline::ProjectionError> {
        use crate::chat_timeline::ProjectionError as E;
        if self.bindings.get(&ticket.room) != Some(ticket) {
            return Err(E::Stale);
        }
        self.timelines
            .get_mut(&ticket.room)
            .ok_or(E::UnknownItem)?
            .delta(&ticket.fence, &ticket.thread, item, sequence, delta)
    }
    pub fn user_scrolled(&mut self, room: u64, at_end: bool) {
        if let Some(timeline) = self.timelines.get_mut(&room) {
            timeline.user_scrolled(at_end);
        }
    }
    pub fn jump_to_latest(&mut self, room: u64) {
        if let Some(timeline) = self.timelines.get_mut(&room) {
            timeline.jump_to_latest();
        }
    }
    pub fn can_create_draft(&self) -> bool {
        !self.composing && self.drafts.len() < MAX_LOCAL_DRAFTS
    }

    pub fn has_history(&self, id: u64) -> bool {
        self.timelines
            .get(&id)
            .and_then(|timeline| timeline.history())
            .is_some()
    }
    pub fn title_for(&self, id: u64) -> Option<&str> {
        self.timelines
            .get(&id)
            .and_then(|timeline| timeline.history())
            .map(|history| history.title.as_str())
            .or_else(|| self.drafts.get(&id).map(|draft| draft.title.as_str()))
    }
    pub fn drafts(&self) -> impl Iterator<Item = (u64, &Draft)> {
        self.drafts.iter().map(|(id, draft)| (*id, draft))
    }
    pub fn active_id(&self) -> u64 {
        self.active
    }
    pub fn draft(&self) -> &Draft {
        &self.drafts[&self.active]
    }
    pub fn select(&mut self, id: u64) -> bool {
        if !self.drafts.contains_key(&id) || self.composing {
            return false;
        }
        self.active = id;
        self.navigation_open = false;
        true
    }
    pub fn new_draft(&mut self) -> bool {
        if self.composing || self.drafts.len() >= MAX_LOCAL_DRAFTS {
            return false;
        }
        let Some(next) = self.next.checked_add(1) else {
            return false;
        };
        self.active = self.next;
        self.next = next;
        self.drafts.insert(
            self.active,
            Draft {
                title: "New conversation".into(),
                text: String::new(),
                status: ComposeStatus::LocalDraft,
            },
        );
        self.navigation_open = false;
        true
    }
    pub fn edit(&mut self, text: String) -> bool {
        let draft = self
            .drafts
            .get_mut(&self.active)
            .expect("selected local draft");
        if text.len() > MAX_DRAFT_BYTES || text.contains('\0') {
            draft.status = ComposeStatus::InputLimit;
            return false;
        }
        draft.title = text
            .lines()
            .find(|line| !line.trim().is_empty())
            .map(|line| line.trim().chars().take(48).collect())
            .unwrap_or_else(|| "New conversation".into());
        draft.text = text;
        draft.status = ComposeStatus::LocalDraft;
        true
    }
    pub fn clear(&mut self) -> bool {
        if self.composing {
            return false;
        }
        self.edit(String::new())
    }
    /// No authenticated chat backend is composed by either current host.
    /// This method never queues an operation, clears a draft or creates a message.
    pub fn request_send(&mut self) -> bool {
        if !self.composing {
            self.drafts
                .get_mut(&self.active)
                .expect("selected local draft")
                .status = ComposeStatus::TransportUnavailable;
        }
        false
    }
}

#[cfg(test)]
#[path = "chat/basic_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "chat/integration_tests.rs"]
mod integration_tests;

#[cfg(test)]
#[path = "chat/partition_tests.rs"]
mod partition_tests;

#[cfg(feature = "ui-fixtures")]
pub mod fixtures;
