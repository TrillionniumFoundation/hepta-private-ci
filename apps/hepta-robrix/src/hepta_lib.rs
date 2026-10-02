//! Robrix widgets consume original owner observations. No embedded Matrix/model owner.
pub use makepad_widgets;
#[path = "../../hepta-ui-shared/chat_transport.rs"]
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
