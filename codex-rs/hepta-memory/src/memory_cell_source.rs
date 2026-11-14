//! Admission reads the actual durable owner; a self-consistent claim is insufficient.

use codex_hepta_cognitive_types::hnmf::MemoryLifecycleV1;
use codex_hepta_cognitive_types::hnmf::MemoryScopeV1;
use codex_hepta_cognitive_types::hnmf::MemoryVerificationStateV1;
use codex_hepta_cognitive_types::hnmf::ModalityKindV1;
use codex_hepta_cognitive_types::hnmf::RetentionPolicyV1;
use codex_hepta_cognitive_types::hnmf::SpanRangeV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::Digest32;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::MemoryCellDocumentV1;
use super::MemoryCellQueryV1;
use super::MemoryCellSourceBindingV1;
use super::MemoryCellSourceClaimV1;
use super::MemoryCellSourceError;
use super::ProductionCognitiveMutationCommitJournalV1;
use super::ProductionCognitiveMutationIntentJournalV1;
use super::ProductionDurableWriter;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::MemoryLifecycleState;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;

impl ProductionDurableWriter {
    pub(super) async fn memory_cell_source_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        query: &MemoryCellQueryV1,
        claim: &MemoryCellSourceClaimV1,
        now_unix_ms: u64,
    ) -> Result<MemoryCellSourceBindingV1, MemoryCellSourceError> {
        query.validate_at(now_unix_ms)?;
        let receipt = &claim.production;
        receipt.validate()?;
        let reject = MemoryCellSourceError::Invalid;
        let memory = self
            .store
            .latest_memory_tx(tx, access, &receipt.write.memory.id.memory_id)
            .await?;
        let expected_id = StableMemoryId::for_key(
            self.store.owner_agent_id(),
            &memory.scope,
            &query.key.stable_key()?,
        );
        let now_seconds = i64::try_from(now_unix_ms / 1000).map_err(|_| reject("clock"))?;
        if memory != receipt.write.memory
            || memory.id.memory_id != expected_id
            || memory.verification != MemoryVerification::Verified
            || memory.lifecycle != MemoryLifecycleState::Active
            || memory.valid_from_unix_seconds > now_seconds
            || memory
                .valid_to_unix_seconds
                .is_some_and(|end| end <= now_seconds)
            || receipt.owner_agent_id != *self.store.owner_agent_id()
            || memory.citations != vec![receipt.write.source.clone()]
            || memory.content_sha256 != Sha256Digest::for_bytes(memory.content.as_bytes())
        {
            return Err(reject("current source revision or typed identity"));
        }
        let document: MemoryCellDocumentV1 =
            serde_json::from_str(&memory.content).map_err(|_| reject("stored typed document"))?;
        document.validate()?;
        if document.key != query.key {
            return Err(reject("query key differs from stored key"));
        }

        let row =
            sqlx::query("SELECT * FROM source_ledger WHERE source_id = ? AND source_revision = ?")
                .bind(receipt.write.source.source_id.as_str())
                .bind(
                    i64::try_from(receipt.write.source.revision)
                        .map_err(|_| reject("source revision"))?,
                )
                .fetch_optional(&mut **tx)
                .await
                .map_err(unavailable)?
                .ok_or_else(|| reject("source absent"))?;
        let (scope_kind, workspace) = memory.scope.database_parts();
        let content: Vec<u8> = row.try_get("content").map_err(unavailable)?;
        if row
            .try_get::<String, _>("owner_agent_id")
            .map_err(unavailable)?
            != self.store.owner_agent_id().as_str()
            || row
                .try_get::<String, _>("scope_kind")
                .map_err(unavailable)?
                != scope_kind
            || row
                .try_get::<Option<String>, _>("workspace_sha256")
                .map_err(unavailable)?
                .as_deref()
                != workspace
            || row
                .try_get::<String, _>("content_sha256")
                .map_err(unavailable)?
                != receipt.source_content_sha256.as_str()
            || Sha256Digest::for_bytes(&content) != receipt.source_content_sha256
            || row
                .try_get::<i64, _>("observed_at_unix_seconds")
                .map_err(unavailable)?
                != receipt.source_observed_at_unix_seconds
            || content != memory.content.as_bytes()
        {
            return Err(reject("durable source bytes or scope"));
        }
        self.memory_cell_journal_tx(tx, claim).await?;
        let event = &claim.event;
        event.validate().map_err(|_| reject("HNMF event"))?;
        let scope_matches = match (&event.scope, &memory.scope) {
            (MemoryScopeV1::AgentPrivate { agent_id }, CognitiveScope::AgentPrivate) => {
                agent_id.as_str() == receipt.owner_agent_id.as_str()
            }
            (
                MemoryScopeV1::WorkspacePrivate {
                    agent_id,
                    workspace_sha256,
                },
                CognitiveScope::WorkspacePrivate {
                    workspace_sha256: expected,
                },
            ) => {
                agent_id.as_str() == receipt.owner_agent_id.as_str()
                    && workspace_sha256.to_string() == expected.as_str()
            }
            _ => false,
        };
        if !scope_matches
            || event.verification != MemoryVerificationStateV1::Verified
            || event.lifecycle != MemoryLifecycleV1::Active
            || event.provenance.len() != 1
            || event.semantic_keys != [query.key.stable_key()?].into_iter().collect()
            || event.modality_spans.len() != 1
            || !event.cross_modal_bindings.is_empty()
        {
            return Err(reject("HNMF source profile"));
        }
        match event.retention_policy {
            RetentionPolicyV1::Persistent {
                retain_until_unix_ms,
            } if retain_until_unix_ms.is_none_or(|end| end > now_unix_ms) => {}
            _ => return Err(reject("HNMF persistent source expired or unsupported")),
        }
        let provenance = &event.provenance[0];
        let observed_ms = u64::try_from(receipt.source_observed_at_unix_seconds)
            .ok()
            .and_then(|seconds| seconds.checked_mul(1000))
            .ok_or_else(|| reject("source time"))?;
        let span = &event.modality_spans[0];
        if provenance.source_id.as_str() != receipt.write.source.source_id.as_str()
            || provenance.source_revision != receipt.write.source.revision
            || provenance.source_sha256.to_string() != receipt.source_content_sha256.as_str()
            || provenance.observed_at_unix_ms != observed_ms
            || event.observed_interval.start_unix_ms != observed_ms
            || span.modality != ModalityKindV1::Text
            || span.asset_sha256.to_string() != receipt.source_content_sha256.as_str()
            || span.range
                != (SpanRangeV1::ByteRange {
                    start: 0,
                    end: content.len() as u64,
                })
        {
            return Err(reject("HNMF provenance differs from owner source"));
        }
        let mut binding = MemoryCellSourceBindingV1 {
            memory: memory.id,
            memory_content_sha256: memory.content_sha256,
            source_content_sha256: receipt.source_content_sha256.clone(),
            event_digest: canonical_contract_digest_v1(event)
                .map_err(|_| reject("HNMF encoding"))?,
            production_receipt_digest: receipt.receipt_sha256.clone(),
            query_digest: query.digest()?,
            binding_digest: Digest32::ZERO,
        };
        binding.bind()?;
        Ok(binding)
    }

    async fn memory_cell_journal_tx(
        &self,
        tx: &mut Transaction<'_, Sqlite>,
        claim: &MemoryCellSourceClaimV1,
    ) -> Result<(), MemoryCellSourceError> {
        let r = &claim.production;
        let reject = MemoryCellSourceError::Invalid;
        let occurrence = format!("cognitive-mutation:{}", r.operation_digest.as_str());
        let intent = serde_json::to_string(&ProductionCognitiveMutationIntentJournalV1 {
            schema_version: r.schema_version,
            namespace: super::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE,
            mutation_kind: &r.mutation_kind,
            operation_digest: &r.operation_digest,
            input_payload_sha256: &r.input_payload_sha256,
            expected_predecessor_revision: r.expected_predecessor_revision,
            authority_grant_digest: &r.authority_grant_digest,
            authority_epoch: r.authority_epoch,
            owner_epoch: r.owner_epoch,
            lease_id: &r.lease_id,
            generation: r.generation,
            owner_agent_id: r.owner_agent_id.as_str(),
        })
        .map_err(|_| reject("intent encoding"))?;
        let commit = serde_json::to_string(&ProductionCognitiveMutationCommitJournalV1 {
            schema_version: r.schema_version,
            namespace: super::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE,
            operation_digest: &r.operation_digest,
            write_digest: &r.write_digest,
            source_content_sha256: &r.source_content_sha256,
            source_observed_at_unix_seconds: r.source_observed_at_unix_seconds,
            memory_id: r.write.memory.id.memory_id.as_str(),
            memory_revision: r.write.memory.id.revision,
            source_id: r.write.source.source_id.as_str(),
            source_revision: r.write.source.revision,
            projection_output_sha256: &r.write.projection.output_sha256,
        })
        .map_err(|_| reject("commit encoding"))?;
        for (id, kind, expected) in [
            (&r.provenance_event_id, "admitted", &intent),
            (
                &r.provenance_commit_event_id,
                "reconcile_committed",
                &commit,
            ),
        ] {
            let found: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_events WHERE event_id = ? AND event_kind = ? AND owner_agent_id = ? AND lease_id = ? AND generation = ? AND occurrence_key = ? AND payload_json = ? AND payload_sha256 = ?")
                .bind(id).bind(kind).bind(r.owner_agent_id.as_str()).bind(&r.lease_id)
                .bind(i64::try_from(r.generation).map_err(|_| reject("generation"))?)
                .bind(&occurrence).bind(expected).bind(Sha256Digest::for_bytes(expected.as_bytes()).as_str())
                .fetch_one(&mut **tx).await.map_err(unavailable)?;
            if found != 1 {
                return Err(reject("production event not in owner journal"));
            }
        }
        let found: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox WHERE outbox_id = ? AND event_id = ? AND lease_id = ? AND owner_agent_id = ? AND occurrence_key = ? AND topic = ? AND payload_json = ?")
            .bind(&r.provenance_outbox_id).bind(&r.provenance_event_id).bind(&r.lease_id)
            .bind(r.owner_agent_id.as_str()).bind(&occurrence).bind(super::PRODUCTION_COGNITIVE_MUTATION_TOPIC).bind(intent)
            .fetch_one(&mut **tx).await.map_err(unavailable)?;
        if found != 1 {
            return Err(reject("production outbox not in owner journal"));
        }
        Ok(())
    }
}
