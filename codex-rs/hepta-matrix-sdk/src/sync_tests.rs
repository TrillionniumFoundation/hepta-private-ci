use std::fs;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixBindingV1;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_store::InboxDraft;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use matrix_sdk::deserialized_responses::TimelineEvent;
use matrix_sdk::sync::JoinedRoomUpdate;
use matrix_sdk::sync::LeftRoomUpdate;
use matrix_sdk::sync::Timeline;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;

use super::*;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error>>;
const ROOM: &str = "!room:example.test";
const SECOND_ROOM: &str = "!z-room:example.test";
const AGENT: &str = "@agent:example.test";
const OWNER: &str = "@owner:example.test";

struct Fixture {
    _temp: TempDir,
    layout: HeptaAgentLayout,
    store: MatrixDurableStore,
    config: MatrixSidecarConfig,
    ingress: MatrixIngress,
}

impl Fixture {
    async fn new() -> TestResult<Self> {
        let temp = TempDir::new()?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let root = temp.path().join("fleet");
        fs::create_dir(&root)?;
        let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
            .layout()
            .agent(&agent);
        let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
        let config = MatrixSidecarConfig {
            binding: MatrixBindingV1 {
                schema_version: MATRIX_BINDING_SCHEMA_VERSION,
                agent_id: agent,
                revision: 1,
                homeserver: MatrixHomeserverUrl::parse("https://example.test")?,
                expected_mxid: MatrixUserId::parse(AGENT)?,
                expected_device_id: MatrixDeviceId::parse("DEVICE")?,
                allowed_rooms: vec![
                    MatrixRoomId::parse(ROOM)?,
                    MatrixRoomId::parse(SECOND_ROOM)?,
                ],
                allowed_senders: vec![MatrixUserId::parse(OWNER)?],
                require_explicit_mention: true,
            },
            matrix_generation: 1,
            sync_timeline_limit: 32,
            sync_timeout: Duration::from_secs(1),
        };
        for room_id in &config.binding.allowed_rooms {
            store
                .bind_room(&RoomBindingDraft {
                    room_id: room_id.clone(),
                    agent_user_id: config.binding.expected_mxid.clone(),
                    expected_revision: None,
                    generation: 1,
                    changed_at_ms: 1,
                })
                .await?;
        }
        let ingress = MatrixIngress::new(config.clone(), store.clone());
        Ok(Self {
            _temp: temp,
            layout,
            store,
            config,
            ingress,
        })
    }

    fn composer(&self) -> MatrixSyncComposer<'_> {
        MatrixSyncComposer {
            config: &self.config,
            store: &self.store,
            ingress: &self.ingress,
        }
    }
}

fn message(id: &str, body: &str) -> Value {
    json!({"event_id":id,"sender":OWNER,"origin_server_ts":10,"type":"m.room.message",
        "content":{"msgtype":"m.text","body":body,"m.mentions":{"user_ids":[AGENT]}}})
}

fn redaction(id: &str, target: &str) -> Value {
    json!({"event_id":id,"sender":"@moderator:example.test","origin_server_ts":12,
        "type":"m.room.redaction","content":{"redacts":target}})
}

fn timeline(events: Vec<Value>) -> TestResult<Timeline> {
    Ok(Timeline {
        events: events
            .iter()
            .map(|event| {
                Raw::from_json_string(serde_json::to_string(event)?)
                    .map(TimelineEvent::from_plaintext)
            })
            .collect::<Result<_, serde_json::Error>>()?,
        ..Default::default()
    })
}

fn response(events: Vec<Value>) -> TestResult<SyncResponse> {
    let mut response = SyncResponse {
        next_batch: "s1".to_string(),
        ..Default::default()
    };
    response.rooms.joined.insert(
        ROOM.try_into()?,
        JoinedRoomUpdate {
            timeline: timeline(events)?,
            ..Default::default()
        },
    );
    Ok(response)
}

