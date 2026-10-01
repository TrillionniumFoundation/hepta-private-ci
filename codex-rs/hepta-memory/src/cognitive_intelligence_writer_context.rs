use crate::StableMemoryId;

/// The immutable memory head targeted by one caller-owned CAS transaction.
/// Grouping this identity does not validate or authorize the correction.
pub(crate) struct MemoryCorrectionTarget<'a> {
    pub(crate) memory_id: &'a StableMemoryId,
    pub(crate) expected_revision: u64,
}
