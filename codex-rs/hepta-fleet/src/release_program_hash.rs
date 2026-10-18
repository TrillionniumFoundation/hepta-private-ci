//! The existing AWS-LC SHA-256 implementation, with the original byte preimages.
//! This private streaming context carries byte facts, never launch authority.

use aws_lc_rs::digest::Context;
use aws_lc_rs::digest::SHA256;
use std::fmt;

#[derive(Clone)]
pub(super) struct ProgramSha256(Context);

impl ProgramSha256 {
    pub(super) fn new() -> Self {
        Self(Context::new(&SHA256))
    }
    pub(super) fn update(&mut self, bytes: impl AsRef<[u8]>) {
        self.0.update(bytes.as_ref());
    }
    pub(super) fn finalize(self) -> [u8; 32] {
        let digest = self.0.finish();
        let mut bytes = [0; 32];
        bytes.copy_from_slice(digest.as_ref());
        bytes
    }
}

impl fmt::Debug for ProgramSha256 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ProgramSha256")
    }
}
