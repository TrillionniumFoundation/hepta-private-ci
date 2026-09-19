//! Shared bounded-capacity limits for the learning-artifact owner.
//!
//! These ceilings are part of the durable format contract: an in-memory state
//! accepted by this crate must remain representable by its corresponding
//! create-only snapshot writer.

pub const MAX_REGISTRY_RECORDS: usize = 4_096;
pub const MAX_WITHDRAWAL_RECORDS: usize = 4_096;
pub const MAX_LIFECYCLE_RECORDS: usize = 4_096;
