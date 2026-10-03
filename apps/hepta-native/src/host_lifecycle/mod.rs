//! Renderer-neutral pieces of the existing native host lifecycle.
//!
//! These types coordinate presentation with the retained native owners. They
//! confer no authority, start no alternate runtime, and own no persistent state.
//! The current GUI remains the caller until another renderer is composed.

pub(crate) mod controller;
pub(crate) mod readiness;
pub(crate) mod shutdown;
pub(crate) mod task;

#[cfg(test)]
#[path = "lifecycle_tests.rs"]
mod tests;
