//! One retained original issuance, not a transaction log or alternate owner.
//! Actual progress and ACKs are read from the original ledger and checkpoint.
use super::super::*;
use super::source;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;
use serde::Serialize;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Issuance {
    pub request_digest: String,
    pub evidence: ReviewEvidenceWireV1,
    pub source_event: String,
    pub event: String,
    pub admitted_at: u64,
    pub head: state::OriginalHead,
    pub suffix: Vec<Change>,
    pub before: Snapshot,
    pub delivery_targets: Vec<String>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Change {
    event_id: String,
    artifact_id: String,
    evaluator_id: String,
    reason_digest: String,
}
impl Change {
    pub fn of(event: &ArtifactEvent) -> HostResult<Self> {
        let ArtifactEvent::Revoke(change) = event else {
            return Err("withdrawal suffix must retain original Revoke events".into());
        };
        Ok(Self {
            event_id: change.event_id.to_string(),
            artifact_id: change.artifact_id.to_string(),
            evaluator_id: change.evaluator_id.to_string(),
            reason_digest: change.reason_digest.to_string(),
        })
    }
    pub fn native(&self) -> HostResult<ArtifactEvent> {
        Ok(ArtifactEvent::Revoke(StateChange {
            event_id: id(&self.event_id)?,
            artifact_id: id(&self.artifact_id)?,
            evaluator_id: id(&self.evaluator_id)?,
            reason_digest: digest(&self.reason_digest)?,
        }))
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Snapshot {
    binding: String,
    head: String,
    file: String,
    records: usize,
    bytes: usize,
}
impl Snapshot {
    pub fn of(value: RegistrySnapshotReceipt) -> Self {
        Self {
            binding: value.binding.to_string(),
            head: value.head_digest.to_string(),
            file: value.file_digest.to_string(),
            records: value.records,
            bytes: value.encoded_bytes,
        }
    }
    pub fn native(&self) -> HostResult<RegistrySnapshotReceipt> {
        Ok(RegistrySnapshotReceipt {
            binding: digest(&self.binding)?,
            head_digest: digest(&self.head)?,
            file_digest: digest(&self.file)?,
            records: self.records,
            encoded_bytes: self.bytes,
        })
    }
}
pub(super) fn read(path: &Path, request: Digest32) -> HostResult<Option<Issuance>> {
    source::directory(path.parent().ok_or("issuance parent")?)?;
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
        Ok(_) => {
            let value: Issuance =
                serde_json::from_slice(&read_root_review_input(path, 64 * 1024)?)?;
            if value.request_digest != request.to_string()
                || value.suffix.len() > 64
                || value.delivery_targets.is_empty()
                || value.delivery_targets.len() > 64
            {
                return Err(
                    "original withdrawal issuance conflicts with this exact request".into(),
                );
            }
            Ok(Some(value))
        }
    }
}
pub(super) fn retain(path: &Path, issuance: &Issuance) -> HostResult<()> {
    let parent = source::directory(path.parent().ok_or("issuance parent")?)?;
    let bytes = serde_json::to_vec(issuance)?;
    if bytes.len() > 64 * 1024 {
        return Err("original withdrawal issuance exceeds bound".into());
    }
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(
            rustix::fs::OFlags::NOFOLLOW.bits() as i32 | rustix::fs::OFlags::NONBLOCK.bits() as i32,
        )
        .open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    parent.sync_all()?;
    // Require the same protected byte record before any delivery-fence effect.
    if read_root_review_input(path, 64 * 1024)? != bytes {
        return Err("retained withdrawal issuance changed".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "initial_cpu_withdrawal_issuance_tests.rs"]
mod tests;
