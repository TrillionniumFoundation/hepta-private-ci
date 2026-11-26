use super::ResponseBudget;

#[test]
fn bounded_history_response_counts_escaped_wire_bytes() {
    let value = "\0".repeat(100);
    // Each NUL expands to six JSON wire bytes; include the two quotation marks.
    assert!(serde_json::to_writer(ResponseBudget(602), &value).is_ok());
    assert!(serde_json::to_writer(ResponseBudget(601), &value).is_err());
}
