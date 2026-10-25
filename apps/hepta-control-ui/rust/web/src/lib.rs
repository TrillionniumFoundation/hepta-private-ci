#![forbid(unsafe_code)]
//! Semantic browser host for the shared authority-free Rust control core.

#[cfg(target_arch = "wasm32")]
mod app;
#[cfg(target_arch = "wasm32")]
mod dom;
#[cfg(any(test, target_arch = "wasm32"))]
pub mod recovery;
#[cfg(any(test, target_arch = "wasm32"))]
pub mod transport;

#[cfg(target_arch = "wasm32")]
pub use app::close_session;
#[cfg(target_arch = "wasm32")]
pub use app::destroy;
#[cfg(target_arch = "wasm32")]
pub use app::read_view;
#[cfg(target_arch = "wasm32")]
pub use app::reconnect;
#[cfg(target_arch = "wasm32")]
pub use app::start;
