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
