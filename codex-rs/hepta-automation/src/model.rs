use std::fmt;
use std::str::FromStr;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use uuid::Uuid;

// Leaves room for the strict 64-KiB agentd control frame envelope.
const MAX_PROMPT_BYTES: usize = 32 * 1024;
const MIN_INTERVAL_MS: u64 = 1_000;
const MAX_INTERVAL_MS: u64 = 366 * 24 * 60 * 60 * 1_000;
const MAX_CATCH_UP_OCCURRENCES: u32 = 1_024;
const AUTOMATION_OCCURRENCE_DOMAIN: &[u8] = b"hepta.automation.occurrence.v1\0";

#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct AutomationTaskId(Uuid);

impl AutomationTaskId {
    pub fn new() -> Self {
        Self(Uuid::now_v7())
    }

    pub fn parse(value: &str) -> Result<Self, AutomationError> {
        let parsed = Uuid::parse_str(value).map_err(|_| AutomationError::Invalid)?;
        if parsed.get_version_num() != 7 || parsed.hyphenated().to_string() != value {
            return Err(AutomationError::Invalid);
        }
        Ok(Self(parsed))
    }

    pub fn as_uuid(&self) -> &Uuid {
        &self.0
    }
}

impl Default for AutomationTaskId {
    fn default() -> Self {
        Self::new()
    }
}

