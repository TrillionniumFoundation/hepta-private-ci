use super::*;

#[test]
fn canonical_request_is_bounded_and_sorted() {
    assert_eq!(
        encode_body(&json!({"z":1,"a":true})).unwrap(),
        r#"{"a":true,"z":1}"#
    );
    let error = encode_body(&json!({"padding":"x".repeat(MAX_REQUEST_BYTES)})).unwrap_err();
    assert_eq!(
        (error.code, error.request_dispatched),
        (ErrorCode::InvalidInput, Some(false))
    );
}

#[test]
fn invalid_request_preparation_never_becomes_ambiguous() {
    for input in [Value::Null, json!([]), json!({"method":"runtime/start"})] {
        let error = mutation_body("runtime/stop", &input).unwrap_err();
        assert_eq!(mutation_outcome(error.clone(), "op"), error);
    }
    assert!(mutation_body("runtime/stop\n", &json!({})).is_err());
    assert_eq!(
        mutation_body("runtime/stop", &json!({"operationId":"op"})).unwrap(),
        json!({"operationId":"op", "method":"runtime/stop"})
    );
}

#[test]
fn lookup_validates_every_identity_component() {
    let input = json!({"operationId":"op:1", "sessionId":"session-1", "connectionGeneration":1, "semanticDigest":"a".repeat(64)});
    assert_eq!(
        lookup_identity(&input).unwrap(),
        ("op:1".into(), "session-1".into(), 1, "a".repeat(64))
    );
    for (field, invalid) in [
        ("operationId", json!("../escaped")),
        ("sessionId", json!("")),
        ("connectionGeneration", json!(0)),
        ("connectionGeneration", json!(9_007_199_254_740_992_u64)),
        ("connectionGeneration", json!(1.5)),
        ("semanticDigest", json!("0".repeat(64))),
        ("semanticDigest", json!("A".repeat(64))),
    ] {
        let mut changed = input.clone();
        changed[field] = invalid;
        assert_eq!(
            lookup_identity(&changed).unwrap_err().request_dispatched,
            Some(false)
        );
    }
}

#[test]
fn response_media_types_are_explicit_and_strict() {
    for media in [
        "application/json",
        "APPLICATION/JSON",
        "application/problem+json; charset=utf-8",
        "application/vnd.hepta+json ; charset=utf-8",
    ] {
        assert_eq!(validate_headers(media, None, 200), Ok(()));
    }
    for media in [
        "",
        "text/plain",
        "application/jsonp",
        " application/json",
        "application/json ",
        "application/+json",
        "application/problem_json",
        "application/json, text/html",
        "application/json\u{0085}; charset=utf-8",
    ] {
        assert_eq!(
            validate_headers(media, None, 200).unwrap_err().code,
            ErrorCode::Transport
        );
    }
}

#[test]
fn content_length_is_safe_canonical_decimal_and_bounded() {
    for length in ["0", "10", " 1024 ", "1048576"] {
        assert_eq!(
            validate_headers("application/json", Some(length), 200),
            Ok(())
        );
    }
    for length in [
        "",
        "01",
        "+1",
        "-1",
        "1.0",
        "1e3",
        "1, 1",
        "9007199254740992",
        "18446744073709551616",
        "\u{0085}10",
    ] {
        assert!(validate_headers("application/json", Some(length), 200).is_err());
    }
    assert_eq!(
        validate_headers("application/json", Some("1048577"), 200)
            .unwrap_err()
            .details
            .get("maxBytes"),
        Some(&json!(MAX_RESPONSE_BYTES))
    );
}

#[test]
fn byte_ceiling_is_enforced_before_extending_buffer() {
    let mut bytes = ResponseBytes::default();
    bytes.append(&vec![b' '; MAX_RESPONSE_BYTES], 200).unwrap();
    assert_eq!(
        bytes.append(b"x", 200).unwrap_err().details.get("maxBytes"),
        Some(&json!(MAX_RESPONSE_BYTES))
    );
    assert_eq!(bytes.bytes.len(), MAX_RESPONSE_BYTES);
}

#[test]
fn strict_utf8_handles_split_scalars_and_rejects_invalid_prefix_immediately() {
    let mut bytes = ResponseBytes::default();
    for chunk in [b"\xf0".as_slice(), b"\x9f\x8c", b"\x8d"] {
        bytes.append(chunk, 200).unwrap();
    }
    assert_eq!(bytes.finish(200).unwrap(), "🌍".as_bytes());
    for invalid in [
        b"\xff".as_slice(),
        b"\xc0\x80",
        b"\xed\xa0\x80",
        b"\xf4\x90\x80\x80",
    ] {
        assert!(ResponseBytes::default().append(invalid, 200).is_err());
    }
    let mut truncated = ResponseBytes::default();
    truncated.append(b"\xe2\x82", 200).unwrap();
    assert!(truncated.finish(200).is_err());
}

#[test]
fn response_requires_json_object_without_reflecting_backend_text() {
    assert_eq!(
        parse_response(b"\xef\xbb\xbf{\"ok\":true}", 200).unwrap(),
        json!({"ok":true})
    );
    for bytes in [b"".as_slice(), b"null", b"[]", b"broken", b"\xff"] {
        assert!(parse_response(bytes, 200).is_err());
    }
    let error = parse_response(
        br#"{"errorCode":"DENIED","message":"internal secret"}"#,
        403,
    )
    .unwrap_err();
    assert_eq!(error.code, ErrorCode::PermissionDenied);
    assert!(!format!("{error:?} {error}").contains("internal secret"));
    assert_eq!(error.details.get("backendCode"), Some(&json!("DENIED")));
    assert_eq!(
        classify_http(500, &json!({"errorCode":"secret\nline"}))
            .details
            .get("backendCode"),
        Some(&Value::Null)
    );
}

#[test]
fn mutation_definite_rejection_and_dispatch_uncertainty_are_distinct() {
    for (status, code) in [
        (400, ErrorCode::BackendRejected),
        (401, ErrorCode::SessionExpired),
        (403, ErrorCode::PermissionDenied),
        (404, ErrorCode::BackendRejected),
        (409, ErrorCode::OperationConflict),
        (412, ErrorCode::StaleRevision),
        (422, ErrorCode::BackendRejected),
    ] {
        let error = mutation_outcome(classify_http(status, &json!({})), "op-1");
        assert_eq!(error.code, code);
        assert!(error.definitely_not_accepted());
    }
    for code in [
        ErrorCode::Transport,
        ErrorCode::Aborted,
        ErrorCode::AckMismatch,
    ] {
        let error = mutation_outcome(ControlError::new(code).with_dispatch(true), "op-1");
        assert_eq!(
            (error.code, error.request_dispatched),
            (ErrorCode::AmbiguousSubmission, Some(true))
        );
        assert!(!error.definitely_not_accepted());
    }
}
