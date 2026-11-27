//! Bounded reuse of pure HEPTEX01 parsing, never a CURRENT or authority cache.
//!
//! Callers must first read the complete stable image through the original held
//! file, and must still compare length, image digest, replayed records and anchor
//! against the retained owner. Their original witness and poison checks remain
//! outside this module. Only a fully checked image can enter this private memo.

use std::sync::Arc;

use super::*;

pub(super) const MAX_VERIFIED_REPLAY_IMAGE_BYTES: usize = 256 * 1024;

pub(super) struct VerifiedReplayImage {
    binding: Digest32,
    minimum: ProductEvaluationExecutionAnchorV1,
    bytes: Box<[u8]>,
    pub(super) replayed: Arc<physical::Replay>,
}

impl LockedFileProductEvaluationExecutionStoreV1 {
    /// Return only a deterministic parse of these exact bytes and grammar inputs.
    /// The caller must perform its unchanged current-state comparisons afterwards.
    pub(super) fn replay_current_image(
        &self,
        bytes: &[u8],
    ) -> Result<Arc<physical::Replay>, FileError> {
        if let Some(verified) = &self.verified_replay
            && verified.binding == self.binding
            && verified.minimum == self.anchor
            && verified.bytes.as_ref() == bytes
        {
            return Ok(Arc::clone(&verified.replayed));
        }
        physical::replay_image(bytes, self.binding, self.anchor).map(Arc::new)
    }

    /// Called only after the original complete physical and retained-state checks.
    /// A larger image remains valid but is parsed on every subsequent observation.
    pub(super) fn remember_verified_replay(
        &mut self,
        bytes: &[u8],
        replayed: Arc<physical::Replay>,
    ) {
        if bytes.len() > MAX_VERIFIED_REPLAY_IMAGE_BYTES {
            self.verified_replay = None;
            return;
        }
        if self
            .verified_replay
            .as_ref()
            .is_some_and(|verified| Arc::ptr_eq(&verified.replayed, &replayed))
        {
            return;
        }
        self.verified_replay = Some(VerifiedReplayImage {
            binding: self.binding,
            minimum: self.anchor,
            bytes: bytes.to_vec().into_boxed_slice(),
            replayed,
        });
    }
}
