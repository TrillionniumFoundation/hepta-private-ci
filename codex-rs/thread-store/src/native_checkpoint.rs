//! Non-model pending state owned by the selected thread store.
//!
//! These records correlate existing authority; neither a record nor its hash
//! authorizes a model request, tool dispatch, generation change, or lease takeover.

use std::sync::Arc;

use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;

use crate::ThreadStoreFuture;
use crate::ThreadStoreResult;

/// Immutable original-operation binding, including its original generation/lease.
/// These are not the current writer's generation or lease. Recovery retains them;
/// the host separately supplies current authority to observe/settle this operation.
/// `lease_id` is correlation, never a serialized lease token.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeCheckpointBinding {
    pub thread_id: ThreadId,
    pub turn_id: String,
    pub operation_id: String,
    pub generation: u64,
    pub lease_id: String,
}

/// A complete, bounded native state encoding under its original binding.
/// The embedding codec must validate its own typed payload on recovery.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeCheckpointState {
    pub binding: NativeCheckpointBinding,
    pub payload: Vec<u8>,
}

/// Exact compare-and-swap head of one checkpoint chain.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeCheckpointVersion {
    pub revision: u64,
    pub sha256: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeCheckpointExpected {
    Absent,
    Version(NativeCheckpointVersion),
}

/// Recovery never initializes a missing database or treats a missing record as new work.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NativeCheckpointOpenMode {
    Create,
    Recover,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredNativeCheckpoint {
    pub rollout_id: ThreadId,
    pub version: NativeCheckpointVersion,
    pub state: NativeCheckpointState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeCheckpointLoad {
    Missing,
    Present(StoredNativeCheckpoint),
}

/// Keeps an existing host-owned fence/lease guard alive through the storage commit.
/// The host supplies the guard; constructing this wrapper does not validate authority.
/// It is intentionally neither serializable nor cloneable.
pub struct NativeCheckpointPermit<'a> {
    _guard: Box<dyn Send + 'a>,
}

impl<'a> NativeCheckpointPermit<'a> {
    pub fn hold<T: Send + 'a>(guard: T) -> Self {
        Self {
            _guard: Box::new(guard),
        }
    }
}

/// Existing host authority supplies a permit for the exact original binding.
///
/// An implementation must check its live generation and lease, retaining any
/// owner-provided fence in the returned permit until it is dropped. A transient
/// boolean check cannot promise atomic production revocation. This storage seam
/// never replaces FinalUse at the later physical model/tool entry.
/// Acquisition runs inside the store's writer fence and must not reenter that writer.
pub trait NativeCheckpointCurrentness: Send + Sync {
    fn acquire<'a>(
        &'a self,
        binding: &'a NativeCheckpointBinding,
    ) -> ThreadStoreFuture<'a, NativeCheckpointPermit<'a>>;
}

/// In-process handle to an existing live writer; clones share that same instance.
/// Its epoch is not restart authority and never renews the original operation.
#[derive(Clone)]
pub struct NativeCheckpointSession {
    pub(crate) binding: NativeCheckpointBinding,
    pub(crate) rollout_id: ThreadId,
    pub(crate) writer_epoch: Arc<()>,
    pub(crate) currentness: Arc<dyn NativeCheckpointCurrentness>,
    pub(crate) mode: NativeCheckpointOpenMode,
}

impl NativeCheckpointSession {
    pub fn binding(&self) -> &NativeCheckpointBinding {
        &self.binding
    }

    pub(crate) fn require_thread(&self, thread_id: ThreadId) -> ThreadStoreResult<()> {
        if self.binding.thread_id != thread_id {
            return Err(crate::ThreadStoreError::Conflict {
                message: "native checkpoint belongs to another live thread".to_string(),
            });
        }
        Ok(())
    }
}
