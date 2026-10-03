#![recursion_limit = "256"]
//! Actual Robrix-derived Makepad UI. See UPSTREAM.json and licenses/ROBRIX-MIT.txt.
#[cfg(feature = "ui")]
pub mod app;
#[cfg(feature = "ui")]
pub mod robrix;

pub mod presentation;

#[cfg(feature = "ui")]
pub mod visual_theme;
