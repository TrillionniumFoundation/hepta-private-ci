use super::*;
#[test]
fn ambiguous_or_oversized_framing_is_rejected() {
    let good = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nX-Hepta-Response-MAC: tag";
    assert!(parse_headers(good.as_bytes(), 120).is_ok());
    for extra in [
        "\r\nContent-Length: 2",
        "\r\nTransfer-Encoding: chunked",
        "\r\nX-Hepta-Response-MAC: second",
    ] {
        assert!(parse_headers(format!("{good}{extra}").as_bytes(), 120).is_err());
    }
    assert!(
        parse_headers(
            good.replace("Content-Length: 2", "Content-Length: 999999999")
                .as_bytes(),
            120
        )
        .is_err()
    );
    assert!(parse_headers(good.replace("HTTP/1.1 200", "garbage 200").as_bytes(), 120).is_err());
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
