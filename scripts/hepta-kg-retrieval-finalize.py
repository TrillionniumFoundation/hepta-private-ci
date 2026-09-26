#!/usr/bin/env python3
"""Select the indexed multi-seed KG query in the cognitive retrieval owner.

The cache is request/transaction scoped and generation keyed. It is never a source of truth:
canonical generations and physical support maps are still reconstructed from the same SQLite
snapshot, but each immutable generation/support map is loaded at most once across all relation
channels in that request.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "codex-rs" / "hepta-memory" / "src" / "cognitive_retrieval.rs"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL_HEPTA_KG_RETRIEVAL_FINALIZE: {message}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        fail(f"{label}: expected one source anchor, observed {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        fail(
            f"{label}: boundary counts are start={text.count(start)} end={text.count(end)}"
        )
    begin = text.index(start)
    finish = text.index(end, begin)
    if finish <= begin:
        fail(f"{label}: invalid source boundary ordering")
    return text[:begin] + replacement + text[finish:]


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    source = replace_once(
        source,
        "use codex_hepta_kg::KnowledgeGenerationV2;\n"
        "use codex_hepta_kg::KnowledgeRelationQueryV2;\n"
        "use codex_hepta_kg::query_relations;\n",
        "use codex_hepta_kg::KnowledgeRelationQueryV2;\n"
        "use codex_hepta_kg::MAX_QUERY_RELATION_KINDS_V2;\n"
        "use codex_hepta_kg::ValidatedKnowledgeGenerationV2;\n"
        "use codex_hepta_kg::query_validated_relations;\n",
        "validated query imports",
    )
    source = replace_once(
        source,
        "// Scratch space for one SQLite read transaction, never shared across requests.\n"
        "// Each selected scope/generation is materialized once across relation channels.\n"
        "type RetrievalGenerations = BTreeMap<(String, i64), KnowledgeGenerationV2>;\n",
        "// Scratch space for one SQLite read transaction, never shared across requests.\n"
        "// Each immutable scope/generation and its physical support map is materialized\n"
        "// once across generic, causal, procedural and contradiction channels.\n"
        "#[derive(Default)]\n"
        "struct RetrievalGenerations {\n"
        "    generations: BTreeMap<(String, i64), ValidatedKnowledgeGenerationV2>,\n"
        "    support_indexes: BTreeMap<(String, i64), Option<BTreeMap<String, (String, i64)>>>,\n"
        "}\n\n"
        "impl RetrievalGenerations {\n"
        "    fn new() -> Self {\n"
        "        Self::default()\n"
        "    }\n"
        "}\n",
        "request-scoped generation and support cache",
    )

    start = "    async fn graph_channel_tx(\n"
    end = "    #[cfg(test)]\n    pub(crate) async fn graph_channel_for_test(\n"
    replacement = r'''    async fn graph_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        seeds: &[EntitySeed],
        generations: &mut RetrievalGenerations,
        now: i64,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        self.relation_channel_tx(transaction, seeds, generations, now, None)
            .await
    }

    async fn typed_relation_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        seeds: &[EntitySeed],
        generations: &mut RetrievalGenerations,
        now: i64,
        semantic: KgRelationSemanticV1,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        self.relation_channel_tx(transaction, seeds, generations, now, Some(semantic))
            .await
    }

    async fn relation_channel_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        seeds: &[EntitySeed],
        generations: &mut RetrievalGenerations,
        now: i64,
        semantic: Option<KgRelationSemanticV1>,
    ) -> Result<ChannelOutput<MemoryKey>, CognitiveStoreError> {
        // All entity seeds for one immutable generation are merged into one
        // generation-bound query. BTree containers make grouping and query input
        // deterministic regardless of FTS row order.
        let mut grouped = BTreeMap::<
            (String, i64),
            (Option<Sha256Digest>, BTreeSet<String>),
        >::new();
        for seed in seeds {
            let group = grouped
                .entry((seed.projection_scope.clone(), seed.generation))
                .or_default();
            match (&group.0, &seed.generation_sha256) {
                (Some(existing), Some(incoming)) if existing != incoming => {
                    return Err(CognitiveStoreError::Corrupt(
                        "entity seeds disagree on one KG generation digest".to_string(),
                    ));
                }
                (None, Some(incoming)) => group.0 = Some(incoming.clone()),
                _ => {}
            }
            group.1.insert(seed.canonical_entity_id.clone());
        }

        let typed_kinds = [
            KgRelationSemanticV1::Causes,
            KgRelationSemanticV1::ProcedureStep,
            KgRelationSemanticV1::Contradicts,
        ]
        .into_iter()
        .map(|kind| crate::cognitive_kg_store::canonical_relation_kind(kind.relation()))
        .collect::<Result<BTreeSet<_>, _>>()?;
        let mut seen = BTreeSet::new();
        let mut result = Vec::new();
        let mut limit = RetrievalLimitObservation::Exhausted;

        'groups: for ((projection_scope, generation_number), (bound_digest, seed_ids)) in grouped {
            if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                limit = RetrievalLimitObservation::LimitReached;
                break;
            }

            let generation_sha256 = match bound_digest {
                Some(digest) => Some(digest),
                None => sqlx::query_scalar::<_, String>(
                    "SELECT generation_sha256
                     FROM kg_projection_generation_semantics
                     WHERE projection_scope = ? AND generation = ?",
                )
                .bind(&projection_scope)
                .bind(generation_number)
                .fetch_optional(&mut **transaction)
                .await
                .map_err(unavailable)?
                .map(Sha256Digest::parse)
                .transpose()
                .map_err(CognitiveStoreError::Corrupt)?,
            };
            let Some(generation_sha256) = generation_sha256 else {
                // Legacy projections without a canonical V2 receipt remain
                // available to lexical/entity channels, but cannot drive graph
                // expansion until a canonical generation has been published.
                continue;
            };

            let cache_key = (projection_scope.clone(), generation_number);
            if !generations.generations.contains_key(&cache_key) {
                let generation = load_canonical_generation_tx(
                    transaction,
                    &projection_scope,
                    generation_number,
                )
                .await?;
                let validated = ValidatedKnowledgeGenerationV2::new(generation).map_err(|error| {
                    CognitiveStoreError::Corrupt(format!(
                        "persisted KG generation failed one-time V2 validation: {error}"
                    ))
                })?;
                generations.generations.insert(cache_key.clone(), validated);
            }
            let validated = generations.generations.get(&cache_key).ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "validated KG generation cache lost its inserted entry".to_string(),
                )
            })?;
            if validated.generation_digest().to_string() != generation_sha256.as_str() {
                return Err(CognitiveStoreError::Corrupt(
                    "KG product query generation digest diverged from persisted semantics"
                        .to_string(),
                ));
            }

            let mut relation_kinds = match semantic {
                Some(kind) => vec![crate::cognitive_kg_store::canonical_relation_kind(
                    kind.relation(),
                )?],
                None => validated
                    .generation()
                    .edges
                    .iter()
                    .map(|edge| edge.identity.relation.clone())
                    .filter(|kind| !typed_kinds.contains(kind))
                    .collect::<BTreeSet<_>>()
                    .into_iter()
                    .collect::<Vec<_>>(),
            };
            // Keep the public query budget authoritative. A generic relation
            // channel with more kinds is a bounded prefix, never a false
            // exhaustive claim.
            if relation_kinds.len() > MAX_QUERY_RELATION_KINDS_V2 {
                relation_kinds.truncate(MAX_QUERY_RELATION_KINDS_V2);
                limit = RetrievalLimitObservation::LimitReached;
            }
            // An empty KG query filter means all relations; an empty generic
            // channel must instead stay empty so typed support cannot leak in.
            if relation_kinds.is_empty() {
                continue;
            }

            let seed_node_ids = seed_ids
                .into_iter()
                .map(|seed| {
                    StableId::new(seed).map_err(|error| {
                        CognitiveStoreError::Corrupt(format!(
                            "invalid canonical KG query seed identity: {error}"
                        ))
                    })
                })
                .collect::<Result<Vec<_>, _>>()?;
            let remaining = MAX_RETRIEVAL_CHANNEL_CANDIDATES - result.len();
            let query_result = query_validated_relations(
                validated,
                KnowledgeRelationQueryV2 {
                    query_id: StableId::new("query:cognitive-retrieval-graph-v2").map_err(
                        |error| {
                            CognitiveStoreError::Corrupt(format!(
                                "invalid canonical KG retrieval query identity: {error}"
                            ))
                        },
                    )?,
                    generation_digest: validated.generation_digest(),
                    seed_node_ids,
                    relation_kinds,
                    valid_at_unix_seconds: Some(now),
                    maximum_edges: u32::try_from(remaining).map_err(|_| {
                        CognitiveStoreError::Invalid(
                            "graph retrieval limit exceeds u32".to_string(),
                        )
                    })?,
                },
            )
            .map_err(|error| {
                CognitiveStoreError::Corrupt(format!(
                    "persisted KG generation failed indexed multi-seed V2 query: {error}"
                ))
            })?;
            if query_result.omitted_count != 0 {
                limit = RetrievalLimitObservation::LimitReached;
            }

            if !generations.support_indexes.contains_key(&cache_key) {
                let index = load_compact_edge_support_index_tx(
                    transaction,
                    &projection_scope,
                    generation_number,
                )
                .await?;
                generations.support_indexes.insert(cache_key.clone(), index);
            }
            let compact_supports = generations.support_indexes.get(&cache_key).ok_or_else(|| {
                CognitiveStoreError::Corrupt(
                    "KG physical support-index cache lost its inserted entry".to_string(),
                )
            })?;

            for edge in query_result.edges {
                for support in edge.supports {
                    let (memory_id, revision) = if let Some(index) = compact_supports.as_ref() {
                        index
                            .get(support.source_id.as_str())
                            .cloned()
                            .ok_or_else(|| {
                                CognitiveStoreError::Corrupt(
                                    "canonical compact KG edge support has no immutable revision occurrence"
                                        .to_string(),
                                )
                            })?
                    } else {
                        let row = sqlx::query(
                            "SELECT memory_id, memory_revision
                             FROM kg_edges
                             WHERE projection_scope = ? AND generation = ? AND edge_id = ?",
                        )
                        .bind(&projection_scope)
                        .bind(generation_number)
                        .bind(support.source_id.as_str())
                        .fetch_optional(&mut **transaction)
                        .await
                        .map_err(unavailable)?
                        .ok_or_else(|| {
                            CognitiveStoreError::Corrupt(
                                "canonical KG edge support has no persisted occurrence".to_string(),
                            )
                        })?;
                        (
                            row.try_get("memory_id").map_err(unavailable)?,
                            row.try_get("memory_revision").map_err(unavailable)?,
                        )
                    };
                    let key = MemoryKey {
                        memory_id,
                        revision: u64::try_from(revision).map_err(|_| {
                            CognitiveStoreError::Corrupt(
                                "negative KG edge-support memory revision".to_string(),
                            )
                        })?,
                    };
                    if seen.insert(key.clone()) {
                        result.push(key);
                    }
                    if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                        limit = RetrievalLimitObservation::LimitReached;
                        break 'groups;
                    }
                }
            }
        }
        Ok(ChannelOutput {
            values: result,
            limit,
        })
    }

'''
    source = replace_between(
        source,
        start,
        end,
        replacement,
        "relation-channel implementation",
    )
    TARGET.write_text(source, encoding="utf-8")
    print(
        "PASS_HEPTA_KG_RETRIEVAL_FINALIZE "
        "query=indexed_multi_seed support_cache=request_generation_bound"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
