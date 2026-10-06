use super::*;
fn document(observation: serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(
        &serde_json::json!({"schema":"hepta.owner-lease-observation.v1","observation":observation}),
    )
    .expect("synthetic wire fixture")
}
#[test]
fn max_unsigned_wire_generation_renders_exactly_without_implying_sqlite_admission() {
    let bytes = document(
        serde_json::json!({"status":"observed","generation":u64::MAX,"disposition":"released"}),
    );
    let value = parse(200, &bytes).expect("lossless Rust serde bytes");
    let text = OwnerReadState::Received(value).display_text();
    assert!(text.contains("18446744073709551615"));
    assert!(text.contains("not current write authority"));
    let overflow = String::from_utf8(bytes)
        .expect("JSON")
        .replace("18446744073709551615", "18446744073709551616");
    assert_eq!(
        parse(200, overflow.as_bytes()),
        Err(RuntimeUnavailable::InvalidStatus)
    );
}
#[test]
fn malformed_private_fields_and_inconsistent_generation_are_rejected() {
    for value in [
        serde_json::json!({"status":"not_attached","fencing_token":"forbidden"}),
        serde_json::json!({"status":"observed","generation":null,"disposition":"active"}),
        serde_json::json!({"status":"observed","generation":1,"disposition":"missing"}),
        serde_json::json!({"status":"unavailable","reason":"/private/key/path"}),
        serde_json::json!({"status":"observed","generation":-1,"disposition":"released"}),
    ] {
        assert_eq!(
            parse(200, &document(value)),
            Err(RuntimeUnavailable::InvalidStatus)
        );
    }
    assert_eq!(
        parse(200, &vec![b' '; MAX_OWNER_STATUS_BYTES + 1]),
        Err(RuntimeUnavailable::Oversize)
    );
    assert_eq!(parse(503, b"{}"), Err(RuntimeUnavailable::Transport));
}
#[test]
fn not_attached_and_read_failure_never_become_ready_or_write_authority() {
    for observation in [
        serde_json::json!({"status":"not_attached"}),
        serde_json::json!({"status":"unavailable","reason":"busy"}),
    ] {
        let text =
            OwnerReadState::Received(parse(200, &document(observation)).expect("valid status"))
                .display_text();
        assert!(text.contains("commands remain unavailable"));
        assert!(!text.contains("Ready"));
    }
}
#[test]
fn refresh_cancel_epoch_and_late_reply_preserve_single_flight_and_clear_old_observation() {
    let body = document(serde_json::json!({"status":"not_attached"}));
    let mut reader = OwnerReader::default();
    let first = reader.begin().expect("first");
    assert_eq!(reader.begin(), None);
    reader.disconnect();
    let second = reader.begin().expect("new epoch");
    assert!(!reader.complete(first, 200, &body));
    assert_eq!(reader.state(), &OwnerReadState::Loading);
    assert!(reader.complete(second, 200, &body));
    let third = reader.begin().expect("explicit refresh");
    assert!(reader.fail(third, RuntimeUnavailable::TimedOut));
    assert!(!reader.complete(third, 200, &body));
    assert_eq!(
        reader.state(),
        &OwnerReadState::Unavailable(RuntimeUnavailable::TimedOut)
    );
    reader.disconnect();
    assert_eq!(
        reader.state(),
        &OwnerReadState::Unavailable(RuntimeUnavailable::NotConnected)
    );
}
#[test]
fn ticket_exhaustion_does_not_recycle_request_identity() {
    let mut reader = OwnerReader {
        next: u64::MAX,
        ..Default::default()
    };
    assert_eq!(reader.begin(), None);
    assert_eq!(
        reader.state(),
        &OwnerReadState::Unavailable(RuntimeUnavailable::CounterExhausted)
    );
}

#[test]
fn card_headlines_distinguish_absence_from_recorded_metadata() {
    assert_eq!(
        OwnerReader::default().state().observation_headline(),
        "Not requested"
    );
    assert_eq!(OwnerReadState::Loading.observation_headline(), "Reading…");
    for (observation, expected) in [
        (serde_json::json!({"status":"not_attached"}), "Not attached"),
        (
            serde_json::json!({"status":"unavailable","reason":"busy"}),
            "Unavailable",
        ),
        (
            serde_json::json!({"status":"observed","generation":null,"disposition":"missing"}),
            "Recorded missing",
        ),
        (
            serde_json::json!({"status":"observed","generation":1,"disposition":"active"}),
            "Recorded active",
        ),
        (
            serde_json::json!({"status":"observed","generation":1,"disposition":"expired_active"}),
            "Recorded expired active",
        ),
        (
            serde_json::json!({"status":"observed","generation":1,"disposition":"released"}),
            "Recorded released",
        ),
        (
            serde_json::json!({"status":"observed","generation":1,"disposition":"rolled_back"}),
            "Recorded rolled back",
        ),
    ] {
        let state =
            OwnerReadState::Received(parse(200, &document(observation)).expect("valid fixture"));
        assert_eq!(state.observation_headline(), expected);
        assert!(state.display_text().contains("not current write authority"));
    }
    for reason in [
        RuntimeUnavailable::Transport,
        RuntimeUnavailable::TimedOut,
        RuntimeUnavailable::Oversize,
        RuntimeUnavailable::InvalidStatus,
        RuntimeUnavailable::CounterExhausted,
    ] {
        let state = OwnerReadState::Unavailable(reason);
        assert_eq!(state.observation_headline(), "Unavailable");
        assert!(state.display_text().contains(&format!("{reason:?}")));
    }
}
