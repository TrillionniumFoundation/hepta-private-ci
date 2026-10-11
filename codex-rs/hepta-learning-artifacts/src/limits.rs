//! Shared resource ceilings for state that the crate promises can be durably represented.

/// Maximum number of records accepted by artifact, withdrawal and lifecycle
/// state machines that are covered by the canonical bounded snapshot adapters.
/// Keeping the logical ceiling equal to the durable ceiling prevents an
/// in-memory state from becoming impossible to persist after it was accepted.
pub const MAX_DURABLE_ARTIFACT_RECORDS: usize = 4_096;
