//! Content-bound image transfer through the existing authorized TaskFlow seam.
//!
//! This provider moves a quiesced image into a private immutable destination.
//! It does not issue a writer lease, select a model, or grant source access.
//! Destination readers must independently reopen their owners at the retained
//! current-cut witness and verify the existing signed artifact selection.

#[path = "memory_cell_migration_v9_image.rs"]
mod image;
#[path = "memory_cell_migration_v9_store.rs"]
mod store;
#[path = "memory_cell_migration_v9_transport.rs"]
mod transport;

pub use image::MemoryCellMigrationImageV9;
pub use image::MemoryCellMigrationManifestV9;
pub use image::MemoryCellMigrationPinV9;
pub use store::MemoryCellMigrationStoreV9;
pub use transport::MemoryCellMigrationProviderV9;
pub use transport::MemoryCellMigrationReceiverV9;
pub use transport::MemoryCellMigrationTrafficV9;

#[cfg(test)]
#[path = "memory_cell_migration_v9_tests.rs"]
mod tests;

const MAX_IMAGE_BYTES: usize = 32 * 1024 * 1024;
const MAX_HEADER_BYTES: usize = 65_536;

fn failure(error: impl std::fmt::Display) -> String {
    error.to_string()
}
