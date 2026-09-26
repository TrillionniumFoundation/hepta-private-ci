//! Crash-safe checkpoint and content-addressed archive generations.
//!
//! The active journal owner can compact a replayed state without truncating its
//! predecessor in place. A generation becomes visible only after its archive
//! and checkpoint are synced and an atomic `CURRENT` pointer is directory-synced.

include!("journal_generation/types.rs");
include!("journal_generation/store.rs");
include!("journal_generation/io.rs");
include!("journal_generation/tests.rs");
