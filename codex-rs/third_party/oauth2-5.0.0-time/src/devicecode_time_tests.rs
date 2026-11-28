use crate::tests::new_client;
use crate::StandardDeviceAuthorizationResponse;
use serde_json::json;
use std::time::Duration;
use time::OffsetDateTime;

fn details() -> StandardDeviceAuthorizationResponse {
    serde_json::from_value(json!({
        "device_code": "device-code",
        "user_code": "user-code",
        "verification_uri": "https://example.com/activate",
        "expires_in": 2,
        "interval": 1,
    }))
    .unwrap()
}

#[test]
fn deadline_keeps_subsecond_arithmetic_across_the_unix_epoch() {
    let details = details();
    let client = new_client();
    for nanos in [-1_000_000_001, -1, 0, 1] {
        let start = OffsetDateTime::from_unix_timestamp_nanos(nanos).unwrap();
        let request = client
            .exchange_device_access_token(&details)
            .set_time_fn(move || start);
        let result =
            request.compute_timeout::<std::io::Error>(Some(Duration::from_nanos(/*nanos*/ 1)));
        assert_eq!(
            result.unwrap(),
            OffsetDateTime::from_unix_timestamp_nanos(nanos + 1).unwrap()
        );
    }
}

#[test]
fn deadline_preserves_default_expiry_and_explicit_timeout() {
    let details = details();
    let client = new_client();
    let request = client
        .exchange_device_access_token(&details)
        .set_time_fn(|| OffsetDateTime::UNIX_EPOCH);
    assert_eq!(
        request
            .compute_timeout::<std::io::Error>(None)
            .unwrap()
            .unix_timestamp_nanos(),
        2_000_000_000,
    );
    assert_eq!(
        request
            .compute_timeout::<std::io::Error>(Some(Duration::from_millis(/*millis*/ 300)))
            .unwrap()
            .unix_timestamp_nanos(),
        300_000_000,
    );
}

#[test]
fn deadline_keeps_the_prior_timestamp_limits() {
    let details = details();
    let client = new_client();
    for seconds in [
        crate::timestamp::MIN_UNIX_SECONDS,
        crate::timestamp::MAX_UNIX_SECONDS,
    ] {
        let start = OffsetDateTime::from_unix_timestamp(seconds).unwrap();
        let request = client
            .exchange_device_access_token(&details)
            .set_time_fn(move || start);
        assert_eq!(
            request
                .compute_timeout::<std::io::Error>(Some(Duration::ZERO))
                .unwrap(),
            start
        );
    }
    let last_nanosecond =
        i128::from(crate::timestamp::MAX_UNIX_SECONDS) * 1_000_000_000 + 999_999_999;
    let start = OffsetDateTime::from_unix_timestamp_nanos(last_nanosecond).unwrap();
    let request = client
        .exchange_device_access_token(&details)
        .set_time_fn(move || start);
    assert_eq!(
        request
            .compute_timeout::<std::io::Error>(Some(Duration::ZERO))
            .unwrap(),
        start
    );
    assert!(request
        .compute_timeout::<std::io::Error>(Some(Duration::from_nanos(/*nanos*/ 1)))
        .is_err());
}

#[test]
fn deadline_rejects_unrepresentable_duration_without_panicking() {
    let details = details();
    let client = new_client();
    let request = client
        .exchange_device_access_token(&details)
        .set_time_fn(|| OffsetDateTime::UNIX_EPOCH);
    assert!(request
        .compute_timeout::<std::io::Error>(Some(Duration::MAX))
        .is_err());
}
