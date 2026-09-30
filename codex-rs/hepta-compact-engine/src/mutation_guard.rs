//! Database-enforced mutation intents for the existing durable compaction owner.
//!
//! This is not a second artifact store or owner. It installs guards over the
//! existing tables so every publication/revocation/retention mutation is bound
//! to one exact owner, root, manifest, lease generation and operation identity
//! at the point SQLite performs the write.

use std::str::FromStr;

use codex_hepta_types::Digest32;
use sqlx::sqlite::{
    SqliteConnectOptions, SqliteJournalMode, SqlitePoolOptions, SqliteSynchronous,
};
use sqlx::{Acquire, Executor, Row, Sqlite, SqlitePool, Transaction};

use crate::coordinator::CompactionCoordinatorErrorV2;
use crate::durable::DurableCompactionError;
use crate::{
    CompactionTrustRoleV1, VerifiedCompactionPublicationV1,
};

const REVOKE_OPERATION_DOMAIN: &[u8] = b"hepta.compaction.revoke-operation.v1\0";
const RELEASE_OPERATION_DOMAIN: &[u8] = b"hepta.compaction.release-operation.v1\0";
const RELEASE_AUXILIARY_DOMAIN: &[u8] = b"hepta.compaction.release-auxiliary.v1\0";

const MUTATION_GUARD_SCHEMA: &str = r#"
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS compaction_mutation_fences_v3 (
    owner_id TEXT NOT NULL CHECK (length(trim(owner_id)) BETWEEN 1 AND 128),
    operation_id TEXT NOT NULL CHECK (length(trim(operation_id)) BETWEEN 1 AND 256),
    operation_kind TEXT NOT NULL CHECK (
        operation_kind IN ('publish-checkpoint', 'revoke-checkpoint', 'release-retention')
    ),
    target_digest TEXT NOT NULL CHECK (length(target_digest) = 64),
    auxiliary_digest TEXT NOT NULL CHECK (length(auxiliary_digest) = 64),
    root_key_digest TEXT NOT NULL CHECK (length(root_key_digest) = 64),
    manifest_digest TEXT NOT NULL CHECK (length(manifest_digest) = 64),
    lease_token_digest TEXT NOT NULL CHECK (length(lease_token_digest) = 64),
    lease_epoch INTEGER NOT NULL CHECK (lease_epoch > 0),
    execution_now_unix_seconds INTEGER NOT NULL CHECK (execution_now_unix_seconds >= 0),
    guard_revision INTEGER NOT NULL CHECK (guard_revision > 0),
    state TEXT NOT NULL CHECK (state IN ('prepared', 'committed', 'quarantined')),
    committed_at_unix_seconds INTEGER,
    PRIMARY KEY (owner_id, operation_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS compaction_publication_mutations_v3 (
    owner_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 128),
    request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
    archive_digest TEXT NOT NULL CHECK (length(archive_digest) = 64),
    scope_id TEXT NOT NULL,
    purpose_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
    candidate_digest TEXT NOT NULL CHECK (length(candidate_digest) = 64),
    evaluation_digest TEXT NOT NULL CHECK (length(evaluation_digest) = 64),
    proof_digest TEXT NOT NULL CHECK (length(proof_digest) = 64),
    checkpoint_digest TEXT NOT NULL CHECK (length(checkpoint_digest) = 64),
    selector_key_id TEXT NOT NULL,
    selector_trust_epoch INTEGER NOT NULL CHECK (selector_trust_epoch > 0),
    generator_key_id TEXT NOT NULL,
    generator_trust_epoch INTEGER NOT NULL CHECK (generator_trust_epoch > 0),
    tokenizer_key_id TEXT NOT NULL,
    tokenizer_trust_epoch INTEGER NOT NULL CHECK (tokenizer_trust_epoch > 0),
    evaluator_key_id TEXT NOT NULL,
    evaluator_trust_epoch INTEGER NOT NULL CHECK (evaluator_trust_epoch > 0),
    retain_source_until_unix_seconds INTEGER NOT NULL CHECK (
        retain_source_until_unix_seconds >= 0
    ),
    PRIMARY KEY (owner_id, idempotency_key),
    FOREIGN KEY (owner_id, idempotency_key)
      REFERENCES compaction_mutation_fences_v3(owner_id, operation_id)
      ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE VIEW IF NOT EXISTS current_compaction_mutation_fences_v3 AS
SELECT mutation.owner_id,
       mutation.operation_id,
       mutation.operation_kind,
       mutation.target_digest,
       mutation.auxiliary_digest,
       mutation.root_key_digest,
       mutation.manifest_digest,
       mutation.lease_token_digest,
       mutation.lease_epoch,
       mutation.execution_now_unix_seconds,
       mutation.guard_revision,
       mutation.state
  FROM compaction_mutation_fences_v3 AS mutation
  JOIN compaction_owner_fence_v2 AS owner
    ON owner.owner_id = mutation.owner_id
   AND owner.root_key_digest = mutation.root_key_digest
   AND owner.lease_token_digest = mutation.lease_token_digest
   AND owner.lease_epoch = mutation.lease_epoch
  JOIN active_compaction_manifest_v2 AS active
    ON active.owner_id = mutation.owner_id
   AND active.manifest_digest = mutation.manifest_digest
 WHERE mutation.state IN ('prepared', 'committed')
   AND owner.lease_expires_at_unix_seconds > CAST(strftime('%s', 'now') AS INTEGER);

CREATE TRIGGER IF NOT EXISTS compaction_mutation_fence_identity_v3
BEFORE UPDATE ON compaction_mutation_fences_v3
WHEN NEW.owner_id != OLD.owner_id
 OR NEW.operation_id != OLD.operation_id
 OR NEW.operation_kind != OLD.operation_kind
 OR NEW.target_digest != OLD.target_digest
 OR NEW.auxiliary_digest != OLD.auxiliary_digest
 OR NEW.root_key_digest != OLD.root_key_digest
 OR NEW.manifest_digest != OLD.manifest_digest
 OR NEW.guard_revision <= OLD.guard_revision
 OR (OLD.state = 'committed' AND NEW.state != 'committed')
 OR (OLD.state = 'quarantined' AND NEW.state != 'quarantined')
BEGIN
    SELECT RAISE(ABORT, 'compaction mutation identity or revision drift');
END;

CREATE TRIGGER IF NOT EXISTS compaction_mutation_fence_no_delete_v3
BEFORE DELETE ON compaction_mutation_fences_v3 BEGIN
    SELECT RAISE(ABORT, 'compaction mutation fences are append-only');
END;

CREATE TRIGGER IF NOT EXISTS compaction_publication_mutation_no_update_v3
BEFORE UPDATE ON compaction_publication_mutations_v3 BEGIN
    SELECT RAISE(ABORT, 'compaction publication mutation identity is immutable');
END;

CREATE TRIGGER IF NOT EXISTS compaction_publication_mutation_no_delete_v3
BEFORE DELETE ON compaction_publication_mutations_v3 BEGIN
    SELECT RAISE(ABORT, 'compaction publication mutations are append-only');
END;

CREATE TRIGGER IF NOT EXISTS compaction_admission_insert_guard_v3
BEFORE INSERT ON compaction_publication_admissions_v2
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.idempotency_key = NEW.idempotency_key
       AND publication.request_digest = NEW.request_digest
       AND publication.archive_digest = NEW.archive_digest
       AND publication.checkpoint_digest = NEW.checkpoint_digest
       AND publication.retain_source_until_unix_seconds = NEW.retain_source_until_unix_seconds
       AND guard.root_key_digest = NEW.root_key_digest
       AND guard.manifest_digest = NEW.manifest_digest
)
BEGIN
    SELECT RAISE(ABORT, 'publication admission lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_admission_commit_guard_v3
BEFORE UPDATE OF publication_digest, state ON compaction_publication_admissions_v2
WHEN OLD.state = 'reserved' AND NEW.state = 'committed'
 AND NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.idempotency_key = NEW.idempotency_key
       AND publication.checkpoint_digest = NEW.checkpoint_digest
)
BEGIN
    SELECT RAISE(ABORT, 'publication finalization lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_admission_release_guard_v3
BEFORE UPDATE OF released_at_unix_seconds ON compaction_publication_admissions_v2
WHEN OLD.released_at_unix_seconds IS NULL
 AND NEW.released_at_unix_seconds IS NOT NULL
 AND NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'release-retention'
       AND guard.target_digest = NEW.checkpoint_digest
)
BEGIN
    SELECT RAISE(ABORT, 'source retention release lacks a live mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_trust_insert_guard_v3
BEFORE INSERT ON compaction_trust_registry
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND (
            (NEW.role = 'retention-selector'
             AND publication.selector_key_id = NEW.key_id
             AND publication.selector_trust_epoch = NEW.trust_epoch)
         OR (NEW.role = 'semantic-generator'
             AND publication.generator_key_id = NEW.key_id
             AND publication.generator_trust_epoch = NEW.trust_epoch)
         OR (NEW.role = 'tokenizer'
             AND publication.tokenizer_key_id = NEW.key_id
             AND publication.tokenizer_trust_epoch = NEW.trust_epoch)
         OR (NEW.role = 'evaluator'
             AND publication.evaluator_key_id = NEW.key_id
             AND publication.evaluator_trust_epoch = NEW.trust_epoch)
       )
)
BEGIN
    SELECT RAISE(ABORT, 'trust enrollment lacks a live publication mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_payload_insert_guard_v3
BEFORE INSERT ON compaction_payloads
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.payload_digest = NEW.payload_digest
)
BEGIN
    SELECT RAISE(ABORT, 'payload write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_candidate_insert_guard_v3
BEFORE INSERT ON compaction_candidates
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.idempotency_key = NEW.idempotency_key
       AND publication.scope_id = NEW.scope_id
       AND publication.purpose_id = NEW.purpose_id
       AND publication.generation = NEW.generation
       AND publication.candidate_digest = NEW.candidate_digest
       AND publication.payload_digest = NEW.payload_digest
)
BEGIN
    SELECT RAISE(ABORT, 'candidate write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_evaluation_insert_guard_v3
BEFORE INSERT ON compaction_evaluations
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.evaluation_digest = NEW.evaluation_digest
       AND publication.candidate_digest = NEW.candidate_digest
       AND publication.evaluator_key_id = NEW.evaluator_key_id
       AND publication.evaluator_trust_epoch = NEW.evaluator_trust_epoch
)
BEGIN
    SELECT RAISE(ABORT, 'evaluation write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_proof_insert_guard_v3
BEFORE INSERT ON compaction_proofs
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.proof_digest = NEW.proof_digest
       AND publication.candidate_digest = NEW.candidate_digest
       AND publication.checkpoint_digest = NEW.checkpoint_digest
       AND publication.evaluation_digest = NEW.evaluation_digest
)
BEGIN
    SELECT RAISE(ABORT, 'proof write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_checkpoint_insert_guard_v3
BEFORE INSERT ON compaction_checkpoints
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.scope_id = NEW.scope_id
       AND publication.purpose_id = NEW.purpose_id
       AND publication.generation = NEW.generation
       AND publication.checkpoint_digest = NEW.checkpoint_digest
       AND publication.candidate_digest = NEW.candidate_digest
       AND publication.payload_digest = NEW.payload_digest
       AND publication.proof_digest = NEW.proof_digest
)
BEGIN
    SELECT RAISE(ABORT, 'checkpoint write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS active_compaction_checkpoint_insert_guard_v3
BEFORE INSERT ON active_compaction_checkpoint
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.scope_id = NEW.scope_id
       AND publication.purpose_id = NEW.purpose_id
       AND publication.generation = NEW.generation
       AND publication.checkpoint_digest = NEW.checkpoint_digest
)
BEGIN
    SELECT RAISE(ABORT, 'active checkpoint insert lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS active_compaction_checkpoint_update_guard_v3
BEFORE UPDATE ON active_compaction_checkpoint
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND publication.scope_id = NEW.scope_id
       AND publication.purpose_id = NEW.purpose_id
       AND publication.generation = NEW.generation
       AND publication.checkpoint_digest = NEW.checkpoint_digest
)
BEGIN
    SELECT RAISE(ABORT, 'active checkpoint update lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_published_outbox_insert_guard_v3
BEFORE INSERT ON compaction_outbox
WHEN NEW.event_kind = 'checkpoint-published'
 AND NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_publication_mutations_v3 AS publication
        ON publication.owner_id = guard.owner_id
       AND publication.idempotency_key = guard.operation_id
      JOIN compaction_checkpoints AS checkpoint
        ON checkpoint.owner_id = publication.owner_id
       AND checkpoint.checkpoint_digest = publication.checkpoint_digest
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'publish-checkpoint'
       AND checkpoint.publication_digest = NEW.publication_digest
)
BEGIN
    SELECT RAISE(ABORT, 'publication outbox write lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_revocation_insert_guard_v3
BEFORE INSERT ON compaction_checkpoint_revocations
WHEN NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'revoke-checkpoint'
       AND guard.target_digest = NEW.checkpoint_digest
       AND guard.auxiliary_digest = NEW.reason_digest
)
BEGIN
    SELECT RAISE(ABORT, 'checkpoint revocation lacks a live exact mutation fence');
END;

CREATE TRIGGER IF NOT EXISTS compaction_revocation_outbox_insert_guard_v3
BEFORE INSERT ON compaction_outbox
WHEN NEW.event_kind = 'checkpoint-revoked'
 AND NOT EXISTS (
    SELECT 1
      FROM current_compaction_mutation_fences_v3 AS guard
      JOIN compaction_checkpoints AS checkpoint
        ON checkpoint.owner_id = guard.owner_id
       AND checkpoint.checkpoint_digest = guard.target_digest
      JOIN compaction_checkpoint_revocations AS revocation
        ON revocation.owner_id = checkpoint.owner_id
       AND revocation.checkpoint_digest = checkpoint.checkpoint_digest
       AND revocation.reason_digest = guard.auxiliary_digest
     WHERE guard.owner_id = NEW.owner_id
       AND guard.operation_kind = 'revoke-checkpoint'
       AND checkpoint.publication_digest = NEW.publication_digest
)
BEGIN
    SELECT RAISE(ABORT, 'revocation outbox write lacks a live exact mutation fence');
END;
"#;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct MutationIntentV1 {
    operation_id: String,
}

