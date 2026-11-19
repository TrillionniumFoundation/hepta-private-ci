use super::DateFields;
use super::YearInformation;
use super::query_year;
use crate::LocalTimeError;
use crate::Timestamp;
use pretty_assertions::assert_eq;

fn northern() -> YearInformation {
    YearInformation {
        bias: 300,
        standard_bias: 0,
        daylight_bias: -60,
        standard_date: DateFields {
            month: 11,
            weekday: 0,
            day: 1,
            hour: 2,
            ..DateFields::default()
        },
        daylight_date: DateFields {
            month: 3,
            weekday: 0,
            day: 2,
            hour: 2,
            ..DateFields::default()
        },
    }
}

#[test]
fn northern_transitions_use_offsets_on_the_correct_side() {
    let rules = northern();
    for (input, expected) in [
        ("2024-03-10T06:59:59.999999999Z", -18_000),
        ("2024-03-10T07:00:00Z", -14_400),
        ("2024-11-03T05:59:59.999999999Z", -14_400),
        ("2024-11-03T06:00:00Z", -18_000),
    ] {
        assert_eq!(
            rules.offset(input.parse().expect(input)),
            Ok(expected),
            "{input}"
        );
    }
}

#[test]
fn southern_half_hour_transitions_cross_the_year_boundary() {
    let rules = YearInformation {
        bias: -630,
        standard_bias: 0,
        daylight_bias: -30,
        standard_date: DateFields {
            month: 4,
            weekday: 0,
            day: 1,
            hour: 2,
            ..DateFields::default()
        },
        daylight_date: DateFields {
            month: 10,
            weekday: 0,
            day: 1,
            hour: 2,
            ..DateFields::default()
        },
    };
    for (input, expected) in [
        ("2024-01-01T00:00:00Z", 39_600),
        ("2024-04-06T14:59:59Z", 39_600),
        ("2024-04-06T15:00:00Z", 37_800),
        ("2024-10-05T15:29:59Z", 37_800),
        ("2024-10-05T15:30:00Z", 39_600),
    ] {
        assert_eq!(
            rules.offset(input.parse().expect(input)),
            Ok(expected),
            "{input}"
        );
    }
}

#[test]
fn recurring_rules_resolve_in_original_year_outside_os_query_range() {
    let rules = northern();
    for year in [-262_143, -1, 0, 1600, 1601, 30_827, 30_828, 262_142] {
        let source = time::Date::from_calendar_date(year, time::Month::July, /*day*/ 1)
            .expect("date")
            .midnight()
            .assume_utc();
        let timestamp = Timestamp::from_timestamp(source.unix_timestamp(), /*nanoseconds*/ 0)
            .expect("timestamp");
        assert_eq!(rules.offset(timestamp), Ok(-14_400));
        assert!((1601..=30_827).contains(&query_year(year)));
    }
    assert_eq!(query_year(-1), 1601);
    assert_eq!(query_year(40_000), 30_827);
}

#[test]
fn concrete_and_last_weekday_dates_preserve_fractional_boundaries() {
    let last_sunday = DateFields {
        month: 2,
        weekday: 0,
        day: 5,
        hour: 2,
        ..DateFields::default()
    };
    let expected: Timestamp = "2024-02-25T02:00:00Z".parse().expect("date");
    assert_eq!(
        last_sunday.resolve(/*year*/ 2024),
        Ok(Some((expected.timestamp(), 0)))
    );
    let concrete = DateFields {
        year: 2000,
        month: 2,
        day: 29,
        second: 59,
        millisecond: 1500,
        ..DateFields::default()
    };
    let expected: Timestamp = "2000-02-29T00:00:60.500Z"
        .parse()
        .expect("leap representation");
    assert_eq!(
        concrete.resolve(/*year*/ 2024),
        Ok(Some((
            expected.timestamp(),
            expected.timestamp_subsec_nanos()
        )))
    );
}

#[test]
fn absent_or_single_transition_keeps_original_bias_selection() {
    let mut rules = northern();
    rules.standard_date = DateFields::default();
    assert_eq!(
        rules.offset("2024-01-01T00:00:00Z".parse().expect("winter")),
        Ok(-18_000)
    );
    assert_eq!(
        rules.offset(
            "2024-12-01T00:00:00Z"
                .parse()
                .expect("after single transition")
        ),
        Ok(-14_400)
    );
    rules.daylight_date = DateFields::default();
    assert_eq!(
        rules.offset("2024-12-01T00:00:00Z".parse().expect("fixed")),
        Ok(-18_000)
    );
}

#[test]
fn invalid_rule_fields_and_bias_overflow_fail_explicitly() {
    for fields in [
        DateFields {
            month: 13,
            day: 1,
            ..DateFields::default()
        },
        DateFields {
            month: 3,
            day: 0,
            ..DateFields::default()
        },
        DateFields {
            month: 3,
            day: 1,
            weekday: 7,
            ..DateFields::default()
        },
        DateFields {
            month: 3,
            day: 1,
            hour: 24,
            ..DateFields::default()
        },
        DateFields {
            month: 3,
            day: 1,
            second: 58,
            millisecond: 1000,
            ..DateFields::default()
        },
    ] {
        assert_eq!(
            fields.resolve(/*year*/ 2024),
            Err(LocalTimeError::Unavailable)
        );
    }
    for bias in [i32::MIN, -1440, 1440, i32::MAX] {
        let mut rules = northern();
        rules.bias = bias;
        assert_eq!(
            rules.offset("2024-01-01T00:00:00Z".parse().expect("date")),
            Err(LocalTimeError::InvalidOffset)
        );
    }
}
