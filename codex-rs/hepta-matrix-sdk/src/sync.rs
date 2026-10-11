//! Composition of a received SDK response into the owner-local V2 transaction.
//! Bounds here apply to the processed response, not the SDK's HTTP decoder.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2;
use codex_hepta_matrix_protocol::MAX_MATRIX_SYNC_BATCH_PAYLOAD_BYTES_V2;
use codex_hepta_matrix_protocol::MAX_MATRIX_SYNC_MUTATIONS_V2;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixSyncBatchV2;
use codex_hepta_matrix_protocol::MatrixSyncDecisionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationBodyV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationDispositionV2;
use codex_hepta_matrix_protocol::MatrixSyncMutationV2;
use codex_hepta_matrix_protocol::MatrixSyncResultV2;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixSyncCheckpoint;
use codex_hepta_matrix_store::MatrixSyncUnchangedRequestV1;
use codex_hepta_matrix_store::MatrixSyncUnchangedResultV1;
use matrix_sdk::ruma::RoomId;
use matrix_sdk::ruma::events::AnyRedactionEvent;
use matrix_sdk::ruma::events::AnySyncMessageLikeEvent;
use matrix_sdk::ruma::events::AnySyncStateEvent;
use matrix_sdk::ruma::events::AnySyncTimelineEvent;
use matrix_sdk::ruma::events::SyncMessageLikeEvent;
use matrix_sdk::ruma::events::SyncStateEvent;
use matrix_sdk::ruma::events::room::member::MembershipState;
use matrix_sdk::ruma::events::room::message::MessageType;
use matrix_sdk::ruma::room_version_rules::RoomVersionRules;
use matrix_sdk::ruma::serde::Raw;
use matrix_sdk::sync::State;
use matrix_sdk::sync::SyncResponse;
use serde_json::Value;

use crate::IngressIgnoredReason;
use crate::MatrixIngress;
use crate::MatrixSdkError;
use crate::MatrixSidecarConfig;
use crate::MatrixTimelineEvent;

const MAX_RAW_EVENT_BYTES: usize = 1024 * 1024;

pub(crate) struct MatrixSyncComposer<'a> {
    pub config: &'a MatrixSidecarConfig,
    pub ingress: &'a MatrixIngress,
    pub store: &'a MatrixDurableStore,
}