impl MutationIntentV1 {
    fn new(operation_id: String) -> Self {
        Self { operation_id }
    }
}

#[derive(Clone)]
pub(crate) struct MutationGuardStoreV1 {
    pool: SqlitePool,
    owner_id: String,
    root_key_digest: Digest32,
    manifest_digest: Digest32,
    lease_token_digest: Digest32,
    lease_epoch: u64,
}

impl MutationGuardStoreV1 {
    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn open(
        database_url: &str,
        owner_id: &str,
        root_key_digest: Digest32,
        manifest_digest: Digest32,
        lease_token_digest: Digest32,
        lease_epoch: u64,
    ) -> Result<Self, CompactionCoordinatorErrorV2> {
        if owner_id.trim().is_empty() || owner_id.len() > 128 || lease_epoch == 0 {
            return Err(invalid("invalid mutation guard owner or lease epoch"));
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
        sqlx::raw_sql(MUTATION_GUARD_SCHEMA)
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

    pub(crate) async fn prepare_publication(
        &self,
        idempotency_key: &str,
        publication: &VerifiedCompactionPublicationV1,
        retain_source_until_unix_seconds: u64,
        now_unix_seconds: u64,
    ) -> Result<MutationIntentV1, CompactionCoordinatorErrorV2> {
        if idempotency_key.trim().is_empty() || idempotency_key.len() > 128 {
            return Err(invalid("publication idempotency key must contain 1..=128 bytes"));
        }
        let candidate = publication.candidate();
        let checkpoint = candidate.checkpoint();
        let selector = binding(publication, CompactionTrustRoleV1::RetentionSelector)?;
        let generator = binding(publication, CompactionTrustRoleV1::SemanticGenerator)?;
        let tokenizer = binding(publication, CompactionTrustRoleV1::Tokenizer)?;
        let evaluator = binding(publication, CompactionTrustRoleV1::Evaluator)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sql_error)?;
        verify_fence_tx(&mut transaction, self, now_unix_seconds).await?;
        upsert_guard_tx(
            &mut transaction,
            self,
            idempotency_key,
            "publish-checkpoint",
            checkpoint.checkpoint_digest,
            publication.request_digest(),
            now_unix_seconds,
        )
        .await?;
        sqlx::query(
            "INSERT OR IGNORE INTO compaction_publication_mutations_v3
             (owner_id, idempotency_key, request_digest, archive_digest,
              scope_id, purpose_id, generation, payload_digest,
              candidate_digest, evaluation_digest, proof_digest,
              checkpoint_digest, selector_key_id, selector_trust_epoch,
              generator_key_id, generator_trust_epoch, tokenizer_key_id,
              tokenizer_trust_epoch, evaluator_key_id, evaluator_trust_epoch,
              retain_source_until_unix_seconds)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(&self.owner_id)
        .bind(idempotency_key)
        .bind(publication.request_digest().to_string())
        .bind(publication.archive_digest().to_string())
        .bind(checkpoint.source_snapshot.vector.scope_id.as_str())
        .bind(checkpoint.source_snapshot.vector.purpose_id.as_str())
        .bind(to_i64(checkpoint.generation.get(), "checkpoint generation")?)
        .bind(checkpoint.payload_digest.to_string())
        .bind(candidate.candidate_digest().to_string())
        .bind(publication.proof().evaluation_receipt_digest.to_string())
        .bind(publication.proof().proof.proof_digest.to_string())
        .bind(checkpoint.checkpoint_digest.to_string())
        .bind(selector.0)
        .bind(to_i64(selector.1, "selector trust epoch")?)
        .bind(generator.0)
        .bind(to_i64(generator.1, "generator trust epoch")?)
        .bind(tokenizer.0)
        .bind(to_i64(tokenizer.1, "tokenizer trust epoch")?)
        .bind(evaluator.0)
        .bind(to_i64(evaluator.1, "evaluator trust epoch")?)
        .bind(to_i64(
            retain_source_until_unix_seconds,
            "source retention deadline",
        )?)
        .execute(&mut *transaction)
        .await
        .map_err(sql_error)?;
        let exact: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM compaction_publication_mutations_v3
             WHERE owner_id = ? AND idempotency_key = ?
               AND request_digest = ? AND archive_digest = ?
               AND scope_id = ? AND purpose_id = ? AND generation = ?
               AND payload_digest = ? AND candidate_digest = ?
               AND evaluation_digest = ? AND proof_digest = ?
               AND checkpoint_digest = ?
               AND selector_key_id = ? AND selector_trust_epoch = ?
               AND generator_key_id = ? AND generator_trust_epoch = ?
               AND tokenizer_key_id = ? AND tokenizer_trust_epoch = ?
               AND evaluator_key_id = ? AND evaluator_trust_epoch = ?
               AND retain_source_until_unix_seconds = ?",
        )
        .bind(&self.owner_id)
        .bind(idempotency_key)
        .bind(publication.request_digest().to_string())
        .bind(publication.archive_digest().to_string())
        .bind(checkpoint.source_snapshot.vector.scope_id.as_str())
        .bind(checkpoint.source_snapshot.vector.purpose_id.as_str())
        .bind(to_i64(checkpoint.generation.get(), "checkpoint generation")?)
        .bind(checkpoint.payload_digest.to_string())
        .bind(candidate.candidate_digest().to_string())
        .bind(publication.proof().evaluation_receipt_digest.to_string())
        .bind(publication.proof().proof.proof_digest.to_string())
        .bind(checkpoint.checkpoint_digest.to_string())
        .bind(selector.0)
        .bind(to_i64(selector.1, "selector trust epoch")?)
        .bind(generator.0)
        .bind(to_i64(generator.1, "generator trust epoch")?)
        .bind(tokenizer.0)
        .bind(to_i64(tokenizer.1, "tokenizer trust epoch")?)
        .bind(evaluator.0)
        .bind(to_i64(evaluator.1, "evaluator trust epoch")?)
        .bind(to_i64(
            retain_source_until_unix_seconds,
            "source retention deadline",
        )?)
        .fetch_one(&mut *transaction)
        .await
        .map_err(sql_error)?;
        if exact != 1 {
            return Err(conflict(
                "publication mutation idempotency key was reused with drift",
            ));
        }
        transaction.commit().await.map_err(sql_error)?;
        Ok(MutationIntentV1::new(idempotency_key.to_string()))
    }

    pub(crate) async fn prepare_revocation(
        &self,
        checkpoint_digest: Digest32,
        reason_digest: Digest32,
        revoked_at_unix_seconds: u64,
    ) -> Result<MutationIntentV1, CompactionCoordinatorErrorV2> {
        let timestamp = revoked_at_unix_seconds.to_be_bytes();
        let operation = Digest32::of_parts(&[
            REVOKE_OPERATION_DOMAIN,
            self.owner_id.as_bytes(),
            checkpoint_digest.as_array(),
            reason_digest.as_array(),
            &timestamp,
        ])
        .to_string();
        self.prepare_generic(
            &operation,
            "revoke-checkpoint",
            checkpoint_digest,
            reason_digest,
            revoked_at_unix_seconds,
        )
        .await?;
        Ok(MutationIntentV1::new(operation))
    }

    pub(crate) async fn prepare_retention_release(
        &self,
        checkpoint_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<MutationIntentV1, CompactionCoordinatorErrorV2> {
        let operation = Digest32::of_parts(&[
            RELEASE_OPERATION_DOMAIN,
            self.owner_id.as_bytes(),
            checkpoint_digest.as_array(),
        ])
        .to_string();
        let auxiliary = Digest32::of_parts(&[
            RELEASE_AUXILIARY_DOMAIN,
            checkpoint_digest.as_array(),
        ]);
        self.prepare_generic(
            &operation,
            "release-retention",
            checkpoint_digest,
            auxiliary,
            now_unix_seconds,
        )
        .await?;
        Ok(MutationIntentV1::new(operation))
    }

    async fn prepare_generic(
        &self,
        operation_id: &str,
        operation_kind: &'static str,
        target_digest: Digest32,
        auxiliary_digest: Digest32,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sql_error)?;
        verify_fence_tx(&mut transaction, self, now_unix_seconds).await?;
        upsert_guard_tx(
            &mut transaction,
            self,
            operation_id,
            operation_kind,
            target_digest,
            auxiliary_digest,
            now_unix_seconds,
        )
        .await?;
        transaction.commit().await.map_err(sql_error)
    }

    pub(crate) async fn commit_intent(
        &self,
        intent: &MutationIntentV1,
        now_unix_seconds: u64,
    ) -> Result<(), CompactionCoordinatorErrorV2> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(sql_error)?;
        verify_fence_tx(&mut transaction, self, now_unix_seconds).await?;
        let changed = sqlx::query(
            "UPDATE compaction_mutation_fences_v3
             SET state = 'committed', committed_at_unix_seconds = ?,
                 guard_revision = guard_revision + 1
             WHERE owner_id = ? AND operation_id = ?
               AND state IN ('prepared', 'committed')",
        )
        .bind(to_i64(now_unix_seconds, "mutation commit time")?)
        .bind(&self.owner_id)
        .bind(&intent.operation_id)
        .execute(&mut *transaction)
        .await
        .map_err(sql_error)?
        .rows_affected();
        if changed != 1 {
            return Err(conflict("mutation intent did not commit exactly once"));
        }
        transaction.commit().await.map_err(sql_error)
    }
}

