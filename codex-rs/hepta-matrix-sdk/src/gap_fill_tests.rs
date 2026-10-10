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

#[test]
fn visibility_and_page_limit_are_terminal_incomplete_observations() {
    for chunk in [vec![], vec![event("$visible")]] {
        let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
        assert_eq!(
            append(
                &mut accumulator,
                page("s-source", /*end*/ None, chunk, vec![])
            ),
            Ok(GapFillStatus::VisibilityBoundary)
        );
        let before = snapshot(&accumulator);
        assert_eq!(
            append(
                &mut accumulator,
                page("s-source", Some("t-target"), vec![], vec![])
            ),
            Err(GapFillError::Terminal)
        );
        assert_eq!(snapshot(&accumulator), before);
    }
    for (end, expected) in [
        ("hop", GapFillStatus::PageLimitReached),
        ("t-target", GapFillStatus::ReachedTarget),
    ] {
        let mut bounded = plan();
        bounded.limits.pages = 1;
        let mut accumulator = GapFillAccumulator::new(bounded).expect("plan");
        assert_eq!(
            append(
                &mut accumulator,
                page("s-source", Some(end), vec![], vec![])
            ),
            Ok(expected)
        );
        let before = snapshot(&accumulator);
        assert_eq!(
            append(&mut accumulator, page(end, Some("later"), vec![], vec![])),
            Err(GapFillError::Terminal)
        );
        assert_eq!(snapshot(&accumulator), before);
    }
}

#[test]
fn request_scope_drift_and_discontinuous_or_cyclic_pages_are_atomic_rejections() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    let expected_request = accumulator.request.clone();
    let mut requests = vec![expected_request.clone(); 7];
    requests[0].room_id = MatrixRoomId::parse("!other:example.test").expect("room");
    requests[1].from = "wrong-source".to_string();
    requests[2].to = "wrong-target".to_string();
    requests[3].direction = Direction::Backward;
    requests[4].filter_sha256 = Sha256Digest::for_bytes(b"other filter");
    requests[5].scope_sha256 = Sha256Digest::for_bytes(b"other connection or epoch");
    requests[6].limit += 1;
    let before = snapshot(&accumulator);
    for request in requests {
        assert_eq!(
            accumulator.append(&request, page("s-source", Some("t-target"), vec![], vec![])),
            Err(GapFillError::RequestDrift)
        );
        assert_eq!(snapshot(&accumulator), before);
    }
    for rejected in [
        page("wrong-start", Some("t-target"), vec![], vec![]),
        page("s-source", Some(""), vec![], vec![]),
        page("s-source", Some("bad\nend"), vec![], vec![]),
        page(
            "s-source",
            Some(&"x".repeat(MAX_TOKEN_BYTES + 1)),
            vec![],
            vec![],
        ),
    ] {
        assert_eq!(
            append(&mut accumulator, rejected),
            Err(GapFillError::InvalidPage)
        );
        assert_eq!(snapshot(&accumulator), before);
    }
    assert_eq!(
        append(
            &mut accumulator,
            page("s-source", Some("s-source"), vec![], vec![])
        ),
        Err(GapFillError::TokenCycle)
    );
    assert_eq!(snapshot(&accumulator), before);
    assert_eq!(
        append(
            &mut accumulator,
            page("s-source", Some("hop"), vec![], vec![])
        ),
        Ok(GapFillStatus::Fetching)
    );
    let before = snapshot(&accumulator);
    assert_eq!(
        accumulator.append(
            &expected_request,
            page("s-source", Some("hop"), vec![], vec![])
        ),
        Err(GapFillError::RequestDrift)
    );
    assert_eq!(
        append(
            &mut accumulator,
            page("hop", Some("s-source"), vec![], vec![])
        ),
        Err(GapFillError::TokenCycle)
    );
    assert_eq!(snapshot(&accumulator), before);
}

#[test]
fn chunk_and_state_identity_scope_failures_leave_accepted_evidence_unchanged() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    append(
        &mut accumulator,
        page("s-source", Some("hop"), vec![event("$accepted")], vec![]),
    )
    .expect("first page");
    let before = snapshot(&accumulator);
    let mut wrong_room = event("$wrong");
    wrong_room["room_id"] = json!("!other:example.test");
    let mut missing_room = event("$missing");
    missing_room
        .as_object_mut()
        .expect("object")
        .remove("room_id");
    let mut invalid_id = event("$valid");
    invalid_id["event_id"] = json!("not-an-event-id");
    for invalid in [wrong_room, missing_room, invalid_id, json!({})] {
        for rejected in [
            page("hop", Some("t-target"), vec![invalid.clone()], vec![]),
            page("hop", Some("t-target"), vec![], vec![invalid.clone()]),
        ] {
            assert_eq!(
                append(&mut accumulator, rejected),
                Err(GapFillError::InvalidPage)
            );
            assert_eq!(snapshot(&accumulator), before);
        }
    }
}

