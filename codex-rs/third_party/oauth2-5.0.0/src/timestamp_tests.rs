use super::*;
use crate::basic::BasicTokenType;
use crate::EmptyExtraTokenFields;
use crate::StandardTokenIntrospectionResponse;
use crate::TokenIntrospectionResponse;

type Response = StandardTokenIntrospectionResponse<EmptyExtraTokenFields, BasicTokenType>;

#[test]
fn introspection_retains_floor_seconds_and_represented_leap_seconds() {
    for (seconds, nanos) in [
        (-1, 999_999_999),
        (-1, 1_500_000_000),
        (59, 1_500_000_000),
        (0, 1),
    ] {
        let mut response = Response::new(/*active*/ true, EmptyExtraTokenFields {});
        let timestamp = Timestamp::from_parts(seconds, nanos).unwrap();
        response.set_exp(Some(timestamp));
        response.set_iat(Some(timestamp));
        response.set_nbf(Some(timestamp));
        let json = serde_json::to_value(response).unwrap();
        assert_eq!(json["exp"], seconds);
        assert_eq!(json["iat"], seconds);
        assert_eq!(json["nbf"], seconds);
    }
}

#[test]
fn introspection_preserves_null_omission_and_full_civil_range() {
    let empty: Response = serde_json::from_str(r#"{"active":true,"exp":null}"#).unwrap();
    assert_eq!(empty.exp(), None);
    assert_eq!(serde_json::to_string(&empty).unwrap(), r#"{"active":true}"#);
    for year in [-262_143, -200_000, -10_000, 10_000, 200_000, 262_142] {
        let timestamp = Timestamp::from_ymd_hms(
            year, /*month*/ 1, /*day*/ 1, /*hour*/ 0, /*minute*/ 0,
            /*second*/ 0,
        )
        .unwrap();
        let json = format!(r#"{{"active":true,"exp":{}}}"#, timestamp.epoch_seconds());
        let response: Response = serde_json::from_str(&json).unwrap();
        assert_eq!(response.exp(), Some(timestamp));
        assert_eq!(serde_json::to_string(&response).unwrap(), json);
    }
    for value in [
        "9223372036854775807",
        "18446744073709551615",
        "-9223372036854775808",
        "0.5",
        "\"0\"",
    ] {
        let json = format!(r#"{{"active":true,"exp":{value}}}"#);
        assert!(serde_json::from_str::<Response>(&json).is_err());
    }
}

#[test]
fn device_timeout_keeps_the_prior_millisecond_limit() {
    let maximum = Duration::new(
        /*secs*/ 9_223_372_036_854_775,
        /*nanos*/ 807_000_000,
    );
    assert!(duration_from_std(maximum).is_ok());
    assert!(duration_from_std(maximum + Duration::from_nanos(1)).is_err());
    assert!(duration_from_std(Duration::MAX).is_err());
    assert_eq!(
        duration_from_std(Duration::from_nanos(1))
            .unwrap()
            .whole_nanoseconds(),
        1
    );
}