#[tokio::test]
async fn v1_redaction_commits_before_replay_and_survives_reopen() -> TestResult {
    let fixture = Fixture::new().await?;
    let original = message("$v1", "do not replay");
    fixture
        .store
        .ingest_inbox(&InboxDraft {
            event_id: MatrixEventId::parse("$v1")?,
            room_id: MatrixRoomId::parse(ROOM)?,
            sender: MatrixUserId::parse(OWNER)?,
            event_type: "m.room.message".to_string(),
            payload: serde_json::to_vec(&original["content"])?,
            binding_revision: 1,
            generation: 1,
            origin_server_ts_ms: 10,
            received_at_ms: 11,
        })
        .await?;
    let response = response(vec![original, redaction("$redaction", "$v1")])?;
    fixture
        .composer()
        .commit_response(
            &response,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    // An exact lost-response retry cannot create a second inbox admission.
    fixture
        .composer()
        .commit_response(
            &response,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    assert!(
        fixture
            .store
            .inbox(&MatrixEventId::parse("$v1")?)
            .await?
            .is_none()
    );
    assert_eq!(fixture.ingress.metrics().accepted, 0);
    fixture.store.close().await;
    let reopened =
        MatrixDurableStore::open(&fixture.layout, MatrixDurableConfig::default()).await?;
    assert!(reopened.pending_inbox(/*limit*/ 10).await?.is_empty());
    assert_eq!(
        reopened
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?
            .map(|checkpoint| checkpoint.next_batch),
        Some("s1".to_string())
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn nested_redaction_and_missing_target_never_reenter_ingress() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut nested = redaction("$nested", "$deleted");
    nested["content"] = json!({}); // unsigned redactions need no redacts field.
    let deleted = json!({"event_id":"$deleted","sender":OWNER,"origin_server_ts":10,
        "type":"m.room.message","content":{},"unsigned":{"redacted_because":nested}});
    fixture
        .composer()
        .commit_response(
            &response(vec![deleted, redaction("$nested", "$deleted")])?,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let checkpoint = fixture
        .store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?;
    let mut replay = response(vec![message("$deleted", "must remain deleted")])?;
    replay.next_batch = "s2".to_string();
    fixture
        .composer()
        .commit_response(
            &replay,
            checkpoint.as_ref(),
            /*observed_at_ms*/ 30,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    assert!(fixture.store.pending_inbox(/*limit*/ 10).await?.is_empty());
    assert_eq!(fixture.ingress.metrics().accepted, 0);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn incomplete_or_conflicting_response_leaves_all_rooms_and_cursor_unchanged() -> TestResult {
    let fixture = Fixture::new().await?;
    let before = fixture.store.snapshot(/*now_ms*/ 100, /*limit*/ 10).await?;
    let mut limited = response(vec![message("$valid", "must rollback")])?;
    limited.rooms.joined.insert(
        SECOND_ROOM.try_into()?,
        JoinedRoomUpdate {
            timeline: Timeline {
                limited: true,
                ..Default::default()
            },
            ..Default::default()
        },
    );
    let mut missing_leave = response(vec![message("$valid", "must rollback")])?;
    missing_leave
        .rooms
        .left
        .insert(SECOND_ROOM.try_into()?, LeftRoomUpdate::default());
    let mut mixed_room = response(vec![message("$valid", "must rollback")])?;
    mixed_room
        .rooms
        .left
        .insert(ROOM.try_into()?, LeftRoomUpdate::default());
    let mut outside_scope = response(Vec::new())?;
    outside_scope.rooms.joined.insert(
        "!outside:example.test".try_into()?,
        JoinedRoomUpdate::default(),
    );
    let mut invited = response(Vec::new())?;
    invited
        .rooms
        .invited
        .insert(ROOM.try_into()?, Default::default());
    let mut knocked = response(Vec::new())?;
    knocked
        .rooms
        .knocked
        .insert(ROOM.try_into()?, Default::default());
    let mut cross_room = message("$cross-room", "wrong container");
    cross_room["room_id"] = json!(SECOND_ROOM);
    let mut wrong_nested_target = redaction("$nested", "$other-target");
    let mut wrong_nested_room = redaction("$nested", "$deleted");
    wrong_nested_room["room_id"] = json!(SECOND_ROOM);
    let conflicting_nested = [&mut wrong_nested_target, &mut wrong_nested_room]
        .into_iter()
        .map(|deletion| {
            response(vec![
                json!({"event_id":"$deleted","sender":OWNER,"origin_server_ts":10,
            "type":"m.room.message","content":{},"unsigned":{"redacted_because":deletion}}),
            ])
        })
        .collect::<TestResult<Vec<_>>>()?;
    for rejected in [
        limited, missing_leave, mixed_room, outside_scope, invited, knocked,
        response(vec![cross_room])?,
        response(vec![message("$same", "one"), message("$same", "two")])?,
        response(vec![message("$valid", "must rollback"), json!({"type":"m.room.redaction","content":{}})])?,
        response(vec![json!({"event_id":"$encrypted","sender":OWNER,"origin_server_ts":10,
            "type":"m.room.encrypted","content":{"algorithm":"m.megolm.v1.aes-sha2",
                "ciphertext":"ciphertext","sender_key":"key","session_id":"session","device_id":"DEVICE"}})])?,
        response(vec![json!({"event_id":"$deleted","sender":OWNER,"origin_server_ts":10,
            "type":"m.room.message","content":{},"unsigned":{"redacted_because":{}}})])?,
        response(vec![message("$oversized", &"x".repeat(MAX_RAW_EVENT_BYTES))])?,
        response((0..=MAX_MATRIX_SYNC_MUTATIONS_V2).map(|i| message(&format!("$bound-{i}"), "x")).collect())?,
        response((0..17).map(|i| message(&format!("$bytes-{i}"), &"x".repeat(1_000_000))).collect())?,
    ].into_iter().chain(conflicting_nested) {
        assert_eq!(fixture.composer().commit_response(&rejected, /*checkpoint*/ None,
            /*observed_at_ms*/ 20, |_| Some(RoomVersionRules::V11)).await, Err(MatrixSdkError::Sync));
        assert_eq!(fixture.store.snapshot(/*now_ms*/ 100, /*limit*/ 10).await?, before);
        assert_eq!(fixture.store.sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1).await?, None);
    }
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn message_policy_and_repeated_page_keep_exact_ingress_counts() -> TestResult {
    let fixture = Fixture::new().await?;
    let valid = message("$valid", "admit once");
    let mut notice = message("$notice", "ignore notice");
    notice["content"]["msgtype"] = json!("m.notice");
    let mut missing_mention = message("$missing", "ignore missing mention");
    missing_mention["content"]
        .as_object_mut()
        .expect("content")
        .remove("m.mentions");
    let mut wrong_sender = message("$sender", "ignore sender");
    wrong_sender["sender"] = json!("@intruder:example.test");
    fixture
        .composer()
        .commit_response(
            &response(vec![
                json!({"type":"m.room.message","content":{}}),
                notice,
                missing_mention,
                wrong_sender,
                valid.clone(),
            ])?,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let checkpoint = fixture
        .store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?;
    let mut repeated = response(vec![valid])?;
    repeated.next_batch = "s2".to_string();
    fixture
        .composer()
        .commit_response(
            &repeated,
            checkpoint.as_ref(),
            /*observed_at_ms*/ 30,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let checkpoint = fixture
        .store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?;
    let unchanged = SyncResponse {
        next_batch: "s2".to_string(),
        ..Default::default()
    };
    fixture
        .composer()
        .commit_response(
            &unchanged,
            checkpoint.as_ref(),
            /*observed_at_ms*/ 31,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    // The owner validates an unchanged observation without spending a journal
    // entry or modifying the previous commit's timestamp.
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        checkpoint
    );
    assert_eq!(
        fixture.ingress.metrics(),
        crate::IngressMetrics {
            accepted: 1,
            duplicate: 1,
            ignored: 4,
            malformed: 1,
            failed: 0,
        }
    );
    assert_eq!(fixture.store.pending_inbox(/*limit*/ 10).await?.len(), 1);
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn unchanged_observation_requires_full_normalization_and_current_durable_checkpoint()
-> TestResult {
    let fixture = Fixture::new().await?;
    let mut idle = response(Vec::new())?;
    let invented = MatrixSyncCheckpoint {
        owner_agent_id: fixture.store.owner_agent_id().clone(),
        binding_revision: 1,
        generation: 1,
        next_batch: "s1".to_string(),
        updated_at_ms: 1,
    };
    assert_eq!(
        fixture
            .composer()
            .commit_response(
                &idle,
                Some(&invented),
                /*observed_at_ms*/ 10,
                |_| Some(RoomVersionRules::V11)
            )
            .await,
        Err(MatrixSdkError::Store)
    );
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        None
    );
    // A missing checkpoint takes the normal committed bootstrap path.
    fixture
        .composer()
        .commit_response(
            &idle,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let checkpoint = fixture
        .store
        .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
        .await?;
    idle.rooms
        .joined
        .get_mut(ROOM)
        .expect("room")
        .timeline
        .limited = true;
    assert_eq!(
        fixture
            .composer()
            .commit_response(
                &idle,
                checkpoint.as_ref(),
                /*observed_at_ms*/ 21,
                |_| Some(RoomVersionRules::V11)
            )
            .await,
        Err(MatrixSdkError::Sync)
    );
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        checkpoint
    );
    // Same-token observations carrying a mutation must commit it normally.
    fixture
        .composer()
        .commit_response(
            &response(vec![message("$same-token", "persist")])?,
            checkpoint.as_ref(),
            /*observed_at_ms*/ 30,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let mut expected = checkpoint.expect("bootstrap checkpoint");
    expected.updated_at_ms = 30;
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        Some(expected.clone())
    );
    assert_eq!(fixture.store.pending_inbox(/*limit*/ 10).await?.len(), 1);
    assert_eq!(fixture.ingress.metrics().accepted, 1);

    let checkpoint = expected.clone();
    let advancing = SyncResponse {
        next_batch: "s2".to_string(),
        ..Default::default()
    };
    fixture
        .composer()
        .commit_response(
            &advancing,
            Some(&checkpoint),
            /*observed_at_ms*/ 40,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    expected.next_batch = "s2".to_string();
    expected.updated_at_ms = 40;
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        Some(expected.clone())
    );
    let before = fixture
        .store
        .snapshot(/*now_ms*/ 100, /*limit*/ 100)
        .await?;
    idle.rooms
        .joined
        .get_mut(ROOM)
        .expect("room")
        .timeline
        .limited = false;
    assert_eq!(
        fixture
            .composer()
            .commit_response(
                &idle,
                Some(&checkpoint),
                /*observed_at_ms*/ 41,
                |_| Some(RoomVersionRules::V11)
            )
            .await,
        Err(MatrixSdkError::Store)
    );
    assert_eq!(
        fixture
            .store
            .snapshot(/*now_ms*/ 100, /*limit*/ 100)
            .await?,
        before
    );
    assert_eq!(
        fixture
            .store
            .sync_checkpoint(/*binding_revision*/ 1, /*generation*/ 1)
            .await?,
        Some(expected)
    );
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn membership_and_tombstone_state_fence_without_enrolling_replacements() -> TestResult {
    for before_state in [true, false] {
        let fixture = Fixture::new().await?;
        let tombstone = json!({"event_id":"$tombstone","sender":"@moderator:example.test",
            "origin_server_ts":12,"type":"m.room.tombstone","state_key":"",
            "content":{"body":"upgraded","replacement_room":"!replacement:example.test"}});
        let mut response = response(vec![message("$message", "obsolete"), tombstone.clone()])?;
        let state_events = vec![serde_json::from_value(tombstone.clone())?];
        response
            .rooms
            .joined
            .get_mut(ROOM)
            .expect("joined fixture")
            .state = if before_state {
            State::Before(state_events)
        } else {
            State::After(state_events)
        };
        fixture
            .composer()
            .commit_response(
                &response,
                /*checkpoint*/ None,
                /*observed_at_ms*/ 20,
                |_| Some(RoomVersionRules::V11),
            )
            .await?;
        assert!(fixture.store.pending_inbox(/*limit*/ 10).await?.is_empty());
        assert!(
            fixture
                .store
                .room_binding(&MatrixRoomId::parse("!replacement:example.test")?)
                .await?
                .is_none()
        );
        fixture.store.close().await;
    }
    let fixture = Fixture::new().await?;
    let member = json!({"event_id":"$kick","sender":"@moderator:example.test",
        "origin_server_ts":12,"type":"m.room.member","state_key":AGENT,
        "content":{"membership":"ban"}});
    let mut response = response(Vec::new())?;
    response.rooms.joined.clear();
    response.rooms.left.insert(
        ROOM.try_into()?,
        LeftRoomUpdate {
            timeline: timeline(vec![message("$old", "old"), member.clone()])?,
            state: State::After(vec![serde_json::from_value(member)?]),
            ..Default::default()
        },
    );
    fixture
        .composer()
        .commit_response(
            &response,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    assert!(fixture.store.pending_inbox(/*limit*/ 10).await?.is_empty());
    fixture.store.close().await;
    Ok(())
}

#[tokio::test]
async fn redaction_room_version_and_decision_payload_identity_are_enforced() -> TestResult {
    let fixture = Fixture::new().await?;
    let mut deletion = redaction("$redact", "$new");
    deletion["redacts"] = json!("$old");
    let response = response(vec![deletion])?;
    for (rules, target) in [
        (RoomVersionRules::V10, "$old"),
        (RoomVersionRules::V11, "$new"),
    ] {
        let mutations = fixture.composer().normalize(
            &response,
            /*observed_at_ms*/ 20,
            |_| Some(rules.clone()),
        )?;
        assert!(
            matches!(&mutations[0].body, MatrixSyncMutationBodyV2::Redaction { target_event_id }
            if target_event_id.as_str() == target)
        );
    }
    assert!(
        fixture
            .composer()
            .normalize(&response, /*observed_at_ms*/ 20, |_| None)
            .is_err()
    );
    let original = self::response(vec![message("$content", "original")])?;
    fixture
        .composer()
        .commit_response(
            &original,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11),
        )
        .await?;
    let before = fixture.store.snapshot(/*now_ms*/ 100, /*limit*/ 10).await?;
    let changed = self::response(vec![message("$content", "changed")])?;
    assert_eq!(
        fixture
            .composer()
            .commit_response(
                &changed,
                /*checkpoint*/ None,
                /*observed_at_ms*/ 20,
                |_| Some(RoomVersionRules::V11)
            )
            .await,
        Err(MatrixSdkError::Store)
    );
    assert_eq!(
        fixture.store.snapshot(/*now_ms*/ 100, /*limit*/ 10).await?,
        before
    );
    let mut changed_config = fixture.config.clone();
    changed_config.binding.require_explicit_mention = false;
    assert_eq!(
        MatrixSyncComposer {
            config: &changed_config,
            ingress: &fixture.ingress,
            store: &fixture.store
        }
        .commit_response(
            &original,
            /*checkpoint*/ None,
            /*observed_at_ms*/ 20,
            |_| Some(RoomVersionRules::V11)
        )
        .await,
        Err(MatrixSdkError::Configuration)
    );
    fixture.store.close().await;
    Ok(())
}
