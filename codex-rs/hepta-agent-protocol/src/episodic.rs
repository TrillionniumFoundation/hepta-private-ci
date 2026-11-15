//! Bounded transport for host-admitted episodic snapshot synchronization.
//! Source authority and namespace selection are configured by the embedding.
use serde::Deserialize;
use serde::Serialize;

pub const EPISODIC_SNAPSHOT_IMPORT_CAPABILITY: &str = "cognitive.episodic.import";
/// Leave room for JSON string escaping inside the existing 64 KiB control frame.
pub const MAX_EPISODIC_SNAPSHOT_IMPORT_BYTES: usize = 20 * 1024;

/// Compact acknowledgement of the full receipt retained by the original writer.
/// Retrying identical admitted input returns the same receipt digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EpisodicSnapshotImportResult {
    pub authority_id: String,
    pub namespace: String,
    pub generation: u64,
    pub snapshot_sha256: String,
    pub receipt_sha256: String,
    pub active_records: u16,
    pub retired_records: u16,
}
