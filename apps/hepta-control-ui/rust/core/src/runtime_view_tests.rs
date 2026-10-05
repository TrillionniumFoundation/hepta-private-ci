use super::*;

fn payload() -> serde_json::Value {
    serde_json::json!({
        "schema":"hepta_vnext_live_runtime_status_v1","product":"hepta","status":"ready",
        "state_root":"/existing/runtime",
        "state":{"adapter":"sqlite-schema-v5","schema_version":5,"outcome_generation":1,
            "preference_generation":2,"runtime_snapshot_version":1,"runtime_snapshot_generation":3,
            "integrity_binding_present":true,"integrity_verification":"owner-verified",
            "open_mode":"immutable-query-only-open-existing"},
        "authority":{"telegram":false,"outbound":false,"model_invocation":false,
            "operator_mutation":false,"enforce":false,"promotion":false,"retirement":false,
            "automatic_transition":false}
    })
}

#[test]
fn repeated_start_and_late_reply_cannot_replace_newer_status() {
    let mut reader = RuntimeReader::default();
    let first = reader.begin().expect("first request");
    assert_eq!(reader.begin(), None);
    assert_eq!(reader.disconnect(), Some(first));
    let second = reader.begin().expect("second request");
    let body = serde_json::to_vec(&payload()).expect("fixture");
    assert!(!reader.complete(first, 200, &body));
    assert_eq!(reader.state(), &RuntimeReadState::Loading);
    assert!(reader.complete(second, 200, &body));
    let ready = reader.state().clone();
    assert!(!reader.fail(first, RuntimeUnavailable::Transport));
    assert_eq!(reader.state(), &ready);
}

#[test]
fn timeout_and_disconnect_never_leave_old_success_displayed_as_current() {
    let mut reader = RuntimeReader::default();
    let body = serde_json::to_vec(&payload()).expect("fixture");
    let first = reader.begin().expect("request");
    assert!(reader.complete(first, 200, &body));
    let second = reader.begin().expect("refresh");
    assert!(reader.fail(second, RuntimeUnavailable::TimedOut));
    assert_eq!(
        reader.state(),
        &RuntimeReadState::Unavailable(RuntimeUnavailable::TimedOut)
    );
    assert!(!reader.complete(second, 200, &body));
    reader.disconnect();
    assert_eq!(
        reader.state(),
        &RuntimeReadState::Unavailable(RuntimeUnavailable::NotConnected)
    );
}

#[test]
fn malformed_http_schema_and_authority_are_unavailable_without_truncation() {
    assert_eq!(
        parse_snapshot(503, b"{}"),
        Err(RuntimeUnavailable::Transport)
    );
    assert_eq!(
        parse_snapshot(200, b"{"),
        Err(RuntimeUnavailable::InvalidStatus)
    );
    let mut changed = payload();
    changed["authority"]["outbound"] = true.into();
    assert_eq!(
        parse_snapshot(200, &serde_json::to_vec(&changed).expect("fixture")),
        Err(RuntimeUnavailable::InvalidStatus)
    );
    changed = payload();
    changed["state"]["schema_version"] = 6.into();
    assert_eq!(
        parse_snapshot(200, &serde_json::to_vec(&changed).expect("fixture")),
        Err(RuntimeUnavailable::InvalidStatus)
    );
    assert_eq!(
        parse_snapshot(200, &vec![b' '; MAX_RUNTIME_JSON_BYTES + 1]),
        Err(RuntimeUnavailable::Oversize)
    );
}

#[test]
fn long_escaped_path_is_preserved_above_wire_v2_limit_within_json_bound() {
    let mut value = payload();
    // JSON and wire-v2 have different envelopes/limits. No module collection
    // exists in this DTO; the path is its variable-size production field.
    let path = format!("/{}", "漢\\\n".repeat(8192));
    value["state_root"] = path.clone().into();
    let bytes = serde_json::to_vec(&value).expect("fixture");
    assert!(bytes.len() > 32 * 1024 && bytes.len() < MAX_RUNTIME_JSON_BYTES);
    let result = parse_snapshot(200, &bytes).expect("bounded complete DTO");
    assert_eq!(result.state_root, path);
    let text = RuntimeReadState::Ready(Box::new(result)).display_text();
    assert!(text.contains(&format!("{path:?}")));
}

#[test]
fn request_counter_exhaustion_does_not_reuse_a_ticket() {
    let mut reader = RuntimeReader {
        next: u64::MAX,
        ..RuntimeReader::default()
    };
    assert_eq!(reader.begin(), None);
    assert_eq!(
        reader.state(),
        &RuntimeReadState::Unavailable(RuntimeUnavailable::CounterExhausted)
    );
}
