//! Private destinations for the single canonical encoder. A destination never
//! chooses framing, ordering, validation, or a protocol resource limit.
use sha2::Digest;
use sha2::Sha256;

use crate::Digest32;

/// Append-only destination. The shared encoder checks every byte budget before
/// calling `extend_from_slice`; implementations preserve the exact byte stream.
pub(super) trait CanonicalSink {
    fn len(&self) -> usize;
    fn extend_from_slice(&mut self, bytes: &[u8]);
}

impl CanonicalSink for Vec<u8> {
    fn len(&self) -> usize {
        Vec::len(self)
    }

    fn extend_from_slice(&mut self, bytes: &[u8]) {
        Vec::extend_from_slice(self, bytes);
    }
}

pub(super) struct DigestSink {
    hasher: Sha256,
    length: usize,
}

impl DigestSink {
    pub(super) fn new() -> Self {
        Self {
            hasher: Sha256::new(),
            length: 0,
        }
    }

    pub(super) fn finish(self) -> Digest32 {
        let digest = self.hasher.finalize();
        let mut bytes = [0_u8; 32];
        bytes.copy_from_slice(&digest);
        Digest32::from_array(bytes)
    }
}

impl CanonicalSink for DigestSink {
    fn len(&self) -> usize {
        self.length
    }

    fn extend_from_slice(&mut self, bytes: &[u8]) {
        self.hasher.update(bytes);
        self.length += bytes.len();
    }
}