#[test]
fn duplicate_or_null_scope_fields_are_rejected_in_both_raw_page_vectors() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    let before = snapshot(&accumulator);
    for raw in [
        r#"{"room_id":"!room:example.test","room_id":"!room:example.test","event_id":"$a"}"#,
        r#"{"room_id":"!other:example.test","room_id":"!room:example.test","event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","room_id":"!other:example.test","event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","room\u005fid":"!room:example.test","event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","event_id":"$a","event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","event_id":"$a","event_id":"$b"}"#,
        r#"{"room_id":"!room:example.test","event_id":"$b","event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","event_id":"$a","event\u005fid":"$a"}"#,
        r#"{"room_id":null,"event_id":"$a"}"#,
        r#"{"room_id":"!room:example.test","event_id":null}"#,
        r#"["!room:example.test","$a"]"#,
        "42",
    ] {
        let mut chunk_page = page("s-source", Some("t-target"), vec![], vec![]);
        chunk_page.chunk.push(TimelineEvent::from_plaintext(
            Raw::from_json_string(raw.to_string()).expect("raw"),
        ));
        let mut state_page = page("s-source", Some("t-target"), vec![], vec![]);
        state_page
            .state
            .push(Raw::from_json_string(raw.to_string()).expect("raw"));
        for rejected in [chunk_page, state_page] {
            assert_eq!(
                append(&mut accumulator, rejected),
                Err(GapFillError::InvalidPage)
            );
            assert_eq!(snapshot(&accumulator), before);
        }
    }
}

#[test]
fn sdk_bundled_metadata_is_dropped_instead_of_retained_outside_raw_bounds() {
    let mut baseline = GapFillAccumulator::new(plan()).expect("plan");
    append(
        &mut baseline,
        page(
            "s-source",
            Some("t-target"),
            vec![event("$visible")],
            vec![],
        ),
    )
    .expect("baseline page");
    let mut enriched = page(
        "s-source",
        Some("t-target"),
        vec![event("$visible")],
        vec![],
    );
    let mut large = event("$bundled");
    large["content"]["body"] = json!("x".repeat(MAX_BYTES + 1));
    let bundled = page("unused", /*end*/ None, vec![large], vec![])
        .chunk
        .pop()
        .expect("bundle");
    assert!(bundled.raw().json().get().len() > MAX_BYTES);
    enriched.chunk[0].bundled_latest_thread_event = Some(Box::new(bundled));
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    assert_eq!(
        append(&mut accumulator, enriched),
        Ok(GapFillStatus::ReachedTarget)
    );
    assert_eq!(snapshot(&accumulator), snapshot(&baseline));
    assert_eq!(
        accumulator.pages[0].chunk[0].json().get().len(),
        accumulator.observation.event_bytes
    );
}

#[test]
fn page_and_accumulated_count_and_byte_limits_include_ancillary_state() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    let before = snapshot(&accumulator);
    assert_eq!(
        append(
            &mut accumulator,
            page(
                "s-source",
                Some("t-target"),
                vec![event("$one")],
                vec![state("$member"); MAX_PAGE_EVENTS]
            )
        ),
        Err(GapFillError::Bounds)
    );
    let mut oversized = event("$large");
    oversized["content"]["body"] = json!("x".repeat(MAX_EVENT_BYTES));
    assert_eq!(
        append(
            &mut accumulator,
            page("s-source", Some("t-target"), vec![], vec![oversized])
        ),
        Err(GapFillError::Bounds)
    );
    assert_eq!(snapshot(&accumulator), before);

    let mut bounded = plan();
    bounded.limits.events = 3;
    let mut accumulator = GapFillAccumulator::new(bounded).expect("plan");
    append(
        &mut accumulator,
        page(
            "s-source",
            Some("hop"),
            vec![event("$one")],
            vec![state("$member")],
        ),
    )
    .expect("first page");
    let before = snapshot(&accumulator);
    assert_eq!(
        append(
            &mut accumulator,
            page(
                "hop",
                Some("t-target"),
                vec![event("$two")],
                vec![state("$member")]
            )
        ),
        Err(GapFillError::Bounds)
    );
    assert_eq!(snapshot(&accumulator), before);

    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    let mut large = event("$bytes");
    large["content"]["body"] = json!("x".repeat(1_000_000));
    append(
        &mut accumulator,
        page("s-source", Some("hop"), vec![large.clone(); 16], vec![]),
    )
    .expect("bounded first page");
    let before = accumulator.observation.clone();
    assert_eq!(
        append(
            &mut accumulator,
            page("hop", Some("t-target"), vec![], vec![large])
        ),
        Err(GapFillError::Bounds)
    );
    assert_eq!(accumulator.observation, before);
    assert_eq!(accumulator.pages.len(), 1);
}

