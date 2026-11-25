use std::sync::Arc;

use codex_protocol::ThreadId;
use codex_utils_absolute_path::AbsolutePathBuf;
use futures::future::BoxFuture;
use serde::Serialize;
use serde::Serializer;
use time::OffsetDateTime;

const GREGORIAN_CYCLE_SECONDS: i64 = 12_622_780_800;

/// UTC timestamp carried by a hook payload.
///
/// Its wire representation retains whole seconds, a UTC `Z` suffix, signed expanded years,
/// and leap seconds. The accepted calendar range remains -262143 through 262142 inclusive.
/// This replaces the former public `chrono::DateTime<Utc>` field type; callers can construct a
/// timestamp from Unix seconds and nanoseconds without depending on Chrono.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HookTimestamp {
    seconds: i64,
    year: i32,
    within_cycle: OffsetDateTime,
    nanoseconds: u32,
}

impl HookTimestamp {
    /// Reads the current UTC clock, preserving the native clock's pre-Unix-epoch rejection.
    pub fn now_utc() -> Self {
        #[cfg(not(all(
            target_arch = "wasm32",
            not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
        )))]
        {
            Self::from_native_clock(std::time::SystemTime::now())
        }
        #[cfg(all(
            target_arch = "wasm32",
            not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
        ))]
        {
            let millis = js_sys::Date::new_0().get_time() as i64;
            Self::from_unix_timestamp(
                millis.div_euclid(1_000),
                (millis.rem_euclid(1_000) as u32) * 1_000_000,
            )
            .expect("system time outside hook timestamp range")
        }
    }

    /// Constructs a UTC timestamp with the previous hook timestamp's range and leap rules.
    ///
    /// Nanoseconds must be below one billion, except in a Unix second ending in `:59`, where
    /// values below two billion retain a leap second. Invalid components return `None`.
    pub fn from_unix_timestamp(seconds: i64, nanoseconds: u32) -> Option<Self> {
        // Gregorian month/day rules repeat every 400 years. Time only sees the
        // 1970..=2369 cycle; the real Unix second and restored year stay private.
        // This preserves the old range without enabling global `large-dates`.
        let within_cycle =
            OffsetDateTime::from_unix_timestamp(seconds.rem_euclid(GREGORIAN_CYCLE_SECONDS))
                .ok()?;
        let year = seconds
            .div_euclid(GREGORIAN_CYCLE_SECONDS)
            .checked_mul(400)?
            .checked_add(i64::from(within_cycle.year()))?;
        if !(-262_143..=262_142).contains(&year)
            || nanoseconds >= 2_000_000_000
            || (nanoseconds >= 1_000_000_000 && seconds.rem_euclid(60) != 59)
        {
            return None;
        }
        Some(Self {
            seconds,
            year: i32::try_from(year).ok()?,
            within_cycle,
            nanoseconds,
        })
    }

    pub(crate) fn timestamp(self) -> i64 {
        self.seconds
    }

    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    fn from_native_clock(now: std::time::SystemTime) -> Self {
        let elapsed = now
            .duration_since(std::time::UNIX_EPOCH)
            .expect("system time before Unix epoch");
        let seconds =
            i64::try_from(elapsed.as_secs()).expect("system time outside hook timestamp range");
        Self::from_unix_timestamp(seconds, elapsed.subsec_nanos())
            .expect("system time outside hook timestamp range")
    }
}

pub type HookFn = Arc<dyn for<'a> Fn(&'a HookPayload) -> BoxFuture<'a, HookResult> + Send + Sync>;

