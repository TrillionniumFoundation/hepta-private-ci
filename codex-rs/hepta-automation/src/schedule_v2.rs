//! Deterministic Calendar V2 scheduling with explicit timezone evidence.
//!
//! This surface is additive. Existing Once and FixedInterval rows keep their
//! historical meaning. Calendar V2 stores an append-only versioned schedule
//! beside the compatibility timer row. The owner computes canonical UTC
//! instants from a bounded timezone transition profile, so DST ambiguity is a
//! deterministic data problem rather than ambient host-time behavior.

use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationError;
use crate::AutomationMissedRunPolicy;
use crate::AutomationOverlapPolicy;
use crate::AutomationSchedule;
use crate::AutomationSchedulePolicy;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskDraft;
use crate::AutomationTaskId;

const DAY_MS: u64 = 86_400_000;
const MAX_TIMEZONE_TRANSITIONS: usize = 512;
const MAX_TIMEZONE_ID_BYTES: usize = 96;
const MAX_OFFSET_SECONDS: i32 = 18 * 60 * 60;
const MAX_CALENDAR_SCAN: usize = 1_032;
const ZERO_DIGEST: &str =
    "0000000000000000000000000000000000000000000000000000000000000000";

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

impl AutomationTimeZoneProfileV1 {
    fn validate(&self) -> Result<(), AutomationError> {
        validate_timezone_id(&self.timezone_id)?;
        validate_digest(&self.tzdb_digest)?;
        if self.valid_until_utc_ms <= self.valid_from_utc_ms
            || !valid_offset(self.initial_offset_seconds)
            || self.transitions.len() > MAX_TIMEZONE_TRANSITIONS
        {
            return Err(AutomationError::Invalid);
        }
        let mut previous_at = self.valid_from_utc_ms;
        let mut expected_before = self.initial_offset_seconds;
        for transition in &self.transitions {
            if transition.at_utc_ms <= previous_at
                || transition.at_utc_ms >= self.valid_until_utc_ms
                || !valid_offset(transition.offset_before_seconds)
                || !valid_offset(transition.offset_after_seconds)
                || transition.offset_before_seconds != expected_before
            {
                return Err(AutomationError::Invalid);
            }
            previous_at = transition.at_utc_ms;
            expected_before = transition.offset_after_seconds;
        }
        Ok(())
    }

    fn offset_at_utc(&self, utc_ms: u64) -> Result<i32, AutomationError> {
        if utc_ms < self.valid_from_utc_ms || utc_ms >= self.valid_until_utc_ms {
            return Err(AutomationError::Unavailable);
        }
        let mut offset = self.initial_offset_seconds;
        for transition in &self.transitions {
            if utc_ms < transition.at_utc_ms {
                break;
            }
            offset = transition.offset_after_seconds;
        }
        Ok(offset)
    }

    fn utc_to_local_ms(&self, utc_ms: u64) -> Result<u64, AutomationError> {
        shift_ms(utc_ms, self.offset_at_utc(utc_ms)?)
    }

