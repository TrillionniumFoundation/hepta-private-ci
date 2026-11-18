use ::serde::Deserialize;
use ::serde::Serialize;
use pretty_assertions::assert_eq;
use serde_json::json;
use time::OffsetDateTime;
use time::UtcOffset;

use crate::CanonicalUtcTimestamp;
use crate::Precision;
use crate::TimestampError;
use crate::UtcSuffix;
use crate::format_rfc3339_utc;
use crate::from_unix_millis;
use crate::from_unix_parts;
use crate::parse_rfc3339_utc;
use crate::unix_millis_floor;

type TestResult = Result<(), Box<dyn std::error::Error>>;

#[derive(Deserialize)]
struct Corpus {
    parse: Vec<ParseCase>,
    parts: Vec<PartsCase>,
    #[serde(default)]
    millis: Vec<MillisCase>,
}

#[derive(Deserialize)]
struct ParseCase {
    input: String,
    strict: Option<Snapshot>,
    serde: Option<Snapshot>,
}

#[derive(Deserialize)]
struct PartsCase {
    seconds: i64,
    nanos: u32,
    value: Option<Snapshot>,
}

#[derive(Deserialize)]
struct MillisCase {
    millis: i64,
    value: Option<Snapshot>,
}

#[derive(Deserialize)]
struct Snapshot {
    serde: String,
    seconds: i64,
    millis: i64,
    nanos: u32,
    rfc3339: String,
    formats: [String; 6],
}

#[derive(Deserialize)]
struct ComparisonCorpus {
    comparisons: Vec<ComparisonCase>,
}

#[derive(Deserialize)]
struct ComparisonCase {
    carrier: String,
    instant: String,
    ordering: String,
}

