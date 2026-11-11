//! Atomic canonical owner synchronization of an admitted episodic namespace.
use std::collections::BTreeMap;

use serde_json::json;

use super::ProductionCognitiveMutationCapability;
use crate::AdmittedEpisodicSnapshot;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::EpisodicImportReceipt;
use crate::EpisodicSnapshotVerifier;
use crate::LocalAdmission;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::ProductionCognitiveMutationError;
use crate::ProductionWriterError;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;
use crate::episodic_source::invalid;
use crate::episodic_source::snapshot::MAX_BINDINGS;
use crate::episodic_source::snapshot::digest;

impl ProductionCognitiveMutationCapability {
    /// Synchronize at most 32 lifetime slots from the complete current namespace.
    /// Missing facts are withdrawn atomically with corrections, so a valid
    /// dependency-closed snapshot propagates update/revocation to descendants.
    /// V1 permanently retires a slot: even a valid later Python version is
    /// rejected. Reintroduction requires a separately authorized namespace or
    /// a future qualified native reconstruction path; this is narrower than
    /// the Python store's explicit write-after-revoke semantics.
    /// An identical retry reconciles the original receipt without another
    /// canonical memory revision.
    /// The final admission check is a read linearization point, not an external
    /// effect fence; callers still use ordinary owner revalidation for inference.
    pub async fn import_episodic_snapshot(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        snapshot_json: &str,
        admission: &dyn EpisodicSnapshotVerifier,
    ) -> Result<EpisodicImportReceipt, ProductionCognitiveMutationError> {
        let store = self.writer.store();
        store.authorize(access, scope)?;
        self.writer.verify_current_authority().await?;
        let verified = AdmittedEpisodicSnapshot::admit(snapshot_json, scope, admission)?;
        let snapshot = &verified.snapshot;
        let body = &snapshot.body;
        let admitted = &verified.admitted;
        let admission_sha256 = verified.admission_sha256.clone();
        let scope_binding = digest(&json!([store.owner_agent_id(), scope, body.namespace]))?;
        let topic = format!("cognitive.episodic.snapshot:{scope_binding}");
        // This lock outlives both the native transaction and its outcome guard.
        // An admitted import waiting here must recheck the original writer
        // after its predecessor either settles or permanently fences the pool.
        let _import = self.writer.episodic_imports.lock().await;
        self.writer.verify_current_authority().await?;
        let begin_attempt = store.commit_gate.transition_attempt();
        let mut transaction = store.begin_write_transaction().await.map_err(|source| {
            ProductionCognitiveMutationError::TransactionSettlementUnknown { operation: "begin", source }
        })?;
        // Move after transaction acquisition: panic drops this guard before
        // Transaction queues rollback, and before the import lock is released.
        let settlement = begin_attempt;
        let outcome = async {
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
                verified.revalidate()?;
                self.writer.verify_current_authority().await?;
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
        verified.revalidate()?;
        self.writer.verify_current_authority().await?;
        Ok(receipt)
        }.await;
        // Retained callers may release drain ownership only after SQLite has
        // acknowledged either the commit or the rollback. Drop only queues a
        // rollback and is not a settlement acknowledgement.
        match outcome {
            Ok(receipt) => {
                transaction.commit().await.map_err(|error| {
                    ProductionCognitiveMutationError::TransactionSettlementUnknown {
                        operation: "commit", source: unavailable(error),
                    }
                })?;
                settlement.acknowledge();
                Ok(receipt)
            }
            Err(error) => {
                transaction.rollback().await.map_err(|error| {
                    ProductionCognitiveMutationError::TransactionSettlementUnknown {
                        operation: "rollback", source: unavailable(error),
                    }
                })?;
                settlement.acknowledge();
                Err(error)
            }
        }
    }

}

#[path = "production_episodic_write.rs"]
mod write;

#[cfg(test)]
#[path = "production_episodic_test_support.rs"]
mod test_support;

#[cfg(test)]
#[path = "production_episodic_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "production_episodic_regression_tests.rs"]
mod regression_tests;
