//! Canonical semantic mutations inside the bridge's original owner transaction.
use serde_json::json;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::ProductionCognitiveMutationCapability;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::EpisodicMemoryBinding;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryVerification;
use crate::ProductionCognitiveMutationError;
use crate::SourceDraft;
use crate::StableMemoryId;
use crate::episodic_source::invalid;
use crate::episodic_source::snapshot::Record;
use crate::episodic_source::snapshot::digest;

impl ProductionCognitiveMutationCapability {
    #[allow(clippy::too_many_arguments)]
    pub(super) async fn commit_episodic_record(
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
