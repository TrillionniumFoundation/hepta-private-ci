//! Explicit, non-default qualification hooks for destructive transport cuts.
//!
//! This module is compiled only by the `qualification-failpoints` feature.
//! Production/default builds contain neither the marker parser nor the
//! post-send acknowledgement drop. The checked-in real-Synapse harness arms
//! one exact payload under an owner-private per-Agent Matrix root.

use std::fs;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_paths::HeptaAgentLayout;

const QUALIFICATION_SCHEMA_VERSION: u64 = 1;
const ROOT_NAME: &str = "qualification-outbound-post-send-pre-mark-v1";
const ARM_NAME: &str = "armed.once";
const CLAIMED_NAME: &str = "claimed.once";
const RECEIPT_NAME: &str = "receipt.json";
const RECEIPT_TEMP_NAME: &str = "receipt.json.tmp";
const MATRIX_ROOM_MESSAGE_EVENT_TYPE: &str = "m.room.message";
const ACK_DISPOSITION: &str = "dropped_after_synapse_response_before_outbox_mark_sent";

/// Arm one response-loss cut for the exact normalized outbox payload.
///
/// The call fails if this qualification root has already been armed or used.
/// A fresh per-Agent test root is therefore required for each dynamic proof.
pub fn arm_post_send_pre_mark_ack_drop_once(
    layout: &HeptaAgentLayout,
    expected_payload: &[u8],
) -> io::Result<PathBuf> {
    let root = qualification_root(layout);
    create_private_directory(&root)?;
    let arm = root.join(ARM_NAME);
    let claimed = root.join(CLAIMED_NAME);
    let receipt = root.join(RECEIPT_NAME);
    let receipt_temp = root.join(RECEIPT_TEMP_NAME);
    for path in [&arm, &claimed, &receipt, &receipt_temp] {
        if path.exists() {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "post-send/pre-mark qualification hook was already armed or consumed",
            ));
        }
    }
    let digest = Sha256Digest::for_bytes(expected_payload);
    let body = serde_json::to_vec(&serde_json::json!({
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "expected_payload_sha256": digest.as_str(),
    }))
    .map_err(io::Error::other)?;
    write_new_private(&arm, &body)?;
    sync_directory(&root)?;
    Ok(receipt)
}

pub fn post_send_pre_mark_ack_drop_receipt_path(layout: &HeptaAgentLayout) -> PathBuf {
    qualification_root(layout).join(RECEIPT_NAME)
}

/// Consume the exact one-shot marker after Synapse returned an event ID but
/// before the durable dispatcher can mark the outbox record sent.
pub(crate) fn consume_post_send_pre_mark_ack_drop(
    paths_root: &Path,
    record: &OutboxRecord,
    event_id: &MatrixEventId,
) -> io::Result<bool> {
    let Some(matrix_root) = paths_root.parent() else {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "Matrix SDK root has no parent",
        ));
    };
    let root = matrix_root.join(ROOT_NAME);
    let arm = root.join(ARM_NAME);
    let arm_body = match fs::read(&arm) {
        Ok(body) => body,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    };
    if expected_payload_sha256(&arm_body)?.as_str()
        != Sha256Digest::for_bytes(&record.payload).as_str()
    {
        return Ok(false);
    }

    let claimed = root.join(CLAIMED_NAME);
    match fs::rename(&arm, &claimed) {
        Ok(()) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error),
    }
    // Re-read the claimed marker so a path replacement between the initial
    // read and rename cannot arm a different payload.
    let claimed_body = fs::read(&claimed)?;
    let payload_sha256 = expected_payload_sha256(&claimed_body)?;
    if payload_sha256.as_str() != Sha256Digest::for_bytes(&record.payload).as_str() {
        fs::rename(&claimed, &arm)?;
        return Ok(false);
    }

    let receipt = root.join(RECEIPT_NAME);
    let receipt_temp = root.join(RECEIPT_TEMP_NAME);
    let receipt_body = serde_json::to_vec(&serde_json::json!({
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "stable_txn_id": record.stable_txn_id.as_str(),
        "synapse_event_id": event_id.as_str(),
        "requested_event_type": MATRIX_ROOM_MESSAGE_EVENT_TYPE,
        "ack_disposition": ACK_DISPOSITION,
        "payload_sha256": payload_sha256.as_str(),
        "attempt": record.attempts,
    }))
    .map_err(io::Error::other)?;
    write_new_private(&receipt_temp, &receipt_body)?;
    fs::rename(&receipt_temp, &receipt)?;
    sync_directory(&root)?;
    fs::remove_file(&claimed)?;
    sync_directory(&root)?;
    Ok(true)
}

