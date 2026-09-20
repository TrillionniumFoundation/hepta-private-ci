use std::fmt;
use std::str::FromStr;

use codex_hepta_contracts::AgentId;
use serde::Deserialize;
use serde::Serialize;
use uuid::Uuid;

// Leaves room for the strict 64-KiB agentd control frame envelope.
const MAX_PROMPT_BYTES: usize = 32 * 1024;
const MIN_INTERVAL_MS: u64 = 1_000;
const MAX_INTERVAL_MS: u64 = 366 * 24 * 60 * 60 * 1_000;

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
            first_run_at_ms,
            created_at_ms,
        }
    }

    pub(crate) fn validate(&self) -> Result<(), AutomationError> {
        self.schedule.validate()?;
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

pub(crate) fn client_message_id(
    agent_id: &AgentId,
    task_id: AutomationTaskId,
    occurrence: u64,
) -> String {
    format!("hepta.automation.v1:{agent_id}:{task_id}:{occurrence}")
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
