//! Durable pilot limits shared by in-memory owners and snapshot adapters.
//!
//! Owner state must never accept a mutation that the crate's canonical durable
//! format cannot represent. Hosts may impose stricter limits.

pub const MAX_DURABLE_ARTIFACT_RECORDS: usize = 4096;
pub const MAX_DURABLE_ARTIFACT_SNAPSHOT_BYTES: usize = 8 * 1024 * 1024;
