#![forbid(unsafe_code)]

pub mod backend;
pub mod error;
pub mod journal;
mod journal_storage;
pub mod model;
pub mod platform;
pub mod private_state;
pub mod qualification;
pub mod runtime;
pub mod security;
pub mod session_store;
pub mod ui;
pub mod updater;

pub use runtime::NativeShellRuntime;

pub mod file_input;

mod native_http;

pub mod update_handoff;
mod update_storage;

pub mod fonts;
pub mod launch_config;
pub mod startup;

// Snapshot research tests are not a production capability handoff.
#[cfg(test)]
mod resource;

mod retirement;

#[cfg(test)]
mod storage_qualification_tests;
