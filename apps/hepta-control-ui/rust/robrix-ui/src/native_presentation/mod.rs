//! A UI-thread composition for the original App, separate from `NativeHost`.
//!
//! The caller moves its existing draft/state owner into this composition. It
//! must return the same workspace for the lifetime of the window: switching
//! between unrelated workspaces with coincident RoomKeys is not supported.
//! This port supplies neither a chat writer nor an owner/readiness witness.

use hepta_control_core::chat::ChatWorkspace;
use crate::presentation::RoomKey;
use std::sync::Arc;

/// Bounds the text passed to the original Console labels. This is an observed
/// view, never a durable transcript or an authoritative operation receipt.
pub const MAX_NATIVE_CONSOLE_BYTES: usize = 32 * 1024;

/// Original resource/notice inventory, not embedded font bytes or a rendering
/// attestation. A native caller must prepare and verify the actual files.
pub const NATIVE_RESOURCE_MANIFEST_JSON: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../hepta-native/resources/NATIVE-ASSETS.json"
));

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeConsoleObservation {
    pub text: String,
    /// A queued/in-flight refresh is not a successful Session response.
    pub refresh_pending: bool,
}

/// Controls advertised by the independent authenticated host for the current
/// room. A connected socket or observed runtime health cannot enable them.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct NativeChatAvailability {
    pub can_submit: bool,
    pub can_interrupt: bool,
}

/// Supplies one existing workspace and nonblocking observations to the original
/// App. Implementations keep the workspace stable, queue only existing read-only
/// work, and release their own client resources when the App exits.
pub trait NativeChatComposition {
    /// The original, sole active draft owner. These two borrows must refer to
    /// the same stable workspace; no copy or renderer-owned draft is created.
    fn workspace(&self) -> &ChatWorkspace;
    fn workspace_mut(&mut self) -> &mut ChatWorkspace;
    fn set_waker(&mut self, waker: Arc<dyn Fn() + Send + Sync>);
    /// Drain bounded, already-received chat events into the same workspace.
    /// Implementations must fence owner, thread and connection generations.
    fn poll_chat(&mut self) -> NativeChatAvailability {
        NativeChatAvailability::default()
    }
    /// Queue the existing host's authenticated sign/submit path. No UI key,
    /// optimistic sent entry, synchronous I/O, or replacement owner is allowed.
    fn request_send(&mut self, _source: RoomKey) -> Result<(), String> {
        Err("Authenticated chat host unavailable; draft retained".into())
    }
    /// Interrupt only the active host-bound turn; closing the window is separate.
    fn request_interrupt(&mut self, _source: RoomKey) -> Result<(), String> {
        Err("No authenticated active turn is available to interrupt".into())
    }
    /// Nonblocking: consume already received observations and evaluate age.
    /// Called outside Draw and without a live mutable workspace borrow.
    fn poll_console(&mut self) -> NativeConsoleObservation;
    /// Queue only the caller's existing read-only observation request.
    fn request_refresh(&mut self);
    /// Release this UI client's channels. This is not runtime/run cancellation.
    /// Called once, including failure before adoption or an abnormal loop exit.
    fn on_ui_exit(&mut self);
}

/// Owns cleanup even when resource setup, App creation or loop admission fails.
/// The exit flag is set before the callback, so unwinding cannot call it twice.
#[cfg(any(feature = "ui", test))]
pub(crate) struct OwnedComposition {
    pub(crate) inner: Box<dyn NativeChatComposition>,
    closed: bool,
}

#[cfg(any(feature = "ui", test))]
impl OwnedComposition {
    pub(crate) fn new(inner: Box<dyn NativeChatComposition>) -> Self {
        Self {
            inner,
            closed: false,
        }
    }

    pub(crate) fn exit(&mut self) {
        if !self.closed {
            self.closed = true;
            self.inner.on_ui_exit();
        }
    }
}

#[cfg(any(feature = "ui", test))]
impl Drop for OwnedComposition {
    fn drop(&mut self) {
        self.exit();
    }
}

#[cfg(any(feature = "ui", test))]
pub(crate) fn bounded_console(
    mut observation: NativeConsoleObservation,
) -> NativeConsoleObservation {
    const OMITTED: &str = "\n[Additional observation text omitted: native Console view limit.]";
    if observation.text.len() > MAX_NATIVE_CONSOLE_BYTES {
        let mut end = MAX_NATIVE_CONSOLE_BYTES - OMITTED.len();
        while !observation.text.is_char_boundary(end) {
            end -= 1;
        }
        observation.text.truncate(end);
        observation.text.push_str(OMITTED);
    }
    observation
}

#[cfg(feature = "ui")]
pub(crate) mod render;
#[cfg(feature = "ui")]
pub(crate) mod chat_controls;
#[cfg(all(feature = "ui", target_os = "linux"))]
pub use render::run_native_presentation;

#[cfg(test)]
#[path = "native_presentation_tests.rs"]
pub(crate) mod tests;
