use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::SqlitePool;
use sqlx::Transaction;

use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::CognitiveWriteReceipt;
use crate::ForgetMemoryDraft;
use crate::KgFactSetDraft;
use crate::MemoryDraft;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionDraft;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::SourceDraft;
use crate::SourceRevisionId;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

const EXTRACTOR_CONTRACT: &str = "structured_cognitive_kg_v1";
pub(crate) const LEGACY_ZERO_FACT_CONTRACT: &str = "legacy_memory_api_zero_v1";
const MAX_ENTITIES: usize = 64;
const MAX_RELATIONS: usize = 128;
const MAX_KEY_BYTES: usize = 256;
const MAX_TYPE_BYTES: usize = 128;
const MAX_LABEL_BYTES: usize = 1024;
const MAX_RELATION_BYTES: usize = 128;

#[derive(Clone, Debug)]
pub(crate) struct CanonicalEntityFact {
    pub(crate) key: String,
    pub(crate) canonical_entity_id: String,
    pub(crate) entity_type: String,
    pub(crate) label: String,
}

#[derive(Clone, Debug)]
pub(crate) struct CanonicalRelationFact {
    pub(crate) key: String,
    pub(crate) canonical_relation_id: String,
    pub(crate) from_entity_key: String,
    pub(crate) from_canonical_entity_id: String,
    pub(crate) to_entity_key: String,
    pub(crate) to_canonical_entity_id: String,
    pub(crate) relation: String,
}

#[derive(Clone, Debug)]
pub(crate) struct CanonicalFactSet {
    pub(crate) extractor_contract: &'static str,
    pub(crate) digest: Sha256Digest,
    pub(crate) entities: Vec<CanonicalEntityFact>,
    pub(crate) relations: Vec<CanonicalRelationFact>,
}

impl CognitiveStore {
    /// Atomically appends the cited source, creates the first memory revision,
    /// persists its immutable structured facts, and publishes the next complete
    /// scope projection. Any failure rolls the entire write back.
    pub async fn remember_with_kg(
        &self,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        validate_source_binding(source, &draft.revision.scope, &draft.revision.content)?;
        if draft.revision.lifecycle != MemoryLifecycleState::Active {
            return Err(CognitiveStoreError::Invalid(
                "remember requires an active memory revision".to_string(),
            ));
        }
        validate_fact_eligibility(&draft.revision, facts)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let citation = self
            .append_source_tx(&mut transaction, access, source)
            .await?;
        let mut bound_draft = draft.clone();
        bind_exact_citation(&mut bound_draft.revision, &citation)?;
        let memory = self
            .create_memory_revision_tx(&mut transaction, access, &bound_draft)
            .await?;
        let canonical =
            self.canonicalize_fact_set(&memory, &citation, facts, EXTRACTOR_CONTRACT)?;
        self.insert_revision_facts_tx(&mut transaction, &memory, &citation, &canonical)
            .await?;
        let projection = self
            .refresh_scope_projection_tx(
                &mut transaction,
                &memory.scope,
                &memory,
                &citation,
                &canonical,
            )
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(CognitiveWriteReceipt {
            memory,
            source: citation,
            projection,
        })
    }

    /// Atomically appends one compare-and-swap correction and replaces the
    /// corrected revision's projected facts. Tombstoned heads cannot be
    /// resurrected through this path.
    pub async fn correct_with_kg(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        facts: &KgFactSetDraft,
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        validate_source_binding(source, &draft.scope, &draft.content)?;
        if draft.verification != MemoryVerification::Verified
            || draft.lifecycle != MemoryLifecycleState::Active
        {
            return Err(CognitiveStoreError::Invalid(
                "correction requires a verified active memory revision".to_string(),
            ));
        }
        validate_fact_eligibility(draft, facts)?;
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let citation = self
            .append_source_tx(&mut transaction, access, source)
            .await?;
        let mut bound_draft = draft.clone();
        bind_exact_citation(&mut bound_draft, &citation)?;
        let memory = self
            .revise_memory_revision_tx(
                &mut transaction,
                access,
                memory_id,
                expected_revision,
                &bound_draft,
            )
            .await?;
        let canonical =
            self.canonicalize_fact_set(&memory, &citation, facts, EXTRACTOR_CONTRACT)?;
        self.insert_revision_facts_tx(&mut transaction, &memory, &citation, &canonical)
            .await?;
        let projection = self
            .refresh_scope_projection_tx(
                &mut transaction,
                &memory.scope,
                &memory,
                &citation,
                &canonical,
            )
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(CognitiveWriteReceipt {
            memory,
            source: citation,
            projection,
        })
    }

