#![recursion_limit = "256"]
//! Actual Robrix-derived Makepad UI. See UPSTREAM.json and licenses/ROBRIX-MIT.txt.
#[cfg(feature = "ui")]
pub mod app;
#[cfg(any(feature = "ui", test))]
mod chat_source;
#[cfg(all(
    feature = "ui",
    any(feature = "native-host", feature = "native-presentation")
))]
mod native_launch;
#[cfg(all(
    feature = "ui",
    not(target_arch = "wasm32"),
    any(feature = "native-host", feature = "native-presentation")
))]
mod native_resources;
#[cfg(feature = "ui")]
mod native_status;
#[cfg(feature = "ui")]
pub mod robrix;
#[cfg(feature = "ui")]
mod runtime_status;

#[cfg(any(feature = "ui", test))]
mod ime_pointer_gate;
#[cfg(feature = "ui")]
mod ime_router;
pub mod presentation;

#[cfg(feature = "ui")]
pub mod visual_theme;

#[cfg(feature = "native-host")]
pub mod native_host;
#[cfg(feature = "native-presentation")]
pub mod native_presentation;

#[cfg(feature = "ui")]
pub use makepad_widgets;
