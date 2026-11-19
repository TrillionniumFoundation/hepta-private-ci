use super::NativeContextDelivery;
use super::validate_context_delivery;

#[test]
fn delivery_rejects_ambiguous_modes_before_authority_or_journal_open() {
    for (value, query, intelligence) in [
        ("withhold", None, false),
        ("withhold", Some(""), false),
        ("withhold", Some("fixture nonce"), true),
        ("reader-off", None, false),
    ] {
        assert!(validate_context_delivery(value, query, intelligence).is_err());
    }
    assert!(matches!(
        validate_context_delivery("attach", None, false),
        Ok(NativeContextDelivery::Attach)
    ));
    assert!(matches!(
        validate_context_delivery("withhold", Some("fixture nonce"), false),
        Ok(NativeContextDelivery::Withhold)
    ));
}
