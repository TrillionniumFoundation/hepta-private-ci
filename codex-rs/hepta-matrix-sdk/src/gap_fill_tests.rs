use codex_hepta_contracts::AgentId;
use codex_hepta_matrix_protocol::MATRIX_BINDING_SCHEMA_VERSION;
use codex_hepta_matrix_protocol::MatrixDeviceId;
use codex_hepta_matrix_protocol::MatrixHomeserverUrl;
use codex_hepta_matrix_protocol::MatrixUserId;
use matrix_sdk::deserialized_responses::TimelineEvent;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::*;

const ROOM: &str = "!room:example.test";

fn plan() -> GapFillPlan {
    GapFillPlan {
        binding: MatrixBindingV1 {
            schema_version: MATRIX_BINDING_SCHEMA_VERSION,
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            revision: 1,
            homeserver: MatrixHomeserverUrl::parse("https://example.test").expect("server"),
            expected_mxid: MatrixUserId::parse("@agent:example.test").expect("user"),
            expected_device_id: MatrixDeviceId::parse("DEVICE").expect("device"),
            allowed_rooms: vec![MatrixRoomId::parse(ROOM).expect("room")],
            allowed_senders: vec![MatrixUserId::parse("@owner:example.test").expect("sender")],
            require_explicit_mention: true,
        },
        generation: 1,
        room_id: MatrixRoomId::parse(ROOM).expect("room"),
        connection_sha256: Sha256Digest::for_bytes(b"connection-1"),
        room_version: RoomVersionId::V11,
        filter_sha256: Sha256Digest::for_bytes(b"frozen-filter-v1"),
        source_sync_token: "s-source".to_string(),
        target_prev_batch: "t-target".to_string(),
        response_next_batch: "s-next".to_string(),
        limits: GapFillLimits {
            pages: MAX_PAGES,
            events: MAX_EVENTS,
            event_bytes: MAX_BYTES,
        },
    }
}

fn event(id: &str) -> Value {
    json!({"event_id":id,"room_id":ROOM,"sender":"@owner:example.test",
        "origin_server_ts":10,"type":"m.room.message","content":{"msgtype":"m.text","body":id}})
}

fn state(id: &str) -> Value {
    json!({"event_id":id,"room_id":ROOM,"sender":"@owner:example.test",
        "origin_server_ts":10,"type":"m.room.member","state_key":"@agent:example.test",
        "content":{"membership":"join"}})
}

fn page(start: &str, end: Option<&str>, chunk: Vec<Value>, state: Vec<Value>) -> Messages {
    Messages {
        start: start.to_string(),
        end: end.map(str::to_owned),
        chunk: chunk
            .into_iter()
            .map(|value| {
                TimelineEvent::from_plaintext(
                    Raw::from_json_string(serde_json::to_string(&value).expect("JSON"))
                        .expect("raw event"),
                )
            })
            .collect(),
        state: state
            .into_iter()
            .map(|value| serde_json::from_value(value).expect("raw state"))
            .collect(),
    }
}

fn append(
    accumulator: &mut GapFillAccumulator,
    page: Messages,
) -> Result<GapFillStatus, GapFillError> {
    accumulator.append(&accumulator.request.clone(), page)
}

fn snapshot(accumulator: &GapFillAccumulator) -> Value {
    json!({
        "status":accumulator.observation.status,
        "pages":accumulator.observation.pages,
        "events":accumulator.observation.events,
        "bytes":accumulator.observation.event_bytes,
        "digest":accumulator.observation.transcript_sha256,
        "request":accumulator.request,
        "visited":accumulator.visited_tokens,
        "accepted":accumulator.pages.iter().map(|page| json!({
            "start":page.start,"end":page.end,
            "chunk":page.chunk,
            "state":page.state,
        })).collect::<Vec<_>>()
    })
}

#[test]
fn empty_page_continues_and_exact_target_preserves_page_and_event_order() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    assert_eq!(
        append(
            &mut accumulator,
            page("s-source", Some("hop-1"), vec![], vec![])
        ),
        Ok(GapFillStatus::Fetching)
    );
    assert_eq!(
        append(
            &mut accumulator,
            page(
                "hop-1",
                Some("hop-2"),
                vec![event("$a"), event("$overlap")],
                vec![state("$state")]
            )
        ),
        Ok(GapFillStatus::Fetching)
    );
    assert_eq!(
        append(
            &mut accumulator,
            page(
                "hop-2",
                Some("t-target"),
                vec![event("$overlap"), event("$b")],
                vec![]
            )
        ),
        Ok(GapFillStatus::ReachedTarget)
    );
    assert_eq!(
        snapshot(&accumulator)["accepted"],
        json!([
            {"start":"s-source","end":"hop-1","chunk":[],"state":[]},
            {"start":"hop-1","end":"hop-2","chunk":[event("$a"),event("$overlap")],"state":[state("$state")]},
            {"start":"hop-2","end":"t-target","chunk":[event("$overlap"),event("$b")],"state":[]},
        ])
    );
    assert_eq!(
        (
            accumulator.observation.status,
            accumulator.observation.pages,
            accumulator.observation.events
        ),
        (GapFillStatus::ReachedTarget, 3, 5)
    );
    let before = snapshot(&accumulator);
    assert_eq!(
        append(
            &mut accumulator,
            page("t-target", Some("later"), vec![], vec![])
        ),
        Err(GapFillError::Terminal)
    );
    assert_eq!(snapshot(&accumulator), before);
}
