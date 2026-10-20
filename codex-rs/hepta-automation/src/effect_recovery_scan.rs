//! Bounded, read-only discovery over immutable provider attempts.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AuthorizedEffectError;
use crate::AuthorizedEffectPending;
use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowStepObservation;
use crate::authorized_effect::effect_command_id;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::effect_attempt_from_row;

/// Opaque continuation for this owner and database path. Immutable attempt
/// anchors reject reuse against a replaced/incompatible database. Keep the
/// value to resume after reopening the same store; it grants no authority.
/// The path/owner digest is a binding label, not a physical incarnation or
/// credential. Replaced contents or rowid remapping must preserve both exact
/// immutable anchors or the continuation rejects. No untrusted decoding API
/// is provided; a process that loses the cursor starts a new scan.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedEffectRecoveryCursor {
    store: Sha256Digest,
    after: AttemptAnchor,
    through: AttemptAnchor,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct AttemptAnchor {
    rowid: i64,
    identity: Sha256Digest,
}

/// Completion applies only to this immutable-attempt scan. Settlement is read
/// when each page is visited, not from one cross-page transaction snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthorizedEffectRecoveryProgress {
    More(AuthorizedEffectRecoveryCursor),
    Complete,
}

/// An empty effects list can still have More progress. Always consume the
/// continuation; start another scan to observe new attempts or later changes.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedEffectRecoveryPage {
    pub effects: Vec<AuthorizedEffectPending>,
    pub scanned_attempts: usize,
    pub progress: AuthorizedEffectRecoveryProgress,
}

// Shared by the bounded page and the two immutable cursor-anchor reads.
const ATTEMPTS: &str = "SELECT a.rowid AS scan_rowid, a.*,
    COALESCE(r.observation, o.observation) AS observation,
    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms,
    CASE WHEN w.run_id IS NOT NULL THEN 'accepted'
         ELSE o.provider_dispatch_status END AS provider_dispatch_status
    FROM taskflow_effect_dispatch_attempts a
    LEFT JOIN taskflow_effect_dispatch_observations o
      USING(owner_agent_id, run_id, step_id, attempt)
    LEFT JOIN taskflow_effect_dispatch_reconciliations r
      USING(owner_agent_id, run_id, step_id, attempt)
    LEFT JOIN taskflow_effect_provider_acceptances w
      USING(owner_agent_id, run_id, step_id, attempt)";

