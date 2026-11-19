use crate::basic::BasicTokenIntrospectionResponse;
use crate::EmptyExtraTokenFields;
use crate::TokenIntrospectionResponse;
use serde_json::json;
use time::OffsetDateTime;

#[test]
fn negative_fractional_timestamps_keep_floor_epoch_seconds() {
    for nanoseconds in [-1, -1_000_000, -999_999_999, -1_000_000_001] {
        let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanoseconds).unwrap();
        let mut response = BasicTokenIntrospectionResponse::new(true, EmptyExtraTokenFields {});
        response.set_exp(Some(timestamp));
        response.set_iat(Some(timestamp));
        response.set_nbf(Some(timestamp));
        let seconds = nanoseconds.div_euclid(1_000_000_000);
        assert_eq!(
            serde_json::to_value(response).unwrap(),
            json!({ "active": true, "exp": seconds, "iat": seconds, "nbf": seconds })
        );
    }
}

#[test]
fn integer_timestamps_round_trip_at_existing_range_boundaries() {
    for seconds in [
        super::MIN_UNIX_SECONDS,
        -1,
        0,
        1,
        253_402_300_800, // The year 10000 remains representable.
        super::MAX_UNIX_SECONDS,
    ] {
        let value = json!({ "active": true, "exp": seconds, "iat": seconds, "nbf": seconds });
        let response: BasicTokenIntrospectionResponse =
            serde_json::from_value(value.clone()).unwrap();
        let expected = Some(OffsetDateTime::from_unix_timestamp(seconds).unwrap());
        assert_eq!(
            (response.exp(), response.iat(), response.nbf()),
            (expected, expected, expected)
        );
        assert_eq!(serde_json::to_value(response).unwrap(), value);
    }
}

#[test]
fn invalid_numeric_dates_remain_rejected_for_all_fields() {
    for invalid in [
        json!(super::MIN_UNIX_SECONDS - 1),
        json!(super::MAX_UNIX_SECONDS + 1),
        json!(i64::MIN),
        json!(i64::MAX),
        json!(u64::MAX),
        json!(0.5),
        json!("0"),
    ] {
        for field in ["exp", "iat", "nbf"] {
            let mut value = json!({ "active": true });
            value[field] = invalid.clone();
            assert!(serde_json::from_value::<BasicTokenIntrospectionResponse>(value).is_err());
        }
    }
}

#[test]
fn missing_and_null_timestamps_keep_the_same_optional_contract() {
    for value in [
        json!({ "active": true }),
        json!({ "active": true, "exp": null, "iat": null, "nbf": null }),
    ] {
        let response: BasicTokenIntrospectionResponse = serde_json::from_value(value).unwrap();
        assert_eq!(
            (response.exp(), response.iat(), response.nbf()),
            (None, None, None)
        );
        assert_eq!(
            serde_json::to_value(response).unwrap(),
            json!({ "active": true })
        );
    }
}

#[test]
fn typed_setters_cannot_serialize_outside_the_existing_range() {
    for seconds in [super::MIN_UNIX_SECONDS - 1, super::MAX_UNIX_SECONDS + 1] {
        let timestamp = OffsetDateTime::from_unix_timestamp(seconds).unwrap();
        let mut response = BasicTokenIntrospectionResponse::new(true, EmptyExtraTokenFields {});
        response.set_exp(Some(timestamp));
        assert!(serde_json::to_value(response).is_err());
    }
}
