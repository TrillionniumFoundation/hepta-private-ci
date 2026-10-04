//! Native presentation seam. Implementations retain their runtime/recovery
//! owner; these observations never grant chat, signer or operation authority.

use std::sync::Arc;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NativeViewIdentity {
    pub session_id: String,
    pub session_generation: u64,
    pub generation: u64,
    pub revision: u64,
    pub digest: String,
    pub modules: Vec<String>,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum NativeHostPhase {
    #[default]
    Loading,
    Connected,
    Closing,
    Closed,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NativeHostView {
    pub identity: Option<NativeViewIdentity>,
    pub status: String,
    pub phase: NativeHostPhase,
    pub can_retry_close: bool,
    pub needs_rendered_callback: bool,
}

/// Bounded observations for an external development harness. These carry no
/// input or authorization and do not replace the owner's readiness witness.
pub enum NativeRendererObservation {
    ReadinessBlocked {
        reason: &'static str,
    },
    StatusDrawList {
        identity: NativeViewIdentity,
        callback: u64,
        glyph_count: usize,
        status: String,
        status_rect: [f64; 4],
        caption_close_rect: Option<[f64; 4]>,
        inner_size: [f64; 2],
        dpi: f64,
    },
    LaterCallback {
        identity: NativeViewIdentity,
        callback: u64,
    },
    CloseRequested {
        cause: &'static str,
    },
}

/// An existing native owner adapted to the shared widgets. Every method runs
/// on the UI thread. Blocking owner work must remain supervised off that thread.
pub trait NativeHost {
    /// Install the renderer's thread-safe notification for completed workers.
    fn set_waker(&mut self, wake: Arc<dyn Fn() + Send + Sync>);
    /// Join completed workers without waiting and return a bounded observation.
    fn poll(&mut self) -> NativeHostView;
    /// Observe the exact visible identity on a distinct GUI callback. The owner
    /// must recheck that identity and its existing witness before durable I/O.
    fn observe_rendered(&mut self, identity: &NativeViewIdentity, callback: u64);
    /// Discard an earlier draw witness after geometry, visibility or draw changes.
    fn invalidate_rendered(&mut self);
    /// Record a renderer observation without modifying owner state.
    fn observe_renderer(&self, observation: NativeRendererObservation);
    /// Route all window close paths through the existing safe-shutdown owner.
    fn request_close(&mut self);
    /// Retry the same failed close without extending deadlines or enabling an update.
    fn retry_close(&mut self);
    /// Record renderer failure; it must never become a successful readiness ACK.
    fn rendering_failed(&mut self, detail: &str);
    /// Apply the original post-close activation predicate on actual renderer exit.
    fn on_exit(&mut self);
}

#[cfg(feature = "ui")]
pub(crate) mod render;

#[cfg(all(feature = "ui", target_os = "linux"))]
pub use render::run_native;