async fn upsert_guard_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &MutationGuardStoreV1,
    operation_id: &str,
    operation_kind: &'static str,
    target_digest: Digest32,
    auxiliary_digest: Digest32,
    now_unix_seconds: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    sqlx::query(
        "INSERT INTO compaction_mutation_fences_v3
         (owner_id, operation_id, operation_kind, target_digest,
          auxiliary_digest, root_key_digest, manifest_digest,
          lease_token_digest, lease_epoch, execution_now_unix_seconds,
          guard_revision, state, committed_at_unix_seconds)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'prepared', NULL)
         ON CONFLICT(owner_id, operation_id) DO UPDATE SET
           lease_token_digest = excluded.lease_token_digest,
           lease_epoch = excluded.lease_epoch,
           execution_now_unix_seconds = excluded.execution_now_unix_seconds,
           guard_revision = compaction_mutation_fences_v3.guard_revision + 1
         WHERE compaction_mutation_fences_v3.state = 'prepared'
           AND compaction_mutation_fences_v3.operation_kind = excluded.operation_kind
           AND compaction_mutation_fences_v3.target_digest = excluded.target_digest
           AND compaction_mutation_fences_v3.auxiliary_digest = excluded.auxiliary_digest
           AND compaction_mutation_fences_v3.root_key_digest = excluded.root_key_digest
           AND compaction_mutation_fences_v3.manifest_digest = excluded.manifest_digest",
    )
    .bind(&store.owner_id)
    .bind(operation_id)
    .bind(operation_kind)
    .bind(target_digest.to_string())
    .bind(auxiliary_digest.to_string())
    .bind(store.root_key_digest.to_string())
    .bind(store.manifest_digest.to_string())
    .bind(store.lease_token_digest.to_string())
    .bind(to_i64(store.lease_epoch, "mutation lease epoch")?)
    .bind(to_i64(now_unix_seconds, "mutation execution time")?)
    .execute(&mut **transaction)
    .await
    .map_err(sql_error)?;
    let exact: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM compaction_mutation_fences_v3
         WHERE owner_id = ? AND operation_id = ? AND operation_kind = ?
           AND target_digest = ? AND auxiliary_digest = ?
           AND root_key_digest = ? AND manifest_digest = ?
           AND lease_token_digest = ? AND lease_epoch = ?
           AND state IN ('prepared', 'committed')",
    )
    .bind(&store.owner_id)
    .bind(operation_id)
    .bind(operation_kind)
    .bind(target_digest.to_string())
    .bind(auxiliary_digest.to_string())
    .bind(store.root_key_digest.to_string())
    .bind(store.manifest_digest.to_string())
    .bind(store.lease_token_digest.to_string())
    .bind(to_i64(store.lease_epoch, "mutation lease epoch")?)
    .fetch_one(&mut **transaction)
    .await
    .map_err(sql_error)?;
    if exact != 1 {
        return Err(conflict("mutation operation identity or owner fence drift"));
    }
    Ok(())
}

