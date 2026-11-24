//! Integer OAuth timestamps at the existing protocol boundary.
//!
//! Keep floor-based seconds and the prior civil range. Jiff's signed
//! fractional-second representation alone would truncate negative values
//! toward zero when using its seconds-only serde helper.

use codex_utils_time::SignedDuration;
use codex_utils_time::Timestamp;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serializer;
use std::time::Duration;

pub(crate) fn serialize<S>(value: &Option<Timestamp>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    match value {
        Some(value) => serializer.serialize_some(&value.epoch_seconds()),
        None => serializer.serialize_none(),
    }
}

pub(crate) fn deserialize<'de, D>(deserializer: D) -> Result<Option<Timestamp>, D::Error>
where
    D: Deserializer<'de>,
{
    Option::<i64>::deserialize(deserializer)?
        .map(|seconds| {
            Timestamp::from_parts(seconds, /*nanos*/ 0)
                .ok_or_else(|| serde::de::Error::custom("timestamp is outside the supported range"))
        })
        .transpose()
}

pub(crate) fn duration_from_std(value: Duration) -> Result<SignedDuration, &'static str> {
    // Preserve the old device-polling timeout bound before date arithmetic.
    const MAX: Duration = Duration::new(
        (i64::MAX / 1_000) as u64,
        ((i64::MAX % 1_000) * 1_000_000) as u32,
    );
    const ERROR: &str = "Source duration value is out of range for the target type";
    if value > MAX {
        return Err(ERROR);
    }
    SignedDuration::try_from(value).map_err(|_| ERROR)
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