impl MatrixSyncComposer<'_> {
    pub async fn commit_response(
        &self,
        response: &SyncResponse,
        checkpoint: Option<&MatrixSyncCheckpoint>,
        observed_at_ms: u64,
        room_rules: impl Fn(&RoomId) -> Option<RoomVersionRules>,
    ) -> Result<(), MatrixSdkError> {
        if self.config != &self.ingress.config
            || self.store.path() != self.ingress.store.path()
            || self.store.owner_agent_id() != &self.config.binding.agent_id
        {
            return Err(MatrixSdkError::Configuration);
        }
        let mutations = self.normalize(response, observed_at_ms, room_rules)?;
        let expected = checkpoint.map(|checkpoint| checkpoint.next_batch.as_str());
        // The whole decision, including first-observed time, remains fixed for
        // this attempt. The store binds its complete semantic digest; a reused
        // operation identity with a different response cannot become replay.
        let identity = serde_json::to_vec(&(
            "hepta.matrix.sdk-sync.v2",
            &self.config.binding,
            self.config.matrix_generation,
            expected,
            &response.next_batch,
            observed_at_ms,
        ))
        .map_err(|_| MatrixSdkError::Sync)?;
        let batch = MatrixSyncBatchV2 {
            schema_version: MATRIX_SYNC_MUTATION_SCHEMA_VERSION_V2,
            operation_id: format!("sync-{}", Sha256Digest::for_bytes(&identity).as_str()),
            checkpoint_revision: self.config.binding.revision,
            checkpoint_generation: self.config.matrix_generation,
            expected_next_batch: expected.map(str::to_owned),
            next_batch: response.next_batch.clone(),
            observed_at_ms,
            mutations,
        };
        batch.validate().map_err(|_| MatrixSdkError::Sync)?;
        if batch.mutations.is_empty()
            && batch.expected_next_batch.as_deref() == Some(batch.next_batch.as_str())
        {
            // Empty observations still require a fresh owner transaction and
            // every ordinary journal capacity check. They are not V2 commits
            // and reserve no operation identity for reconciliation.
            return match self
                .store
                .verify_unchanged_sync_v1(&MatrixSyncUnchangedRequestV1 {
                    owner_agent_id: self.config.binding.agent_id.clone(),
                    checkpoint_revision: batch.checkpoint_revision,
                    checkpoint_generation: batch.checkpoint_generation,
                    expected_next_batch: batch.next_batch.clone(),
                    observed_next_batch: batch.next_batch,
                })
                .await
                .map_err(|_| MatrixSdkError::Store)?
            {
                MatrixSyncUnchangedResultV1::Verified { checkpoint }
                    if checkpoint.owner_agent_id == self.config.binding.agent_id
                        && checkpoint.binding_revision == batch.checkpoint_revision
                        && checkpoint.generation == batch.checkpoint_generation
                        && Some(checkpoint.next_batch.as_str()) == expected =>
                {
                    Ok(())
                }
                MatrixSyncUnchangedResultV1::Verified { .. } => Err(MatrixSdkError::Store),
                MatrixSyncUnchangedResultV1::CapacityExhausted => {
                    Err(MatrixSdkError::CapacityExhausted)
                }
            };
        }
        let decision = MatrixSyncDecisionV2::Commit { batch };
        let result = self
            .store
            .apply_sync_decision_v2(&decision)
            .await
            .map_err(|_| MatrixSdkError::Store)?;
        if matches!(result, MatrixSyncResultV2::CapacityExhausted { .. }) {
            return Err(MatrixSdkError::CapacityExhausted);
        }
        let MatrixSyncDecisionV2::Commit { batch } = &decision else {
            return Err(MatrixSdkError::Store);
        };
        let MatrixSyncResultV2::Committed {
            schema_version,
            operation_id,
            checkpoint_revision,
            checkpoint_generation,
            next_batch,
            outcomes,
        } = result
        else {
            // A cancelled decision never establishes commit readiness.
            return Err(MatrixSdkError::Store);
        };
        if schema_version != batch.schema_version
            || operation_id != batch.operation_id
            || checkpoint_revision != batch.checkpoint_revision
            || checkpoint_generation != batch.checkpoint_generation
            || next_batch != batch.next_batch
            || outcomes.len() != batch.mutations.len()
        {
            return Err(MatrixSdkError::Store);
        }
        let mut accepted = 0;
        let mut duplicates = 0;
        for (mutation, outcome) in batch.mutations.iter().zip(outcomes) {
            if mutation.source_event_id != outcome.source_event_id {
                return Err(MatrixSdkError::Store);
            }
            if matches!(mutation.body, MatrixSyncMutationBodyV2::Timeline { .. }) {
                match outcome.disposition {
                    MatrixSyncMutationDispositionV2::Applied => accepted += 1,
                    MatrixSyncMutationDispositionV2::Duplicate => duplicates += 1,
                    MatrixSyncMutationDispositionV2::Tombstoned => {}
                    MatrixSyncMutationDispositionV2::Missing => return Err(MatrixSdkError::Store),
                }
            } else {
                match outcome.disposition {
                    MatrixSyncMutationDispositionV2::Applied
                    | MatrixSyncMutationDispositionV2::Duplicate
                    | MatrixSyncMutationDispositionV2::Missing => {}
                    MatrixSyncMutationDispositionV2::Tombstoned => {
                        return Err(MatrixSdkError::Store);
                    }
                }
            }
        }
        self.ingress.record_sync_commit(accepted, duplicates);
        Ok(())
    }

    fn normalize(
        &self,
        response: &SyncResponse,
        observed_at_ms: u64,
        room_rules: impl Fn(&RoomId) -> Option<RoomVersionRules>,
    ) -> Result<Vec<MatrixSyncMutationV2>, MatrixSdkError> {
        if !response.rooms.invited.is_empty() || !response.rooms.knocked.is_empty() {
            // Stripped membership state cannot establish a complete joined
            // history or supply a source identity for fencing an old inbox.
            return Err(MatrixSdkError::Sync);
        }
        let rooms = response
            .rooms
            .joined
            .iter()
            .map(|(id, room)| (id, &room.state, &room.timeline))
            .chain(
                response
                    .rooms
                    .left
                    .iter()
                    .map(|(id, room)| (id, &room.state, &room.timeline)),
            );
        let mut mutations = Vec::new();
        let mut identities = BTreeMap::new();
        let mut raw_count = 0_usize;
        let mut raw_bytes = 0_usize;
        for (native_room_id, state, timeline) in rooms {
            let room_id =
                MatrixRoomId::parse(native_room_id.as_str()).map_err(|_| MatrixSdkError::Sync)?;
            if timeline.limited
                || !self.config.binding.allowed_rooms.contains(&room_id)
                || (response.rooms.joined.contains_key(room_id.as_str())
                    && response.rooms.left.contains_key(room_id.as_str()))
            {
                return Err(MatrixSdkError::Sync);
            }
            let (State::Before(state_events) | State::After(state_events)) = state;
            raw_count = raw_count
                .checked_add(state_events.len())
                .and_then(|count| count.checked_add(timeline.events.len()))
                .ok_or(MatrixSdkError::Sync)?;
            if raw_count > MAX_MATRIX_SYNC_MUTATIONS_V2 {
                return Err(MatrixSdkError::Sync);
            }
            let state_events = state_events
                .iter()
                .map(Raw::cast_ref::<AnySyncTimelineEvent>);
            let timeline_events = timeline
                .events
                .iter()
                .map(matrix_sdk::deserialized_responses::TimelineEvent::raw);
            let events = match state {
                State::Before(_) => state_events.chain(timeline_events).collect::<Vec<_>>(),
                State::After(_) => timeline_events.chain(state_events).collect::<Vec<_>>(),
            };
            let rules = room_rules(native_room_id);
            let start = mutations.len();
            for raw in events {
                raw_bytes = raw_bytes
                    .checked_add(raw.json().get().len())
                    .ok_or(MatrixSdkError::Sync)?;
                if raw_bytes > MAX_MATRIX_SYNC_BATCH_PAYLOAD_BYTES_V2
                    || raw.json().get().len() > MAX_RAW_EVENT_BYTES
                {
                    return Err(MatrixSdkError::Sync);
                }
                for mutation in self.event(raw, &room_id, observed_at_ms, rules.as_ref())? {
                    if let Some(&index) = identities.get(&mutation.source_event_id) {
                        if mutations[index] != mutation {
                            return Err(MatrixSdkError::Sync);
                        }
                    } else {
                        if mutations.len() == MAX_MATRIX_SYNC_MUTATIONS_V2 {
                            return Err(MatrixSdkError::Sync);
                        }
                        identities.insert(mutation.source_event_id.clone(), mutations.len());
                        mutations.push(mutation);
                    }
                }
            }
            if response.rooms.left.contains_key(room_id.as_str())
                && !mutations[start..].iter().any(|mutation| {
                    matches!(mutation.body, MatrixSyncMutationBodyV2::RoomLeave { .. })
                })
            {
                // A left-room section without the actual membership event is
                // insufficient to invent a durable source-event identity.
                return Err(MatrixSdkError::Sync);
            }
        }
        Ok(mutations)
    }

    fn event(
        &self,
        raw: &Raw<AnySyncTimelineEvent>,
        room_id: &MatrixRoomId,
        received_at_ms: u64,
        rules: Option<&RoomVersionRules>,
    ) -> Result<Vec<MatrixSyncMutationV2>, MatrixSdkError> {
        if raw
            .get_field::<String>("room_id")
            .map_err(|_| MatrixSdkError::Sync)?
            .is_some_and(|id| id != room_id.as_str())
        {
            return Err(MatrixSdkError::Sync);
        }
        let unsigned = raw
            .get_field::<Value>("unsigned")
            .map_err(|_| MatrixSdkError::Sync)?;
        let redacted_because = unsigned
            .as_ref()
            .and_then(|unsigned| unsigned.get("redacted_because"));
        let event = match raw.deserialize() {
            Ok(event) => event,
            Err(_)
                if redacted_because.is_none()
                    && raw
                        .get_field::<String>("type")
                        .map_err(|_| MatrixSdkError::Sync)?
                        .as_deref()
                        == Some("m.room.message") =>
            {
                self.ingress.record_malformed_event();
                return Ok(Vec::new());
            }
            Err(_) => return Err(MatrixSdkError::Sync),
        };
        let source_event_id =
            MatrixEventId::parse(event.event_id().as_str()).map_err(|_| MatrixSdkError::Sync)?;
        let sender =
            MatrixUserId::parse(event.sender().as_str()).map_err(|_| MatrixSdkError::Sync)?;
        let origin_server_ts_ms = u64::from(event.origin_server_ts().get());
        let mut mutations = Vec::new();
        if let Some(redaction) = redacted_because {
            for target in [
                redaction.get("redacts"),
                redaction.pointer("/content/redacts"),
            ]
            .into_iter()
            .flatten()
            {
                if target.as_str() != Some(source_event_id.as_str()) {
                    return Err(MatrixSdkError::Sync);
                }
            }
            if redaction
                .get("room_id")
                .is_some_and(|id| id.as_str() != Some(room_id.as_str()))
            {
                return Err(MatrixSdkError::Sync);
            }
            let raw_redaction: Raw<AnyRedactionEvent> =
                serde_json::from_value(redaction.clone()).map_err(|_| MatrixSdkError::Sync)?;
            let AnyRedactionEvent::RoomRedaction(redaction) = raw_redaction
                .deserialize()
                .map_err(|_| MatrixSdkError::Sync)?
            else {
                return Err(MatrixSdkError::Sync);
            };
            mutations.push(MatrixSyncMutationV2 {
                source_event_id: MatrixEventId::parse(redaction.event_id.as_str())
                    .map_err(|_| MatrixSdkError::Sync)?,
                room_id: room_id.clone(),
                sender: MatrixUserId::parse(redaction.sender.as_str())
                    .map_err(|_| MatrixSdkError::Sync)?,
                binding_revision: self.config.binding.revision,
                generation: self.config.matrix_generation,
                origin_server_ts_ms: u64::from(redaction.origin_server_ts.get()),
                received_at_ms,
                body: MatrixSyncMutationBodyV2::Redaction {
                    target_event_id: source_event_id.clone(),
                },
            });
        }
        let body = match event {
            AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomMessage(
                SyncMessageLikeEvent::Original(event),
            )) => {
                if !matches!(&event.content.msgtype, MessageType::Text(_)) {
                    self.ingress
                        .record_ignored(IngressIgnoredReason::UnsupportedMessageType);
                    return Ok(mutations);
                }
                let content =
                    serde_json::to_value(&event.content).map_err(|_| MatrixSdkError::Sync)?;
                let payload = serde_json::to_vec(&content).map_err(|_| MatrixSdkError::Sync)?;
                let mentioned_user_ids = event
                    .content
                    .mentions
                    .as_ref()
                    .map(|mentions| {
                        mentions
                            .user_ids
                            .iter()
                            .map(|id| MatrixUserId::parse(id.as_str()))
                            .collect::<Result<Vec<_>, _>>()
                    })
                    .transpose()
                    .map_err(|_| MatrixSdkError::Sync)?
                    .unwrap_or_default();
                let message = MatrixTimelineEvent {
                    event_id: source_event_id.clone(),
                    room_id: room_id.clone(),
                    sender: sender.clone(),
                    event_type: "m.room.message".to_string(),
                    payload: payload.clone(),
                    mentioned_user_ids,
                    origin_server_ts_ms,
                    received_at_ms,
                };
                if let Some(reason) = self.ingress.filter(&message) {
                    self.ingress.record_ignored(reason);
                    return Ok(mutations);
                }
                MatrixSyncMutationBodyV2::Timeline {
                    event_type: message.event_type,
                    payload,
                }
            }
            AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomRedaction(event)) => {
                let target = if let Some(rules) = rules {
                    event.redacts(&rules.redaction)
                } else if let Some(original) = event.as_original() {
                    if original.redacts.is_some()
                        && original.content.redacts.is_some()
                        && original.redacts != original.content.redacts
                    {
                        return Err(MatrixSdkError::Sync);
                    }
                    original
                        .redacts
                        .as_deref()
                        .or(original.content.redacts.as_deref())
                } else {
                    return Err(MatrixSdkError::Sync);
                }
                .ok_or(MatrixSdkError::Sync)?;
                MatrixSyncMutationBodyV2::Redaction {
                    target_event_id: MatrixEventId::parse(target.as_str())
                        .map_err(|_| MatrixSdkError::Sync)?,
                }
            }
            AnySyncTimelineEvent::State(AnySyncStateEvent::RoomMember(event))
                if event.state_key().as_str() == self.config.binding.expected_mxid.as_str()
                    && matches!(
                        event.membership(),
                        MembershipState::Leave | MembershipState::Ban
                    ) =>
            {
                MatrixSyncMutationBodyV2::RoomLeave {
                    departed_user_id: self.config.binding.expected_mxid.clone(),
                }
            }
            AnySyncTimelineEvent::State(AnySyncStateEvent::RoomTombstone(
                SyncStateEvent::Original(event),
            )) => MatrixSyncMutationBodyV2::RoomTombstone {
                replacement_room_id: MatrixRoomId::parse(event.content.replacement_room.as_str())
                    .map_err(|_| MatrixSdkError::Sync)?,
            },
            AnySyncTimelineEvent::MessageLike(AnySyncMessageLikeEvent::RoomEncrypted(_))
            | AnySyncTimelineEvent::State(AnySyncStateEvent::RoomTombstone(
                SyncStateEvent::Redacted(_),
            )) => return Err(MatrixSdkError::Sync),
            _ => return Ok(mutations),
        };
        mutations.push(MatrixSyncMutationV2 {
            source_event_id,
            room_id: room_id.clone(),
            sender,
            binding_revision: self.config.binding.revision,
            generation: self.config.matrix_generation,
            origin_server_ts_ms,
            received_at_ms,
            body,
        });
        for mutation in &mutations {
            mutation.validate().map_err(|_| MatrixSdkError::Sync)?;
        }
        Ok(mutations)
    }
}

#[cfg(test)]
#[path = "sync_tests.rs"]
mod tests;
