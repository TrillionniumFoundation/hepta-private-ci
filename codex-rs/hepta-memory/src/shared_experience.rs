//! Purpose-specific native owner access for shared experience.
//!
//! Recall grants never authorize Replay. Each admitted use pins one actual
//! Memory revision and the consumer workspace. This is an in-process owner API;
//! it does not enroll a remote peer, copy context, or authorize a model update.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::FederationConsumerAccess;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

const MAX_ACTIVE_POLICY_IDENTITIES: i64 = 4096;
const MAX_POLICY_REVISIONS: i64 = 1024;
const MAX_LIFETIME_SECONDS: i64 = 31 * 24 * 60 * 60;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SharedExperiencePurposeV1 {
    Recall,
    Replay {
        parameter_scope: String,
        artifact_consumer: AgentId,
    },
}

impl SharedExperiencePurposeV1 {
    fn parts(&self) -> Result<(&str, &str, &str), CognitiveStoreError> {
        match self {
            Self::Recall => Ok(("recall", "", "")),
            Self::Replay {
                parameter_scope,
                artifact_consumer,
            } if !parameter_scope.trim().is_empty()
                && parameter_scope.len() <= 128
                && !parameter_scope.as_bytes().contains(&0) =>
            {
                Ok(("replay", parameter_scope, artifact_consumer.as_str()))
            }
            _ => Err(CognitiveStoreError::Invalid(
                "invalid shared parameter scope".into(),
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedExperienceGrantV1 {
    pub memory_id: StableMemoryId,
    pub memory_revision: u64,
    pub consumer: FederationConsumerAccess,
    pub purpose: SharedExperiencePurposeV1,
    pub expires_at_unix_seconds: i64,
}

/// Owner-produced current use. Call revalidate_shared_experience immediately
/// before attachment/training/artifact use; a cloned receipt is not a live grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedExperienceUseV1 {
    policy_id: Sha256Digest,
    policy_revision: u64,
    owner_id: AgentId,
    consumer: FederationConsumerAccess,
    purpose: SharedExperiencePurposeV1,
    memory: MemoryRevisionRecord,
}

impl SharedExperienceUseV1 {
    pub fn memory(&self) -> &MemoryRevisionRecord {
        &self.memory
    }
    pub fn policy_id(&self) -> &Sha256Digest {
        &self.policy_id
    }
    pub fn policy_revision(&self) -> u64 {
        self.policy_revision
    }
    pub fn purpose(&self) -> &SharedExperiencePurposeV1 {
        &self.purpose
    }
    pub fn owner_id(&self) -> &AgentId {
        &self.owner_id
    }

    /// Bind learning support to this exact source revision, not just equal text.
    /// Consumer/purpose authorization is checked separately at every use boundary.
    pub fn source_support_digest(&self) -> Sha256Digest {
        let mut hash = Sha256::new();
        for part in [
            b"hepta.shared-experience.source-support.v1".as_slice(),
            self.owner_id.as_str().as_bytes(),
            self.memory.id.memory_id.as_str().as_bytes(),
            &self.memory.id.revision.to_be_bytes(),
            self.memory.content_sha256.as_str().as_bytes(),
        ] {
            frame_part(&mut hash, part);
        }
        Sha256Digest::from_sha256_output(hash.finalize())
    }
}

fn now() -> Result<i64, CognitiveStoreError> {
    let value = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(unavailable)?
        .as_secs();
    i64::try_from(value).map_err(unavailable)
}

fn valid_memory(memory: &MemoryRevisionRecord, now: i64) -> bool {
    memory.lifecycle == MemoryLifecycleState::Active
        && memory.verification == MemoryVerification::Verified
        && memory.valid_from_unix_seconds <= now
        && memory
            .valid_to_unix_seconds
            .is_none_or(|expiry| expiry > now)
}

fn policy_id(
    owner: &AgentId,
    request: &SharedExperienceGrantV1,
) -> Result<Sha256Digest, CognitiveStoreError> {
    let (purpose, scope, recipient) = request.purpose.parts()?;
    let mut hash = Sha256::new();
    for part in [
        b"hepta.shared-experience.use.v1".as_slice(),
        owner.as_str().as_bytes(),
        request.memory_id.as_str().as_bytes(),
        &request.memory_revision.to_be_bytes(),
        request.consumer.agent_id().as_str().as_bytes(),
        request.consumer.workspace_sha256().as_str().as_bytes(),
        purpose.as_bytes(),
        scope.as_bytes(),
        recipient.as_bytes(),
    ] {
        frame_part(&mut hash, part);
    }
    Ok(Sha256Digest::from_sha256_output(hash.finalize()))
}

impl CognitiveStore {
    /// Append an owner-authorized exact-revision purpose grant. Expected revision
    /// is zero for first admission; updates compare against the durable head.
    /// Product callers must enter through the existing owner authorization path.
    pub async fn grant_shared_experience(
        &self,
        owner: &CognitiveAccess,
        request: &SharedExperienceGrantV1,
        expected_revision: u64,
    ) -> Result<SharedExperienceUseV1, CognitiveStoreError> {
        let key = policy_id(self.owner_agent_id(), request)?;
        let (purpose, scope, recipient) = request.purpose.parts()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let memory = self
            .latest_memory_tx(&mut tx, owner, &request.memory_id)
            .await?;
        // The writer may have queued behind another transaction. Admission time
        // must be sampled after that wait, not before acquiring the owner cut.
        let time = now()?;
        if request.expires_at_unix_seconds <= time
            || request.expires_at_unix_seconds.saturating_sub(time) > MAX_LIFETIME_SECONDS
        {
            return Err(CognitiveStoreError::Invalid(
                "shared use expiry outside bounded lifetime".into(),
            ));
        }
        if memory.id.revision != request.memory_revision || !valid_memory(&memory, time) {
            return Err(CognitiveStoreError::Conflict(
                "shared source is not current verified evidence".into(),
            ));
        }
        let previous: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(revision) FROM shared_experience_use_events WHERE policy_id = ?",
        )
        .bind(key.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        let previous = previous.unwrap_or(0);
        if expected_revision.checked_add(1) == u64::try_from(previous).ok() {
            let same: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM shared_experience_use_events WHERE policy_id=? AND revision=? AND revoked=0 AND expires_at=? AND content_sha256=?")
                .bind(key.as_str()).bind(previous).bind(request.expires_at_unix_seconds).bind(memory.content_sha256.as_str())
                .fetch_one(&mut *tx).await.map_err(unavailable)?;
            if same == 1 {
                tx.commit().await.map_err(unavailable)?;
                return Ok(SharedExperienceUseV1 {
                    policy_id: key,
                    policy_revision: previous as u64,
                    owner_id: self.owner_agent_id().clone(),
                    consumer: request.consumer.clone(),
                    purpose: request.purpose.clone(),
                    memory,
                });
            }
        }
        if u64::try_from(previous).map_err(unavailable)? != expected_revision
            || previous >= MAX_POLICY_REVISIONS
        {
            return Err(CognitiveStoreError::Conflict(
                "shared use policy predecessor".into(),
            ));
        }
        let already_active: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM shared_experience_use_heads WHERE policy_id=? AND revoked=0 AND expires_at>?)",
        )
        .bind(key.as_str()).bind(time).fetch_one(&mut *tx).await.map_err(unavailable)?;
        if !already_active {
            // Revoked/expired predecessors remain durable, but consume no live
            // slot. Re-activation must pass the same admission as a new identity.
            // The partial expiry index and LIMIT bound work by the active quota,
            // not by all identities or revisions ever recorded.
            let count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM (SELECT 1 FROM shared_experience_use_heads WHERE revoked=0 AND expires_at>? LIMIT ?)",
            )
            .bind(time).bind(MAX_ACTIVE_POLICY_IDENTITIES)
            .fetch_one(&mut *tx).await.map_err(unavailable)?;
            if count >= MAX_ACTIVE_POLICY_IDENTITIES {
                return Err(CognitiveStoreError::Invalid("shared use capacity".into()));
            }
        }
        let revision = previous + 1;
        sqlx::query("INSERT INTO shared_experience_use_events (policy_id,revision,revoked,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at) VALUES (?,?,0,?,?,?,?,?,?,?,?,?)")
            .bind(key.as_str()).bind(revision).bind(request.memory_id.as_str()).bind(i64::try_from(request.memory_revision).map_err(unavailable)?)
            .bind(memory.content_sha256.as_str()).bind(request.consumer.agent_id().as_str()).bind(request.consumer.workspace_sha256().as_str())
            .bind(purpose).bind(scope).bind(recipient).bind(request.expires_at_unix_seconds)
            .execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(SharedExperienceUseV1 {
            policy_id: key,
            policy_revision: revision as u64,
            owner_id: self.owner_agent_id().clone(),
            consumer: request.consumer.clone(),
            purpose: request.purpose.clone(),
            memory,
        })
    }

    /// Owner-backed read checks policy and Memory head in one coherent transaction.
    /// The caller supplies its authenticated local consumer context, not authority
    /// inferred from a string found inside the shared Memory payload.
    pub async fn read_shared_experience(
        &self,
        consumer: &FederationConsumerAccess,
        key: &Sha256Digest,
        purpose: &SharedExperiencePurposeV1,
    ) -> Result<SharedExperienceUseV1, CognitiveStoreError> {
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query("SELECT * FROM shared_experience_use_events WHERE policy_id = ? ORDER BY revision DESC LIMIT 1")
            .bind(key.as_str()).fetch_optional(&mut *tx).await.map_err(unavailable)?
            .ok_or_else(|| CognitiveStoreError::AccessDenied("shared use unavailable".into()))?;
        let (kind, target, recipient) = purpose.parts()?;
        let denied = row.try_get::<i64, _>("revoked").map_err(unavailable)? != 0
            || row
                .try_get::<String, _>("consumer_agent_id")
                .map_err(unavailable)?
                != consumer.agent_id().as_str()
            || row
                .try_get::<String, _>("consumer_workspace_sha256")
                .map_err(unavailable)?
                != consumer.workspace_sha256().as_str()
            || row.try_get::<String, _>("purpose").map_err(unavailable)? != kind
            || row
                .try_get::<String, _>("parameter_scope")
                .map_err(unavailable)?
                != target
            || row
                .try_get::<String, _>("artifact_consumer_id")
                .map_err(unavailable)?
                != recipient
            || row.try_get::<i64, _>("expires_at").map_err(unavailable)? <= now()?;
        if denied {
            return Err(CognitiveStoreError::AccessDenied(
                "shared use unavailable".into(),
            ));
        }
        let memory_id =
            StableMemoryId::parse(row.try_get::<String, _>("memory_id").map_err(unavailable)?)
                .map_err(CognitiveStoreError::Corrupt)?;
        let scope_row = sqlx::query("SELECT scope_kind,workspace_sha256 FROM memory_revisions WHERE memory_id = ? AND revision = ?")
            .bind(memory_id.as_str()).bind(row.try_get::<i64,_>("memory_revision").map_err(unavailable)?)
            .fetch_one(&mut *tx).await.map_err(unavailable)?;
        let scope = crate::cognitive_store::decode_scope(&scope_row)?;
        let owner = match scope {
            crate::CognitiveScope::AgentPrivate => {
                CognitiveAccess::agent_private(self.owner_agent_id().clone())
            }
            crate::CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
                CognitiveAccess::workspace_private(self.owner_agent_id().clone(), workspace_sha256)
            }
        };
        let memory = self.latest_memory_tx(&mut tx, &owner, &memory_id).await?;
        if !valid_memory(&memory, now()?)
            || i64::try_from(memory.id.revision).map_err(unavailable)?
                != row
                    .try_get::<i64, _>("memory_revision")
                    .map_err(unavailable)?
            || memory.content_sha256.as_str()
                != row
                    .try_get::<String, _>("content_sha256")
                    .map_err(unavailable)?
        {
            return Err(CognitiveStoreError::Conflict(
                "shared source changed or withdrawn".into(),
            ));
        }
        let result = SharedExperienceUseV1 {
            policy_id: key.clone(),
            policy_revision: row.try_get::<i64, _>("revision").map_err(unavailable)? as u64,
            owner_id: self.owner_agent_id().clone(),
            consumer: consumer.clone(),
            purpose: purpose.clone(),
            memory,
        };
        tx.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub async fn revalidate_shared_experience(
        &self,
        receipt: &SharedExperienceUseV1,
    ) -> Result<(), CognitiveStoreError> {
        if receipt.owner_id != *self.owner_agent_id() {
            return Err(CognitiveStoreError::AccessDenied(
                "wrong shared source owner".into(),
            ));
        }
        let current = self
            .read_shared_experience(&receipt.consumer, &receipt.policy_id, &receipt.purpose)
            .await?;
        if current != *receipt {
            return Err(CognitiveStoreError::Conflict(
                "shared use binding changed".into(),
            ));
        }
        Ok(())
    }

    /// Revocation appends a successor and does not claim parameter unlearning.
    /// The last ordinary revision can always enter its reserved terminal slot.
    /// Grant capacity is never a reason to reject withdrawal of an active grant.
    pub async fn revoke_shared_experience(
        &self,
        owner: &CognitiveAccess,
        receipt: &SharedExperienceUseV1,
    ) -> Result<(), CognitiveStoreError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        self.latest_memory_tx(&mut tx, owner, &receipt.memory.id.memory_id)
            .await?;
        if receipt.owner_id != *self.owner_agent_id()
            || receipt.policy_revision > MAX_POLICY_REVISIONS as u64
        {
            return Err(CognitiveStoreError::Conflict(
                "invalid shared policy owner/revision".into(),
            ));
        }
        let head: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(revision) FROM shared_experience_use_events WHERE policy_id=?",
        )
        .bind(receipt.policy_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if head == Some(receipt.policy_revision as i64 + 1) {
            let revoked: i64 = sqlx::query_scalar(
                "SELECT revoked FROM shared_experience_use_events WHERE policy_id=? AND revision=?",
            )
            .bind(receipt.policy_id.as_str())
            .bind(head)
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
            if revoked == 1 {
                tx.commit().await.map_err(unavailable)?;
                return Ok(());
            }
        }
        if head != Some(receipt.policy_revision as i64) {
            return Err(CognitiveStoreError::Conflict(
                "shared use policy predecessor".into(),
            ));
        }
        sqlx::query("INSERT INTO shared_experience_use_events SELECT policy_id,revision+1,1,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events WHERE policy_id=? AND revision=?")
            .bind(receipt.policy_id.as_str()).bind(receipt.policy_revision as i64).execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(())
    }
}

/// Check the quota projection against immutable history at startup/recovery.
/// Admission uses the bounded index; a missing or stale head is never rebuilt
/// silently from an untrusted database while the owner is already serving.
pub(crate) async fn verify_current_use_heads(
    pool: &sqlx::SqlitePool,
) -> Result<(), CognitiveStoreError> {
    let mismatch: bool = sqlx::query_scalar(
        "WITH current AS (
            SELECT e.policy_id,e.revision,e.revoked,e.expires_at
            FROM shared_experience_use_events e
            JOIN (SELECT policy_id,MAX(revision) AS revision
                  FROM shared_experience_use_events GROUP BY policy_id) h
            USING(policy_id,revision)
         )
         SELECT EXISTS(SELECT * FROM current EXCEPT SELECT * FROM shared_experience_use_heads)
             OR EXISTS(SELECT * FROM shared_experience_use_heads EXCEPT SELECT * FROM current)",
    )
    .fetch_one(pool)
    .await
    .map_err(unavailable)?;
    if mismatch {
        return Err(CognitiveStoreError::Corrupt(
            "shared use current projection differs from immutable history".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "shared_experience_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "shared_experience_capacity_tests.rs"]
mod capacity_tests;
