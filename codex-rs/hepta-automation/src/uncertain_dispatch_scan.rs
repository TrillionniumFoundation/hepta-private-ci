//! Read-only bounded round-robin discovery of unknown queue admissions.

use super::*;

/// Process-local scheduling position for one live store instance and its clones.
/// This non-serializable cursor is not effect authority or provider evidence.
/// A fresh open needs a fresh cursor, including reopening the same database.
/// Row deletion/reuse or rollback can defer work until the next finite scan,
/// but cannot change its durable uncertainty or authorize another admission.
#[derive(Debug)]
pub struct AutomationUncertainDispatchScan {
    store_identity: Arc<()>,
    after: i64,
    through: Option<i64>,
}

impl AutomationStore {
    /// Start a bounded unknown-dispatch scan. Keep one cursor per observer.
    pub fn uncertain_dispatch_scan(&self) -> AutomationUncertainDispatchScan {
        AutomationUncertainDispatchScan {
            store_identity: Arc::clone(&self.uncertainty_scan_identity),
            after: 0,
            through: None,
        }
    }

    /// Inspect at most 64 physical outcome rows and return at most one current
    /// unknown dispatch without changing evidence. Submitted/other-owner rows
    /// consume the same scan budget; LIMIT is applied before the joins/filter.
    /// An empty result can mean a filtered page or the end of this scan; keep
    /// calling on later ticks. Exhaustion starts a new scan on the next call. Newly inserted work cannot extend the captured high-water.
    /// Progress is committed locally before the caller awaits its observation;
    /// cancellation cannot remove or settle that durable occurrence.
    pub async fn next_uncertain_dispatch(
        &self,
        scan: &mut AutomationUncertainDispatchScan,
    ) -> Result<Option<AutomationDispatchUncertainty>, AutomationError> {
        if !Arc::ptr_eq(&scan.store_identity, &self.uncertainty_scan_identity) {
            return Err(AutomationError::AccessDenied);
        }
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let through = match scan.through {
            Some(through) => Some(through),
            None => {
                let first = sqlx::query_scalar::<_, i64>(
                    "SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid LIMIT 1",
                )
                .fetch_optional(&mut *tx)
                .await
                .map_err(unavailable)?;
                if first.is_some_and(|rowid| rowid <= 0) {
                    return Err(AutomationError::Corrupt);
                }
                sqlx::query_scalar::<_, i64>(
                    "SELECT rowid FROM automation_dispatch_outcomes ORDER BY rowid DESC LIMIT 1",
                )
                .fetch_optional(&mut *tx)
                .await
                .map_err(unavailable)?
            }
        };
        let Some(through) = through else {
            tx.commit().await.map_err(unavailable)?;
            scan.after = 0;
            scan.through = None;
            return Ok(None);
        };
        let rows = sqlx::query(
            "SELECT o.*, t.owner_agent_id, r.scheduled_for_ms FROM (
                 SELECT rowid AS scan_rowid, task_id, occurrence,
                        client_user_message_id, observed_at_ms, outcome
                 FROM automation_dispatch_outcomes NOT INDEXED
                 WHERE rowid > ? AND rowid <= ? ORDER BY rowid LIMIT 64
             ) o
             LEFT JOIN automation_runs r
               ON r.task_id = o.task_id AND r.occurrence = o.occurrence
             LEFT JOIN automation_tasks t ON t.task_id = o.task_id
             ORDER BY o.scan_rowid",
        )
        .bind(scan.after)
        .bind(through)
        .fetch_all(&mut *tx)
        .await
        .map_err(unavailable)?;
        let mut last_scanned = scan.after;
        let mut next = None;
        for row in &rows {
            let rowid: i64 = row.try_get("scan_rowid").map_err(unavailable)?;
            if rowid <= last_scanned || rowid > through {
                return Err(AutomationError::Corrupt);
            }
            last_scanned = rowid;
            let owner: String = row.try_get("owner_agent_id").map_err(unavailable)?;
            let scheduled_for_ms = to_u64(row.try_get("scheduled_for_ms").map_err(unavailable)?)?;
            let outcome: String = row.try_get("outcome").map_err(unavailable)?;
            if owner != self.owner_agent_id.as_str() || outcome != "uncertain" {
                continue;
            }
            next = Some(AutomationDispatchUncertainty {
                task_id: parse_task_id(row, "task_id")?,
                occurrence: to_u64(row.try_get("occurrence").map_err(unavailable)?)?,
                scheduled_for_ms,
                client_user_message_id: row
                    .try_get("client_user_message_id")
                    .map_err(unavailable)?,
                observed_at_ms: to_u64(row.try_get("observed_at_ms").map_err(unavailable)?)?,
            });
            break;
        }
        tx.commit().await.map_err(unavailable)?;
        // No local cursor mutation precedes successful snapshot completion.
        if rows.is_empty() || last_scanned == through {
            scan.after = 0;
            scan.through = None;
        } else {
            scan.after = last_scanned;
            scan.through = Some(through);
        }
        Ok(next)
    }
}

#[cfg(test)]
#[path = "uncertain_dispatch_scan_tests.rs"]
mod tests;