    /// Atomically appends a tombstone and publishes a projection that excludes
    /// the withdrawn head. The tombstone still receives an explicit zero-fact
    /// receipt so composition cannot be confused with a writer that never ran.
    pub async fn forget_with_kg(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &ForgetMemoryDraft,
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        validate_source_binding(source, &draft.scope, &draft.reason)?;
        let revision = MemoryRevisionDraft {
            scope: draft.scope.clone(),
            content: "Memory withdrawn by explicit user request.".to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Tombstoned {
                reason: draft.reason.clone(),
            },
            valid_from_unix_seconds: draft.valid_from_unix_seconds,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        };
        let facts = KgFactSetDraft::default();
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let citation = self
            .append_source_tx(&mut transaction, access, source)
            .await?;
        let mut bound_revision = revision;
        bind_exact_citation(&mut bound_revision, &citation)?;
        let memory = self
            .revise_memory_revision_tx(
                &mut transaction,
                access,
                memory_id,
                expected_revision,
                &bound_revision,
            )
            .await?;
        let canonical =
            self.canonicalize_fact_set(&memory, &citation, &facts, EXTRACTOR_CONTRACT)?;
        self.insert_revision_facts_tx(&mut transaction, &memory, &citation, &canonical)
            .await?;
        let projection = self
            .refresh_scope_projection_tx(
                &mut transaction,
                &memory.scope,
                &memory,
                &citation,
                &canonical,
            )
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(CognitiveWriteReceipt {
            memory,
            source: citation,
            projection,
        })
    }

