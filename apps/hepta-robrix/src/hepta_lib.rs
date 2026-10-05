//! Robrix widgets consume original owner observations. No embedded Matrix/model owner.
#[cfg(not(target_arch = "wasm32"))]
pub use hepta_native::chat_protocol::wire as chat_transport;
pub use makepad_widgets;
#[cfg(target_arch = "wasm32")]
#[path = "../../../codex-rs/hepta-contracts/src/chat_transport.rs"]
pub mod chat_transport;
pub mod hepta_app;
// Presentation-only upstream Robrix styles and controls. Its Matrix client,
// login, persistence and model modules are not compiled by this renderer.
#[cfg(not(target_arch = "wasm32"))]
mod hepta_owner_worker;
#[path = "shared/icon_button.rs"]
mod owner_icon_button;
#[path = "shared/styles.rs"]
mod owner_styles;