    fn resolve_local_ms(
        &self,
        local_ms: u64,
        gap_policy: AutomationDstGapPolicy,
        overlap_policy: AutomationDstOverlapPolicy,
    ) -> Result<Option<u64>, AutomationError> {
        let mut offsets = BTreeSet::new();
        offsets.insert(self.initial_offset_seconds);
        for transition in &self.transitions {
            offsets.insert(transition.offset_before_seconds);
            offsets.insert(transition.offset_after_seconds);
        }
        let mut candidates = Vec::new();
        for offset in offsets {
            let Some(candidate) = unshift_ms(local_ms, offset)? else {
                continue;
            };
            if candidate < self.valid_from_utc_ms || candidate >= self.valid_until_utc_ms {
                continue;
            }
            if self.offset_at_utc(candidate)? == offset
                && self.utc_to_local_ms(candidate)? == local_ms
            {
                candidates.push(candidate);
            }
        }
        candidates.sort_unstable();
        candidates.dedup();
        match candidates.as_slice() {
            [] => {
                if gap_policy == AutomationDstGapPolicy::Skip {
                    return Ok(None);
                }
                for transition in &self.transitions {
                    if transition.offset_after_seconds <= transition.offset_before_seconds {
                        continue;
                    }
                    let gap_start = shift_ms(
                        transition.at_utc_ms,
                        transition.offset_before_seconds,
                    )?;
                    let gap_end =
                        shift_ms(transition.at_utc_ms, transition.offset_after_seconds)?;
                    if local_ms >= gap_start && local_ms < gap_end {
                        return Ok(Some(transition.at_utc_ms));
                    }
                }
                Ok(None)
            }
            [only] => Ok(Some(*only)),
            [first, second] => Ok(Some(match overlap_policy {
                AutomationDstOverlapPolicy::First => *first,
                AutomationDstOverlapPolicy::Second => *second,
            })),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

impl AutomationCalendarScheduleV2 {
    pub fn validate(&self) -> Result<(), AutomationError> {
        self.clock_profile.validate()?;
        validate_timezone_id(&self.timezone_id)?;
        validate_digest(&self.tzdb_digest)?;
        if self.timezone_id != self.clock_profile.timezone_id
            || self.tzdb_digest != self.clock_profile.tzdb_digest
            || self.every_days == 0
            || self.local_time_ms >= DAY_MS as u32
            || self.start_at_utc_ms < self.clock_profile.valid_from_utc_ms
            || self.start_at_utc_ms >= self.clock_profile.valid_until_utc_ms
        {
            return Err(AutomationError::Invalid);
        }
        if let Some(end) = self.end_at_utc_ms
            && (end < self.start_at_utc_ms || end >= self.clock_profile.valid_until_utc_ms)
        {
            return Err(AutomationError::Invalid);
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, AutomationError> {
        self.validate()?;
        let bytes = serde_json::to_vec(self).map_err(|_| AutomationError::Corrupt)?;
        Ok(Sha256Digest::for_bytes(&bytes))
    }

    pub fn first_at_or_after(&self, reference_utc_ms: u64) -> Result<Option<u64>, AutomationError> {
        self.candidate_near(reference_utc_ms, true, true)
    }

    pub fn next_after(&self, current_utc_ms: u64) -> Result<Option<u64>, AutomationError> {
        self.candidate_near(current_utc_ms, false, true)
    }

    pub fn latest_at_or_before(
        &self,
        reference_utc_ms: u64,
    ) -> Result<Option<u64>, AutomationError> {
        self.candidate_near(reference_utc_ms, true, false)
    }

    fn candidate_near(
        &self,
        reference_utc_ms: u64,
        inclusive: bool,
        forward: bool,
    ) -> Result<Option<u64>, AutomationError> {
        self.validate()?;
        if let Some(end) = self.end_at_utc_ms
            && forward
            && reference_utc_ms > end
        {
            return Ok(None);
        }
        if !forward && reference_utc_ms < self.start_at_utc_ms {
            return Ok(None);
        }
        if reference_utc_ms < self.clock_profile.valid_from_utc_ms
            || reference_utc_ms >= self.clock_profile.valid_until_utc_ms
        {
            return Err(AutomationError::Unavailable);
        }

        let anchor_local = self.clock_profile.utc_to_local_ms(self.start_at_utc_ms)?;
        let reference_local = self.clock_profile.utc_to_local_ms(reference_utc_ms)?;
        let anchor_day = anchor_local / DAY_MS;
        let reference_day = reference_local / DAY_MS;
        let stride = u64::from(self.every_days);

        let mut day = if reference_day <= anchor_day {
            anchor_day
        } else {
            let delta = reference_day - anchor_day;
            if forward {
                anchor_day + (delta / stride) * stride
            } else {
                anchor_day + (delta / stride) * stride
            }
        };

        for _ in 0..MAX_CALENDAR_SCAN {
            let local = day
                .checked_mul(DAY_MS)
                .and_then(|value| value.checked_add(u64::from(self.local_time_ms)))
                .ok_or(AutomationError::Invalid)?;
            let candidate = self.clock_profile.resolve_local_ms(
                local,
                self.dst_gap_policy,
                self.dst_overlap_policy,
            )?;
            if let Some(candidate) = candidate {
                let lower_ok = candidate >= self.start_at_utc_ms;
                let upper_ok = self.end_at_utc_ms.is_none_or(|end| candidate <= end);
                let direction_ok = if forward {
                    candidate > reference_utc_ms || inclusive && candidate == reference_utc_ms
                } else {
                    candidate < reference_utc_ms || inclusive && candidate == reference_utc_ms
                };
                if lower_ok && upper_ok && direction_ok {
                    return Ok(Some(candidate));
                }
            }

            if forward {
                day = day.checked_add(stride).ok_or(AutomationError::Invalid)?;
                let probe = day
                    .checked_mul(DAY_MS)
                    .ok_or(AutomationError::Invalid)?;
                if probe >= self.clock_profile.utc_to_local_ms(
                    self.clock_profile.valid_until_utc_ms.saturating_sub(1),
                )? {
                    if self.end_at_utc_ms.is_some() {
                        return Ok(None);
                    }
                    return Err(AutomationError::Unavailable);
                }
            } else {
                if day < anchor_day.saturating_add(stride) {
                    return Ok(None);
                }
                day = day.checked_sub(stride).ok_or(AutomationError::Invalid)?;
            }
        }
        Err(AutomationError::Unavailable)
    }
}

impl AutomationStore {
    pub async fn create_calendar_task_v2(
        &self,
        draft: &AutomationTaskDraft,
        schedule: &AutomationCalendarScheduleV2,
        missed_run: AutomationMissedRunPolicy,
        overlap: AutomationOverlapPolicy,
    ) -> Result<AutomationTask, AutomationError> {
        draft.validate()?;
        if draft.schedule != AutomationSchedule::Once {
            return Err(AutomationError::Invalid);
        }
        validate_missed_run(missed_run)?;
        schedule.validate()?;
        let lower = draft.first_run_at_ms.max(schedule.start_at_utc_ms);
        let first = schedule
            .first_at_or_after(lower)?
            .ok_or(AutomationError::Invalid)?;
        let encoded = serde_json::to_string(schedule).map_err(|_| AutomationError::Corrupt)?;
        let digest = schedule.digest()?;
        let (missed_kind, maximum) = missed_parts(missed_run);
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        sqlx::query(
            "INSERT INTO automation_tasks (
                task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, 'once', NULL, 'enabled', ?, 1, ?, ?)",
        )
        .bind(draft.task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&draft.thread_id)
        .bind(&draft.prompt)
        .bind(to_i64(first)?)
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(constraint_or_unavailable)?;
        sqlx::query(
            "INSERT INTO automation_schedule_metadata (
                task_id, owner_agent_id, revision, missed_run_policy,
                max_catch_up_occurrences, catch_up_remaining, overlap_policy,
                created_at_ms, updated_at_ms, catch_up_active
             ) VALUES (?, ?, 1, ?, ?, 0, ?, ?, ?, 0)",
        )
        .bind(draft.task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(missed_kind)
        .bind(i64::from(maximum))
        .bind(overlap_str(overlap))
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(constraint_or_unavailable)?;
        sqlx::query(
            "INSERT INTO automation_calendar_schedule_versions (
                task_id, owner_agent_id, revision, schedule_json, schedule_digest,
                created_at_ms
             ) VALUES (?, ?, 1, ?, ?, ?)",
        )
        .bind(draft.task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(encoded)
        .bind(digest.as_str())
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(constraint_or_unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        self.task(draft.task_id)
            .await?
            .ok_or(AutomationError::Corrupt)
    }

    pub async fn calendar_schedule_v2(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<Option<(u64, AutomationCalendarScheduleV2)>, AutomationError> {
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let value = load_calendar_v2_tx(&mut tx, self, task_id).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(value)
    }

    pub async fn replace_calendar_schedule_v2(
        &self,
        task_id: AutomationTaskId,
        expected_revision: u64,
        schedule: &AutomationCalendarScheduleV2,
        now_ms: u64,
    ) -> Result<u64, AutomationError> {
        if expected_revision == 0 {
            return Err(AutomationError::Invalid);
        }
        schedule.validate()?;
        let next_revision = expected_revision
            .checked_add(1)
            .ok_or(AutomationError::Invalid)?;
        let next = schedule
            .first_at_or_after(now_ms.max(schedule.start_at_utc_ms))?
            .ok_or(AutomationError::Invalid)?;
        let encoded = serde_json::to_string(schedule).map_err(|_| AutomationError::Corrupt)?;
        let digest = schedule.digest()?;
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let active: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM automation_occurrence_lifecycle
             WHERE task_id = ? AND owner_agent_id = ?
               AND state IN ('claimed', 'admitted', 'running', 'indeterminate')",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if active != 0 {
            return Err(AutomationError::Conflict);
        }
        let current: Option<i64> = sqlx::query_scalar(
            "SELECT revision FROM automation_schedule_metadata
             WHERE task_id = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if current != Some(to_i64(expected_revision)?) {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "INSERT INTO automation_calendar_schedule_versions (
                task_id, owner_agent_id, revision, schedule_json, schedule_digest,
                created_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?)",
        )
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(to_i64(next_revision)?)
        .bind(encoded)
        .bind(digest.as_str())
        .bind(to_i64(now_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(constraint_or_unavailable)?;
        let changed = sqlx::query(
            "UPDATE automation_schedule_metadata
             SET revision = ?, catch_up_remaining = 0, catch_up_active = 0,
                 updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ? AND revision = ?",
        )
        .bind(to_i64(next_revision)?)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(to_i64(expected_revision)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if changed.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }
        sqlx::query(
            "UPDATE automation_tasks
             SET next_run_at_ms = CASE WHEN state = 'enabled' THEN ? ELSE NULL END,
                 updated_at_ms = ?
             WHERE task_id = ? AND owner_agent_id = ?
               AND state IN ('enabled', 'disabled')",
        )
        .bind(to_i64(next)?)
        .bind(to_i64(now_ms)?)
        .bind(task_id.to_string())
        .bind(self.taskflow_owner_agent_id().as_str())
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(next_revision)
    }
}

pub(crate) async fn load_calendar_v2_tx(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
) -> Result<Option<(u64, AutomationCalendarScheduleV2)>, AutomationError> {
    let row = sqlx::query(
        "SELECT v.revision, v.schedule_json, v.schedule_digest
         FROM automation_schedule_metadata m
         JOIN automation_calendar_schedule_versions v
           ON v.task_id = m.task_id
          AND v.owner_agent_id = m.owner_agent_id
          AND v.revision = m.revision
         WHERE m.task_id = ? AND m.owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let revision = to_u64(row.try_get("revision").map_err(unavailable)?)?;
    let encoded: String = row.try_get("schedule_json").map_err(unavailable)?;
    let stored_digest: String = row.try_get("schedule_digest").map_err(unavailable)?;
    let schedule: AutomationCalendarScheduleV2 =
        serde_json::from_str(&encoded).map_err(|_| AutomationError::Corrupt)?;
    schedule.validate().map_err(|_| AutomationError::Corrupt)?;
    if schedule.digest()?.as_str() != stored_digest {
        return Err(AutomationError::Corrupt);
    }
    Ok(Some((revision, schedule)))
}

pub(crate) async fn advance_calendar_schedule_v2(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    scheduled_for_ms: u64,
    observed_at_ms: u64,
    policy: AutomationSchedulePolicy,
) -> Result<bool, AutomationError> {
    let Some((revision, schedule)) = load_calendar_v2_tx(tx, store, task_id).await? else {
        return Ok(false);
    };
    if revision != policy.revision {
        return Err(AutomationError::Corrupt);
    }
    let state: String = sqlx::query_scalar(
        "SELECT state FROM automation_tasks
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_optional(&mut **tx)
    .await
    .map_err(unavailable)?
    .ok_or(AutomationError::AccessDenied)?;
    if state != "enabled" {
        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
        return Ok(true);
    }
    let Some(baseline) = schedule.next_after(scheduled_for_ms)? else {
        complete_calendar_task(tx, store, task_id, observed_at_ms).await?;
        return Ok(true);
    };
    let next = if baseline > observed_at_ms {
        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
        Some(baseline)
    } else {
        match policy.missed_run {
            AutomationMissedRunPolicy::Skip => {
                reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                schedule.first_at_or_after(observed_at_ms.saturating_add(1))?
            }
            AutomationMissedRunPolicy::Coalesce => {
                reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                schedule
                    .latest_at_or_before(observed_at_ms)?
                    .filter(|candidate| *candidate >= baseline)
                    .or(Some(baseline))
            }
            AutomationMissedRunPolicy::CatchUp { max_occurrences } => {
                let (active, remaining) = catch_up_state(tx, store, task_id).await?;
                if active {
                    if remaining == 0 {
                        reset_catch_up(tx, store, task_id, observed_at_ms).await?;
                        schedule.first_at_or_after(observed_at_ms.saturating_add(1))?
                    } else {
                        set_catch_up_state(
                            tx,
                            store,
                            task_id,
                            true,
                            remaining - 1,
                            observed_at_ms,
                        )
                        .await?;
                        Some(baseline)
                    }
                } else {
                    let mut count: u16 = 0;
                    let mut cursor = Some(baseline);
                    while let Some(value) = cursor
                        && value <= observed_at_ms
                        && count < max_occurrences
                    {
                        count = count.saturating_add(1);
                        cursor = schedule.next_after(value)?;
                    }
                    if count == 0 {
                        schedule.first_at_or_after(observed_at_ms.saturating_add(1))?
                    } else {
                        set_catch_up_state(
                            tx,
                            store,
                            task_id,
                            true,
                            count - 1,
                            observed_at_ms,
                        )
                        .await?;
                        Some(baseline)
                    }
                }
            }
        }
    };
    let Some(next) = next else {
        complete_calendar_task(tx, store, task_id, observed_at_ms).await?;
        return Ok(true);
    };
    sqlx::query(
        "UPDATE automation_tasks
         SET next_run_at_ms = ?, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
    )
    .bind(to_i64(next)?)
    .bind(to_i64(observed_at_ms)?)
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(true)
}

async fn complete_calendar_task(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    now_ms: u64,
) -> Result<(), AutomationError> {
    sqlx::query(
        "UPDATE automation_tasks
         SET state = 'completed', next_run_at_ms = NULL, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ? AND state = 'enabled'",
    )
    .bind(to_i64(now_ms)?)
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    reset_catch_up(tx, store, task_id, now_ms).await
}

async fn catch_up_state(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
) -> Result<(bool, u16), AutomationError> {
    let row = sqlx::query(
        "SELECT catch_up_active, catch_up_remaining
         FROM automation_schedule_metadata
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .fetch_one(&mut **tx)
    .await
    .map_err(unavailable)?;
    let active: i64 = row.try_get("catch_up_active").map_err(unavailable)?;
    let remaining = u16::try_from(
        row.try_get::<i64, _>("catch_up_remaining")
            .map_err(unavailable)?,
    )
    .map_err(|_| AutomationError::Corrupt)?;
    match active {
        0 => Ok((false, remaining)),
        1 => Ok((true, remaining)),
        _ => Err(AutomationError::Corrupt),
    }
}

async fn set_catch_up_state(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    active: bool,
    remaining: u16,
    now_ms: u64,
) -> Result<(), AutomationError> {
    sqlx::query(
        "UPDATE automation_schedule_metadata
         SET catch_up_active = ?, catch_up_remaining = ?, updated_at_ms = ?
         WHERE task_id = ? AND owner_agent_id = ?",
    )
    .bind(if active { 1_i64 } else { 0_i64 })
    .bind(i64::from(remaining))
    .bind(to_i64(now_ms)?)
    .bind(task_id.to_string())
    .bind(store.taskflow_owner_agent_id().as_str())
    .execute(&mut **tx)
    .await
    .map_err(unavailable)?;
    Ok(())
}

async fn reset_catch_up(
    tx: &mut Transaction<'_, Sqlite>,
    store: &AutomationStore,
    task_id: AutomationTaskId,
    now_ms: u64,
) -> Result<(), AutomationError> {
    set_catch_up_state(tx, store, task_id, false, 0, now_ms).await
}

fn missed_parts(policy: AutomationMissedRunPolicy) -> (&'static str, u16) {
    match policy {
        AutomationMissedRunPolicy::Skip => ("skip", 0),
        AutomationMissedRunPolicy::Coalesce => ("coalesce", 0),
        AutomationMissedRunPolicy::CatchUp { max_occurrences } => ("catch_up", max_occurrences),
    }
}

fn validate_missed_run(policy: AutomationMissedRunPolicy) -> Result<(), AutomationError> {
    match policy {
        AutomationMissedRunPolicy::Skip | AutomationMissedRunPolicy::Coalesce => Ok(()),
        AutomationMissedRunPolicy::CatchUp { max_occurrences }
            if (1..=1_024).contains(&max_occurrences) =>
        {
            Ok(())
        }
        AutomationMissedRunPolicy::CatchUp { .. } => Err(AutomationError::Invalid),
    }
}

fn overlap_str(value: AutomationOverlapPolicy) -> &'static str {
    match value {
        AutomationOverlapPolicy::Forbid => "forbid",
        AutomationOverlapPolicy::Allow => "allow",
    }
}

fn valid_offset(value: i32) -> bool {
    (-MAX_OFFSET_SECONDS..=MAX_OFFSET_SECONDS).contains(&value)
}

fn validate_timezone_id(value: &str) -> Result<(), AutomationError> {
    if value.is_empty()
        || value.len() > MAX_TIMEZONE_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_+-./".contains(&byte))
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn validate_digest(value: &Sha256Digest) -> Result<(), AutomationError> {
    let raw = value.as_str();
    if raw == ZERO_DIGEST
        || raw.len() != 64
        || !raw
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(AutomationError::Invalid);
    }
    Ok(())
}

fn shift_ms(value: u64, offset_seconds: i32) -> Result<u64, AutomationError> {
    let shifted = i128::from(value) + i128::from(offset_seconds) * 1_000;
    u64::try_from(shifted).map_err(|_| AutomationError::Invalid)
}

fn unshift_ms(value: u64, offset_seconds: i32) -> Result<Option<u64>, AutomationError> {
    let shifted = i128::from(value) - i128::from(offset_seconds) * 1_000;
    if shifted < 0 || shifted > i128::from(u64::MAX) {
        return Ok(None);
    }
    Ok(Some(
        u64::try_from(shifted).map_err(|_| AutomationError::Invalid)?,
    ))
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

fn constraint_or_unavailable(error: sqlx::Error) -> AutomationError {
    if matches!(
        error,
        sqlx::Error::Database(ref database) if database.is_unique_violation()
    ) {
        AutomationError::Conflict
    } else {
        AutomationError::Unavailable
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const HOUR: u64 = 3_600_000;
    const DAY: u64 = DAY_MS;

    fn digest(label: &[u8]) -> Sha256Digest {
        Sha256Digest::for_bytes(label)
    }

    fn profile(
        at_utc_ms: u64,
        before: i32,
        after: i32,
    ) -> AutomationTimeZoneProfileV1 {
        AutomationTimeZoneProfileV1 {
            timezone_id: "America/Test".to_string(),
            tzdb_digest: digest(b"tzdb-test"),
            valid_from_utc_ms: 90 * DAY,
            valid_until_utc_ms: 110 * DAY,
            initial_offset_seconds: before,
            transitions: vec![AutomationTimezoneTransitionV1 {
                at_utc_ms,
                offset_before_seconds: before,
                offset_after_seconds: after,
            }],
        }
    }

    fn schedule(
        profile: AutomationTimeZoneProfileV1,
        local_time_ms: u32,
        gap: AutomationDstGapPolicy,
        overlap: AutomationDstOverlapPolicy,
    ) -> AutomationCalendarScheduleV2 {
        AutomationCalendarScheduleV2 {
            timezone_id: profile.timezone_id.clone(),
            tzdb_digest: profile.tzdb_digest.clone(),
            start_at_utc_ms: 95 * DAY,
            end_at_utc_ms: Some(105 * DAY),
            every_days: 1,
            local_time_ms,
            dst_gap_policy: gap,
            dst_overlap_policy: overlap,
            clock_profile: profile,
        }
    }

    #[test]
    fn dst_gap_policy_is_explicit_and_deterministic() {
        let transition = 100 * DAY + 10 * HOUR;
        let profile = profile(transition, -8 * 3_600, -7 * 3_600);
        let target = (2 * HOUR + HOUR / 2) as u32;
        let next_valid = schedule(
            profile.clone(),
            target,
            AutomationDstGapPolicy::NextValid,
            AutomationDstOverlapPolicy::First,
        );
        assert_eq!(
            next_valid
                .first_at_or_after(100 * DAY)
                .expect("gap resolution"),
            Some(transition)
        );
        let skip = schedule(
            profile,
            target,
            AutomationDstGapPolicy::Skip,
            AutomationDstOverlapPolicy::First,
        );
        assert!(
            skip.first_at_or_after(100 * DAY)
                .expect("skip resolution")
                .is_some_and(|value| value > transition + 12 * HOUR)
        );
    }

    #[test]
    fn dst_overlap_selects_first_or_second_utc_instant() {
        let transition = 100 * DAY + 9 * HOUR;
        let profile = profile(transition, -7 * 3_600, -8 * 3_600);
        let target = (HOUR + HOUR / 2) as u32;
        let first = schedule(
            profile.clone(),
            target,
            AutomationDstGapPolicy::Skip,
            AutomationDstOverlapPolicy::First,
        );
        let second = schedule(
            profile,
            target,
            AutomationDstGapPolicy::Skip,
            AutomationDstOverlapPolicy::Second,
        );
        let first_value = first
            .first_at_or_after(100 * DAY)
            .expect("first overlap")
            .expect("first instant");
        let second_value = second
            .first_at_or_after(100 * DAY)
            .expect("second overlap")
            .expect("second instant");
        assert_eq!(second_value - first_value, HOUR);
        assert!(first_value < transition);
        assert!(second_value > transition);
    }

    #[test]
    fn tzdb_identity_changes_schedule_digest() {
        let transition = 100 * DAY + 9 * HOUR;
        let profile = profile(transition, -7 * 3_600, -8 * 3_600);
        let first = schedule(
            profile.clone(),
            HOUR as u32,
            AutomationDstGapPolicy::Skip,
            AutomationDstOverlapPolicy::First,
        );
        let mut second = first.clone();
        second.tzdb_digest = digest(b"tzdb-second");
        second.clock_profile.tzdb_digest = second.tzdb_digest.clone();
        assert_ne!(first.digest().expect("first"), second.digest().expect("second"));
    }
}
