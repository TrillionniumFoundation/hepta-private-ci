//! Storage-free transport values; runtime methods remain with the existing owner.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationMissedRunPolicy {
    Skip,
    Coalesce,
    CatchUp { max_occurrences: u16 },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOverlapPolicy {
    /// Do not materialize the next occurrence until this occurrence is terminal.
    Forbid,
    /// Advance recurrence after durable Core admission while retaining this
    /// occurrence as non-terminal until its terminal observer settles it.
    Allow,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationDstGapPolicy {
    Skip,
    NextValid,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationDstOverlapPolicy {
    First,
    Second,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationTimezoneTransitionV1 {
    pub at_utc_ms: u64,
    pub offset_before_seconds: i32,
    pub offset_after_seconds: i32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationTimeZoneProfileV1 {
    pub timezone_id: String,
    pub tzdb_digest: Sha256Digest,
    pub valid_from_utc_ms: u64,
    pub valid_until_utc_ms: u64,
    pub initial_offset_seconds: i32,
    pub transitions: Vec<AutomationTimezoneTransitionV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationCalendarScheduleV2 {
    pub timezone_id: String,
    pub tzdb_digest: Sha256Digest,
    pub start_at_utc_ms: u64,
    pub end_at_utc_ms: Option<u64>,
    pub every_days: u16,
    pub local_time_ms: u32,
    pub dst_gap_policy: AutomationDstGapPolicy,
    pub dst_overlap_policy: AutomationDstOverlapPolicy,
    pub clock_profile: AutomationTimeZoneProfileV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorizedEffectDependency {
    pub step_id: String,
    pub state_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AuthorizedEffectIntent {
    pub run_id: String,
    pub step_id: String,
    pub attempt: u32,
    pub operation_id: String,
    pub subject_id: String,
    pub destination_id: String,
    pub payload_digest: Sha256Digest,
    pub final_use_scope_digest: Sha256Digest,
    pub policy_generation: u64,
    pub expected_predecessor_digest: Option<Sha256Digest>,
    pub dependencies: Vec<AuthorizedEffectDependency>,
    pub compensation_for: Option<String>,
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
