use super::*;

fn parse(text: &str) -> Result<Headers, ShellError> {
    parse_headers(text.as_bytes(), text.len() + 4)
}

#[test]
fn ambiguous_or_oversized_framing_is_rejected() {
    let good = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    assert!(parse(good).is_ok());
    for extra in [
        "\r\nContent-Length: 2",
        "\r\nTransfer-Encoding: chunked",
        "\r\nX-Hepta-Response-MAC: second",
    ] {
        assert!(parse(&format!("{good}{extra}")).is_err());
    }
    assert!(parse(&good.replace("Content-Length: 2", "Content-Length: 999999999")).is_err());
    assert!(parse(&good.replace("HTTP/1.1 200", "garbage 200")).is_err());
}

#[test]
fn status_line_has_one_unambiguous_grammar() {
    let fields =
        "\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    for status in [
        "HTTP/1.1\t200 OK",
        "HTTP/1.1  200 OK",
        "HTTP/1.1 +200 OK",
        "HTTP/1.1 0200 OK",
        "HTTP/1.1 200",
        "HTTP/1.1 200 OK\nInjected: true",
        "HTTP/1.1 200 OK\0",
    ] {
        assert!(parse(&format!("{status}{fields}")).is_err());
    }
}

#[test]
fn unknown_header_cannot_smuggle_controls() {
    let good = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    for value in ["x\ny", "x\ry", "x\0y", "x\u{7f}y", "x\u{a0}y"] {
        assert!(parse(&format!("{good}\r\nX-Unknown: {value}")).is_err());
    }
    assert!(parse(&format!("{good}\r\nX-Unknown: \tvalue\t")).is_ok());
}

#[test]
fn content_length_is_nonempty_unsigned_decimal() {
    let good = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    for value in ["", "+2", "-2", "2, 2", "2 2", "0x2", "2\u{a0}"] {
        let invalid = good.replace("Content-Length: 2", &format!("Content-Length: {value}"));
        assert!(parse(&invalid).is_err());
    }
}

#[test]
fn declared_body_start_must_match_header_bytes() {
    let good = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    assert!(parse_headers(good.as_bytes(), 0).is_err());
    assert!(parse_headers(good.as_bytes(), usize::MAX).is_err());
}

#[test]
fn total_deadline_is_not_reset_by_progress() {
    let expired = Instant::now() - Duration::from_millis(1);
    assert!(remaining(expired).is_err());
    let deadline = Instant::now() + Duration::from_millis(100);
    let first = remaining(deadline).unwrap();
    std::thread::sleep(Duration::from_millis(5));
    assert!(remaining(deadline).unwrap() < first);
}

#[test]
fn lifecycle_real_http_binds_exact_post_and_authenticates_indeterminate_response() {
    use crate::fleet_lifecycle::FleetLifecycleOperation;
    use codex_hepta_contracts::native_gateway::lifecycle::NATIVE_GATEWAY_LIFECYCLE_PATH;
    for wrong_response in [false, true] {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let body=br#"{"schema_version":1,"request_id":71,"method":{"type":"receipt","agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","mutation_request_id":70}}"#;
        let worker = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(3)))
                .unwrap();
            let mut frame = Vec::new();
            let mut byte = [0];
            while !frame.ends_with(b"\r\n\r\n") {
                stream.read_exact(&mut byte).unwrap();
                frame.push(byte[0]);
            }
            let headers = std::str::from_utf8(&frame).unwrap();
            assert!(headers.starts_with(&format!(
                "POST {NATIVE_GATEWAY_LIFECYCLE_PATH} HTTP/1.1\r\n"
            )));
            let proof = NativeGatewayLifecycleRequestV2::parse_header(
                headers
                    .lines()
                    .find_map(|line| line.strip_prefix("Authorization: "))
                    .unwrap(),
            )
            .unwrap();
            let length = headers
                .lines()
                .find_map(|line| line.strip_prefix("Content-Length: "))
                .unwrap()
                .parse::<usize>()
                .unwrap();
            let mut received = vec![0; length];
            stream.read_exact(&mut received).unwrap();
            assert_eq!(received, body);
            proof
                .verify(
                    &[31; 32],
                    "POST",
                    NATIVE_GATEWAY_LIFECYCLE_PATH,
                    FleetLifecycleOperation::Receipt,
                    &received,
                    now_unix_ms().unwrap(),
                    &[11; 32],
                )
                .unwrap();
            assert!(
                proof
                    .verify(
                        &[31; 32],
                        "POST",
                        NATIVE_GATEWAY_LIFECYCLE_PATH,
                        FleetLifecycleOperation::Restart,
                        &received,
                        now_unix_ms().unwrap(),
                        &[11; 32]
                    )
                    .is_err()
            );
            let response = br#"{"type":"transport_indeterminate","request_id":71}"#;
            let tag = proof
                .response_tag(
                    if wrong_response { &[30; 32] } else { &[31; 32] },
                    503,
                    response,
                )
                .unwrap();
            write!(stream,"HTTP/1.1 503 Unavailable\r\nContent-Type: application/json\r\nContent-Length: {}\r\nX-Hepta-Response-MAC: {tag}\r\n\r\n",response.len()).unwrap();
            stream.write_all(response).unwrap();
        });
        let result = post_lifecycle(
            address,
            &[31; 32],
            FleetLifecycleOperation::Receipt,
            body,
            [11; 32],
        );
        if wrong_response {
            assert!(matches!(result, Err(ShellError::Security(_))));
        } else {
            assert_eq!(result.unwrap().value["request_id"], 71);
        }
        worker.join().unwrap();
    }
}
