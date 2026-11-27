use time::OffsetDateTime;
use time::UtcOffset;

pub(super) fn agent_timestamp(timestamp: OffsetDateTime) -> String {
    let timestamp = timestamp.to_offset(UtcOffset::UTC);
    format!(
        "{}T{:02}:{:02}:{:02}Z",
        timestamp.date(),
        timestamp.hour(),
        timestamp.minute(),
        timestamp.second(),
    )
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