#[derive(Debug, Deserialize, Serialize)]
struct Instant(#[serde(with = "crate::serde::rfc3339")] OffsetDateTime);

#[derive(Debug, Deserialize, Serialize)]
struct OptionalInstant {
    #[serde(default, with = "crate::serde::optional_rfc3339")]
    timestamp: Option<OffsetDateTime>,
}

fn corpora() -> Result<Vec<Corpus>, serde_json::Error> {
    [
        include_str!("../tests/fixtures/wire-oracle.json"),
        include_str!("../tests/fixtures/grammar-oracle.json"),
    ]
    .into_iter()
    .map(serde_json::from_str)
    .collect()
}

fn assert_snapshot(actual: OffsetDateTime, expected: &Snapshot) -> TestResult {
    assert_eq!(actual.offset(), UtcOffset::UTC);
    assert_eq!(actual.unix_timestamp(), expected.seconds);
    assert_eq!(unix_millis_floor(actual), expected.millis);
    assert_eq!(actual.nanosecond(), expected.nanos);
    assert_eq!(
        serde_json::to_value(Instant(actual))?,
        json!(expected.serde)
    );
    assert_eq!(
        format_rfc3339_utc(actual, Precision::AutoSi, UtcSuffix::Offset)?,
        expected.rfc3339,
    );
    let formats = [
        (Precision::Seconds, UtcSuffix::Z),
        (Precision::Millis, UtcSuffix::Z),
        (Precision::Micros, UtcSuffix::Z),
        (Precision::Nanos, UtcSuffix::Z),
        (Precision::AutoSi, UtcSuffix::Z),
        (Precision::AutoSi, UtcSuffix::Offset),
    ];
    for ((precision, suffix), expected) in formats.into_iter().zip(&expected.formats) {
        assert_eq!(&format_rfc3339_utc(actual, precision, suffix)?, expected);
    }
    Ok(())
}

#[test]
fn strict_parser_matches_actual_old_parser_or_explicitly_rejects_leap() -> TestResult {
    for corpus in corpora()? {
        for case in corpus.parse {
            let actual = parse_rfc3339_utc(&case.input);
            match case.strict {
                None => assert!(actual.is_err(), "unexpected acceptance: {:?}", case.input),
                Some(expected) if expected.nanos >= 1_000_000_000 => assert_eq!(
                    actual,
                    Err(TimestampError::UnrepresentableLeapSecond),
                    "{:?}",
                    case.input,
                ),
                Some(expected) => assert_snapshot(actual?, &expected)?,
            }
        }
    }
    Ok(())
}

#[test]
fn canonical_carrier_matches_actual_old_serde_including_leap_seconds() -> TestResult {
    for corpus in corpora()? {
        for case in corpus.parse {
            let actual = CanonicalUtcTimestamp::parse_legacy(&case.input);
            let Some(expected) = case.serde else {
                assert!(actual.is_err(), "unexpected acceptance: {:?}", case.input);
                continue;
            };
            let actual = actual?;
            assert_eq!(actual.canonical_wire(), expected.serde, "{:?}", case.input);
            assert_eq!(serde_json::to_value(actual)?, json!(expected.serde));
            assert_eq!(
                serde_json::from_value::<CanonicalUtcTimestamp>(json!(case.input))?,
                actual,
            );
            if expected.nanos >= 1_000_000_000 {
                assert_eq!(
                    actual.try_into_instant(),
                    Err(TimestampError::UnrepresentableLeapSecond),
                );
            } else {
                assert_snapshot(actual.try_into_instant()?, &expected)?;
            }
        }
    }
    Ok(())
}

#[test]
fn instant_serde_preserves_legacy_grammar_but_does_not_normalize_leap() -> TestResult {
    for corpus in corpora()? {
        for case in corpus.parse {
            let actual = serde_json::from_value::<Instant>(json!(case.input));
            match case.serde {
                None => assert!(actual.is_err(), "unexpected acceptance: {:?}", case.input),
                Some(expected) if expected.nanos >= 1_000_000_000 => {
                    assert!(actual.is_err(), "leap second became an instant");
                }
                Some(expected) => assert_snapshot(actual?.0, &expected)?,
            }
        }
    }
    Ok(())
}

#[test]
fn epoch_parts_match_actual_old_constructor_without_coercing_leaps() -> TestResult {
    for corpus in corpora()? {
        for case in corpus.parts {
            let actual = from_unix_parts(case.seconds, case.nanos);
            match case.value {
                None => assert!(actual.is_err(), "{}, {}", case.seconds, case.nanos),
                Some(expected) if expected.nanos >= 1_000_000_000 => assert_eq!(
                    actual,
                    Err(TimestampError::UnrepresentableLeapSecond),
                    "{}, {}",
                    case.seconds,
                    case.nanos,
                ),
                Some(expected) => assert_snapshot(actual?, &expected)?,
            }
        }
    }
    Ok(())
}

#[test]
fn epoch_millis_match_actual_old_constructor_including_negative_fractions() -> TestResult {
    for corpus in corpora()? {
        for case in corpus.millis {
            let actual = from_unix_millis(case.millis);
            match case.value {
                None => assert!(actual.is_err(), "{}", case.millis),
                Some(expected) => {
                    let actual = actual?;
                    assert_snapshot(actual, &expected)?;
                    assert_eq!(unix_millis_floor(actual), case.millis);
                }
            }
        }
    }
    Ok(())
}

#[test]
fn optional_serde_preserves_null_and_absent_fields_but_rejects_invalid_values() -> TestResult {
    for value in [json!({}), json!({ "timestamp": null })] {
        let actual: OptionalInstant = serde_json::from_value(value)?;
        assert_eq!(actual.timestamp, None);
        assert_eq!(serde_json::to_value(actual)?, json!({ "timestamp": null }));
    }
    let actual: OptionalInstant = serde_json::from_value(json!({
        "timestamp": "1969-12-31T23:59:59.999999999Z",
    }))?;
    assert_eq!(actual.timestamp.map(unix_millis_floor), Some(-1));
    assert_eq!(
        serde_json::to_value(actual)?,
        json!({ "timestamp": "1969-12-31T23:59:59.999999999Z" }),
    );
    for value in [
        json!(0),
        json!(true),
        json!([]),
        json!({}),
        json!("not a timestamp"),
        json!("2016-12-31T23:59:60Z"),
    ] {
        assert!(serde_json::from_value::<Instant>(value.clone()).is_err());
        assert!(serde_json::from_value::<OptionalInstant>(json!({ "timestamp": value })).is_err());
    }
    assert!(serde_json::from_value::<Instant>(json!(null)).is_err());
    Ok(())
}

#[test]
fn formatter_normalizes_offset_and_truncates_without_rounding() -> TestResult {
    let instant = parse_rfc3339_utc("1969-12-31T23:59:59.999999999Z")?
        .to_offset(UtcOffset::from_hms(5, 45, 0)?);
    assert_eq!(
        format_rfc3339_utc(instant, Precision::Seconds, UtcSuffix::Z)?,
        "1969-12-31T23:59:59Z",
    );
    assert_eq!(
        format_rfc3339_utc(instant, Precision::Millis, UtcSuffix::Offset)?,
        "1969-12-31T23:59:59.999+00:00",
    );
    assert_eq!(unix_millis_floor(instant), -1);
    Ok(())
}

#[test]
fn formatting_refuses_instants_outside_the_previous_timestamp_range() -> TestResult {
    for seconds in [crate::MIN_UNIX_SECONDS - 1, crate::MAX_UNIX_SECONDS + 1] {
        let instant = OffsetDateTime::from_unix_timestamp(seconds)?;
        assert_eq!(
            format_rfc3339_utc(instant, Precision::AutoSi, UtcSuffix::Z),
            Err(TimestampError::OutOfRange),
        );
        assert!(serde_json::to_value(Instant(instant)).is_err());
    }
    Ok(())
}

#[test]
fn expiry_comparison_matches_actual_old_ordering_even_at_leap_boundaries() -> TestResult {
    let corpus: ComparisonCorpus =
        serde_json::from_str(include_str!("../tests/fixtures/comparison-oracle.json"))?;
    for case in corpus.comparisons {
        let carrier = CanonicalUtcTimestamp::parse_legacy(&case.carrier)?;
        let instant = parse_rfc3339_utc(&case.instant)?;
        let actual = carrier.compare_to_instant(instant);
        assert_eq!(
            format!("{actual:?}"),
            case.ordering,
            "{} compared to {}",
            case.carrier,
            case.instant,
        );
    }
    Ok(())
}

#[test]
fn carrier_epoch_parts_and_all_wire_precisions_match_actual_old_leap_output() -> TestResult {
    let formats = [
        (Precision::Seconds, UtcSuffix::Z),
        (Precision::Millis, UtcSuffix::Z),
        (Precision::Micros, UtcSuffix::Z),
        (Precision::Nanos, UtcSuffix::Z),
        (Precision::AutoSi, UtcSuffix::Z),
        (Precision::AutoSi, UtcSuffix::Offset),
    ];
    for corpus in corpora()? {
        for case in corpus.parts {
            let actual = CanonicalUtcTimestamp::from_unix_parts(case.seconds, case.nanos);
            let Some(expected) = case.value else {
                assert!(actual.is_err(), "{}, {}", case.seconds, case.nanos);
                continue;
            };
            let actual = actual?;
            assert_eq!(actual.canonical_wire(), expected.serde);
            for ((precision, suffix), expected) in formats.into_iter().zip(expected.formats) {
                assert_eq!(actual.format(precision, suffix), expected);
            }
            if case.nanos >= 1_000_000_000 {
                assert_eq!(
                    actual.try_into_instant(),
                    Err(TimestampError::UnrepresentableLeapSecond),
                );
                assert_eq!(
                    from_unix_parts(case.seconds, case.nanos),
                    Err(TimestampError::UnrepresentableLeapSecond),
                );
            }
        }
    }
    Ok(())
}
