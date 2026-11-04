//! Presentation port for an explicitly installed original Objective owner.
//! These values are observations and callback bindings, never grants or signatures.

use crate::chat_owner::OwnerScope;
use sha2::Digest;
use sha2::Sha256;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectiveUiBinding {
    pub owner: OwnerScope,
    pub owner_expires_at_ms: u64,
    pub window_id: String,
    pub window_generation: u64,
    pub presentation_epoch: u64,
    pub room: u64,
    pub draft_sha256: [u8; 32],
}

impl ObjectiveUiBinding {
    pub fn valid(&self) -> bool {
        !self.window_id.is_empty()
            && self.window_id.len() <= 128
            && !self.window_id.chars().any(char::is_control)
            && self.window_generation > 0
            && self.owner_expires_at_ms > 0
            && self.draft_sha256 != [0; 32]
    }

    /// Correlation identity that the independent issuer must already have signed
    /// in the original Objective body. This helper neither signs nor authorizes.
    /// Length framing prevents ambiguous concatenation of owner/window strings.
    pub fn original_run_id(&self) -> String {
        let mut hash = Sha256::new();
        hash.update(b"hepta:desktop-objective-binding:v1\0");
        for value in [
            &self.owner.principal_id,
            &self.owner.session_id,
            &self.owner.agent_id,
            &self.owner.thread_id,
            &self.window_id,
        ] {
            hash.update((value.len() as u64).to_be_bytes());
            hash.update(value.as_bytes());
        }
        for value in [
            self.owner.connection_generation,
            self.owner.permission_revision,
            self.owner.agent_generation,
            self.window_generation,
            self.presentation_epoch,
            self.room,
            self.owner_expires_at_ms,
        ] {
            hash.update(value.to_be_bytes());
        }
        hash.update(self.draft_sha256);
        format!("objective.ui.{:x}", hash.finalize())
    }

    pub fn matches_draft(&self, text: &str) -> bool {
        !text.is_empty()
            && text.len() <= crate::chat::MAX_DRAFT_BYTES
            && !text.contains('\0')
            && <[u8; 32]>::from(Sha256::digest(text.as_bytes())) == self.draft_sha256
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectiveUiCommand {
    Submit,
    Cancel,
    Refresh,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectiveUiRequest {
    Queued,
    Existing,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectiveUiError {
    Unavailable,
    Binding,
    DraftChanged,
    Retired,
    Busy,
}

impl ObjectiveUiError {
    pub fn label(self) -> &'static str {
        match self {
            Self::Unavailable => "The original request owner is unavailable.",
            Self::Binding => "This action belongs to another owner session or window.",
            Self::DraftChanged => "The draft changed; independent request preparation is required.",
            Self::Retired => "This owner session or window has closed.",
            Self::Busy => "An owner request is pending. No additional request was queued.",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectiveUiPhase {
    Prepared,
    Submitting,
    Unknown,
    Published,
    Abstained,
    Conflict,
    LocalCancelled,
    Cancelling,
    CancelledBeforeDispatch,
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
    Closed,
}

impl ObjectiveUiPhase {
    pub fn label(self) -> &'static str {
        match self {
            Self::Prepared => "An independently authorized request is ready.",
            Self::Submitting => "Waiting for owner admission; completion is not yet known.",
            Self::Unknown => {
                "The outcome is unknown. Refresh the original request without sending again."
            }
            Self::Published => "Request admitted; no completed response has been observed.",
            Self::Abstained => "The owner declined to execute this objective.",
            Self::Conflict => "The owner reported an objective conflict.",
            Self::LocalCancelled => "Cancelled before the original request was dispatched.",
            Self::Cancelling => "Cancellation requested; waiting for terminal acknowledgement.",
            Self::CancelledBeforeDispatch => "The owner acknowledged cancellation before dispatch.",
            Self::Succeeded => "The runtime reported success.",
            Self::Failed => "The runtime reported failure.",
            Self::Cancelled => "The runtime reported cancellation.",
            Self::Indeterminate => "The runtime outcome is indeterminate.",
            Self::Closed => "This owner session or window is closed.",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ObjectiveUiPublication {
    Compiled,
    Abstained,
    Conflict,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectiveUiObservation {
    pub binding: ObjectiveUiBinding,
    pub sequence: u64,
    pub phase: ObjectiveUiPhase,
    pub retained_publication: Option<ObjectiveUiPublication>,
    pub can_cancel: bool,
    pub can_refresh: bool,
}

/// The trusted host owns the original sender and a bounded asynchronous worker.
/// All methods here must be nonblocking. Raw requests, issuer keys, signatures,
/// database handles and recovered sending permissions never enter the renderer.
pub trait ObjectiveUiPort: Send {
    fn binding(&self) -> &ObjectiveUiBinding;
    fn request(
        &mut self,
        command: ObjectiveUiCommand,
        presentation_epoch: u64,
        room: u64,
        draft: &str,
    ) -> Result<ObjectiveUiRequest, ObjectiveUiError>;
    fn poll(&mut self) -> Option<ObjectiveUiObservation>;
    /// Retire this window's callbacks. This does not cancel an admitted run.
    fn close(&mut self);
}
