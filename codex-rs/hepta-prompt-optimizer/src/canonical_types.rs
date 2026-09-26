//! Internal migration shim for the first sealed-canonical split.
//!
//! This file contains no independent contracts or implementation. It keeps the
//! exercise/codec slices source-compatible while all semantics live in
//! `canonical_error.rs` and the sealed stage modules.

pub(crate) use super::error::CanonicalPromptError;
pub(crate) use super::error::PromptStaleReasonV1;
pub(crate) use super::error::ensure_digest;
pub(crate) use super::error::push_id;
