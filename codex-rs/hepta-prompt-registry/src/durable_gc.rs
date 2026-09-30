//! Owner-local payload collection with a bounded two-slot publication protocol.
//!
//! 1. Keep the selected generation intact while writing the other private slot.
//! 2. Publish an outer V5 manifest selecting the new slot, then sync the directory.
//! 3. Only after that durable boundary unlink the unselected predecessor.
//!
//! An uncertain publication poisons the owner and retains both slots. Reopen
//! validates whichever manifest is selected; a later collection retries cleanup.
//! Audit records, revocation, relationships and supersession are never pruned.

use serde::Serialize;

#[cfg(unix)]
use super::Access;
use super::DurablePromptRegistry;
use super::DurableRegistryError;
#[cfg(unix)]
use super::entry_exists;
#[cfg(unix)]
use super::open_private;
use super::validate_restored;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryGcReceipt {
    pub source_revision: u64,
    pub selected_revision: u64,
    pub selected_registry_digest: [u8; 32],
    pub collected_payload_records: usize,
    pub collected_payload_bytes: u64,
    /// Namespace/file allocation reclamation only, not secure device erasure.
    pub unlinked_file_bytes: u64,
    /// False only after predecessor removal and its directory sync succeed.
    pub cleanup_pending: bool,
    pub selected_payload_file_bytes: u64,
    pub total_nanos: u128,
}

impl DurablePromptRegistry {
    /// Collect only inactive raw payloads under the existing exclusive writer.
    /// Identical retries with no newly inactive payloads allocate no revision.
    /// A successful publication followed by failed unlink is reported as a
    /// successful receipt with cleanup_pending, never an ambiguous write retry.
    pub fn collect_payload_garbage(
        &mut self,
    ) -> Result<PromptRegistryGcReceipt, DurableRegistryError> {
        self.ensure_available()?;
        let started = std::time::Instant::now();
        let source_revision = self.registry.revision.get();
        let mut next = self.registry.clone();
        let mut records = 0_usize;
        let mut bytes = 0_u64;
        next.realization_payloads.retain(|id, payload| {
            let active = next
                .realizations
                .get(id)
                .is_some_and(|realization| realization.active);
            if !active {
                records = records.saturating_add(1);
                bytes = bytes.saturating_add(u64::try_from(payload.len()).unwrap_or(u64::MAX));
            }
            active
        });
        if records != 0 {
            let revision = next.next_revision().map_err(DurableRegistryError::Core)?;
            next.commit_revision(revision, /*revocation*/ false);
            validate_restored(&next)?;
            let predecessor = self.store.payloads.clone();
            self.store.payloads = predecessor.next_generation();
            if let Err(error) = self.store.persist(&next) {
                self.store.payloads = predecessor;
                if matches!(error, DurableRegistryError::IndeterminateDurability) {
                    self.poisoned = true;
                }
                return Err(error);
            }
            self.registry = next;
        }
        // Sync the selected namespace even on a retry after reopen: unlinking
        // the other slot must never precede stabilizing the selected manifest.
        let (unlinked_file_bytes, cleanup_pending) = self.cleanup_unselected_payload_slot();
        Ok(PromptRegistryGcReceipt {
            source_revision,
            selected_revision: self.registry.revision.get(),
            selected_registry_digest: self.registry.snapshot_digest().into_array(),
            collected_payload_records: records,
            collected_payload_bytes: bytes,
            unlinked_file_bytes,
            cleanup_pending,
            selected_payload_file_bytes: self.store.payloads.selected_file_bytes(),
            total_nanos: started.elapsed().as_nanos(),
        })
    }

    #[cfg(unix)]
    fn cleanup_unselected_payload_slot(&self) -> (u64, bool) {
        let name = self.store.payloads.slot().other().file_name();
        if self.store.root.sync_all().is_err() {
            return (0, true);
        }
        match entry_exists(&self.store.root, name) {
            Ok(false) => return (0, false),
            Ok(true) => {}
            Err(_) => return (0, true),
        }
        let Ok(file) = open_private(&self.store.root, name, Access::Read) else {
            // Never follow or unlink an unexpected symlink/hardlink/unsafe file.
            return (0, true);
        };
        let Ok(metadata) = file.metadata() else {
            return (0, true);
        };
        if rustix::fs::unlinkat(&self.store.root, name, rustix::fs::AtFlags::empty()).is_err() {
            return (0, true);
        }
        (metadata.len(), self.store.root.sync_all().is_err())
    }

    #[cfg(not(unix))]
    fn cleanup_unselected_payload_slot(&self) -> (u64, bool) {
        (0, true)
    }
}

#[cfg(all(test, unix))]
#[path = "durable_gc_tests.rs"]
mod tests;
