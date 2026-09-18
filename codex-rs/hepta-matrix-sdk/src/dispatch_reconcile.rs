use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableStore;
use matrix_sdk::ruma::RoomId;
use matrix_sdk::ruma::events::AnySyncTimelineEvent;
use matrix_sdk::ruma::serde::Raw;
use matrix_sdk::sync::SyncResponse;
use serde_json::Value;

use crate::MatrixSdkError;

/// Reconcile transport-accepted or transport-unknown sends only after the
/// homeserver exposes a matching event through the authenticated sync stream.
/// This runs before advancing the authoritative Hepta sync cursor. If a crash
/// occurs between the observation write and the ingress commit, replay of the
/// same event is idempotent and cannot invent a second send.
pub(crate) async fn reconcile_sync_dispatches(
    store: &MatrixDurableStore,
    response: &SyncResponse,
    binding_revision: u64,
    generation: u64,
    expected_sender: &MatrixUserId,
    observed_at_ms: u64,
) -> Result<(), MatrixSdkError> {
    for (native_room_id, timeline) in response
        .rooms
        .joined
        .iter()
        .map(|(room_id, room)| (room_id, &room.timeline))
        .chain(
            response
                .rooms
                .left
                .iter()
                .map(|(room_id, room)| (room_id, &room.timeline)),
        )
    {
        let room_id =
            MatrixRoomId::parse(native_room_id.as_str()).map_err(|_| MatrixSdkError::Sync)?;
        for event in &timeline.events {
            reconcile_raw_event(
                store,
                native_room_id,
                &room_id,
                event.raw(),
                binding_revision,
                generation,
                expected_sender,
                observed_at_ms,
            )
            .await?;
        }
    }
    Ok(())
}

async fn reconcile_raw_event(
    store: &MatrixDurableStore,
    native_room_id: &RoomId,
    room_id: &MatrixRoomId,
    raw: &Raw<AnySyncTimelineEvent>,
    binding_revision: u64,
    generation: u64,
    expected_sender: &MatrixUserId,
    observed_at_ms: u64,
) -> Result<(), MatrixSdkError> {
    if raw
        .get_field::<String>("room_id")
        .map_err(|_| MatrixSdkError::Sync)?
        .is_some_and(|embedded| embedded != native_room_id.as_str())
    {
        return Err(MatrixSdkError::Sync);
    }
    let Some(event_id) = raw
        .get_field::<String>("event_id")
        .map_err(|_| MatrixSdkError::Sync)?
    else {
        return Err(MatrixSdkError::Sync);
    };
    let event_id = MatrixEventId::parse(&event_id).map_err(|_| MatrixSdkError::Sync)?;
    let unsigned = raw
        .get_field::<Value>("unsigned")
        .map_err(|_| MatrixSdkError::Sync)?;
    let txn_hint = unsigned
        .as_ref()
        .and_then(|value| value.get("transaction_id"))
        .and_then(Value::as_str)
        .map(MatrixTransactionId::parse)
        .transpose()
        .map_err(|_| MatrixSdkError::Sync)?;
    let raw_digest = Sha256Digest::for_bytes(raw.json().get().as_bytes());

    let sender = raw
        .get_field::<String>("sender")
        .map_err(|_| MatrixSdkError::Sync)?
        .ok_or(MatrixSdkError::Sync)
        .and_then(|value| MatrixUserId::parse(&value).map_err(|_| MatrixSdkError::Sync))?;

    let existing = match txn_hint.as_ref() {
        Some(txn_id) => store
            .matrix_dispatch_receipt(txn_id)
            .await
            .map_err(|_| MatrixSdkError::Store)?,
        None => store
            .matrix_dispatch_receipt_for_event(&event_id)
            .await
            .map_err(|_| MatrixSdkError::Store)?,
    };
    let already_observed = existing.as_ref().is_some_and(|receipt| {
        receipt.archived
            && matches!(
                receipt.state,
                MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted
            )
            && receipt.observed_event_id.as_ref() == Some(&event_id)
    });
    if existing.is_some() && sender != *expected_sender {
        return Err(MatrixSdkError::Sync);
    }
    if !already_observed {
        store
            .observe_matrix_server_event(
                txn_hint.as_ref(),
                &event_id,
                room_id,
                binding_revision,
                generation,
                raw_digest.as_str(),
                observed_at_ms,
            )
            .await
            .map_err(|_| MatrixSdkError::Store)?;
    }

    if raw
        .get_field::<String>("type")
        .map_err(|_| MatrixSdkError::Sync)?
        .as_deref()
        == Some("m.room.redaction")
    {
        let root_target = raw
            .get_field::<String>("redacts")
            .map_err(|_| MatrixSdkError::Sync)?;
        let content = raw
            .get_field::<Value>("content")
            .map_err(|_| MatrixSdkError::Sync)?;
        let content_target = content
            .as_ref()
            .and_then(|value| value.get("redacts"))
            .and_then(Value::as_str)
            .map(str::to_owned);
        let target = match (root_target, content_target) {
            (Some(root), Some(content)) if root != content => return Err(MatrixSdkError::Sync),
            (Some(root), _) => Some(root),
            (_, Some(content)) => Some(content),
            (None, None) => None,
        };
        if let Some(target) = target {
            let target = MatrixEventId::parse(&target).map_err(|_| MatrixSdkError::Sync)?;
            store
                .observe_matrix_redaction(&target, &event_id, raw_digest.as_str(), observed_at_ms)
                .await
                .map_err(|_| MatrixSdkError::Store)?;
        }
    }

    if let Some(redacted_because) = unsigned
        .as_ref()
        .and_then(|value| value.get("redacted_because"))
    {
        let redaction_event_id = redacted_because
            .get("event_id")
            .and_then(Value::as_str)
            .ok_or(MatrixSdkError::Sync)
            .and_then(|value| MatrixEventId::parse(value).map_err(|_| MatrixSdkError::Sync))?;
        let redaction_bytes =
            serde_json::to_vec(redacted_because).map_err(|_| MatrixSdkError::Sync)?;
        let redaction_digest = Sha256Digest::for_bytes(&redaction_bytes);
        store
            .observe_matrix_redaction(
                &event_id,
                &redaction_event_id,
                redaction_digest.as_str(),
                observed_at_ms,
            )
            .await
            .map_err(|_| MatrixSdkError::Store)?;
    }
    Ok(())
}
