//! Admission identities distinguish normalized ordinary requests from old probes.
#![allow(
    clippy::expect_used,
    reason = "explicit prepared wire fixture invariants"
)]

use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

#[test]
fn ordinary_semantics_bind_settings_body_and_both_header_absences() {
    let body = Digest32::of_bytes(b"actual encoded fixed-marker body");
    let settings = Digest32::of_bytes(b"original owner metadata observation");
    let wire = PreparedOrdinaryWire::new(body, settings).expect("prepared before admission");
    let record = semantic_record(body, settings);
    assert_eq!(record["routing_hint"], Value::Null);
    assert_eq!(record["responses_lite"], false);
    assert_eq!(
        record["expected_absent_headers"],
        json!([
            "x-codex-routing-hint",
            "x-openai-internal-codex-responses-lite",
        ])
    );
    assert_eq!(wire.body_digest(), body);
    assert_ne!(
        wire.semantic_digest(),
        body,
        "old body-only admission remains a different identity"
    );
    assert!(!wire.dispatch_metadata().transport_invoked());
    assert_ne!(
        wire.semantic_digest(),
        PreparedOrdinaryWire::new(Digest32::of_bytes(b"changed body"), settings)
            .expect("other body")
            .semantic_digest()
    );
    assert_ne!(
        wire.semantic_digest(),
        PreparedOrdinaryWire::new(body, Digest32::of_bytes(b"changed owner metadata"))
            .expect("other metadata")
            .semantic_digest()
    );
}
