//! Atomic import of an explicitly admitted complete Python episodic namespace.
//! This reuses the retained production writer; it cannot open or mint an owner.
use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;
use serde_json::json;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::ProductionCognitiveMutationCapability;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::LocalAdmission;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::ProductionCognitiveMutationError;
use crate::ProductionWriterError;
use crate::SourceDraft;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;

#[path = "production_episodic_snapshot.rs"]
mod snapshot;
use snapshot::MAX_BINDINGS;
use snapshot::Record;
use snapshot::Snapshot;
use snapshot::digest;

/// Original-host admission of a complete, current source namespace.
/// Implementations must authenticate the live source owner, its complete
/// roster and exact observed fact bytes (not an implied whole-document copy).
/// Return the original canonical source observations for those bytes.
/// A checksum or Python provenance fields alone
/// cannot implement this contract. Called before use and again before commit;
/// there is no default implementation or qualification fallback.
pub trait EpisodicSnapshotVerifier: Send + Sync {
    fn verify_current(&self, snapshot_json: &str) -> Result<EpisodicSnapshotAdmission, String>;
}

/// One original-host source observation and its independently chosen native
/// verification state. Source custody alone cannot upgrade a fact to Verified.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EpisodicRecordAdmission {
    pub source: SourceDraft,
    pub verification: MemoryVerification,
}

/// Source payloads admitted by the original host, never deserialized from the
/// import request. Each record maps to its actual canonical source observation.
/// Withdrawing prior facts additionally requires an admitted withdrawal event.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EpisodicSnapshotAdmission {
    pub records: BTreeMap<String, EpisodicRecordAdmission>,
    pub withdrawal: Option<SourceDraft>,
}

/// Persistent association between one Python fact slot and its canonical head.
/// Retired slots remain in the receipt, preventing old snapshot resurrection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EpisodicMemoryBinding {
    pub source_id: String,
    pub key: String,
    pub version: u64,
    pub record_id: String,
    pub memory_id: String,
    pub memory_revision: u64,
    pub canonical_source_id: String,
    pub canonical_source_revision: u64,
    pub active: bool,
    pub source_admission_sha256: String,
    pub source_content_sha256: String,
    pub mutation_receipt_sha256: String,
    pub mutation_commit_event_id: String,
}

/// Committed bridge state, replayed unchanged after an acknowledgement is lost.
/// Hashes identify source bytes; authority comes from the retained writer and
/// the separately supplied source verifier, not from this serializable receipt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EpisodicImportReceipt {
    pub schema_version: u32,
    pub owner_agent_id: String,
    pub scope_binding: String,
    pub authority_id: String,
    pub namespace: String,
    pub generation: u64,
    pub snapshot_sha256: String,
    pub admission_sha256: String,
    pub lease_id: String,
    pub writer_generation: u64,
    pub bindings: Vec<EpisodicMemoryBinding>,
}

