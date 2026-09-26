//! Explicit statement stances from the same owner transaction as candidate
//! generation. A retrieval channel or a generic `contradicts` edge is not a
//! proposition stance. Only the two exact predicates below opt into this port.

use super::*;
use codex_hepta_memory_retrieval::ContradictionEvidenceV1;
use codex_hepta_memory_retrieval::ContradictionPolarityV1;
use codex_hepta_types::Digest32;

const MAX_STATEMENT_ROWS: usize = 64;

pub(super) fn serialize_evidence<S: serde::Serializer>(
    evidence: &[ContradictionEvidenceV1],
    serializer: S,
) -> Result<S::Ok, S::Error> {
    serializer.collect_seq(evidence.iter().map(|item| {
        let polarity = match item.polarity {
            ContradictionPolarityV1::Supports => "supports",
            ContradictionPolarityV1::Opposes => "opposes",
        };
        (item.proposition_digest.to_string(), polarity)
    }))
}

pub(super) async fn read_evidence(
    transaction: &mut Transaction<'_, Sqlite>,
    owner_id: &str,
    binding: &MemoryRevalidationBinding,
    as_of: i64,
) -> Result<Vec<ContradictionEvidenceV1>, CognitiveStoreError> {
    let revision = i64::try_from(binding.memory.revision).map_err(|error| {
        CognitiveStoreError::Corrupt(format!("statement revision overflow: {error}"))
    })?;
    let rows = sqlx::query(
        "SELECT r.to_canonical_entity_id AS proposition, r.relation AS stance
         FROM kg_revision_relations r
         JOIN kg_revision_entities e
           ON e.memory_id = r.memory_id AND e.memory_revision = r.memory_revision
          AND e.entity_key = r.to_entity_key
          AND e.canonical_entity_id = r.to_canonical_entity_id
         WHERE r.memory_id = ? AND r.memory_revision = ?
           AND r.relation IN ('supports_proposition', 'opposes_proposition')
           AND e.entity_type = 'proposition'
           AND r.valid_from_unix_seconds <= ?
           AND (r.valid_to_unix_seconds IS NULL OR r.valid_to_unix_seconds > ?)
           AND e.valid_from_unix_seconds <= ?
           AND (e.valid_to_unix_seconds IS NULL OR e.valid_to_unix_seconds > ?)
         ORDER BY r.to_canonical_entity_id, r.relation, r.relation_key
         LIMIT 65",
    )
    .bind(binding.memory.memory_id.as_str())
    .bind(revision)
    .bind(as_of)
    .bind(as_of)
    .bind(as_of)
    .bind(as_of)
    .fetch_all(&mut **transaction)
    .await
    .map_err(unavailable)?;
    // Never truncate away an opposing stance and then certify no conflict.
    if rows.len() > MAX_STATEMENT_ROWS {
        return Err(CognitiveStoreError::Unavailable(
            "explicit proposition evidence exceeds the bounded owner read".to_string(),
        ));
    }
    let scope = binding.scope.projection_key();
    let mut evidence = BTreeSet::new();
    for row in rows {
        let proposition: String = row.try_get("proposition").map_err(unavailable)?;
        let stance: String = row.try_get("stance").map_err(unavailable)?;
        let polarity = match stance.as_str() {
            "supports_proposition" => ContradictionPolarityV1::Supports,
            "opposes_proposition" => ContradictionPolarityV1::Opposes,
            _ => {
                return Err(CognitiveStoreError::Corrupt(
                    "unexpected explicit proposition predicate".to_string(),
                ));
            }
        };
        let mut bytes = b"hepta.sqlite.proposition-at-cut.v1".to_vec();
        for value in [owner_id, scope.as_str(), proposition.as_str()] {
            bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
            bytes.extend_from_slice(value.as_bytes());
        }
        // Bind the common query instant, not each source's interval endpoints.
        // Overlapping valid statements must still conflict at this read cut.
        bytes.extend_from_slice(&as_of.to_be_bytes());
        evidence.insert(ContradictionEvidenceV1 {
            proposition_digest: Digest32::of_bytes(&bytes),
            polarity,
        });
    }
    Ok(evidence.into_iter().collect())
}