#[test]
fn exact_total_event_limit_can_reach_target_without_truncation() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    for i in 0..MAX_PAGES {
        let from = accumulator.request.from.clone();
        let end = if i + 1 == MAX_PAGES {
            "t-target".to_string()
        } else {
            format!("hop-{i}")
        };
        let expected = if i + 1 == MAX_PAGES {
            GapFillStatus::ReachedTarget
        } else {
            GapFillStatus::Fetching
        };
        assert_eq!(
            append(
                &mut accumulator,
                page(
                    &from,
                    Some(&end),
                    vec![event("$overlap"); MAX_PAGE_EVENTS],
                    vec![]
                )
            ),
            Ok(expected)
        );
    }
    assert_eq!(
        (
            accumulator.observation.pages,
            accumulator.observation.events
        ),
        (MAX_PAGES, MAX_EVENTS)
    );
}

#[test]
fn transcript_binds_scope_limits_order_raw_bytes_state_and_terminal_evidence() {
    let mut accumulator = GapFillAccumulator::new(plan()).expect("plan");
    append(
        &mut accumulator,
        page(
            "s-source",
            Some("t-target"),
            vec![event("$a"), event("$b")],
            vec![],
        ),
    )
    .expect("page");
    let expected = accumulator.observation.clone();
    let mut replay = GapFillAccumulator::new(plan()).expect("plan");
    append(
        &mut replay,
        page(
            "s-source",
            Some("t-target"),
            vec![event("$a"), event("$b")],
            vec![],
        ),
    )
    .expect("page");
    assert_eq!(replay.observation, expected);
    let mut changed = event("$a");
    changed["unsigned"] = json!({"age":123});
    for alternate in [
        page(
            "s-source",
            Some("t-target"),
            vec![event("$b"), event("$a")],
            vec![],
        ),
        page(
            "s-source",
            Some("t-target"),
            vec![changed, event("$b")],
            vec![],
        ),
        page(
            "s-source",
            Some("t-target"),
            vec![event("$a")],
            vec![event("$b")],
        ),
        page(
            "s-source",
            /*end*/ None,
            vec![event("$a"), event("$b")],
            vec![],
        ),
    ] {
        let mut alternate_accumulator = GapFillAccumulator::new(plan()).expect("plan");
        append(&mut alternate_accumulator, alternate).expect("observed page");
        assert_ne!(
            alternate_accumulator.observation.transcript_sha256,
            expected.transcript_sha256
        );
    }
    let mut plans = vec![plan(); 8];
    plans[0].binding.expected_device_id = MatrixDeviceId::parse("OTHER").expect("device");
    plans[1].generation += 1;
    plans[2].connection_sha256 = Sha256Digest::for_bytes(b"connection-2");
    plans[3].room_version = RoomVersionId::V10;
    plans[4].filter_sha256 = Sha256Digest::for_bytes(b"different filter");
    plans[5].response_next_batch = "s-other-next".to_string();
    plans[6].limits.events -= 1;
    plans[7].limits.pages -= 1;
    for changed_plan in plans {
        let mut alternate = GapFillAccumulator::new(changed_plan).expect("plan");
        append(
            &mut alternate,
            page(
                "s-source",
                Some("t-target"),
                vec![event("$a"), event("$b")],
                vec![],
            ),
        )
        .expect("page");
        assert_ne!(
            alternate.observation.transcript_sha256,
            expected.transcript_sha256
        );
    }
}

#[test]
fn invalid_plan_cannot_start_or_manufacture_zero_length_completion() {
    let mut plans = vec![plan(); 13];
    plans[0].source_sync_token.clear();
    plans[1].target_prev_batch = "s-source".to_string();
    plans[2].response_next_batch = "bad\nnext".to_string();
    plans[3].source_sync_token = "x".repeat(MAX_TOKEN_BYTES + 1);
    plans[4].limits.pages = 0;
    plans[5].limits.pages = MAX_PAGES + 1;
    plans[6].limits.events = MAX_EVENTS + 1;
    plans[7].limits.event_bytes = MAX_BYTES + 1;
    plans[8].generation = 0;
    plans[9].room_id = MatrixRoomId::parse("!other:example.test").expect("room");
    plans[10].binding.revision = 0;
    plans[11].room_version = "org.example.unknown"
        .try_into()
        .expect("custom room version");
    plans[12].binding.homeserver = MatrixHomeserverUrl::parse(format!(
        "https://example.test/{}",
        "x".repeat(MAX_HOMESERVER_BYTES)
    ))
    .expect("large URL");
    for invalid in plans {
        assert!(matches!(
            GapFillAccumulator::new(invalid),
            Err(GapFillError::InvalidPlan)
        ));
    }
}
