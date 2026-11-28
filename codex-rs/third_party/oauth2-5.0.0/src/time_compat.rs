//! OAuth2's existing integer wire and timeout limits without a calendar dependency.
//!
//! The public Rust timestamp type changes to Timestamp. Keep the accepted
//! integer range, subsecond truncation, and error text of the 5.0.0 wire contract.

use serde::{de, ser};
use std::fmt;
use std::time::Duration;

const MIN_SECONDS: i64 = -8_334_601_228_800;
const MAX_SECONDS: i64 = 8_210_266_876_799;

/// A bounded UTC Unix timestamp used by OAuth2 polling and token introspection.
///
/// Seconds identify a non-leap Unix second. Nanoseconds may represent a leap
/// second only at the last second of a minute. This retains the previous wire
/// range without changing another crate's calendar feature configuration.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct Timestamp {
    seconds: i64,
    nanoseconds: u32,
}

impl Timestamp {
    /// Constructs a timestamp within the original complete UTC range.
    ///
    /// Nanoseconds are below one billion, or below two billion during the
    /// leap second represented by a Unix second congruent to 59 modulo 60.
    pub const fn from_timestamp(seconds: i64, nanoseconds: u32) -> Option<Self> {
        if seconds < MIN_SECONDS || seconds > MAX_SECONDS
            || nanoseconds >= 2_000_000_000
            || (nanoseconds >= 1_000_000_000 && seconds.rem_euclid(60) != 59)
        {
            None
        } else {
            Some(Self { seconds, nanoseconds })
        }
    }

    /// Returns the non-leap Unix seconds, rounding a fractional second down.
    pub const fn timestamp(&self) -> i64 {
        self.seconds
    }

    /// Returns nanoseconds within the second, including a represented leap second.
    pub const fn timestamp_subsec_nanos(&self) -> u32 {
        self.nanoseconds
    }

    /// Adds a forward duration, retaining the original represented leap second.
    pub fn checked_add(self, value: Duration) -> Option<Self> {
        let mut fraction = u64::from(self.nanoseconds);
        let extra = u64::from(value.subsec_nanos());
        if fraction >= 1_000_000_000 {
            if value.as_secs() == 0 && fraction + extra < 2_000_000_000 {
                return Self::from_timestamp(self.seconds, (fraction + extra) as u32);
            }
            fraction -= 1_000_000_000;
        }
        let fraction = fraction + extra;
        let seconds = i128::from(self.seconds) + i128::from(value.as_secs())
            + i128::from(fraction / 1_000_000_000);
        Self::from_timestamp(i64::try_from(seconds).ok()?, (fraction % 1_000_000_000) as u32)
    }

    /// Reads the same wall clock used by the previous OAuth2 implementation.
    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    pub fn now() -> Self {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system time before Unix epoch");
        Self::from_timestamp(now.as_secs() as i64, now.subsec_nanos()).unwrap()
    }

    /// Reads the JavaScript wall clock on the original browser-like Wasm targets.
    #[cfg(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    ))]
    pub fn now() -> Self {
        let millis = js_sys::Date::new_0().get_time() as i64;
        Self::from_timestamp(
            millis.div_euclid(1000),
            (millis.rem_euclid(1000) as u32) * 1_000_000,
        ).unwrap()
    }
}

pub(crate) fn duration(value: Duration) -> Result<Duration, String> {
    let error = || format!(
        "failed to convert `{value:?}` to `chrono::Duration`: Source duration value is out of range for the target type"
    );
    // The historical limit also determines whether the caller's clock is read.
    if value > Duration::from_millis(i64::MAX as u64) {
        return Err(error());
    }
    Ok(value)
}

pub(crate) mod seconds_option {
    use super::*;

    pub(crate) fn serialize<S>(value: &Option<Timestamp>, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: ser::Serializer,
    {
        match value {
            Some(value) => serializer.serialize_some(&value.timestamp()),
            None => serializer.serialize_none(),
        }
    }

    pub(crate) fn deserialize<'de, D>(deserializer: D) -> Result<Option<Timestamp>, D::Error>
    where
        D: de::Deserializer<'de>,
    {
        deserializer.deserialize_option(OptionalSeconds)
    }

    struct OptionalSeconds;

    impl<'de> de::Visitor<'de> for OptionalSeconds {
        type Value = Option<Timestamp>;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a unix timestamp in seconds or none")
        }

        fn visit_some<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
        where
            D: de::Deserializer<'de>,
        {
            deserializer.deserialize_i64(Seconds).map(Some)
        }

        fn visit_none<E>(self) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(None)
        }

        fn visit_unit<E>(self) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(None)
        }
    }

    struct Seconds;

    impl de::Visitor<'_> for Seconds {
        type Value = Timestamp;

        fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str("a unix timestamp in seconds")
        }

        fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            if !(MIN_SECONDS..=MAX_SECONDS).contains(&value) {
                return Err(E::custom(format!("value is not a legal timestamp: {value}")));
            }
            Timestamp::from_timestamp(value, 0)
                .ok_or_else(|| E::custom(format!("value is not a legal timestamp: {value}")))
        }

        fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
        where
            E: de::Error,
        {
            if value > i64::MAX as u64 {
                return Err(E::custom(format!("value is not a legal timestamp: {value}")));
            }
            self.visit_i64(value as i64)
        }
    }
}
