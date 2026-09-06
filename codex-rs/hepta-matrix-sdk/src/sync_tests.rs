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
