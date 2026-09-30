//! Bounded recovery and claim lifecycle for the durable compaction owner.
//!
//! This module is the single recovery boundary above the immutable artifact
//! store. It does not rebuild checkpoints or mint authority. Every mutation is
//! performed in a cancellation-safe SQLx transaction and revalidates the full
//! owner/root/manifest/lease fence inside that transaction.

use std::str::FromStr;

use codex_hepta_types::Digest32;
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::{Executor, Row, Sqlite, SqlitePool, Transaction};

use crate::coordinator::CompactionCoordinatorErrorV2;
use crate::durable::{DurableCompactionError, DurableCompactionOutboxEventV1};
use crate::MutationFenceContextV1;

const MAX_RECOVERY_BATCH: u32 = 1_000;
const MAX_OUTBOX_CLAIM_SECONDS: u64 = 3_600;

const RECOVERY_SCHEMA: &str = r#"
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS compaction_admission_recovery_v3 (
    owner_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    recovery_state TEXT NOT NULL CHECK (
        recovery_state IN (
            'no-artifact',
            'committed-unfinalized',
            'indeterminate',
            'terminal-failure',
            'quarantined',
            'committed'
        )
    ),
    observed_publication_digest TEXT CHECK (
        observed_publication_digest IS NULL OR length(observed_publication_digest) = 64
    ),
    detail_digest TEXT NOT NULL CHECK (length(detail_digest) = 64),
    observation_revision INTEGER NOT NULL CHECK (observation_revision > 0),
    observed_at_unix_seconds INTEGER NOT NULL CHECK (observed_at_unix_seconds >= 0),
    PRIMARY KEY (owner_id, idempotency_key),
    FOREIGN KEY (owner_id, idempotency_key)
      REFERENCES compaction_publication_admissions_v2(owner_id, idempotency_key)
      ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS compaction_admission_recovery_state_v3
  ON compaction_admission_recovery_v3(
      owner_id, recovery_state, observed_at_unix_seconds, idempotency_key
  );

CREATE TABLE IF NOT EXISTS compaction_outbox_claim_leases_v3 (
    owner_id TEXT NOT NULL,
    event_id TEXT NOT NULL CHECK (length(event_id) = 64),
    worker_id TEXT NOT NULL CHECK (length(trim(worker_id)) BETWEEN 1 AND 128),
    claim_token_digest TEXT NOT NULL CHECK (length(claim_token_digest) = 64),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    claim_deadline_unix_seconds INTEGER NOT NULL CHECK (claim_deadline_unix_seconds > 0),
    claimed_at_unix_seconds INTEGER NOT NULL CHECK (claimed_at_unix_seconds >= 0),
    completed_at_unix_seconds INTEGER,
    state TEXT NOT NULL CHECK (state IN ('claimed', 'completed', 'abandoned', 'quarantined')),
    PRIMARY KEY (owner_id, event_id),
    UNIQUE (owner_id, claim_token_digest),
    FOREIGN KEY (owner_id, event_id)
      REFERENCES compaction_outbox(owner_id, event_id) ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE INDEX IF NOT EXISTS compaction_outbox_claim_deadline_v3
  ON compaction_outbox_claim_leases_v3(
      owner_id, state, claim_deadline_unix_seconds, event_id
  );

-- Legacy read paths used to reset every claimed outbox row. Once a V3 claim
-- lease exists, such a reset is ignored. The recovery owner first moves an
-- expired/old-generation lease to `abandoned` in its own transaction and only
-- then requeues the outbox row.
CREATE TRIGGER IF NOT EXISTS compaction_outbox_active_claim_guard_v3
BEFORE UPDATE OF state, claim_token ON compaction_outbox
WHEN OLD.state = 'claimed'
 AND NEW.state = 'pending'
 AND EXISTS (
     SELECT 1
       FROM compaction_outbox_claim_leases_v3 AS lease
      WHERE lease.owner_id = OLD.owner_id
        AND lease.event_id = OLD.event_id
        AND lease.state = 'claimed'
 )
BEGIN
    SELECT RAISE(IGNORE);
END;

CREATE TRIGGER IF NOT EXISTS compaction_admission_recovery_identity_v3
BEFORE UPDATE ON compaction_admission_recovery_v3
WHEN NEW.owner_id != OLD.owner_id
 OR NEW.idempotency_key != OLD.idempotency_key
 OR NEW.checkpoint_digest != OLD.checkpoint_digest
 OR NEW.observation_revision <= OLD.observation_revision
BEGIN
    SELECT RAISE(ABORT, 'compaction admission recovery identity/revision is invalid');
END;

CREATE TRIGGER IF NOT EXISTS compaction_admission_recovery_no_delete_v3
BEFORE DELETE ON compaction_admission_recovery_v3 BEGIN
    SELECT RAISE(ABORT, 'compaction admission recovery history is append-only');
END;
"#;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableCompactionOutboxClaimV2 {
    pub owner_id: String,
    pub worker_id: String,
    pub claim_deadline_unix_seconds: u64,
    pub lease_epoch: u64,
    pub event: DurableCompactionOutboxEventV1,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionClaimReconciliationSummaryV1 {
    pub inspected: u64,
    pub requeued: u64,
    pub quarantined_orphans: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionAdmissionReconciliationSummaryV1 {
    pub inspected: u64,
    pub no_artifact: u64,
    pub committed_unfinalized: u64,
    pub indeterminate: u64,
    pub terminal_failure: u64,
    pub quarantined: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CompactionRecoveryStartupSummaryV1 {
    pub claims: CompactionClaimReconciliationSummaryV1,
    pub admissions: CompactionAdmissionReconciliationSummaryV1,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum CompactionAdmissionRecoveryStateV1 {
    NoArtifact,
    CommittedUnfinalized,
    Indeterminate,
    TerminalFailure,
    Quarantined,
    Committed,
}

impl CompactionAdmissionRecoveryStateV1 {
    const fn label(self) -> &'static str {
        match self {
            Self::NoArtifact => "no-artifact",
            Self::CommittedUnfinalized => "committed-unfinalized",
            Self::Indeterminate => "indeterminate",
            Self::TerminalFailure => "terminal-failure",
            Self::Quarantined => "quarantined",
            Self::Committed => "committed",
        }
    }

    fn parse(value: &str) -> Result<Self, CompactionCoordinatorErrorV2> {
        match value {
            "no-artifact" => Ok(Self::NoArtifact),
            "committed-unfinalized" => Ok(Self::CommittedUnfinalized),
            "indeterminate" => Ok(Self::Indeterminate),
            "terminal-failure" => Ok(Self::TerminalFailure),
            "quarantined" => Ok(Self::Quarantined),
            "committed" => Ok(Self::Committed),
            _ => Err(corrupt("unknown admission recovery state")),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[non_exhaustive]
pub enum CompactionOperationStatusV1 {
    Absent,
    Reserved {
        checkpoint_digest: Digest32,
    },
    NoArtifact {
        checkpoint_digest: Digest32,
    },
    CommittedUnfinalized {
        checkpoint_digest: Digest32,
        publication_digest: Digest32,
    },
    Committed {
        checkpoint_digest: Digest32,
        publication_digest: Digest32,
    },
    Indeterminate {
        checkpoint_digest: Digest32,
    },
    TerminalFailure {
        checkpoint_digest: Digest32,
    },
    Quarantined {
        checkpoint_digest: Digest32,
    },
}

#[derive(Clone)]
pub(crate) struct RecoveryStoreV1 {
    pool: SqlitePool,
    owner_id: String,
    root_key_digest: Digest32,
    manifest_digest: Digest32,
    lease_token_digest: Digest32,
    lease_epoch: u64,
}

impl RecoveryStoreV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn open(
        database_url: &str,
        owner_id: &str,
        root_key_digest: Digest32,
        manifest_digest: Digest32,
        lease_token_digest: Digest32,
        lease_epoch: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        validate_identity("recovery owner id", owner_id, 128)?;
        if lease_epoch == 0 {
            return Err(invalid("recovery lease epoch must be non-zero"));
        }
        let options = SqliteConnectOptions::from_str(database_url)
            .map_err(sql_error)?
            .create_if_missing(true)
            .foreign_keys(true)
            .journal_mode(SqliteJournalMode::Wal)
            .synchronous(SqliteSynchronous::Full);
        let pool = SqlitePoolOptions::new()
            .max_connections(4)
            .connect_with(options)
            .await
            .map_err(sql_error)?;
        sqlx::raw_sql(RECOVERY_SCHEMA)
            .execute(&pool)
            .await
            .map_err(sql_error)?;
        Ok(Self {
            pool,
            owner_id: owner_id.to_string(),
            root_key_digest,
            manifest_digest,
            lease_token_digest,
            lease_epoch,
        })
    }

    pub(crate) fn set_manifest_digest(&mut self, manifest_digest: Digest32) {
        self.manifest_digest = manifest_digest;
    }

    fn fence_context(
        &self,
        execution_now_unix_seconds: u64,
    ) -> Result<MutationFenceContextV1, CompactionCoordinatorErrorV2> {
        MutationFenceContextV1::new(
            self.owner_id.clone(),
            self.root_key_digest,
            self.manifest_digest,
            self.lease_token_digest,
            self.lease_epoch,
            execution_now_unix_seconds,
        )
        .map_err(|error| invalid(error.to_string()))
    }

    pub(crate) async fn verify_local_state(
        &self,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let context = self.fence_context(now_unix_seconds)?;
        let mut transaction = self.pool.begin().await.map_err(sql_error)?;
        verify_mutation_fence_tx(&mut transaction, &context).await?;
        let required: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM sqlite_schema
             WHERE type IN ('table', 'trigger')
               AND name IN (
                 'compaction_admission_recovery_v3',
                 'compaction_outbox_claim_leases_v3',
                 'compaction_outbox_active_claim_guard_v3'
               )",
        )
        .fetch_one(&mut **transaction)
        .await
        .map_err(sql_error)?;
        if required != 3 {
            return Err(corrupt("recovery schema is incomplete"));
        }
        transaction.commit().await.map_err(sql_error)
    }

    pub(crate) async fn reconcile_startup(
        &self,
        now_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionRecoveryStartupSummaryV1, CompactionCoordinatorErrorV2> {
        Ok(CompactionRecoveryStartupSummaryV1 {
            claims: self.reconcile_claims(now_unix_seconds, limit).await?,
            admissions: self.reconcile_admissions(now_unix_seconds, limit).await?,
        })
    }

    pub(crate) async fn claim_next_outbox(
        &self,
        now_unix_seconds: u64,
        worker_id: &str,
        claim_token: &str,
        claim_deadline_unix_seconds: u64,
    ) -> Result<Option<DurableCompactionOutboxClaimV2>, CompactionCoordinatorErrorV2> {
        validate_identity("outbox worker id", worker_id, 128)?;
        validate_identity("outbox claim token", claim_token, 256)?;
        let maximum_deadline = now_unix_seconds
            .checked_add(MAX_OUTBOX_CLAIM_SECONDS)
            .ok_or_else(|| invalid("outbox claim deadline overflow"))?;
        if claim_deadline_unix_seconds <= now_unix_seconds
            || claim_deadline_unix_seconds > maximum_deadline
        {
            return Err(invalid(
                "outbox claim deadline must be within the bounded claim window",
            ));
        }

        let context = self.fence_context(now_unix_seconds)?;
        let mut transaction = self.pool.begin().await.map_err(sql_error)?;
        verify_mutation_fence_tx(&mut transaction, &context).await?;
        let row = sqlx::query(
            "SELECT event_id, publication_digest, event_kind, payload, attempt_count
             FROM compaction_outbox
             WHERE owner_id = ? AND state = 'pending'
               AND next_attempt_at_unix_seconds <= ?
             ORDER BY created_at_unix_seconds, event_id
             LIMIT 1",
        )
        .bind(&self.owner_id)
        .bind(to_i64(now_unix_seconds, "outbox claim time")?)
        .fetch_optional(&mut **transaction)
        .await
        .map_err(sql_error)?;
        let Some(row) = row else {
            transaction.commit().await.map_err(sql_error)?;
            return Ok(None);
        };

        let event_id_text: String = row.try_get("event_id").map_err(sql_error)?;
        let attempt_count: i64 = row.try_get("attempt_count").map_err(sql_error)?;
        if attempt_count >= 1_000 {
            return Err(corrupt("outbox attempt count reached its durable ceiling"));
        }
        let changed = sqlx::query(
            "UPDATE compaction_outbox
             SET state = 'claimed', claim_token = ?,
                 attempt_count = attempt_count + 1,
                 next_attempt_at_unix_seconds = ?
             WHERE owner_id = ? AND event_id = ? AND state = 'pending'",
        )
        .bind(claim_token)
        .bind(to_i64(
            claim_deadline_unix_seconds,
            "outbox claim deadline",
        )?)
        .bind(&self.owner_id)
        .bind(&event_id_text)
        .execute(&mut **transaction)
        .await
        .map_err(sql_error)?
        .rows_affected();
        if changed != 1 {
            return Err(conflict("outbox claim lost its durable CAS"));
        }

        let token_digest = Digest32::of_bytes(claim_token.as_bytes());
        sqlx::query(
            "INSERT INTO compaction_outbox_claim_leases_v3
             (owner_id, event_id, worker_id, claim_token_digest, lease_epoch,
              claim_deadline_unix_seconds, claimed_at_unix_seconds,
              completed_at_unix_seconds, state)
             VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'claimed')
             ON CONFLICT(owner_id, event_id) DO UPDATE SET
               worker_id = excluded.worker_id,
               claim_token_digest = excluded.claim_token_digest,
               lease_epoch = excluded.lease_epoch,
               claim_deadline_unix_seconds = excluded.claim_deadline_unix_seconds,
               claimed_at_unix_seconds = excluded.claimed_at_unix_seconds,
               completed_at_unix_seconds = NULL,
               state = 'claimed'",
        )
        .bind(&self.owner_id)
        .bind(&event_id_text)
        .bind(worker_id)
        .bind(token_digest.to_string())
        .bind(to_i64(self.lease_epoch, "outbox claim lease epoch")?)
        .bind(to_i64(
            claim_deadline_unix_seconds,
            "outbox claim deadline",
        )?)
        .bind(to_i64(now_unix_seconds, "outbox claimed at")?)
        .execute(&mut **transaction)
        .await
        .map_err(sql_error)?;

        let event = DurableCompactionOutboxEventV1 {
            event_id: parse_digest(&event_id_text, "outbox event id")?,
            publication_digest: parse_digest(
                &row.try_get::<String, _>("publication_digest")
                    .map_err(sql_error)?,
                "outbox publication digest",
            )?,
            event_kind: row.try_get("event_kind").map_err(sql_error)?,
            payload: row.try_get("payload").map_err(sql_error)?,
            attempt_count: u32::try_from(attempt_count + 1)
                .map_err(|_| corrupt("outbox attempt count overflow"))?,
            claim_token: claim_token.to_string(),
        };
        transaction.commit().await.map_err(sql_error)?;
        Ok(Some(DurableCompactionOutboxClaimV2 {
            owner_id: self.owner_id.clone(),
            worker_id: worker_id.to_string(),
            claim_deadline_unix_seconds,
            lease_epoch: self.lease_epoch,
            event,
        }))
    }

    pub(crate) async fn complete_outbox_claim(
        &self,
        claim: &DurableCompactionOutboxClaimV2,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        if claim.owner_id != self.owner_id
            || claim.lease_epoch != self.lease_epoch
            || delivered_at_unix_seconds > claim.claim_deadline_unix_seconds
        {
            return Err(conflict(
                "outbox completion is bound to another owner generation or expired claim",
            ));
        }
        validate_identity("outbox worker id", &claim.worker_id, 128)?;
        validate_identity("outbox claim token", &claim.event.claim_token, 256)?;
        let context = self.fence_context(delivered_at_unix_seconds)?;
        let mut transaction = self.pool.begin().await.map_err(sql_error)?;
        verify_mutation_fence_tx(&mut transaction, &context).await?;

        let token_digest = Digest32::of_bytes(claim.event.claim_token.as_bytes());
        let lease_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM compaction_outbox_claim_leases_v3
             WHERE owner_id = ? AND event_id = ? AND worker_id = ?
               AND claim_token_digest = ? AND lease_epoch = ?
               AND claim_deadline_unix_seconds = ? AND state = 'claimed'",
        )
        .bind(&self.owner_id)
        .bind(claim.event.event_id.to_string())
        .bind(&claim.worker_id)
        .bind(token_digest.to_string())
        .bind(to_i64(self.lease_epoch, "outbox claim lease epoch")?)
        .bind(to_i64(
            claim.claim_deadline_unix_seconds,
            "outbox claim deadline",
        )?)
        .fetch_one(&mut **transaction)
        .await
        .map_err(sql_error)?;
        if lease_count != 1 {
            return Err(conflict("outbox completion lost its claim lease"));
        }

        let delivered = sqlx::query(
            "UPDATE compaction_outbox
             SET state = 'delivered', delivered_at_unix_seconds = ?,
                 claim_token = NULL
             WHERE owner_id = ? AND event_id = ? AND state = 'claimed'
               AND claim_token = ?",
        )
        .bind(to_i64(delivered_at_unix_seconds, "outbox delivery time")?)
        .bind(&self.owner_id)
        .bind(claim.event.event_id.to_string())
        .bind(&claim.event.claim_token)
        .execute(&mut **transaction)
        .await
        .map_err(sql_error)?
        .rows_affected();
        if delivered != 1 {
            return Err(conflict("outbox completion lost its durable claim CAS"));
        }

        let completed = sqlx::query(
            "UPDATE compaction_outbox_claim_leases_v3
             SET state = 'completed', completed_at_unix_seconds = ?
             WHERE owner_id = ? AND event_id = ? AND state = 'claimed'
               AND worker_id = ? AND claim_token_digest = ? AND lease_epoch = ?",
        )
        .bind(to_i64(delivered_at_unix_seconds, "outbox completion time")?)
        .bind(&self.owner_id)
        .bind(claim.event.event_id.to_string())
        .bind(&claim.worker_id)
        .bind(token_digest.to_string())
        .bind(to_i64(self.lease_epoch, "outbox claim lease epoch")?)
        .execute(&mut **transaction)
        .await
        .map_err(sql_error)?
        .rows_affected();
        if completed != 1 {
            return Err(corrupt("outbox claim lease did not complete exactly once"));
        }
        transaction.commit().await.map_err(sql_error)
    }

    pub(crate) async fn complete_legacy_outbox(
        &self,
        event: &DurableCompactionOutboxEventV1,
        delivered_at_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let token_digest = Digest32::of_bytes(event.claim_token.as_bytes());
        let row = sqlx::query(
            "SELECT worker_id, claim_deadline_unix_seconds, lease_epoch
             FROM compaction_outbox_claim_leases_v3
             WHERE owner_id = ? AND event_id = ? AND claim_token_digest = ?
               AND state = 'claimed'",
        )
        .bind(&self.owner_id)
        .bind(event.event_id.to_string())
        .bind(token_digest.to_string())
        .fetch_optional(&self.pool)
        .await
        .map_err(sql_error)?
        .ok_or_else(|| conflict("legacy outbox event has no current V3 claim lease"))?;
        let deadline: i64 = row
            .try_get("claim_deadline_unix_seconds")
            .map_err(sql_error)?;
        let epoch: i64 = row.try_get("lease_epoch").map_err(sql_error)?;
        let claim = DurableCompactionOutboxClaimV2 {
            owner_id: self.owner_id.clone(),
            worker_id: row.try_get("worker_id").map_err(sql_error)?,
            claim_deadline_unix_seconds: u64::try_from(deadline)
                .map_err(|_| corrupt("negative outbox claim deadline"))?,
            lease_epoch: u64::try_from(epoch)
                .map_err(|_| corrupt("negative outbox claim lease epoch"))?,
            event: event.clone(),
        };
        self.complete_outbox_claim(&claim, delivered_at_unix_seconds)
            .await
    }

    pub(crate) async fn reconcile_claims(
        &self,
        now_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionClaimReconciliationSummaryV1, CompactionCoordinatorErrorV2> {
        let limit = validate_limit(limit)?;
        let context = self.fence_context(now_unix_seconds)?;
        let mut transaction = self.pool.begin().await.map_err(sql_error)?;
        verify_mutation_fence_tx(&mut transaction, &context).await?;
        let rows = sqlx::query(
            "SELECT lease.event_id
             FROM compaction_outbox_claim_leases_v3 AS lease
             JOIN compaction_outbox AS outbox
               ON outbox.owner_id = lease.owner_id
              AND outbox.event_id = lease.event_id
             WHERE lease.owner_id = ? AND lease.state = 'claimed'
               AND outbox.state = 'claimed'
               AND (lease.claim_deadline_unix_seconds <= ? OR lease.lease_epoch != ?)
             ORDER BY lease.claim_deadline_unix_seconds, lease.event_id
             LIMIT ?",
        )
        .bind(&self.owner_id)
        .bind(to_i64(now_unix_seconds, "claim reconciliation time")?)
        .bind(to_i64(self.lease_epoch, "claim reconciliation epoch")?)
        .bind(i64::from(limit))
        .fetch_all(&mut **transaction)
        .await
        .map_err(sql_error)?;

        let mut summary = CompactionClaimReconciliationSummaryV1 {
            inspected: u64::try_from(rows.len()).unwrap_or(u64::MAX),
            ..CompactionClaimReconciliationSummaryV1::default()
        };
        for row in rows {
            let event_id: String = row.try_get("event_id").map_err(sql_error)?;
            let abandoned = sqlx::query(
                "UPDATE compaction_outbox_claim_leases_v3
                 SET state = 'abandoned', completed_at_unix_seconds = ?
                 WHERE owner_id = ? AND event_id = ? AND state = 'claimed'",
            )
            .bind(to_i64(now_unix_seconds, "claim abandonment time")?)
            .bind(&self.owner_id)
            .bind(&event_id)
            .execute(&mut **transaction)
            .await
            .map_err(sql_error)?
            .rows_affected();
            if abandoned != 1 {
                return Err(conflict("claim reconciliation lost its lease CAS"));
            }
            let requeued = sqlx::query(
                "UPDATE compaction_outbox
                 SET state = 'pending', claim_token = NULL,
                     next_attempt_at_unix_seconds = ?
                 WHERE owner_id = ? AND event_id = ? AND state = 'claimed'",
            )
            .bind(to_i64(now_unix_seconds, "claim retry time")?)
            .bind(&self.owner_id)
            .bind(&event_id)
            .execute(&mut **transaction)
            .await
            .map_err(sql_error)?
            .rows_affected();
            if requeued != 1 {
                return Err(conflict("claim reconciliation lost its outbox CAS"));
            }
            summary.requeued = summary.requeued.saturating_add(1);
        }

        let orphan_count: i64 = sqlx::query_scalar(
            "SELECT COUNT(*)
             FROM compaction_outbox AS outbox
             LEFT JOIN compaction_outbox_claim_leases_v3 AS lease
               ON lease.owner_id = outbox.owner_id
              AND lease.event_id = outbox.event_id
              AND lease.state = 'claimed'
             WHERE outbox.owner_id = ? AND outbox.state = 'claimed'
               AND lease.event_id IS NULL",
        )
        .bind(&self.owner_id)
        .fetch_one(&mut **transaction)
        .await
        .map_err(sql_error)?;
        summary.quarantined_orphans = u64::try_from(orphan_count)
            .map_err(|_| corrupt("negative orphaned outbox claim count"))?;
        transaction.commit().await.map_err(sql_error)?;
        Ok(summary)
    }

    pub(crate) async fn reconcile_admissions(
        &self,
        now_unix_seconds: u64,
        limit: u32,
    ) -> Result<CompactionAdmissionReconciliationSummaryV1, CompactionCoordinatorErrorV2> {
        let limit = validate_limit(limit)?;
        let context = self.fence_context(now_unix_seconds)?;
        let mut transaction = self.pool.begin().await.map_err(sql_error)?;
        verify_mutation_fence_tx(&mut transaction, &context).await?;
        let rows = sqlx::query(
            "SELECT admission.idempotency_key,
                    admission.checkpoint_digest,
                    admission.publication_digest AS admission_publication_digest,
                    admission.state AS admission_state,
                    checkpoint.publication_digest AS checkpoint_publication_digest
             FROM compaction_publication_admissions_v2 AS admission
             LEFT JOIN compaction_checkpoints AS checkpoint
               ON checkpoint.owner_id = admission.owner_id
              AND checkpoint.checkpoint_digest = admission.checkpoint_digest
             LEFT JOIN compaction_admission_recovery_v3 AS recovery
               ON recovery.owner_id = admission.owner_id
              AND recovery.idempotency_key = admission.idempotency_key
             WHERE admission.owner_id = ?
               AND (
                   admission.state = 'reserved'
                   OR recovery.recovery_state IS NULL
                   OR recovery.recovery_state != 'committed'
               )
             ORDER BY admission.reserved_at_unix_seconds,
                      admission.idempotency_key
             LIMIT ?",
        )
        .bind(&self.owner_id)
        .bind(i64::from(limit))
        .fetch_all(&mut **transaction)
        .await
        .map_err(sql_error)?;

        let mut summary = CompactionAdmissionReconciliationSummaryV1 {
            inspected: u64::try_from(rows.len()).unwrap_or(u64::MAX),
            ..CompactionAdmissionReconciliationSummaryV1::default()
        };
        for row in rows {
            let key: String = row.try_get("idempotency_key").map_err(sql_error)?;
            let checkpoint_text: String =
                row.try_get("checkpoint_digest").map_err(sql_error)?;
            let checkpoint_digest = parse_digest(&checkpoint_text, "admission checkpoint")?;
            let admission_publication: Option<String> = row
                .try_get("admission_publication_digest")
                .map_err(sql_error)?;
            let checkpoint_publication: Option<String> = row
                .try_get("checkpoint_publication_digest")
                .map_err(sql_error)?;
            let admission_state: String = row.try_get("admission_state").map_err(sql_error)?;

            let (recovery_state, observed_publication) = match (
                admission_state.as_str(),
                admission_publication.as_deref(),
                checkpoint_publication.as_deref(),
            ) {
                ("reserved", _, None) => {
                    summary.no_artifact = summary.no_artifact.saturating_add(1);
                    (CompactionAdmissionRecoveryStateV1::NoArtifact, None)
                }
                ("reserved", None, Some(publication)) => {
                    summary.committed_unfinalized =
                        summary.committed_unfinalized.saturating_add(1);
                    let changed = sqlx::query(
                        "UPDATE compaction_publication_admissions_v2
                         SET publication_digest = ?, state = 'committed',
                             committed_at_unix_seconds = COALESCE(
                                 committed_at_unix_seconds, ?
                             )
                         WHERE owner_id = ? AND idempotency_key = ?
                           AND state = 'reserved' AND publication_digest IS NULL",
                    )
                    .bind(publication)
                    .bind(to_i64(now_unix_seconds, "admission recovery time")?)
                    .bind(&self.owner_id)
                    .bind(&key)
                    .execute(&mut **transaction)
                    .await
                    .map_err(sql_error)?
                    .rows_affected();
                    if changed != 1 {
                        return Err(conflict("admission finalization lost its durable CAS"));
                    }
                    (
                        CompactionAdmissionRecoveryStateV1::Committed,
                        Some(publication.to_string()),
                    )
                }
                ("reserved", Some(admission), Some(checkpoint)) if admission == checkpoint => {
                    summary.committed_unfinalized =
                        summary.committed_unfinalized.saturating_add(1);
                    let changed = sqlx::query(
                        "UPDATE compaction_publication_admissions_v2
                         SET state = 'committed',
                             committed_at_unix_seconds = COALESCE(
                                 committed_at_unix_seconds, ?
                             )
                         WHERE owner_id = ? AND idempotency_key = ?
                           AND state = 'reserved' AND publication_digest = ?",
                    )
                    .bind(to_i64(now_unix_seconds, "admission recovery time")?)
                    .bind(&self.owner_id)
                    .bind(&key)
                    .bind(admission)
                    .execute(&mut **transaction)
                    .await
                    .map_err(sql_error)?
                    .rows_affected();
                    if changed != 1 {
                        return Err(conflict("admission finalization lost its durable CAS"));
                    }
                    (
                        CompactionAdmissionRecoveryStateV1::Committed,
                        Some(checkpoint.to_string()),
                    )
                }
                ("reserved", Some(_), Some(_)) => {
                    summary.quarantined = summary.quarantined.saturating_add(1);
                    (
                        CompactionAdmissionRecoveryStateV1::Quarantined,
                        checkpoint_publication.clone(),
                    )
                }
                ("committed", Some(admission), Some(checkpoint)) if admission == checkpoint => (
                    CompactionAdmissionRecoveryStateV1::Committed,
                    Some(checkpoint.to_string()),
                ),
                ("committed", _, None) => {
                    summary.terminal_failure = summary.terminal_failure.saturating_add(1);
                    (
                        CompactionAdmissionRecoveryStateV1::TerminalFailure,
                        admission_publication.clone(),
                    )
                }
                ("committed", _, Some(_)) => {
                    summary.quarantined = summary.quarantined.saturating_add(1);
                    (
                        CompactionAdmissionRecoveryStateV1::Quarantined,
                        checkpoint_publication.clone(),
                    )
                }
                _ => {
                    summary.indeterminate = summary.indeterminate.saturating_add(1);
                    (
                        CompactionAdmissionRecoveryStateV1::Indeterminate,
                        checkpoint_publication.or(admission_publication),
                    )
                }
            };

            record_admission_state_tx(
                &mut transaction,
                &self.owner_id,
                &key,
                checkpoint_digest,
                recovery_state,
                observed_publication.as_deref(),
                now_unix_seconds,
            )
            .await?;
        }
        transaction.commit().await.map_err(sql_error)?;
        Ok(summary)
    }

    pub(crate) async fn query_operation(
        &self,
        idempotency_key: &str,
    ) -> Result<CompactionOperationStatusV1, CompactionCoordinatorErrorV2> {
        validate_identity("operation idempotency key", idempotency_key, 128)?;
        let row = sqlx::query(
            "SELECT admission.checkpoint_digest,
                    admission.publication_digest AS admission_publication_digest,
                    admission.state AS admission_state,
                    checkpoint.publication_digest AS checkpoint_publication_digest,
                    recovery.recovery_state
             FROM compaction_publication_admissions_v2 AS admission
             LEFT JOIN compaction_checkpoints AS checkpoint
               ON checkpoint.owner_id = admission.owner_id
              AND checkpoint.checkpoint_digest = admission.checkpoint_digest
             LEFT JOIN compaction_admission_recovery_v3 AS recovery
               ON recovery.owner_id = admission.owner_id
              AND recovery.idempotency_key = admission.idempotency_key
             WHERE admission.owner_id = ? AND admission.idempotency_key = ?",
        )
        .bind(&self.owner_id)
        .bind(idempotency_key)
        .fetch_optional(&self.pool)
        .await
        .map_err(sql_error)?;
        let Some(row) = row else {
            return Ok(CompactionOperationStatusV1::Absent);
        };
        let checkpoint_text: String = row.try_get("checkpoint_digest").map_err(sql_error)?;
        let checkpoint_digest = parse_digest(&checkpoint_text, "operation checkpoint")?;
        let admission_publication: Option<String> = row
            .try_get("admission_publication_digest")
            .map_err(sql_error)?;
        let checkpoint_publication: Option<String> = row
            .try_get("checkpoint_publication_digest")
            .map_err(sql_error)?;
        let admission_state: String = row.try_get("admission_state").map_err(sql_error)?;
        let recovery_state: Option<String> =
            row.try_get("recovery_state").map_err(sql_error)?;

        if admission_state == "committed" {
            if let (Some(admission), Some(checkpoint)) =
                (admission_publication.as_deref(), checkpoint_publication.as_deref())
            {
                if admission == checkpoint {
                    return Ok(CompactionOperationStatusV1::Committed {
                        checkpoint_digest,
                        publication_digest: parse_digest(checkpoint, "operation publication")?,
                    });
                }
            }
        }

        let state = recovery_state
            .as_deref()
            .map(CompactionAdmissionRecoveryStateV1::parse)
            .transpose()?;
        match state {
            Some(CompactionAdmissionRecoveryStateV1::NoArtifact) => {
                Ok(CompactionOperationStatusV1::NoArtifact { checkpoint_digest })
            }
            Some(CompactionAdmissionRecoveryStateV1::CommittedUnfinalized) => {
                let publication = checkpoint_publication
                    .as_deref()
                    .or(admission_publication.as_deref())
                    .ok_or_else(|| corrupt("committed-unfinalized operation lacks digest"))?;
                Ok(CompactionOperationStatusV1::CommittedUnfinalized {
                    checkpoint_digest,
                    publication_digest: parse_digest(publication, "operation publication")?,
                })
            }
            Some(CompactionAdmissionRecoveryStateV1::Committed) => {
                let publication = checkpoint_publication
                    .as_deref()
                    .or(admission_publication.as_deref())
                    .ok_or_else(|| corrupt("committed operation lacks digest"))?;
                Ok(CompactionOperationStatusV1::Committed {
                    checkpoint_digest,
                    publication_digest: parse_digest(publication, "operation publication")?,
                })
            }
            Some(CompactionAdmissionRecoveryStateV1::Indeterminate) => {
                Ok(CompactionOperationStatusV1::Indeterminate { checkpoint_digest })
            }
            Some(CompactionAdmissionRecoveryStateV1::TerminalFailure) => {
                Ok(CompactionOperationStatusV1::TerminalFailure { checkpoint_digest })
            }
            Some(CompactionAdmissionRecoveryStateV1::Quarantined) => {
                Ok(CompactionOperationStatusV1::Quarantined { checkpoint_digest })
            }
            None if admission_state == "reserved" && checkpoint_publication.is_none() => {
                Ok(CompactionOperationStatusV1::Reserved { checkpoint_digest })
            }
            None => Ok(CompactionOperationStatusV1::Indeterminate { checkpoint_digest }),
        }
    }
}

async fn verify_mutation_fence_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    context: &MutationFenceContextV1,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM compaction_owner_fence_v2 AS fence
         JOIN active_compaction_manifest_v2 AS active
           ON active.owner_id = fence.owner_id
         JOIN compaction_manifest_log_v2 AS manifest
           ON manifest.owner_id = active.owner_id
          AND manifest.manifest_digest = active.manifest_digest
         WHERE fence.owner_id = ?
           AND fence.root_key_digest = ?
           AND fence.lease_token_digest = ?
           AND fence.lease_epoch = ?
           AND fence.lease_expires_at_unix_seconds > ?
           AND active.manifest_digest = ?
           AND manifest.root_key_digest = ?",
    )
    .bind(context.owner_id())
    .bind(context.root_key_digest().to_string())
    .bind(context.lease_token_digest().to_string())
    .bind(to_i64(context.lease_epoch(), "mutation lease epoch")?)
    .bind(to_i64(
        context.execution_now_unix_seconds(),
        "mutation execution time",
    )?)
    .bind(context.manifest_digest().to_string())
    .bind(context.root_key_digest().to_string())
    .fetch_one(&mut **transaction)
    .await
    .map_err(sql_error)?;
    if count != 1 {
        return Err(conflict(
            "mutation lost its owner/root/manifest/lease fence",
        ));
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
async fn record_admission_state_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    owner_id: &str,
    idempotency_key: &str,
    checkpoint_digest: Digest32,
    state: CompactionAdmissionRecoveryStateV1,
    observed_publication_digest: Option<&str>,
    observed_at_unix_seconds: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let detail = format!(
        "{}\0{}\0{}\0{}\0{}",
        owner_id,
        idempotency_key,
        checkpoint_digest,
        state.label(),
        observed_publication_digest.unwrap_or("")
    );
    let detail_digest = Digest32::of_bytes(detail.as_bytes());
    sqlx::query(
        "INSERT INTO compaction_admission_recovery_v3
         (owner_id, idempotency_key, checkpoint_digest, recovery_state,
          observed_publication_digest, detail_digest, observation_revision,
          observed_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, 1, ?)
         ON CONFLICT(owner_id, idempotency_key) DO UPDATE SET
           recovery_state = excluded.recovery_state,
           observed_publication_digest = excluded.observed_publication_digest,
           detail_digest = excluded.detail_digest,
           observation_revision =
             compaction_admission_recovery_v3.observation_revision + 1,
           observed_at_unix_seconds = excluded.observed_at_unix_seconds",
    )
    .bind(owner_id)
    .bind(idempotency_key)
    .bind(checkpoint_digest.to_string())
    .bind(state.label())
    .bind(observed_publication_digest)
    .bind(detail_digest.to_string())
    .bind(to_i64(
        observed_at_unix_seconds,
        "admission observation time",
    )?)
    .execute(&mut **transaction)
    .await
    .map_err(sql_error)?;
    Ok(())
}

fn validate_limit(limit: u32) -> Result<u32, CompactionCoordinatorErrorV2> {
    if limit == 0 || limit > MAX_RECOVERY_BATCH {
        return Err(invalid("recovery batch must contain 1..=1000 rows"));
    }
    Ok(limit)
}

fn validate_identity(
    field: &'static str,
    value: &str,
    maximum_bytes: usize,
) -> Result<(), CompactionCoordinatorErrorV2> {
    if value.trim().is_empty() || value.len() > maximum_bytes {
        return Err(invalid(format!(
            "{field} must contain 1..={maximum_bytes} bytes"
        )));
    }
    Ok(())
}

fn parse_digest(
    value: &str,
    field: &'static str,
) -> Result<Digest32, CompactionCoordinatorErrorV2> {
    Digest32::from_str(value).map_err(|_| corrupt(format!("{field} is not a digest")))
}

fn to_i64(value: u64, field: &'static str) -> Result<i64, CompactionCoordinatorErrorV2> {
    i64::try_from(value).map_err(|_| invalid(format!("{field} exceeds SQLite integer range")))
}

fn sql_error(error: sqlx::Error) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Sql(error))
}

fn invalid(message: impl Into<String>) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Invalid(message.into()))
}

fn conflict(message: impl Into<String>) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Conflict(message.into()))
}

fn corrupt(message: impl Into<String>) -> CompactionCoordinatorErrorV2 {
    CompactionCoordinatorErrorV2::Durable(DurableCompactionError::Corrupt(message.into()))
}