    pub(crate) fn canonicalize_fact_set(
        &self,
        memory: &MemoryRevisionRecord,
        source: &SourceRevisionId,
        draft: &KgFactSetDraft,
        extractor_contract: &'static str,
    ) -> Result<CanonicalFactSet, CognitiveStoreError> {
        if draft.entities.len() > MAX_ENTITIES || draft.relations.len() > MAX_RELATIONS {
            return Err(CognitiveStoreError::Invalid(format!(
                "structured KG exceeds {MAX_ENTITIES} entities or {MAX_RELATIONS} relations"
            )));
        }
        let mut entities_by_key = BTreeMap::new();
        for entity in &draft.entities {
            let key = canonical_token(&entity.key, MAX_KEY_BYTES, "KG entity key")?;
            let entity_type =
                canonical_token(&entity.entity_type, MAX_TYPE_BYTES, "KG entity type")?;
            let label = canonical_text(&entity.label, MAX_LABEL_BYTES, "KG entity label")?;
            let canonical_entity_id =
                canonical_entity_id(&self.owner_agent_id, &memory.scope, &key);
            if entities_by_key
                .insert(
                    key.clone(),
                    CanonicalEntityFact {
                        key: key.clone(),
                        canonical_entity_id,
                        entity_type,
                        label,
                    },
                )
                .is_some()
            {
                return Err(CognitiveStoreError::Invalid(format!(
                    "duplicate KG entity key `{key}`"
                )));
            }
        }
        let mut relation_keys = BTreeSet::new();
        let mut relations = Vec::with_capacity(draft.relations.len());
        for relation in &draft.relations {
            let key = canonical_token(&relation.key, MAX_KEY_BYTES, "KG relation key")?;
            if !relation_keys.insert(key.clone()) {
                return Err(CognitiveStoreError::Invalid(format!(
                    "duplicate KG relation key `{key}`"
                )));
            }
            let from_entity_key = canonical_token(
                &relation.from_entity_key,
                MAX_KEY_BYTES,
                "KG relation source key",
            )?;
            let to_entity_key = canonical_token(
                &relation.to_entity_key,
                MAX_KEY_BYTES,
                "KG relation target key",
            )?;
            let relation_name = canonical_token(
                &relation.relation,
                MAX_RELATION_BYTES,
                "KG relation predicate",
            )?;
            let from = entities_by_key.get(&from_entity_key).ok_or_else(|| {
                CognitiveStoreError::Invalid(format!(
                    "KG relation `{key}` has an undeclared source endpoint"
                ))
            })?;
            let to = entities_by_key.get(&to_entity_key).ok_or_else(|| {
                CognitiveStoreError::Invalid(format!(
                    "KG relation `{key}` has an undeclared target endpoint"
                ))
            })?;
            relations.push(CanonicalRelationFact {
                key,
                canonical_relation_id: canonical_relation_id(
                    &self.owner_agent_id,
                    &memory.scope,
                    &from.canonical_entity_id,
                    &relation_name,
                    &to.canonical_entity_id,
                ),
                from_entity_key,
                from_canonical_entity_id: from.canonical_entity_id.clone(),
                to_entity_key,
                to_canonical_entity_id: to.canonical_entity_id.clone(),
                relation: relation_name,
            });
        }
        let entities = entities_by_key.into_values().collect::<Vec<_>>();
        relations.sort_by(|left, right| left.key.cmp(&right.key));
        let digest = fact_set_digest_from_parts(FactSetDigestParts {
            memory_id: memory.id.memory_id.as_str(),
            memory_revision: memory.id.revision,
            content_sha256: memory.content_sha256.as_str(),
            source_id: source.source_id.as_str(),
            source_revision: source.revision,
            extractor_contract,
            entities: &entities,
            relations: &relations,
        });
        Ok(CanonicalFactSet {
            extractor_contract,
            digest,
            entities,
            relations,
        })
    }

    pub(crate) async fn insert_revision_facts_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        memory: &MemoryRevisionRecord,
        source: &SourceRevisionId,
        facts: &CanonicalFactSet,
    ) -> Result<(), CognitiveStoreError> {
        let revision = to_i64(memory.id.revision, "memory revision")?;
        let source_revision = to_i64(source.revision, "source revision")?;
        sqlx::query(
            "INSERT INTO kg_revision_fact_sets (
                memory_id, memory_revision, extractor_contract, fact_set_sha256,
                source_id, source_revision, entity_count, relation_count,
                recorded_at_unix_seconds
             ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, unixepoch())",
        )
        .bind(memory.id.memory_id.as_str())
        .bind(revision)
        .bind(facts.extractor_contract)
        .bind(facts.digest.as_str())
        .bind(source.source_id.as_str())
        .bind(source_revision)
        .bind(to_i64_len(facts.entities.len(), "entity count")?)
        .bind(to_i64_len(facts.relations.len(), "relation count")?)
        .execute(&mut **transaction)
        .await
        .map_err(unavailable)?;
        for entity in &facts.entities {
            sqlx::query(
                "INSERT INTO kg_revision_entities (
                    memory_id, memory_revision, entity_key, canonical_entity_id,
                    entity_type, label, valid_from_unix_seconds,
                    valid_to_unix_seconds, source_id, source_revision
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(memory.id.memory_id.as_str())
            .bind(revision)
            .bind(&entity.key)
            .bind(&entity.canonical_entity_id)
            .bind(&entity.entity_type)
            .bind(&entity.label)
            .bind(memory.valid_from_unix_seconds)
            .bind(memory.valid_to_unix_seconds)
            .bind(source.source_id.as_str())
            .bind(source_revision)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        }
        for relation in &facts.relations {
            sqlx::query(
                "INSERT INTO kg_revision_relations (
                    memory_id, memory_revision, relation_key, canonical_relation_id,
                    from_entity_key, from_canonical_entity_id, to_entity_key,
                    to_canonical_entity_id, relation, valid_from_unix_seconds,
                    valid_to_unix_seconds, source_id, source_revision
                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            )
            .bind(memory.id.memory_id.as_str())
            .bind(revision)
            .bind(&relation.key)
            .bind(&relation.canonical_relation_id)
            .bind(&relation.from_entity_key)
            .bind(&relation.from_canonical_entity_id)
            .bind(&relation.to_entity_key)
            .bind(&relation.to_canonical_entity_id)
            .bind(&relation.relation)
            .bind(memory.valid_from_unix_seconds)
            .bind(memory.valid_to_unix_seconds)
            .bind(source.source_id.as_str())
            .bind(source_revision)
            .execute(&mut **transaction)
            .await
            .map_err(unavailable)?;
        }
        Ok(())
    }
}

