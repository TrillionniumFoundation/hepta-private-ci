//! One bounded, parameterized assertion query in the existing owner transaction.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use super::ObservedRetrievalCandidate;
use super::proposition::OwnerPolarity;
use super::proposition::OwnerProposition;
use crate::CognitiveStoreError;
use crate::cognitive_intelligence_writer::ASSERTED_PREDICATE_PREFIX;
use crate::cognitive_intelligence_writer::ASSERTION_CONTRACT;
use crate::cognitive_intelligence_writer::DENIED_PREDICATE_PREFIX;
use crate::cognitive_store::unavailable;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Digest32;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use sqlx::QueryBuilder;
use sqlx::Row;
use sqlx::Sqlite;
use sqlx::Transaction;

pub(super) async fn read_assertions(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    observed: &[ObservedRetrievalCandidate],
) -> Result<Vec<OwnerProposition>, CognitiveStoreError> {
    if observed.is_empty() {
        return Ok(Vec::new());
    }
    if observed.len()
        > super::MAX_RETRIEVAL_OWNER_CHANNELS * super::MAX_RETRIEVAL_CHANNEL_CANDIDATES
    {
        return Err(CognitiveStoreError::Invalid(
            "owner assertion candidate limit".to_string(),
        ));
    }
    let mut bindings = BTreeMap::new();
    for candidate in observed {
        let binding = &candidate.revalidation;
        let revision = i64::try_from(binding.memory.revision)
            .map_err(|_| CognitiveStoreError::Corrupt("assertion revision overflow".to_string()))?;
        let key = (binding.memory.memory_id.as_str().to_string(), revision);
        if bindings.insert(key, binding).is_some() {
            return Err(CognitiveStoreError::Corrupt(
                "duplicate assertion candidate revision".to_string(),
            ));
        }
    }
    // At most 224 exact revisions, hence at most 448 identity binds plus one
    // contract bind. No record IDs or source text are interpolated into SQL.
    let mut query = QueryBuilder::<Sqlite>::new("WITH observed(memory_id, memory_revision) AS (");
    query.push_values(bindings.keys(), |mut row, (memory_id, revision)| {
        row.push_bind(memory_id).push_bind(*revision);
    });
    query.push(
        ") SELECT s.memory_id, s.memory_revision, r.from_canonical_entity_id, \
        r.to_canonical_entity_id, r.relation, r.canonical_relation_id, \
        r.valid_from_unix_seconds, r.valid_to_unix_seconds, r.source_id, \
        r.source_revision, s.fact_set_sha256 \
        FROM observed o JOIN kg_revision_fact_sets s \
          ON s.memory_id = o.memory_id AND s.memory_revision = o.memory_revision \
        JOIN kg_revision_relations r \
          ON r.memory_id = s.memory_id AND r.memory_revision = s.memory_revision \
        WHERE s.extractor_contract = ",
    );
    query.push_bind(ASSERTION_CONTRACT);
    query.push(" ORDER BY s.memory_id, s.memory_revision, r.relation_key LIMIT 4097");
    let rows = query
        .build()
        .fetch_all(&mut **tx)
        .await
        .map_err(unavailable)?;
    if rows.len() > 4096 {
        return Err(CognitiveStoreError::Invalid(
            "owner assertion capacity exceeded".to_string(),
        ));
    }
    let mut claims = Vec::with_capacity(rows.len());
    let mut per_revision = BTreeMap::<(String, i64), usize>::new();
    for row in rows {
        let memory_id: String = row.try_get("memory_id").map_err(unavailable)?;
        let revision: i64 = row.try_get("memory_revision").map_err(unavailable)?;
        let key = (memory_id, revision);
        let count = per_revision.entry(key.clone()).or_default();
        *count += 1;
        if *count > 128 {
            return Err(CognitiveStoreError::Corrupt(
                "owner assertion revision capacity exceeded".to_string(),
            ));
        }
        let binding = bindings.get(&key).ok_or_else(|| {
            CognitiveStoreError::Corrupt("assertion escaped exact observation".to_string())
        })?;
        let scope_bytes = serde_json::to_vec(&(owner, &binding.scope))
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let relation: String = row.try_get("relation").map_err(unavailable)?;
        let (polarity, predicate) =
            if let Some(predicate) = relation.strip_prefix(ASSERTED_PREDICATE_PREFIX) {
                (OwnerPolarity::Affirmed, predicate)
            } else if let Some(predicate) = relation.strip_prefix(DENIED_PREDICATE_PREFIX) {
                (OwnerPolarity::Denied, predicate)
            } else {
                return Err(CognitiveStoreError::Corrupt(
                    "invalid explicit assertion predicate".to_string(),
                ));
            };
        if predicate.len() != 64
            || !predicate
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(CognitiveStoreError::Corrupt(
                "noncanonical assertion predicate digest".to_string(),
            ));
        }
        let subject: String = row
            .try_get("from_canonical_entity_id")
            .map_err(unavailable)?;
        let object: String = row.try_get("to_canonical_entity_id").map_err(unavailable)?;
        let fact_set: String = row.try_get("fact_set_sha256").map_err(unavailable)?;
        let relation_id: String = row.try_get("canonical_relation_id").map_err(unavailable)?;
        let source_id: String = row.try_get("source_id").map_err(unavailable)?;
        let source_revision: i64 = row.try_get("source_revision").map_err(unavailable)?;
        if subject.is_empty() || object.is_empty() || source_revision <= 0 {
            return Err(CognitiveStoreError::Corrupt(
                "invalid assertion source identity".to_string(),
            ));
        }
        let support = serde_json::to_vec(&(
            "hepta.sqlite.assertion-source.v1",
            binding,
            fact_set,
            relation_id,
            source_id,
            source_revision,
        ))
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        let claim = OwnerProposition {
            record_id: StableId::new(binding.memory.memory_id.as_str())
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            revision: Revision::new(binding.memory.revision)
                .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?,
            subject: Digest32::of_bytes(subject.as_bytes()),
            predicate: predicate.parse().map_err(|error| {
                CognitiveStoreError::Corrupt(format!("invalid assertion predicate: {error}"))
            })?,
            object: Digest32::of_bytes(object.as_bytes()),
            scope: Digest32::of_bytes(&scope_bytes),
            valid_from: row
                .try_get("valid_from_unix_seconds")
                .map_err(unavailable)?,
            valid_to: row.try_get("valid_to_unix_seconds").map_err(unavailable)?,
            polarity,
            source_support: Digest32::of_bytes(&support),
        };
        claim
            .validate()
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
        claims.push(claim);
    }
    claims.sort_by_key(OwnerProposition::evidence_digest);
    super::proposition::admitted_conflicts(&claims, &BTreeSet::new(), 0)
        .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))?;
    Ok(claims)
}