impl fmt::Display for AutomationTaskId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl FromStr for AutomationTaskId {
    type Err = AutomationError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse(value)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct AutomationOccurrenceId(String);

impl AutomationOccurrenceId {
    pub fn derive(
        task_id: AutomationTaskId,
        schedule_revision: u64,
        scheduled_for_ms: u64,
    ) -> Result<Self, AutomationError> {
        if schedule_revision == 0 {
            return Err(AutomationError::Invalid);
        }
        let mut bytes = Vec::with_capacity(128);
        bytes.extend_from_slice(AUTOMATION_OCCURRENCE_DOMAIN);
        bytes.extend_from_slice(task_id.to_string().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(schedule_revision.to_string().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(scheduled_for_ms.to_string().as_bytes());
        Ok(Self(Sha256Digest::for_bytes(&bytes).as_str().to_string()))
    }

    pub fn parse(value: &str) -> Result<Self, AutomationError> {
        if value.len() != 64
            || !value
                .bytes()
                .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
        {
            return Err(AutomationError::Invalid);
        }
        Ok(Self(value.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for AutomationOccurrenceId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOverlapPolicy {
    Forbid,
    Allow,
}

impl AutomationOverlapPolicy {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Forbid => "forbid",
            Self::Allow => "allow",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "forbid" => Ok(Self::Forbid),
            "allow" => Ok(Self::Allow),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields")]
pub enum AutomationMissedRunPolicy {
    Skip,
    Coalesce,
    BoundedCatchUp { max_occurrences: u32 },
}

impl AutomationMissedRunPolicy {
    pub(crate) fn validate(self) -> Result<(), AutomationError> {
        match self {
            Self::Skip | Self::Coalesce => Ok(()),
            Self::BoundedCatchUp { max_occurrences }
                if (1..=MAX_CATCH_UP_OCCURRENCES).contains(&max_occurrences) =>
            {
                Ok(())
            }
            Self::BoundedCatchUp { .. } => Err(AutomationError::Invalid),
        }
    }

    pub(crate) fn columns(self) -> (&'static str, Option<u32>) {
        match self {
            Self::Skip => ("skip", None),
            Self::Coalesce => ("coalesce", None),
            Self::BoundedCatchUp { max_occurrences } => {
                ("bounded_catch_up", Some(max_occurrences))
            }
        }
    }

    pub(crate) fn parse(kind: &str, limit: Option<i64>) -> Result<Self, AutomationError> {
        let policy = match (kind, limit) {
            ("skip", None) => Self::Skip,
            ("coalesce", None) => Self::Coalesce,
            ("bounded_catch_up", Some(limit)) => Self::BoundedCatchUp {
                max_occurrences: u32::try_from(limit).map_err(|_| AutomationError::Corrupt)?,
            },
            _ => return Err(AutomationError::Corrupt),
        };
        policy.validate().map_err(|_| AutomationError::Corrupt)?;
        Ok(policy)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationSchedulePolicy {
    pub overlap: AutomationOverlapPolicy,
    pub missed_run: AutomationMissedRunPolicy,
}

impl Default for AutomationSchedulePolicy {
    fn default() -> Self {
        Self {
            overlap: AutomationOverlapPolicy::Forbid,
            missed_run: AutomationMissedRunPolicy::BoundedCatchUp {
                max_occurrences: 32,
            },
        }
    }
}

impl AutomationSchedulePolicy {
    pub(crate) fn validate(self) -> Result<(), AutomationError> {
        self.missed_run.validate()
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationOccurrenceTerminal {
    Succeeded,
    Failed,
    Cancelled,
}

impl AutomationOccurrenceTerminal {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "succeeded" => Ok(Self::Succeeded),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum AutomationSchedule {
    Once,
    FixedInterval { interval_ms: u64 },
}

impl AutomationSchedule {
    pub(crate) fn validate(self) -> Result<(), AutomationError> {
        match self {
            Self::Once => Ok(()),
            Self::FixedInterval { interval_ms }
                if (MIN_INTERVAL_MS..=MAX_INTERVAL_MS).contains(&interval_ms) =>
            {
                Ok(())
            }
            Self::FixedInterval { .. } => Err(AutomationError::Invalid),
        }
    }

    pub(crate) fn next_after(self, scheduled_for_ms: u64) -> Result<Option<u64>, AutomationError> {
        match self {
            Self::Once => Ok(None),
            Self::FixedInterval { interval_ms } => scheduled_for_ms
                .checked_add(interval_ms)
                .map(Some)
                .ok_or(AutomationError::Invalid),
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AutomationTaskState {
    Enabled,
    Disabled,
    Cancelled,
    Completed,
}

impl AutomationTaskState {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Enabled => "enabled",
            Self::Disabled => "disabled",
            Self::Cancelled => "cancelled",
            Self::Completed => "completed",
        }
    }

    pub(crate) fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "enabled" => Ok(Self::Enabled),
            "disabled" => Ok(Self::Disabled),
            "cancelled" => Ok(Self::Cancelled),
            "completed" => Ok(Self::Completed),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationTaskDraft {
    pub task_id: AutomationTaskId,
    pub thread_id: String,
    pub prompt: String,
    pub schedule: AutomationSchedule,
    #[serde(default)]
    pub policy: AutomationSchedulePolicy,
    pub first_run_at_ms: u64,
    pub created_at_ms: u64,
}

impl AutomationTaskDraft {
    pub fn new(
        thread_id: impl Into<String>,
        prompt: impl Into<String>,
        schedule: AutomationSchedule,
        first_run_at_ms: u64,
        created_at_ms: u64,
    ) -> Self {
        Self {
            task_id: AutomationTaskId::new(),
            thread_id: thread_id.into(),
            prompt: prompt.into(),
            schedule,
            policy: AutomationSchedulePolicy::default(),
            first_run_at_ms,
            created_at_ms,
        }
    }

    pub(crate) fn validate(&self) -> Result<(), AutomationError> {
        self.schedule.validate()?;
        self.policy.validate()?;
        if self.schedule == AutomationSchedule::Once
            && self.policy.overlap == AutomationOverlapPolicy::Allow
        {
            return Err(AutomationError::Invalid);
        }
        let prompt_len = self.prompt.len();
        if prompt_len == 0 || prompt_len > MAX_PROMPT_BYTES || self.prompt.contains('\0') {
            return Err(AutomationError::Invalid);
        }
        let thread = Uuid::parse_str(&self.thread_id).map_err(|_| AutomationError::Invalid)?;
        if thread.to_string() != self.thread_id {
            return Err(AutomationError::Invalid);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationTask {
    pub task_id: AutomationTaskId,
    pub owner_agent_id: AgentId,
    pub thread_id: String,
    pub prompt: String,
    pub schedule: AutomationSchedule,
    pub schedule_revision: u64,
    pub policy: AutomationSchedulePolicy,
    pub state: AutomationTaskState,
    pub next_run_at_ms: Option<u64>,
    pub next_occurrence: u64,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationLease {
    pub task: AutomationTask,
    pub occurrence: u64,
    pub occurrence_id: AutomationOccurrenceId,
    pub schedule_revision: u64,
    pub scheduled_for_ms: u64,
    pub client_user_message_id: String,
    pub lease_generation: u64,
    pub lease_token: String,
    pub lease_expires_at_ms: u64,
}

impl AutomationLease {
    pub fn admission(&self) -> AutomationAdmission {
        AutomationAdmission {
            agent_id: self.task.owner_agent_id.clone(),
            task_id: self.task.task_id,
            occurrence: self.occurrence,
            occurrence_id: self.occurrence_id.clone(),
            schedule_revision: self.schedule_revision,
            scheduled_for_ms: self.scheduled_for_ms,
            thread_id: self.task.thread_id.clone(),
            prompt: self.task.prompt.clone(),
            client_user_message_id: self.client_user_message_id.clone(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationAdmission {
    pub agent_id: AgentId,
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub occurrence_id: AutomationOccurrenceId,
    pub schedule_revision: u64,
    pub scheduled_for_ms: u64,
    pub thread_id: String,
    pub prompt: String,
    pub client_user_message_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationQueueReceipt {
    pub queued_submission_id: String,
    pub client_user_message_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationSubmittedOccurrence {
    pub admission: AutomationAdmission,
    pub queued_submission_id: String,
    pub taskflow_run_id: String,
    pub provider_turn_id: Option<String>,
    pub submitted_at_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationProviderObservationKind {
    QueueAdmitted,
    TurnPersisted,
    TurnCompleted,
    TurnFailed,
    TurnInterrupted,
    Indeterminate,
    ReconciledMissing,
    ReconciledCancelled,
}

impl AutomationProviderObservationKind {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::QueueAdmitted => "queue_admitted",
            Self::TurnPersisted => "turn_persisted",
            Self::TurnCompleted => "turn_completed",
            Self::TurnFailed => "turn_failed",
            Self::TurnInterrupted => "turn_interrupted",
            Self::Indeterminate => "indeterminate",
            Self::ReconciledMissing => "reconciled_missing",
            Self::ReconciledCancelled => "reconciled_cancelled",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationProviderObservation {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub observation_seq: u64,
    pub kind: AutomationProviderObservationKind,
    pub queued_submission_id: Option<String>,
    pub turn_id: Option<String>,
    pub receipt_digest: Sha256Digest,
    pub observed_at_ms: u64,
}

/// Durable evidence that the provider outcome for one occurrence is not yet
/// known.  The scheduler must not blindly re-submit this occurrence until an
/// operator or a provider-specific reconciler supplies a terminal receipt (or
/// explicitly confirms that no admission was accepted).
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationDispatchUncertainty {
    pub task_id: AutomationTaskId,
    pub occurrence: u64,
    pub scheduled_for_ms: u64,
    pub client_user_message_id: String,
    pub observed_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AutomationTick {
    Idle,
    Submitted {
        task_id: AutomationTaskId,
        occurrence: u64,
        queued_submission_id: String,
    },
    RetryScheduled {
        task_id: AutomationTaskId,
        occurrence: u64,
    },
    DispatchUncertain {
        task_id: AutomationTaskId,
        occurrence: u64,
    },
}

pub(crate) fn client_message_id(occurrence_id: &AutomationOccurrenceId) -> String {
    format!("hepta.automation.v2:{occurrence_id}")
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum AutomationError {
    #[error("invalid automation request")]
    Invalid,
    #[error("automation owner denied the request")]
    AccessDenied,
    #[error("automation state conflict")]
    Conflict,
    #[error("automation state is corrupt")]
    Corrupt,
    #[error("automation storage is unavailable")]
    Unavailable,
    #[error("Agent turn queue rejected automation admission")]
    Dispatch,
    #[error("automation provider admission outcome is unknown")]
    DispatchUnknown,
}