impl AutomationStore {
    /// Inspect at most `limit` immutable attempts (1..=1024), in insertion
    /// order. Terminal facts stay discoverable until their exact step and run
    /// projection are verified. No provider is contacted or authorized.
    ///
    /// The first page fixes an immutable-attempt high-water mark. Later pages
    /// read current settlement independently. Even an empty filtered page may
    /// carry More. Complete is the end of this scan, not permanent completion;
    /// a new scan observes later attempts and settlement changes.
    pub async fn scan_authorized_taskflow_effects(
        &self,
        cursor: Option<&AuthorizedEffectRecoveryCursor>,
        limit: usize,
    ) -> Result<AuthorizedEffectRecoveryPage, AuthorizedEffectError> {
        if limit == 0 || limit > 1_024 {
            return Err(TaskFlowError::Invalid("effect recovery scan limit".to_string()).into());
        }
        let store = Sha256Digest::for_bytes(
            &serde_json::to_vec(&(
                "hepta.automation.effect-scan.v1",
                self.taskflow_owner_agent_id().as_str(),
                self.path().as_os_str().as_encoded_bytes(),
            ))
            .map_err(|_| invalid_cursor())?,
        );
        // Anchor validation and candidate selection use one read snapshot,
        // so VACUUM or concurrent writers cannot splice their rowid views.
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let (after, through) = if let Some(cursor) = cursor {
            if cursor.store != store
                || cursor.after.rowid <= 0
                || cursor.after.rowid >= cursor.through.rowid
            {
                return Err(invalid_cursor().into());
            }
            for expected in [&cursor.after, &cursor.through] {
                let query = format!("{ATTEMPTS} WHERE a.owner_agent_id = ? AND a.rowid = ?");
                let row = sqlx::query(sqlx::AssertSqlSafe(query))
                    .bind(self.taskflow_owner_agent_id().as_str())
                    .bind(expected.rowid)
                    .fetch_optional(&mut *transaction)
                    .await
                    .map_err(|_| TaskFlowError::Unavailable)?
                    .ok_or_else(invalid_cursor)?;
                if anchor(&row)? != *expected {
                    return Err(invalid_cursor().into());
                }
            }
            (cursor.after.rowid, cursor.through.clone())
        } else {
            let query =
                format!("{ATTEMPTS} WHERE a.owner_agent_id = ? ORDER BY a.rowid DESC LIMIT 1");
            let Some(row) = sqlx::query(sqlx::AssertSqlSafe(query))
                .bind(self.taskflow_owner_agent_id().as_str())
                .fetch_optional(&mut *transaction)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?
            else {
                transaction
                    .commit()
                    .await
                    .map_err(|_| TaskFlowError::Unavailable)?;
                return Ok(AuthorizedEffectRecoveryPage {
                    effects: Vec::new(),
                    scanned_attempts: 0,
                    progress: AuthorizedEffectRecoveryProgress::Complete,
                });
            };
            (0, anchor(&row)?)
        };
        let query = format!(
            "{ATTEMPTS} WHERE a.owner_agent_id = ? AND a.rowid > ? AND a.rowid <= ?
             ORDER BY a.rowid LIMIT ?"
        );
        let rows = sqlx::query(sqlx::AssertSqlSafe(query))
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(after)
            .bind(through.rowid)
            .bind(i64::try_from(limit).map_err(|_| invalid_cursor())?)
            .fetch_all(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let last = anchor(rows.last().ok_or_else(invalid_cursor)?)?;
        let scanned_attempts = rows.len();
        let mut effects = Vec::new();
        for row in rows {
            let attempt = effect_attempt_from_row(row)?;
            if !self.effect_projection_is_settled(&attempt).await? {
                effects.push(attempt.into());
            }
        }
        let progress = if last == through {
            AuthorizedEffectRecoveryProgress::Complete
        } else {
            AuthorizedEffectRecoveryProgress::More(AuthorizedEffectRecoveryCursor {
                store,
                after: last,
                through,
            })
        };
        Ok(AuthorizedEffectRecoveryPage {
            effects,
            scanned_attempts,
            progress,
        })
    }

    async fn effect_projection_is_settled(
        &self,
        attempt: &EffectDispatchAttempt,
    ) -> Result<bool, TaskFlowError> {
        let Some(observation) = &attempt.observation else {
            return Ok(false);
        };
        let result = match observation.kind {
            EffectDispatchObservationKind::Indeterminate => return Ok(false),
            EffectDispatchObservationKind::Succeeded | EffectDispatchObservationKind::Failed => {
                self.read_terminal_taskflow_step(&attempt.run_id, &attempt.step_id, attempt.attempt)
                    .await
            }
            EffectDispatchObservationKind::ProvenAbsent => {
                self.read_absent_taskflow_step(
                    &attempt.run_id,
                    &attempt.step_id,
                    attempt.attempt,
                    &observation.evidence_digest,
                    &effect_command_id("requeue-absent", attempt),
                )
                .await
            }
        };
        let step = match result {
            Ok(Some(step)) => step,
            Ok(None)
            | Err(
                TaskFlowError::Conflict(_) | TaskFlowError::Corrupt(_) | TaskFlowError::StaleFence,
            ) => return Ok(false),
            Err(error) => return Err(error),
        };
        let outcome_matches = match observation.kind {
            EffectDispatchObservationKind::Succeeded => step.final_outcome.map_or(
                step.observation == Some(TaskFlowStepObservation::Succeeded),
                |outcome| outcome == TaskFlowReconcileOutcome::Succeeded,
            ),
            EffectDispatchObservationKind::Failed => step.final_outcome.map_or(
                step.observation == Some(TaskFlowStepObservation::Failed),
                |outcome| outcome == TaskFlowReconcileOutcome::Failed,
            ),
            EffectDispatchObservationKind::ProvenAbsent => {
                step.final_outcome == Some(TaskFlowReconcileOutcome::Cancelled)
            }
            EffectDispatchObservationKind::Indeterminate => false,
        };
        Ok(step.intent_digest == attempt.intent_digest
            && step.payload_digest == attempt.payload_digest
            && step.receipt_digest.as_ref() == Some(&observation.evidence_digest)
            && outcome_matches)
    }
}

fn anchor(row: &sqlx::sqlite::SqliteRow) -> Result<AttemptAnchor, TaskFlowError> {
    let rowid: i64 = row.try_get("scan_rowid").map_err(|_| invalid_cursor())?;
    if rowid <= 0 {
        return Err(invalid_cursor());
    }
    // Only immutable dispatch identity participates. Provider observations can
    // advance between pages without invalidating an otherwise exact cursor.
    let fields = [
        "owner_agent_id",
        "run_id",
        "step_id",
        "intent_digest",
        "payload_digest",
        "binding_digest",
        "destination_id",
        "grant_id",
        "grant_nonce_digest",
        "record_command_id",
    ]
    .into_iter()
    .map(|name| row.try_get::<String, _>(name))
    .collect::<Result<Vec<_>, _>>()
    .map_err(|_| invalid_cursor())?;
    let counters = [
        "attempt",
        "authority_epoch",
        "started_at_ms",
        "provider_key_version",
    ]
    .into_iter()
    .map(|name| row.try_get::<i64, _>(name))
    .collect::<Result<Vec<_>, _>>()
    .map_err(|_| invalid_cursor())?;
    let contract: Option<String> = row
        .try_get("provider_contract_binding")
        .map_err(|_| invalid_cursor())?;
    let bytes = serde_json::to_vec(&(fields, counters, contract)).map_err(|_| invalid_cursor())?;
    Ok(AttemptAnchor {
        rowid,
        identity: Sha256Digest::for_bytes(&bytes),
    })
}

fn invalid_cursor() -> TaskFlowError {
    TaskFlowError::Invalid("effect recovery cursor is incompatible with this store".to_string())
}

#[cfg(test)]
#[path = "effect_recovery_scan_tests.rs"]
mod tests;