pub(crate) async fn verify_revision_fact_digests(
    pool: &SqlitePool,
    owner: &codex_hepta_contracts::AgentId,
) -> Result<(), CognitiveStoreError> {
    let rows = sqlx::query(
        "SELECT s.memory_id, s.memory_revision, s.extractor_contract,
                s.fact_set_sha256, s.source_id, s.source_revision,
                s.entity_count, s.relation_count, m.content_sha256,
                m.scope_kind, m.workspace_sha256
         FROM kg_revision_fact_sets s
         JOIN memory_revisions m
           ON m.memory_id = s.memory_id AND m.revision = s.memory_revision
         WHERE m.owner_agent_id = ?
         ORDER BY s.memory_id, s.memory_revision",
    )
    .bind(owner.as_str())
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    for row in rows {
        let extractor_contract: String = row.try_get("extractor_contract").map_err(unavailable)?;
        if extractor_contract == "legacy_pre_g3_empty_v1" {
            continue;
        }
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let memory_revision_i64: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        let memory_revision = u64::try_from(memory_revision_i64).map_err(|_| {
            CognitiveStoreError::Corrupt("negative KG fact-set memory revision".to_string())
        })?;
        let source_id: String = row.try_get("source_id").map_err(unavailable)?;
        let source_revision_i64: i64 = row.try_get("source_revision").map_err(unavailable)?;
        let source_revision = u64::try_from(source_revision_i64).map_err(|_| {
            CognitiveStoreError::Corrupt("negative KG fact-set source revision".to_string())
        })?;
        let scope = CognitiveScope::parse(
            row.try_get("scope_kind").map_err(unavailable)?,
            row.try_get("workspace_sha256").map_err(unavailable)?,
        )
        .map_err(CognitiveStoreError::Corrupt)?;
        let entity_rows = sqlx::query(
            "SELECT entity_key, canonical_entity_id, entity_type, label,
                    source_id, source_revision
             FROM kg_revision_entities
             WHERE memory_id = ? AND memory_revision = ?
             ORDER BY entity_key",
        )
        .bind(&memory_id)
        .bind(memory_revision_i64)
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
        let declared_entities: i64 = row.try_get("entity_count").map_err(unavailable)?;
        if declared_entities != to_i64_len(entity_rows.len(), "entity count")? {
            return Err(CognitiveStoreError::Corrupt(
                "KG fact-set entity count changed after publication".to_string(),
            ));
        }
        let mut entities = Vec::with_capacity(entity_rows.len());
        for entity in entity_rows {
            let key: String = entity.try_get("entity_key").map_err(unavailable)?;
            let canonical_id: String =
                entity.try_get("canonical_entity_id").map_err(unavailable)?;
            if canonical_id != canonical_entity_id(owner, &scope, &key) {
                return Err(CognitiveStoreError::Corrupt(
                    "stored KG entity identity failed canonical recomputation".to_string(),
                ));
            }
            if entity
                .try_get::<String, _>("source_id")
                .map_err(unavailable)?
                != source_id
                || entity
                    .try_get::<i64, _>("source_revision")
                    .map_err(unavailable)?
                    != source_revision_i64
            {
                return Err(CognitiveStoreError::Corrupt(
                    "KG entity fact does not bind the fact-set citation".to_string(),
                ));
            }
            entities.push(CanonicalEntityFact {
                key,
                canonical_entity_id: canonical_id,
                entity_type: entity.try_get("entity_type").map_err(unavailable)?,
                label: entity.try_get("label").map_err(unavailable)?,
            });
        }
        let relation_rows = sqlx::query(
            "SELECT relation_key, canonical_relation_id, from_entity_key,
                    from_canonical_entity_id, to_entity_key,
                    to_canonical_entity_id, relation, source_id, source_revision
             FROM kg_revision_relations
             WHERE memory_id = ? AND memory_revision = ?
             ORDER BY relation_key",
        )
        .bind(&memory_id)
        .bind(memory_revision_i64)
        .fetch_all(pool)
        .await
        .map_err(unavailable)?;
        let declared_relations: i64 = row.try_get("relation_count").map_err(unavailable)?;
        if declared_relations != to_i64_len(relation_rows.len(), "relation count")? {
            return Err(CognitiveStoreError::Corrupt(
                "KG fact-set relation count changed after publication".to_string(),
            ));
        }
        let mut relations = Vec::with_capacity(relation_rows.len());
        for relation_row in relation_rows {
            let from_canonical_entity_id: String = relation_row
                .try_get("from_canonical_entity_id")
                .map_err(unavailable)?;
            let to_canonical_entity_id: String = relation_row
                .try_get("to_canonical_entity_id")
                .map_err(unavailable)?;
            let relation: String = relation_row.try_get("relation").map_err(unavailable)?;
            let canonical_id: String = relation_row
                .try_get("canonical_relation_id")
                .map_err(unavailable)?;
            if canonical_id
                != canonical_relation_id(
                    owner,
                    &scope,
                    &from_canonical_entity_id,
                    &relation,
                    &to_canonical_entity_id,
                )
            {
                return Err(CognitiveStoreError::Corrupt(
                    "stored KG relation identity failed canonical recomputation".to_string(),
                ));
            }
            if relation_row
                .try_get::<String, _>("source_id")
                .map_err(unavailable)?
                != source_id
                || relation_row
                    .try_get::<i64, _>("source_revision")
                    .map_err(unavailable)?
                    != source_revision_i64
            {
                return Err(CognitiveStoreError::Corrupt(
                    "KG relation fact does not bind the fact-set citation".to_string(),
                ));
            }
            relations.push(CanonicalRelationFact {
                key: relation_row.try_get("relation_key").map_err(unavailable)?,
                canonical_relation_id: canonical_id,
                from_entity_key: relation_row
                    .try_get("from_entity_key")
                    .map_err(unavailable)?,
                from_canonical_entity_id,
                to_entity_key: relation_row.try_get("to_entity_key").map_err(unavailable)?,
                to_canonical_entity_id,
                relation,
            });
        }
        let content_sha256 = row
            .try_get::<String, _>("content_sha256")
            .map_err(unavailable)?;
        let expected = fact_set_digest_from_parts(FactSetDigestParts {
            memory_id: &memory_id,
            memory_revision,
            content_sha256: &content_sha256,
            source_id: &source_id,
            source_revision,
            extractor_contract: &extractor_contract,
            entities: &entities,
            relations: &relations,
        });
        let stored: String = row.try_get("fact_set_sha256").map_err(unavailable)?;
        if expected.as_str() != stored {
            return Err(CognitiveStoreError::Corrupt(
                "KG fact-set digest failed canonical recomputation".to_string(),
            ));
        }
    }
    let active_shapes = sqlx::query(
        "SELECT r.scope_kind, r.workspace_sha256, e.canonical_entity_id,
                e.entity_type, e.label
         FROM memory_heads h
         JOIN memory_revisions r
           ON r.memory_id = h.memory_id AND r.revision = h.revision
         JOIN kg_revision_entities e
           ON e.memory_id = r.memory_id AND e.memory_revision = r.revision
         WHERE r.owner_agent_id = ? AND r.verification = 'verified'
           AND r.lifecycle = 'active'
         ORDER BY r.scope_kind, r.workspace_sha256, e.canonical_entity_id",
    )
    .bind(owner.as_str())
    .fetch_all(pool)
    .await
    .map_err(unavailable)?;
    let mut shapes = BTreeMap::<(String, String), (String, String)>::new();
    for row in active_shapes {
        let scope = CognitiveScope::parse(
            row.try_get("scope_kind").map_err(unavailable)?,
            row.try_get("workspace_sha256").map_err(unavailable)?,
        )
        .map_err(CognitiveStoreError::Corrupt)?;
        let key = (
            scope.projection_key(),
            row.try_get("canonical_entity_id").map_err(unavailable)?,
        );
        let shape = (
            row.try_get("entity_type").map_err(unavailable)?,
            row.try_get("label").map_err(unavailable)?,
        );
        if shapes
            .insert(key.clone(), shape.clone())
            .is_some_and(|old| old != shape)
        {
            return Err(CognitiveStoreError::Corrupt(format!(
                "current KG supports disagree on canonical entity {}",
                key.1
            )));
        }
    }
    Ok(())
}

