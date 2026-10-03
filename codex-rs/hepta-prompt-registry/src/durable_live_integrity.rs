//! Bounded live-owner integrity checks. These authenticate the bytes selected
//! by this process, not the freshness of an independently restored owner.
//!
//! Every authoritative entry point checks the manifest and selected payload
//! prefix without repair. The existing exclusive owner lock remains the
//! concurrency contract; this is not atomic isolation from a hostile writer.

use codex_hepta_types::Digest32;

use super::Access;
use super::DurableRegistryError;
use super::MAX_STATE_BYTES;
use super::Store;
use super::open_private;

impl Store {
    pub(super) fn verify_selected_bytes(&self) -> Result<(), DurableRegistryError> {
        let expected = self
            .selected_manifest_digest
            .ok_or(DurableRegistryError::Corrupt)?;
        let file = open_private(&self.root, "registry.json", Access::Read)?;
        let observed = Digest32::of_reader(file, MAX_STATE_BYTES)
            .map_err(|_| DurableRegistryError::Corrupt)?;
        if observed != expected {
            return Err(DurableRegistryError::Corrupt);
        }
        self.payloads.verify_selected_bytes(&self.root)
    }
}