#[derive(Debug)]
pub enum HookResult {
    /// Success: hook completed successfully.
    Success,
    /// FailedContinue: hook failed, but other subsequent hooks should still execute and the
    /// operation should continue.
    FailedContinue(Box<dyn std::error::Error + Send + Sync + 'static>),
    /// FailedAbort: hook failed, other subsequent hooks should not execute, and the operation
    /// should be aborted.
    FailedAbort(Box<dyn std::error::Error + Send + Sync + 'static>),
}

impl HookResult {
    pub fn should_abort_operation(&self) -> bool {
        matches!(self, Self::FailedAbort(_))
    }
}

#[derive(Debug)]
pub struct HookResponse {
    pub hook_name: String,
    pub result: HookResult,
}

#[derive(Clone)]
pub struct Hook {
    pub name: String,
    pub func: HookFn,
}

impl Default for Hook {
    fn default() -> Self {
        Self {
            name: "default".to_string(),
            func: Arc::new(|_| Box::pin(async { HookResult::Success })),
        }
    }
}

impl Hook {
    pub async fn execute(&self, payload: &HookPayload) -> HookResponse {
        HookResponse {
            hook_name: self.name.clone(),
            result: (self.func)(payload).await,
        }
    }
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "snake_case")]
pub struct HookPayload {
    pub session_id: ThreadId,
    pub cwd: AbsolutePathBuf,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub client: Option<String>,
    #[serde(serialize_with = "serialize_triggered_at")]
    pub triggered_at: HookTimestamp,
    pub hook_event: HookEvent,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub struct HookEventAfterAgent {
    pub thread_id: ThreadId,
    pub turn_id: String,
    pub input_messages: Vec<String>,
    pub last_assistant_message: Option<String>,
}

fn serialize_triggered_at<S>(value: &HookTimestamp, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    let year = value.year;
    let year = if (0..=9999).contains(&year) {
        format!("{year:04}")
    } else {
        format!("{year:+05}")
    };
    let month = value.within_cycle.month() as u8;
    let day = value.within_cycle.day();
    let hour = value.within_cycle.hour();
    let minute = value.within_cycle.minute();
    let second = value.within_cycle.second() + u8::from(value.nanoseconds >= 1_000_000_000);
    serializer.serialize_str(&format!(
        "{year}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z"
    ))
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "event_type", rename_all = "snake_case")]
pub enum HookEvent {
    AfterAgent {
        #[serde(flatten)]
        event: HookEventAfterAgent,
    },
}

#[cfg(test)]
mod tests {
    use codex_protocol::ThreadId;
    use codex_utils_absolute_path::test_support::PathBufExt;
    use codex_utils_absolute_path::test_support::test_path_buf;
    use pretty_assertions::assert_eq;
    use serde_json::json;

    use super::HookEvent;
    use super::HookEventAfterAgent;
    use super::HookPayload;
    use super::HookTimestamp;
    use super::serialize_triggered_at;
    use time::OffsetDateTime;
    use time::UtcOffset;

    #[test]
    fn hook_payload_serializes_stable_wire_shape() {
        let session_id = ThreadId::new();
        let thread_id = ThreadId::new();
        let cwd = test_path_buf("/tmp").abs();
        let payload = HookPayload {
            session_id,
            cwd: cwd.clone(),
            client: None,
            triggered_at: HookTimestamp::from_unix_timestamp(
                /*seconds*/ 1_735_689_600,
                /*nanoseconds*/ 0,
            )
            .expect("valid timestamp"),
            hook_event: HookEvent::AfterAgent {
                event: HookEventAfterAgent {
                    thread_id,
                    turn_id: "turn-1".to_string(),
                    input_messages: vec!["hello".to_string()],
                    last_assistant_message: Some("hi".to_string()),
                },
            },
        };

        let actual = serde_json::to_value(payload).expect("serialize hook payload");
        let expected = json!({
            "session_id": session_id.to_string(),
            "cwd": cwd.display().to_string(),
            "triggered_at": "2025-01-01T00:00:00Z",
            "hook_event": {
                "event_type": "after_agent",
                "thread_id": thread_id.to_string(),
                "turn_id": "turn-1",
                "input_messages": ["hello"],
                "last_assistant_message": "hi",
            },
        });

        assert_eq!(actual, expected);
    }

    #[test]
    fn hook_timestamp_fractional_seconds_are_truncated_without_rounding() {
        for (seconds, nanoseconds, expected) in [
            (0, 1, "1970-01-01T00:00:00Z"),
            (0, 999_999_999, "1970-01-01T00:00:00Z"),
            (59, 999_999_999, "1970-01-01T00:00:59Z"),
            (-1, 999_999_999, "1969-12-31T23:59:59Z"),
        ] {
            let timestamp = HookTimestamp::from_unix_timestamp(seconds, nanoseconds)
                .expect("valid fractional timestamp");
            let actual = serialize_triggered_at(&timestamp, serde_json::value::Serializer)
                .expect("serialize timestamp");
            assert_eq!(actual, json!(expected));
            assert_eq!(timestamp.timestamp(), seconds);
        }
    }

    #[test]
    fn hook_timestamp_uses_the_utc_instant_for_offset_inputs() {
        for offset_seconds in [-7_200, 3_600, 19_800] {
            let offset = UtcOffset::from_whole_seconds(offset_seconds).expect("valid offset");
            let input = OffsetDateTime::UNIX_EPOCH.to_offset(offset);
            let timestamp =
                HookTimestamp::from_unix_timestamp(input.unix_timestamp(), input.nanosecond())
                    .expect("valid instant");
            let actual = serialize_triggered_at(&timestamp, serde_json::value::Serializer)
                .expect("serialize timestamp");
            assert_eq!(actual, json!("1970-01-01T00:00:00Z"));
        }
    }