fn validate_source_binding(
    source: &SourceDraft,
    scope: &CognitiveScope,
    expected_content: &str,
) -> Result<(), CognitiveStoreError> {
    if &source.scope != scope {
        return Err(CognitiveStoreError::AccessDenied(
            "source and memory revision must have the same scope".to_string(),
        ));
    }
    if source.content != expected_content.as_bytes() {
        return Err(CognitiveStoreError::Invalid(
            "source content must exactly bind the product mutation input".to_string(),
        ));
    }
    Ok(())
}

fn validate_fact_eligibility(
    revision: &MemoryRevisionDraft,
    facts: &KgFactSetDraft,
) -> Result<(), CognitiveStoreError> {
    if (revision.verification != MemoryVerification::Verified
        || revision.lifecycle != MemoryLifecycleState::Active)
        && (!facts.entities.is_empty() || !facts.relations.is_empty())
    {
        return Err(CognitiveStoreError::Invalid(
            "only verified active memory revisions may carry structured KG facts".to_string(),
        ));
    }
    Ok(())
}

fn bind_exact_citation(
    revision: &mut MemoryRevisionDraft,
    citation: &SourceRevisionId,
) -> Result<(), CognitiveStoreError> {
    if !revision.citations.is_empty() {
        return Err(CognitiveStoreError::Invalid(
            "product cognitive writer owns the exact source citation set".to_string(),
        ));
    }
    revision.citations.push(citation.clone());
    Ok(())
}

