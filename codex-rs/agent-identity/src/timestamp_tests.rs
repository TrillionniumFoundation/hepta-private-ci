use super::seconds_at;
use crate::AgentIdentityKey;
use crate::BASE64_STANDARD;
use crate::sign_agent_assertion_payload;
use crate::sign_task_registration_payload;
use base64::Engine as _;
use ed25519_dalek::Signature;
use ed25519_dalek::SigningKey;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::pkcs8::EncodePrivateKey;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;

#[test]
fn seconds_timestamp_preserves_utc_bytes_and_truncates_fraction() {
    let cases = [
        (OffsetDateTime::UNIX_EPOCH, "1970-01-01T00:00:00Z"),
        (
            time::macros::datetime!(2024-02-29 23:59:59.999999999 UTC),
            "2024-02-29T23:59:59Z",
        ),
        (
            time::macros::datetime!(2024-03-01 00:30:00.123456789 +01:00),
            "2024-02-29T23:30:00Z",
        ),
    ];
    for (now, expected) in cases {
        assert_eq!(seconds_at(now), expected);
    }
}

#[test]
fn timestamp_bytes_remain_bound_to_both_original_signed_payloads() {
    let signing_key = SigningKey::from_bytes(&[7u8; 32]);
    let private_key = signing_key.to_pkcs8_der().expect("encode signing key");
    let encoded_key = BASE64_STANDARD.encode(private_key.as_bytes());
    let key = AgentIdentityKey {
        agent_runtime_id: "agent-123",
        private_key_pkcs8_base64: &encoded_key,
    };
    let timestamp = seconds_at(time::macros::datetime!(2024-02-29 23:59:59.999999999 UTC));
    assert_eq!(timestamp, "2024-02-29T23:59:59Z");
    let cases = [
        (
            sign_agent_assertion_payload(key, "task-123", &timestamp)
                .expect("sign agent assertion"),
            b"agent-123:task-123:2024-02-29T23:59:59Z".as_slice(),
        ),
        (
            sign_task_registration_payload(key, &timestamp).expect("sign task registration"),
            b"agent-123:2024-02-29T23:59:59Z".as_slice(),
        ),
    ];
    for (encoded, expected_payload) in cases {
        let bytes = BASE64_STANDARD.decode(encoded).expect("decode signature");
        let signature = Signature::from_slice(&bytes).expect("parse signature");
        signing_key
            .verifying_key()
            .verify(expected_payload, &signature)
            .expect("signature must verify over the original literal payload bytes");
    }
}

#[cfg(not(all(
    target_arch = "wasm32",
    not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
)))]
#[test]
#[should_panic(expected = "system time before Unix epoch")]
fn seconds_timestamp_preserves_native_pre_epoch_refusal() {
    let timestamp = -1;
    let now = OffsetDateTime::from_unix_timestamp_nanos(timestamp).expect("valid pre-epoch time");
    seconds_at(now);
}
