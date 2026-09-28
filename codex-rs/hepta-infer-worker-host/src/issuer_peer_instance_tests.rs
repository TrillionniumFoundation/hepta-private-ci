use super::process_start_ticks;

#[test]
fn parses_start_time_after_parenthesized_process_name() {
    let fields = std::iter::once("S".to_string())
        .chain((4..=21).map(|_| "0".to_string()))
        .chain(std::iter::once("123456".to_string()))
        .collect::<Vec<_>>()
        .join(" ");
    let bytes = format!("42 (issuer with ) brackets) {fields}");
    assert_eq!(process_start_ticks(bytes.as_bytes()).unwrap(), 123_456);
}

#[test]
fn rejects_truncated_malformed_and_zero_start_time() {
    for bytes in [
        b"missing delimiter".as_slice(),
        b"42 (issuer) S 1",
        b"42 (issuer) S",
    ] {
        assert!(process_start_ticks(bytes).is_err());
    }
    let fields = ["0"; 20].join(" ");
    assert!(process_start_ticks(format!("42 (issuer) {fields}").as_bytes()).is_err());
}