fn canonical_token(
    value: &str,
    max_bytes: usize,
    label: &str,
) -> Result<String, CognitiveStoreError> {
    let value = canonical_text(value, max_bytes, label)?.to_ascii_lowercase();
    if value.len() > max_bytes {
        return Err(CognitiveStoreError::Invalid(format!(
            "{label} exceeds {max_bytes} bytes after canonicalization"
        )));
    }
    Ok(value)
}

fn canonical_text(
    value: &str,
    max_bytes: usize,
    label: &str,
) -> Result<String, CognitiveStoreError> {
    if value.as_bytes().contains(&0) {
        return Err(CognitiveStoreError::Invalid(format!(
            "{label} contains a NUL byte"
        )));
    }
    let value = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if value.is_empty() || value.len() > max_bytes {
        return Err(CognitiveStoreError::Invalid(format!(
            "{label} must contain 1..={max_bytes} bytes"
        )));
    }
    Ok(value)
}

pub(crate) fn canonical_entity_id(
    owner: &codex_hepta_contracts::AgentId,
    scope: &CognitiveScope,
    key: &str,
) -> String {
    format!(
        "kg-entity:v1:{}",
        framed_digest(
            b"hepta:cognitive:kg-entity:v1",
            &[
                owner.as_str().as_bytes(),
                scope.projection_key().as_bytes(),
                key.as_bytes(),
            ],
        )
        .as_str()
    )
}

