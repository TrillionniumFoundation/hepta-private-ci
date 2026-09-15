//! Persistent timer-owner lifecycle. These APIs require the trusted Agent host
//! to retain its existing per-Agent writer lock and management authorization.
//! They do not select/activate topology candidates or reconcile TaskFlow effects.

use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationError;
use crate::AutomationStore;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TimerPhase {
    Active,
    Draining,
    Retired,
}

impl TimerPhase {
    fn parse(value: &str) -> Result<Self, AutomationError> {
        match value {
            "active" => Ok(Self::Active),
            "draining" => Ok(Self::Draining),
            "retired" => Ok(Self::Retired),
            _ => Err(AutomationError::Corrupt),
        }
    }
}

/// A coherent local admission/outbox snapshot, not external effect completion.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TimerDrainStatus {
    pub writer_epoch: u64,
    pub phase: TimerPhase,
    pub pending_occurrences: u64,
    pub leased_occurrences: u64,
    pub uncertain_dispatches: u64,
}

impl TimerDrainStatus {
    /// Pending occurrences have not crossed the queue seam and can be handed
    /// over intact. An expired lease or unknown response is not proof of drain.
    pub fn can_handoff(&self) -> bool {
        self.phase == TimerPhase::Draining
            && self.leased_occurrences == 0
            && self.uncertain_dispatches == 0
    }
}

impl AutomationStore {
    /// Read the durable owner, even through an old, fenced observer handle.
    pub async fn timer_status(&self) -> Result<TimerDrainStatus, AutomationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let status = read_status(&mut transaction).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(status)
    }

    /// Stop new timer claims and schedule creation without deleting schedules,
    /// revoking admitted queue work or disturbing another Agent's owner.
    pub async fn quiesce_timer(&self) -> Result<TimerDrainStatus, AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        sqlx::query("UPDATE automation_timer_lifecycle SET phase = 'draining' WHERE singleton = 1")
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        let status = read_status(&mut transaction).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(status)
    }

    /// Resume only this current, compatible timer owner. Cancelled/disabled
    /// schedules and original occurrence/client identities are never reset.
    pub async fn resume_timer(&self) -> Result<TimerDrainStatus, AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        sqlx::query("UPDATE automation_timer_lifecycle SET phase = 'active' WHERE singleton = 1")
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        let status = read_status(&mut transaction).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(status)
    }

    /// Fence all predecessor handles and return a separately pooled successor.
    /// The successor stays draining until its consumer is installed and the
    /// host explicitly resumes it. State is reused in place at the same schema;
    /// this is not a cross-schema migration or a cross-host transfer protocol.
    ///
    /// A compatible rollback is another handoff to a newer epoch, not restoring
    /// an old database or reviving a predecessor handle. If reopening fails
    /// after commit, storage remains draining and the old writer stays fenced.
    pub async fn handoff_timer(&self) -> Result<Self, AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        let status = read_status(&mut transaction).await?;
        if !status.can_handoff() {
            return Err(AutomationError::Conflict);
        }
        let next = self
            .timer_epoch
            .checked_add(1)
            .ok_or(AutomationError::Conflict)?;
        sqlx::query("UPDATE automation_timer_lifecycle SET writer_epoch = ? WHERE singleton = 1")
            .bind(next)
            .execute(&mut *transaction)
            .await
            .map_err(unavailable)?;
        transaction.commit().await.map_err(unavailable)?;
        let root = self
            .path
            .parent()
            .ok_or(AutomationError::Corrupt)?
            .to_path_buf();
        let successor = Self::open_root(root, self.owner_agent_id.clone()).await?;
        if successor.timer_epoch != next {
            successor.close().await;
            return Err(AutomationError::Conflict);
        }
        Ok(successor)
    }

    /// Permanently retire the timer domain after all admitted/unknown work has
    /// drained. One durable tombstone blocks pending work without rewriting an
    /// unbounded backlog. Schedules, counters and receipts remain for audit.
    /// TaskFlow's separate structural ledger is not retired by this operation.
    pub async fn retire_timer(&self) -> Result<TimerDrainStatus, AutomationError> {
        let (mut transaction, _) = self.begin_timer_write().await?;
        let status = read_status(&mut transaction).await?;
        if !status.can_handoff() {
            return Err(AutomationError::Conflict);
        }
        let next = self
            .timer_epoch
            .checked_add(1)
            .ok_or(AutomationError::Conflict)?;
        sqlx::query(
            "UPDATE automation_timer_lifecycle SET phase = 'retired', writer_epoch = ?
             WHERE singleton = 1",
        )
        .bind(next)
        .execute(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let status = read_status(&mut transaction).await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(status)
    }

    /// Acquire SQLite's writer reservation before checking the epoch. Keep the
    /// check and domain mutation in the same transaction: a read-then-write
    /// check outside it would permit stale writers to race the handoff.
    pub(super) async fn begin_timer_write(
        &self,
    ) -> Result<(Transaction<'_, Sqlite>, TimerPhase), AutomationError> {
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let phase: Option<String> = sqlx::query_scalar(
            "UPDATE automation_timer_lifecycle SET writer_epoch = writer_epoch
             WHERE singleton = 1 AND writer_epoch = ? AND phase != 'retired'
             RETURNING phase",
        )
        .bind(self.timer_epoch)
        .fetch_optional(&mut *transaction)
        .await
        .map_err(unavailable)?;
        let phase = phase.ok_or(AutomationError::TimerFenced)?;
        Ok((transaction, TimerPhase::parse(&phase)?))
    }
}

pub(super) async fn read_status(
    transaction: &mut Transaction<'_, Sqlite>,
) -> Result<TimerDrainStatus, AutomationError> {
    let row = sqlx::query(
        "SELECT writer_epoch, phase,
             (SELECT COUNT(*) FROM automation_runs WHERE state = 'pending') AS pending,
             (SELECT COUNT(*) FROM automation_runs WHERE state = 'leased') AS leased,
             (SELECT COUNT(*) FROM automation_dispatch_outcomes WHERE outcome = 'uncertain') AS uncertain
         FROM automation_timer_lifecycle WHERE singleton = 1",
    )
    .fetch_optional(&mut **transaction)
    .await
    .map_err(unavailable)?
    .ok_or(AutomationError::Corrupt)?;
    let count = |key: &str| -> Result<u64, AutomationError> {
        let value: i64 = row.try_get(key).map_err(unavailable)?;
        u64::try_from(value).map_err(|_| AutomationError::Corrupt)
    };
    let epoch = count("writer_epoch")?;
    if epoch == 0 {
        return Err(AutomationError::Corrupt);
    }
    let status = TimerDrainStatus {
        writer_epoch: epoch,
        phase: TimerPhase::parse(&row.try_get::<String, _>("phase").map_err(unavailable)?)?,
        pending_occurrences: count("pending")?,
        leased_occurrences: count("leased")?,
        uncertain_dispatches: count("uncertain")?,
    };
    if status.phase == TimerPhase::Retired
        && (status.leased_occurrences != 0 || status.uncertain_dispatches != 0)
    {
        return Err(AutomationError::Corrupt);
    }
    Ok(status)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}
