//! Bounded process-generation observations of the real durable publication path.
//! Payload stage timing includes append, payload fsync and its directory sync;
//! it is deliberately not labelled as isolated fsync latency or full request time.

use serde::Serialize;

use super::DurableRegistryError;

#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PromptRegistryIoMetrics {
    pub publish_attempts: u64,
    pub successful_publications: u64,
    pub failed_publications: u64,
    pub indeterminate_publications: u64,
    pub storage_full_rejections: u64,
    pub last_publish_nanos: u128,
    pub total_publish_nanos: u128,
    pub maximum_publish_nanos: u128,
    pub payload_stage_nanos: u128,
    pub metadata_bytes_written: u64,
    pub metadata_sync_attempts: u64,
    pub metadata_sync_nanos: u128,
    pub publication_directory_sync_attempts: u64,
    pub publication_directory_sync_nanos: u128,
}

impl PromptRegistryIoMetrics {
    pub(super) fn observe_publish(
        &mut self,
        elapsed: u128,
        result: &Result<(), DurableRegistryError>,
    ) {
        self.publish_attempts = self.publish_attempts.saturating_add(1);
        self.last_publish_nanos = elapsed;
        self.total_publish_nanos = self.total_publish_nanos.saturating_add(elapsed);
        self.maximum_publish_nanos = self.maximum_publish_nanos.max(elapsed);
        match result {
            Ok(()) => self.successful_publications = self.successful_publications.saturating_add(1),
            Err(error) => {
                self.failed_publications = self.failed_publications.saturating_add(1);
                if matches!(error, DurableRegistryError::IndeterminateDurability) {
                    self.indeterminate_publications =
                        self.indeterminate_publications.saturating_add(1);
                }
                if matches!(error, DurableRegistryError::StorageFull) {
                    self.storage_full_rejections = self.storage_full_rejections.saturating_add(1);
                }
            }
        }
    }
}