impl ProductionCognitiveMutationCapability {
    /// Synchronize at most 32 lifetime slots from the complete current namespace.
    /// Missing facts are withdrawn atomically with corrections, so a valid
    /// dependency-closed snapshot propagates update/revocation to descendants.
    /// An identical retry reconciles the original commit without another write.
    /// The final admission check is a read linearization point, not an external
    /// effect fence; callers still use ordinary owner revalidation for inference.
    pub async fn import_episodic_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        snapshot_json: &str,
        admission: &dyn EpisodicSnapshotVerifier,
    ) -> Result<EpisodicImportReceipt, ProductionCognitiveMutationError> {
        let snapshot = Snapshot::parse(snapshot_json)?;
        let body = &snapshot.body;
        let store = self.writer.store();
        store.authorize(access, scope)?;
        self.writer.verify_current_authority().await?;
        let admitted = admission.verify_current(snapshot_json).map_err(|reason| {
            ProductionWriterError::AuthorityRejected(format!("episodic source: {reason}"))
        })?;
        if admitted.records.len() != body.records.len()
            || body.records.iter().any(|record| !admitted.records.get(&record.record_id)
                .is_some_and(|source| source.source.scope == *scope && source.source.content == record.text.as_bytes()))
            || admitted.withdrawal.as_ref().is_some_and(|source| source.scope != *scope)
        {
            return Err(invalid("admitted source payloads do not exactly bind the complete snapshot"));
        }
        for source in admitted.records.values().map(|admission| &admission.source).chain(admitted.withdrawal.iter()) {
            crate::cognitive_store::validate_key(&source.event_key, "episodic source event key")?;
        }
        if admitted.withdrawal.as_ref().is_some_and(|source| source.content.is_empty()
            || source.content.len() > 256 || std::str::from_utf8(&source.content).is_err())
        {
            return Err(invalid("withdrawal event must contain 1..=256 UTF-8 bytes"));
        }
        let admission_sha256 = digest(&serde_json::to_value(&admitted).map_err(|error| invalid(error.to_string()))?)?;
        let scope_binding = digest(&json!([store.owner_agent_id(), scope, body.namespace]))?;
        let topic = format!("cognitive.episodic.snapshot:{scope_binding}");
        let mut transaction = store.begin_write_transaction().await?;
        let previous: Option<String> = sqlx::query_scalar(
            "SELECT e.payload_json FROM cognitive_local_outbox o
             JOIN cognitive_local_events e ON e.lease_id = o.lease_id
               AND e.occurrence_key = o.occurrence_key
             WHERE o.owner_agent_id = ? AND o.topic = ? AND e.event_kind = 'reconcile_committed'
             ORDER BY CAST(json_extract(e.payload_json, '$.generation') AS INTEGER) DESC LIMIT 1",
        )
        .bind(store.owner_agent_id().as_str()).bind(&topic)
        .fetch_optional(&mut *transaction).await.map_err(unavailable)?;
        let previous: Option<EpisodicImportReceipt> = previous.as_deref()
            .map(serde_json::from_str).transpose().map_err(|error| invalid(error.to_string()))?;
        let mut bindings = BTreeMap::new();
        if let Some(previous) = &previous {
            if previous.schema_version != 1
                || previous.owner_agent_id != store.owner_agent_id().as_str()
                || previous.scope_binding != scope_binding
                || previous.authority_id != body.authority_id
                || previous.namespace != body.namespace
                || previous.generation > body.generation
                || previous.bindings.len() > MAX_BINDINGS
            {
                return Err(invalid("episodic source identity or generation changed"));
            }
            for binding in &previous.bindings {
                let id = StableMemoryId::parse(&binding.memory_id).map_err(invalid)?;
                let current = store.latest_memory_tx(&mut transaction, access, &id).await?;
                let source_head: Option<(i64, String)> = sqlx::query_as(
                    "SELECT source_revision, content_sha256 FROM source_ledger
                     WHERE source_id = ? ORDER BY source_revision DESC LIMIT 1",
                ).bind(&binding.canonical_source_id).fetch_optional(&mut *transaction)
                    .await.map_err(unavailable)?;
                if source_head != Some((i64::try_from(binding.canonical_source_revision)
                        .map_err(|error| invalid(error.to_string()))?, binding.source_content_sha256.clone()))
                    || current.citations.len() != 1
                    || current.citations[0].source_id.as_str() != binding.canonical_source_id
                    || current.citations[0].revision != binding.canonical_source_revision
                    || current.id.revision != binding.memory_revision
                    || (current.lifecycle == MemoryLifecycleState::Active) != binding.active
                    || current.scope != *scope
                    || bindings.insert((binding.source_id.clone(), binding.key.clone()), binding.clone()).is_some()
                {
                    return Err(invalid("canonical episodic head changed outside the bridge"));
                }
            }
            if previous.generation == body.generation {
                if previous.snapshot_sha256 != snapshot.sha256 || previous.admission_sha256 != admission_sha256 {
                    return Err(invalid("same episodic generation has different contents or admitted source identity"));
                }
                if admission.verify_current(snapshot_json).map_err(ProductionWriterError::AuthorityRejected)? != admitted {
                    return Err(invalid("source admission changed before commit"));
                }
                self.writer.verify_current_authority().await?;
                transaction.commit().await.map_err(unavailable)?;
                return Ok(previous.clone());
            }
        }
        let incoming: BTreeMap<_, _> = body.records.iter()
            .map(|record| ((record.source_id.clone(), record.key.clone()), record)).collect();
        if bindings.keys().chain(incoming.keys()).collect::<std::collections::BTreeSet<_>>().len() > MAX_BINDINGS {
            return Err(invalid("episodic lifetime slot bound exceeded"));
        }
        let occurrence = format!("episodic:{scope_binding}:{}", body.generation);
        let intent = serde_json::to_string(&json!({
            "generation": body.generation, "snapshot_sha256": snapshot.sha256,
            "authority_id": body.authority_id, "namespace": body.namespace,
        })).map_err(|error| invalid(error.to_string()))?;
        match self.writer.lease.admit_in_transaction(&mut transaction, occurrence.clone(), topic, intent)
            .await.map_err(ProductionWriterError::from)? {
            LocalAdmission::Queued(_) => {}
            LocalAdmission::Replay(_) => return Err(invalid("episodic admission has no complete committed state")),
        }
        for (slot, record) in &incoming {
            let old = bindings.get(slot);
            if let Some(old) = old {
                if !old.active || record.version < old.version
                    || (record.version == old.version && record.record_id != old.record_id)
                {
                    return Err(invalid("episodic slot is retired or its version did not advance"));
                }
                if record.record_id == old.record_id {
                    let source = admitted.records.get(&record.record_id).ok_or_else(|| invalid("missing admitted source"))?;
                    if old.source_admission_sha256 != digest(&serde_json::to_value(source).map_err(|error| invalid(error.to_string()))?)? {
                        return Err(invalid("unchanged episodic fact has different admitted source identity"));
                    }
                    continue;
                }
            }
            let source = admitted.records.get(&record.record_id)
                .ok_or_else(|| invalid("record has no admitted source"))?;
            let binding = self.commit_episodic_record(&mut transaction, access, scope,
                &scope_binding, old, Some(*record), &source.source, source.verification).await?;
            bindings.insert(slot.clone(), binding);
        }
        let withdrawn: Vec<_> = bindings.iter()
            .filter(|(slot, binding)| binding.active && !incoming.contains_key(*slot))
            .map(|(slot, binding)| (slot.clone(), binding.clone())).collect();
        for (slot, old) in withdrawn {
            let source = admitted.withdrawal.as_ref()
                .ok_or_else(|| invalid("withdrawing an imported fact requires an admitted source event"))?;
            let binding = self.commit_episodic_record(&mut transaction, access, scope,
                &scope_binding, Some(&old), /*record*/ None, source, MemoryVerification::Verified).await?;
            bindings.insert(slot, binding);
        }
        let receipt = EpisodicImportReceipt {
            schema_version: 1, owner_agent_id: store.owner_agent_id().as_str().to_owned(),
            scope_binding, authority_id: body.authority_id.clone(), namespace: body.namespace.clone(),
            generation: body.generation, snapshot_sha256: snapshot.sha256.clone(), admission_sha256,
            lease_id: self.writer.lease_id().to_owned(), writer_generation: self.writer.generation(),
            bindings: bindings.into_values().collect(),
        };
        let encoded = serde_json::to_string(&receipt).map_err(|error| invalid(error.to_string()))?;
        self.writer.lease.apply_in_transaction(&mut transaction, occurrence, encoded)
            .await.map_err(ProductionWriterError::from)?;
        if admission.verify_current(snapshot_json).map_err(ProductionWriterError::AuthorityRejected)? != admitted {
                    return Err(invalid("source admission changed before commit"));
                }
        self.writer.verify_current_authority().await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    #[allow(clippy::too_many_arguments)]
    async fn commit_episodic_record(
        &self, transaction: &mut Transaction<'_, Sqlite>, access: &CognitiveAccess,
        scope: &CognitiveScope, scope_binding: &str,
        old: Option<&EpisodicMemoryBinding>, record: Option<&Record>, source: &SourceDraft,
        verification: MemoryVerification,
    ) -> Result<EpisodicMemoryBinding, ProductionCognitiveMutationError> {
        let (source_id, key, version, record_id) = match (record, old) {
            (Some(record), _) => (&record.source_id, &record.key, record.version, &record.record_id),
            (None, Some(old)) => (&old.source_id, &old.key, old.version, &old.record_id),
            (None, None) => return Err(invalid("missing episodic mutation identity")),
        };
        let stable_key = digest(&json!([scope_binding, source_id, key]))?;
        let content = String::from_utf8(source.content.clone()).map_err(|error| invalid(error.to_string()))?;
        let observed_at = source.observed_at_unix_seconds;
        let draft = MemoryRevisionDraft {
            scope: scope.clone(), content, verification,
            lifecycle: MemoryLifecycleState::Active, valid_from_unix_seconds: observed_at,
            valid_to_unix_seconds: None, citations: Vec::new(),
        };
        let facts = KgFactSetDraft::default();
        let id = StableMemoryId::for_key(self.writer.store().owner_agent_id(), scope, &stable_key);
        if old.is_some_and(|old| old.memory_id != id.as_str()) {
            return Err(invalid("episodic canonical identity mismatch"));
        }
        let memory = MemoryDraft { stable_key, revision: draft.clone() };
        let forget = ForgetMemoryDraft {
            scope: scope.clone(), reason: draft.content.clone(),
            valid_from_unix_seconds: observed_at, citations: Vec::new(),
        };
        let prepared = match (old, record) {
            (None, Some(_)) => self.prepare_semantic_mutation("remember", source, /*expected_predecessor_revision*/ None, &(&memory, &facts))?,
            (Some(old), Some(_)) => self.prepare_semantic_mutation("correct", source, Some(old.memory_revision), &(id.as_str(), &draft, &facts))?,
            (Some(old), None) => self.prepare_semantic_mutation("forget", source, Some(old.memory_revision), &(id.as_str(), &forget))?,
            (None, None) => return Err(invalid("missing episodic mutation")),
        };
        let queued = self.admit_prepared_mutation(transaction, &prepared).await?;
        let write = match (old, record) {
            (None, Some(_)) => self.writer.store().remember_with_kg_tx(transaction, access, source, &memory, &facts).await?,
            (Some(old), Some(_)) => self.writer.store().correct_with_kg_tx(transaction, access,
                crate::cognitive_intelligence_writer::MemoryCorrectionTarget { memory_id: &id, expected_revision: old.memory_revision },
                source, &draft, &facts).await?,
            (Some(old), None) => self.writer.store().forget_with_kg_tx(transaction, access, &id,
                old.memory_revision, source, &forget).await?,
            (None, None) => return Err(invalid("missing episodic mutation")),
        };
        let receipt = self.finish_prepared_mutation(transaction, prepared, queued, write).await?;
        receipt.validate()?;
        Ok(EpisodicMemoryBinding {
            source_id: source_id.clone(), key: key.clone(), version, record_id: record_id.clone(),
            memory_id: id.as_str().to_owned(), memory_revision: receipt.write.memory.id.revision,
            canonical_source_id: receipt.write.source.source_id.as_str().to_owned(),
            canonical_source_revision: receipt.write.source.revision, active: record.is_some(),
            source_admission_sha256: digest(&json!({ "source": source, "verification": verification }))?,
            source_content_sha256: receipt.source_content_sha256.as_str().to_owned(),
            mutation_receipt_sha256: receipt.receipt_sha256.as_str().to_owned(),
            mutation_commit_event_id: receipt.provenance_commit_event_id,
        })
    }
}

fn invalid(message: impl Into<String>) -> ProductionCognitiveMutationError {
    ProductionWriterError::Invalid(message.into()).into()
}

#[cfg(test)]
#[path = "production_episodic_tests.rs"]
mod tests;