pub(crate) fn canonical_relation_id(
    owner: &codex_hepta_contracts::AgentId,
    scope: &CognitiveScope,
    from_entity_id: &str,
    relation: &str,
    to_entity_id: &str,
) -> String {
    format!(
        "kg-relation:v1:{}",
        framed_digest(
            b"hepta:cognitive:kg-relation:v1",
            &[
                owner.as_str().as_bytes(),
                scope.projection_key().as_bytes(),
                from_entity_id.as_bytes(),
                relation.as_bytes(),
                to_entity_id.as_bytes(),
            ],
        )
        .as_str()
    )
}

pub(crate) fn occurrence_node_id(memory: &str, revision: i64, entity_key: &str) -> String {
    format!(
        "kg-node:v1:{}",
        framed_digest(
            b"hepta:cognitive:kg-node-occurrence:v1",
            &[
                memory.as_bytes(),
                &revision.to_be_bytes(),
                entity_key.as_bytes()
            ],
        )
        .as_str()
    )
}

pub(crate) fn occurrence_edge_id(memory: &str, revision: i64, relation_key: &str) -> String {
    format!(
        "kg-edge:v1:{}",
        framed_digest(
            b"hepta:cognitive:kg-edge-occurrence:v1",
            &[
                memory.as_bytes(),
                &revision.to_be_bytes(),
                relation_key.as_bytes(),
            ],
        )
        .as_str()
    )
}

struct FactSetDigestParts<'a> {
    memory_id: &'a str,
    memory_revision: u64,
    content_sha256: &'a str,
    source_id: &'a str,
    source_revision: u64,
    extractor_contract: &'a str,
    entities: &'a [CanonicalEntityFact],
    relations: &'a [CanonicalRelationFact],
}

fn fact_set_digest_from_parts(parts: FactSetDigestParts<'_>) -> Sha256Digest {
    let FactSetDigestParts {
        memory_id,
        memory_revision,
        content_sha256,
        source_id,
        source_revision,
        extractor_contract,
        entities,
        relations,
    } = parts;
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, b"hepta:cognitive:kg-fact-set:v1");
    frame_part(&mut hasher, memory_id.as_bytes());
    frame_part(&mut hasher, &memory_revision.to_be_bytes());
    frame_part(&mut hasher, content_sha256.as_bytes());
    frame_part(&mut hasher, extractor_contract.as_bytes());
    frame_part(&mut hasher, source_id.as_bytes());
    frame_part(&mut hasher, &source_revision.to_be_bytes());
    frame_part(
        &mut hasher,
        &u64::try_from(entities.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for entity in entities {
        frame_part(&mut hasher, entity.key.as_bytes());
        frame_part(&mut hasher, entity.canonical_entity_id.as_bytes());
        frame_part(&mut hasher, entity.entity_type.as_bytes());
        frame_part(&mut hasher, entity.label.as_bytes());
    }
    frame_part(
        &mut hasher,
        &u64::try_from(relations.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    for relation in relations {
        frame_part(&mut hasher, relation.key.as_bytes());
        frame_part(&mut hasher, relation.canonical_relation_id.as_bytes());
        frame_part(&mut hasher, relation.from_entity_key.as_bytes());
        frame_part(&mut hasher, relation.from_canonical_entity_id.as_bytes());
        frame_part(&mut hasher, relation.to_entity_key.as_bytes());
        frame_part(&mut hasher, relation.to_canonical_entity_id.as_bytes());
        frame_part(&mut hasher, relation.relation.as_bytes());
    }
    finish_digest(hasher)
}

pub(crate) fn framed_digest(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut hasher = Sha256::new();
    frame_part(&mut hasher, domain);
    for part in parts {
        frame_part(&mut hasher, part);
    }
    finish_digest(hasher)
}

fn finish_digest(hasher: Sha256) -> Sha256Digest {
    Sha256Digest::from_sha256_output(hasher.finalize())
}

fn to_i64(value: u64, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}

fn to_i64_len(value: usize, label: &str) -> Result<i64, CognitiveStoreError> {
    i64::try_from(value).map_err(|_| CognitiveStoreError::Invalid(format!("{label} exceeds i64")))
}