async fn verify_fence_tx(
    transaction: &mut Transaction<'_, Sqlite>,
    store: &MutationGuardStoreV1,
    now_unix_seconds: u64,
) -> Result<(), CompactionCoordinatorErrorV2> {
    let count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*)
         FROM compaction_owner_fence_v2 AS owner
         JOIN active_compaction_manifest_v2 AS active
           ON active.owner_id = owner.owner_id
         JOIN compaction_manifest_log_v2 AS manifest
           ON manifest.owner_id = active.owner_id
          AND manifest.manifest_digest = active.manifest_digest
         WHERE owner.owner_id = ?
           AND owner.root_key_digest = ?
           AND owner.lease_token_digest = ?
           AND owner.lease_epoch = ?
           AND owner.lease_expires_at_unix_seconds > ?
           AND active.manifest_digest = ?
           AND manifest.root_key_digest = ?",
    )
    .bind(&store.owner_id)
    .bind(store.root_key_digest.to_string())
    .bind(store.lease_token_digest.to_string())
    .bind(to_i64(store.lease_epoch, "mutation lease epoch")?)
    .bind(to_i64(now_unix_seconds, "mutation execution time")?)
    .bind(store.manifest_digest.to_string())
    .bind(store.root_key_digest.to_string())
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

fn binding(
    publication: &VerifiedCompactionPublicationV1,
    role: CompactionTrustRoleV1,
) -> Result<(&str, u64), CompactionCoordinatorErrorV2> {
    publication
        .nonce_bindings()
        .iter()
        .find(|binding| binding.role == role)
        .map(|binding| (binding.key_id.as_str(), binding.trust_epoch))
        .ok_or(CompactionCoordinatorErrorV2::Corrupt(
            "verified publication is missing a role binding",
        ))
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
