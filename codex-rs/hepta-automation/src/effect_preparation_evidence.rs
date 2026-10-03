//! Non-authorizing evidence for the pre-contact preparation cut.
//! Hashes bind records to owner history; they are not signatures or a trust
//! root. Only the existing opaque-token consumer appends these rows.

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::taskflow_step::StepAuthoringIdentity;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::VerifiedPreparationEvidence;
use codex_hepta_contracts::VerifiedUseAuthorityRefV1;
use codex_hepta_contracts::VerifiedUseBoundaryV1;
use codex_hepta_contracts::VerifiedUseTokenWitnessV1;
use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use sqlx::Row;
use std::fmt::Write;

const MAX_RECORD_BYTES: usize = 32_768;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct PreparationRecord {
    schema_version: u32,
    attempt_identity: serde_json::Value,
    step_authoring_identity: serde_json::Value,
    grant: FinalUseGrant,
    witness: VerifiedUseTokenWitnessV1,
}

impl AutomationStore {
    /// Missing evidence is not provider absence; a present observation is not
    /// proof of a send or terminality. Neither authorizes settlement or retry.
    pub async fn authorized_taskflow_effect_preparation_witness(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<VerifiedUseTokenWitnessV1>, TaskFlowError> {
        Ok(self
            .read_preparation_record(run_id, step_id, attempt)
            .await?
            .map(|record| record.witness))
    }

    pub(crate) async fn record_effect_preparation_witness(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
        evidence: &VerifiedPreparationEvidence,
    ) -> Result<(), TaskFlowError> {
        let current = self
            .effect_dispatch_attempt(&durable.run_id, &durable.step_id, durable.attempt)
            .await?
            .ok_or_else(|| corrupt("preparation has no immutable attempt"))?;
        if attempt_identity(&current) != attempt_identity(durable) {
            return Err(conflict("preparation attempt identity changed"));
        }
        let step: StepAuthoringIdentity = self
            .read_step_authoring_identity(&durable.run_id, &durable.step_id, durable.attempt)
            .await?
            .ok_or_else(|| corrupt("preparation has no authored step"))?;
        if step.fence != *fence
            || step.intent_digest != durable.intent_digest
            || step.payload_digest != durable.payload_digest
        {
            return Err(conflict("preparation differs from exact step authoring"));
        }
        let record = PreparationRecord {
            schema_version: 1,
            attempt_identity: attempt_identity(durable),
            step_authoring_identity: serde_json::to_value(step)
                .map_err(|_| corrupt("preparation step serialization"))?,
            grant: evidence.grant().clone(),
            witness: evidence.observation().clone(),
        };
        validate_grant_binding(&record, durable)?;
        let bytes =
            serde_json::to_vec(&record).map_err(|_| corrupt("preparation serialization"))?;
        if bytes.len() > MAX_RECORD_BYTES {
            return Err(TaskFlowError::Invalid(
                "preparation record exceeds bound".into(),
            ));
        }
        // History above is immutable. Reserve the writer only for this append.
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        sqlx::query(
            "INSERT INTO taskflow_effect_preparation_evidence (
            owner_agent_id, run_id, step_id, attempt, record_json, record_sha256
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_agent_id, run_id, step_id, attempt) DO NOTHING",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(&durable.run_id)
        .bind(&durable.step_id)
        .bind(i64::from(durable.attempt))
        .bind(&bytes)
        .bind(record_digest(&bytes).as_str())
        .execute(&mut *tx)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        tx.commit().await.map_err(|_| TaskFlowError::Unavailable)?;
        let stored = self
            .read_preparation_record(&durable.run_id, &durable.step_id, durable.attempt)
            .await?
            .ok_or_else(|| corrupt("preparation vanished after append"))?;
        if stored != record {
            return Err(conflict(
                "attempt already has different preparation evidence",
            ));
        }
        Ok(())
    }

    async fn read_preparation_record(
        &self,
        run_id: &str,
        step_id: &str,
        attempt: u32,
    ) -> Result<Option<PreparationRecord>, TaskFlowError> {
        crate::taskflow_step::validate_common_without_digests(
            run_id,
            step_id,
            attempt,
            "preparation_read",
        )?;
        // Bound materialization and refuse duplicate identities even when an
        // offline corruptor removed SQL constraints. Missing evidence is explicit.
        let rows = sqlx::query(
            "SELECT
            CASE WHEN typeof(record_json) = 'blob' AND length(record_json) BETWEEN 2 AND 32768
                THEN record_json END AS record_json,
            CASE WHEN typeof(record_sha256) = 'text' AND length(record_sha256) = 64
                THEN record_sha256 END AS record_sha256
            FROM taskflow_effect_preparation_evidence
            WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ? LIMIT 2",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(step_id)
        .bind(i64::from(attempt))
        .fetch_all(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        let Some(row) = rows.first() else {
            return Ok(None);
        };
        if rows.len() != 1 {
            return Err(corrupt("ambiguous preparation identity"));
        }
        let bytes: Vec<u8> = row
            .try_get("record_json")
            .map_err(|_| corrupt("preparation bytes"))?;
        let digest: String = row
            .try_get("record_sha256")
            .map_err(|_| corrupt("preparation digest"))?;
        if !(2..=MAX_RECORD_BYTES).contains(&bytes.len())
            || record_digest(&bytes).as_str() != digest
        {
            return Err(corrupt("preparation bound or digest mismatch"));
        }
        let record: PreparationRecord =
            serde_json::from_slice(&bytes).map_err(|_| corrupt("preparation JSON"))?;
        if record.schema_version != 1
            || serde_json::to_vec(&record).ok().as_deref() != Some(bytes.as_slice())
        {
            return Err(corrupt("noncanonical preparation record"));
        }
        let durable = self
            .effect_dispatch_attempt(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| corrupt("preparation attempt missing"))?;
        let step = self
            .read_step_authoring_identity(run_id, step_id, attempt)
            .await?
            .ok_or_else(|| corrupt("preparation authoring history missing"))?;
        if record.attempt_identity != attempt_identity(&durable)
            || record.step_authoring_identity
                != serde_json::to_value(&step).map_err(|_| corrupt("step serialization"))?
            || step.intent_digest != durable.intent_digest
            || step.payload_digest != durable.payload_digest
        {
            return Err(corrupt(
                "preparation differs from immutable attempt or authoring history",
            ));
        }
        validate_grant_binding(&record, &durable)?;
        Ok(Some(record))
    }
}

fn validate_grant_binding(
    record: &PreparationRecord,
    durable: &EffectDispatchAttempt,
) -> Result<(), TaskFlowError> {
    record
        .grant
        .signing_bytes()
        .map_err(|_| corrupt("invalid preparation grant proposal"))?;
    record
        .witness
        .validate()
        .map_err(|_| corrupt("invalid preparation witness"))?;
    let grant = &record.grant;
    let binding = serde_json::to_vec(&grant.binding).map_err(|_| corrupt("preparation binding"))?;
    let mut domain = b"hepta.kernel.authority.verified-use-binding.final-use.v1\0".to_vec();
    domain.extend_from_slice(&binding);
    let expected_witness_digest = Sha256Digest::for_bytes(&domain);
    let VerifiedUseAuthorityRefV1::FinalUse(reference) = &record.witness.authority_ref else {
        return Err(corrupt("preparation authority family mismatch"));
    };
    let mut witness_digest = String::with_capacity(64);
    for byte in reference.binding_sha256 {
        write!(&mut witness_digest, "{byte:02x}")
            .map_err(|_| corrupt("preparation witness digest"))?;
    }
    if record.witness.boundary != VerifiedUseBoundaryV1::PreparationEntry
        || reference.signer_id != grant.signer_id
        || reference.grant_id != durable.grant_id
        || grant.grant_id != durable.grant_id
        || grant.authority_epoch != durable.authority_epoch
        || record.witness.authority_epoch != durable.authority_epoch
        || record.witness.verified_at_unix_ms < grant.not_before_unix_ms
        || record.witness.verified_at_unix_ms >= grant.expires_at_unix_ms
        || Sha256Digest::for_bytes(&grant.nonce) != durable.grant_nonce_digest
        || Sha256Digest::for_bytes(&binding) != durable.binding_digest
        || expected_witness_digest.as_str() != witness_digest
        || grant.binding.destination_id != durable.destination_id
        || grant.binding.request_sha256
            != crate::authorized_effect::digest_bytes(&durable.intent_digest)
                .map_err(|_| corrupt("preparation request digest"))?
        || grant.binding.payload_sha256
            != crate::authorized_effect::digest_bytes(&durable.payload_digest)
                .map_err(|_| corrupt("preparation payload digest"))?
    {
        return Err(corrupt(
            "preparation grant/witness does not bind the attempt",
        ));
    }
    Ok(())
}

fn attempt_identity(a: &EffectDispatchAttempt) -> serde_json::Value {
    json!({
        "owner_agent_id": a.owner_agent_id, "run_id": a.run_id, "step_id": a.step_id, "attempt": a.attempt,
        "provider_key_version": a.provider_key_version, "provider_contract_binding": a.provider_contract_binding,
        "intent_digest": a.intent_digest, "payload_digest": a.payload_digest, "binding_digest": a.binding_digest,
        "destination_id": a.destination_id, "authority_epoch": a.authority_epoch, "grant_id": a.grant_id,
        "grant_nonce_digest": a.grant_nonce_digest, "record_command_id": a.record_command_id, "started_at_ms": a.started_at_ms,
    })
}
fn record_digest(bytes: &[u8]) -> Sha256Digest {
    let mut domain = b"hepta.automation.preparation-evidence.v1\0".to_vec();
    domain.extend_from_slice(bytes);
    Sha256Digest::for_bytes(&domain)
}
fn corrupt(reason: &str) -> TaskFlowError {
    TaskFlowError::Corrupt(reason.into())
}
fn conflict(reason: &str) -> TaskFlowError {
    TaskFlowError::Conflict(reason.into())
}

pub(crate) async fn verify_preparation_schema(
    pool: &sqlx::SqlitePool,
) -> Result<(), TaskFlowError> {
    sqlx::query(
        "SELECT owner_agent_id, run_id, step_id, attempt, record_json, record_sha256
        FROM taskflow_effect_preparation_evidence LIMIT 0",
    )
    .fetch_all(pool)
    .await
    .map_err(|_| corrupt("preparation schema missing"))?;
    for (name, action) in [
        ("taskflow_effect_preparation_evidence_no_update", "UPDATE"),
        ("taskflow_effect_preparation_evidence_no_delete", "DELETE"),
    ] {
        let sql: Option<String> =
            sqlx::query_scalar("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?")
                .bind(name)
                .fetch_optional(pool)
                .await
                .map_err(|_| TaskFlowError::Unavailable)?;
        let expected = format!(
            "CREATE TRIGGER {name} BEFORE {action} ON taskflow_effect_preparation_evidence BEGIN SELECT RAISE(ABORT, 'TaskFlow preparation evidence is immutable'); END"
        );
        if sql
            .as_deref()
            .map(|value| value.split_whitespace().collect::<Vec<_>>().join(" "))
            != Some(expected)
        {
            return Err(corrupt("preparation immutability trigger differs"));
        }
    }
    Ok(())
}

#[cfg(all(test, unix))]
#[path = "effect_preparation_evidence_tests.rs"]
mod tests;
