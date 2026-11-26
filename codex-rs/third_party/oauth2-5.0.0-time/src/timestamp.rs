use time::OffsetDateTime;

// Preserve the previously accepted proleptic Gregorian range. The `time`
// dependency enables `large-dates` so every existing integer timestamp remains
// representable, including dates outside the four-digit RFC 3339 year range.
pub(crate) const MIN_UNIX_SECONDS: i64 = -8_334_601_228_800;
pub(crate) const MAX_UNIX_SECONDS: i64 = 8_210_266_876_799;
pub(crate) const MAX_DURATION_NANOS: u128 = i64::MAX as u128 * 1_000_000;

pub(crate) fn is_supported(timestamp: OffsetDateTime) -> bool {
    (MIN_UNIX_SECONDS..=MAX_UNIX_SECONDS).contains(&timestamp.unix_timestamp())
}

pub(crate) mod ts_seconds_option {
    use serde::Deserialize;
    use serde::Deserializer;
    use serde::Serialize;
    use serde::Serializer;
    use time::OffsetDateTime;

    pub fn serialize<S>(
        timestamp: &Option<OffsetDateTime>,
        serializer: S,
    ) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        if timestamp.is_some_and(|timestamp| !super::is_supported(timestamp)) {
            return Err(serde::ser::Error::custom(
                "timestamp is outside the supported range",
            ));
        }
        // unix_timestamp rounds toward negative infinity, preserving the wire
        // value of timestamps with a fractional second before the Unix epoch.
        timestamp
            .map(OffsetDateTime::unix_timestamp)
            .serialize(serializer)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Option<OffsetDateTime>, D::Error>
    where
        D: Deserializer<'de>,
    {
        Option::<i64>::deserialize(deserializer)?
            .map(|seconds| {
                if !(super::MIN_UNIX_SECONDS..=super::MAX_UNIX_SECONDS).contains(&seconds) {
                    return Err(serde::de::Error::custom(
                        "timestamp is outside the supported range",
                    ));
                }
                OffsetDateTime::from_unix_timestamp(seconds).map_err(serde::de::Error::custom)
            })
            .transpose()
    }
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