fn qualification_root(layout: &HeptaAgentLayout) -> PathBuf {
    layout.matrix_root().join(ROOT_NAME)
}

fn expected_payload_sha256(body: &[u8]) -> io::Result<Sha256Digest> {
    let value: serde_json::Value = serde_json::from_slice(body).map_err(io::Error::other)?;
    if value
        .get("schema_version")
        .and_then(serde_json::Value::as_u64)
        != Some(QUALIFICATION_SCHEMA_VERSION)
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "unsupported post-send/pre-mark qualification marker",
        ));
    }
    let digest = value
        .get("expected_payload_sha256")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "qualification marker omitted expected payload digest",
            )
        })?;
    Sha256Digest::parse(digest).map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

fn create_private_directory(path: &Path) -> io::Result<()> {
    fs::create_dir_all(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn write_new_private(path: &Path, body: &[u8]) -> io::Result<()> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(body)?;
    file.write_all(b"\n")?;
    file.sync_all()
}

fn sync_directory(path: &Path) -> io::Result<()> {
    #[cfg(unix)]
    {
        fs::File::open(path)?.sync_all()
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use codex_hepta_contracts::AgentId;
    use codex_hepta_matrix_protocol::MatrixRoomId;
    use codex_hepta_matrix_protocol::MatrixTransactionId;
    use codex_hepta_matrix_store::OutboxKind;
    use codex_hepta_matrix_store::OutboxState;
    use codex_hepta_paths::HeptaFleetRoot;
    use tempfile::TempDir;

    use super::*;

    #[test]
    fn exact_marker_is_consumed_once_after_synapse_event_id_exists()
    -> Result<(), Box<dyn std::error::Error>> {
        let temp = TempDir::new()?;
        let fleet_root = temp.path().join("fleet");
        fs::create_dir(&fleet_root)?;
        let layout = HeptaFleetRoot::parse(fleet_root.canonicalize()?)?
            .layout()
            .agent(&AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?);
        let payload = b"qualification reply";
        let receipt = arm_post_send_pre_mark_ack_drop_once(&layout, payload)?;
        let paths_root = layout.matrix_root().join("matrix-sdk-0.18");
        let record = OutboxRecord {
            outbox_id: 1,
            stable_txn_id: MatrixTransactionId::parse("hepta-v1-qualification-txn")?,
            room_id: MatrixRoomId::parse("!qualification:example.test")?,
            kind: OutboxKind::Final,
            payload: payload.to_vec(),
            logical_txn_count: 1,
            binding_revision: 1,
            generation: 1,
            state: OutboxState::InFlight,
            attempts: 1,
            next_attempt_at_ms: 0,
            lease_until_ms: Some(10),
            created_at_ms: 1,
            updated_at_ms: 1,
            sent_event_id: None,
            replaces_event_id: None,
        };
        let event_id = MatrixEventId::parse("$qualification-event")?;

        assert!(consume_post_send_pre_mark_ack_drop(
            &paths_root,
            &record,
            &event_id
        )?);
        assert!(!consume_post_send_pre_mark_ack_drop(
            &paths_root,
            &record,
            &event_id
        )?);
        let value: serde_json::Value = serde_json::from_slice(&fs::read(receipt)?)?;
        assert_eq!(value["stable_txn_id"], record.stable_txn_id.as_str());
        assert_eq!(value["synapse_event_id"], event_id.as_str());
        assert_eq!(value["requested_event_type"], "m.room.message");
        assert_eq!(
            value["ack_disposition"],
            "dropped_after_synapse_response_before_outbox_mark_sent"
        );
        assert_eq!(value["attempt"], 1);
        Ok(())
    }
}