    #[test]
    fn hook_timestamp_preserves_zero_negative_and_expanded_years() {
        // Frozen Unix inputs come from the original Gregorian day-count formula,
        // independently of the cycle mapping under test.
        for (seconds, expected) in [
            (-8_334_601_228_800, "-262143-01-01T00:00:00Z"),
            (-377_736_739_200, "-10000-01-01T00:00:00Z"),
            (-62_198_755_200, "-0001-01-01T00:00:00Z"),
            (-62_167_219_200, "0000-01-01T00:00:00Z"),
            (253_370_764_800, "9999-01-01T00:00:00Z"),
            (253_402_300_800, "+10000-01-01T00:00:00Z"),
            (8_210_235_340_800, "+262142-01-01T00:00:00Z"),
            (-62_162_121_600, "0000-02-29T00:00:00Z"),
            (-12_622_780_801, "1569-12-31T23:59:59Z"),
            (-12_622_780_800, "1570-01-01T00:00:00Z"),
            (-11_670_998_400, "1600-02-29T00:00:00Z"),
            (-2_203_891_201, "1900-02-28T23:59:59Z"),
            (-2_203_891_200, "1900-03-01T00:00:00Z"),
            (951_782_400, "2000-02-29T00:00:00Z"),
            (12_622_780_799, "2369-12-31T23:59:59Z"),
            (12_622_780_800, "2370-01-01T00:00:00Z"),
        ] {
            let timestamp = HookTimestamp::from_unix_timestamp(seconds, /*nanoseconds*/ 0)
                .expect("supported hook date");
            let actual = serialize_triggered_at(&timestamp, serde_json::value::Serializer)
                .expect("serialize timestamp");
            assert_eq!(actual, json!(expected));
            assert_eq!(timestamp.timestamp(), seconds);
        }
    }

    #[test]
    fn hook_timestamp_keeps_original_calendar_bounds() {
        let minimum = -8_334_601_228_800;
        let maximum = 8_210_266_876_799;
        let timestamp =
            HookTimestamp::from_unix_timestamp(maximum, /*nanoseconds*/ 999_999_999)
                .expect("maximum ordinary timestamp");
        let actual = serialize_triggered_at(&timestamp, serde_json::value::Serializer)
            .expect("serialize timestamp");
        assert_eq!(actual, json!("+262142-12-31T23:59:59Z"));
        assert_eq!(
            HookTimestamp::from_unix_timestamp(minimum - 1, /*nanoseconds*/ 0),
            None
        );
        assert_eq!(
            HookTimestamp::from_unix_timestamp(maximum + 1, /*nanoseconds*/ 0),
            None
        );
    }

    #[test]
    fn hook_timestamp_retains_leap_second_wire_values() {
        for (seconds, nanoseconds, expected) in [
            (59, 1_000_000_000, "1970-01-01T00:00:60Z"),
            (59, 1_999_999_999, "1970-01-01T00:00:60Z"),
            (-1, 1_000_000_000, "1969-12-31T23:59:60Z"),
            (1_483_228_799, 1_500_000_000, "2016-12-31T23:59:60Z"),
        ] {
            let timestamp = HookTimestamp::from_unix_timestamp(seconds, nanoseconds)
                .expect("supported leap second");
            let actual = serialize_triggered_at(&timestamp, serde_json::value::Serializer)
                .expect("serialize timestamp");
            assert_eq!(actual, json!(expected));
            assert_eq!(timestamp.timestamp(), seconds);
        }
    }

    #[test]
    fn hook_timestamp_rejects_invalid_components_without_fallback() {
        for (seconds, nanoseconds) in [
            (0, 1_000_000_000),
            (-60, 1_000_000_000),
            (59, 2_000_000_000),
            (i64::MIN, 0),
            (i64::MAX, 0),
        ] {
            assert_eq!(
                HookTimestamp::from_unix_timestamp(seconds, nanoseconds),
                None
            );
        }
    }

    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    #[test]
    fn native_hook_clock_keeps_original_seconds_and_nanoseconds() {
        for seconds in [59, 253_402_300_800] {
            let now = std::time::UNIX_EPOCH
                + std::time::Duration::new(seconds, /*nanos*/ 123_456_700);
            assert_eq!(
                HookTimestamp::from_native_clock(now),
                HookTimestamp::from_unix_timestamp(
                    i64::try_from(seconds).unwrap(),
                    /*nanoseconds*/ 123_456_700
                )
                .expect("supported clock instant")
            );
        }
    }

    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    #[test]
    #[should_panic(expected = "system time before Unix epoch")]
    fn native_hook_clock_keeps_pre_epoch_rejection() {
        let now = std::time::UNIX_EPOCH - std::time::Duration::from_secs(1);
        let _ = HookTimestamp::from_native_clock(now);
    }
}
