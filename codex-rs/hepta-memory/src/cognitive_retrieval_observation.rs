//! Owner-native observations of one bounded retrieval generator, not a registered
//! wire/ModulePort contract or proof of external completeness, freshness or delivery.
//! No authority or caller-supplied completeness assertion is accepted.

use super::*;

/// Whether the executed channel queries and generator exhausted their input.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum RetrievalLimitObservation {
    /// No local query/output limit was reached; graph coverage is relative to
    /// the supplied bounded entity seeds, not all entities in the store.
    Exhausted,
    /// A query/output limit was reached. Uninspected rows may exist; neither
    /// their existence nor an exact omitted-row count is asserted.
    LimitReached,
}

impl RetrievalLimitObservation {
    pub(super) fn for_rows(rows: usize, limit: usize) -> Self {
        if rows >= limit {
            Self::LimitReached
        } else {
            Self::Exhausted
        }
    }
}

pub(super) struct ChannelOutput<T> {
    pub(super) values: Vec<T>,
    pub(super) limit: RetrievalLimitObservation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetrievalChannelObservation {
    pub channel: RetrievalChannel,
    /// Distinct memory revisions actually contributed to RRF by this channel.
    pub candidate_count: usize,
    pub limit: RetrievalLimitObservation,
}

/// Typed relation semantics that the SQLite KG owner can prove from a current
/// projection edge. Unknown/free-form relation strings are deliberately not
/// classified into one of these signals.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RetrievalRelationSignal {
    Supports,
    Contradicts,
    TemporalBefore,
    TemporalAfter,
    Causes,
    Enables,
    ProcedureStep,
}

impl RetrievalRelationSignal {
    fn parse(value: &str) -> Option<Self> {
        let normalized = value
            .trim()
            .to_ascii_lowercase()
            .replace(' ', "_")
            .replace('-', "_");
        match normalized.as_str() {
            "supports" => Some(Self::Supports),
            "contradicts" => Some(Self::Contradicts),
            "temporal_before" => Some(Self::TemporalBefore),
            "temporal_after" => Some(Self::TemporalAfter),
            "causes" => Some(Self::Causes),
            "enables" => Some(Self::Enables),
            "procedure_step" => Some(Self::ProcedureStep),
            _ => None,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Supports => "supports",
            Self::Contradicts => "contradicts",
            Self::TemporalBefore => "temporal_before",
            Self::TemporalAfter => "temporal_after",
            Self::Causes => "causes",
            Self::Enables => "enables",
            Self::ProcedureStep => "procedure_step",
        }
    }
}

/// Relation evidence for one graph-reached candidate. The candidate and the
/// memory revision that materialized the edge remain separately resolvable.
/// `support_sha256` binds the candidate-relative support while
/// `relation_group_sha256` identifies the same edge independent of which
/// endpoint was the query seed, allowing contradiction evidence to be grouped.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct ObservedRetrievalRelation {
    pub(crate) candidate: MemoryRevisionId,
    pub(crate) support_memory: MemoryRevisionId,
    pub(crate) signal: RetrievalRelationSignal,
    pub(crate) support_sha256: Sha256Digest,
    pub(crate) relation_group_sha256: Sha256Digest,
}

/// Digest-only source and scoring facts; raw memory/citation content is absent.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ObservedRetrievalCandidate {
    pub revalidation: MemoryRevalidationBinding,
    pub reciprocal_rank_score: u64,
    pub channels: Vec<RetrievalChannel>,
}

/// Created only by the owner read API from one SQLite read transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalObservation {
    batch: RetrievalBatch,
    candidates: Vec<ObservedRetrievalCandidate>,
    channels: Vec<RetrievalChannelObservation>,
    relations: Vec<ObservedRetrievalRelation>,
    relation_limit: RetrievalLimitObservation,
    observation_sha256: Sha256Digest,
}

impl RetrievalObservation {
    pub fn batch(&self) -> &RetrievalBatch {
        &self.batch
    }
    /// Every eligible, revalidated output of the bounded generator, ordered by
    /// memory identity, including those omitted from the legacy top-four batch.
    pub fn candidates(&self) -> &[ObservedRetrievalCandidate] {
        &self.candidates
    }
    pub fn channels(&self) -> &[RetrievalChannelObservation] {
        &self.channels
    }
    /// Cross-crate read-only view of registered KG semantics. The owner keeps
    /// its internal relation enum private; callers receive only canonical tokens
    /// plus exact revision/digest identities. This is still a native owner read,
    /// not a registered wire contract or confidence/OOD assertion.
    pub fn relation_signals(
        &self,
    ) -> impl ExactSizeIterator<
        Item = (
            &MemoryRevisionId,
            &MemoryRevisionId,
            &'static str,
            &Sha256Digest,
            &Sha256Digest,
        ),
    > + '_ {
        self.relations.iter().map(|relation| {
            (
                &relation.candidate,
                &relation.support_memory,
                relation.signal.as_str(),
                &relation.support_sha256,
                &relation.relation_group_sha256,
            )
        })
    }
    /// Relation evidence is bounded separately from the four legacy RRF
    /// channels and does not modify their completion/limit observations.
    pub const fn relation_limit(&self) -> RetrievalLimitObservation {
        self.relation_limit
    }
    /// Owner-internal typed view used by source tests.
    pub(crate) fn relations(&self) -> &[ObservedRetrievalRelation] {
        &self.relations
    }
    /// Exact final top-four omission count, not omissions before channel limits.
    pub fn omitted_count(&self) -> usize {
        self.candidates.len() - self.batch.candidates.len()
    }
    pub fn observation_sha256(&self) -> &Sha256Digest {
        &self.observation_sha256
    }
}

pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    channels: Vec<RetrievalChannelObservation>,
    seeds: Vec<EntitySeed>,
}

impl CognitiveStore {
    /// Observe all bounded generator outputs before final top-four truncation.
    /// This optional slow read validates up to 4 * 32 candidate explanations in
    /// one snapshot. It never expands channel limits or changes legacy ranking.
    pub async fn observe_memory_retrieval(
        &self,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
    ) -> Result<RetrievalObservation, CognitiveStoreError> {
        let fts_query = self.validate_retrieval_request(access, request)?;
        let mut transaction = self.pool.begin().await.map_err(unavailable)?;
        let generated = self
            .generate_retrieval_tx(&mut transaction, access, request, &fts_query)
            .await?;
        // Relation semantics are observation-only and therefore do not add SQL
        // work to the legacy `retrieve_memory_candidates` hot path.
        let relation_evidence = self
            .relation_evidence_tx(&mut transaction, &generated.seeds, request.now_unix_seconds)
            .await?;
        let mut candidates = self
            .resolve_retrieval_tx(
                &mut transaction,
                access,
                request,
                generated.ranked,
                4 * MAX_RETRIEVAL_CHANNEL_CANDIDATES,
            )
            .await?;
        let mut observed = candidates
            .iter()
            .map(|candidate| ObservedRetrievalCandidate {
                revalidation: candidate.revalidation.clone(),
                reciprocal_rank_score: candidate.reciprocal_rank_score,
                channels: candidate.channels.clone(),
            })
            .collect::<Vec<_>>();
        observed.sort_by(|left, right| {
            left.revalidation
                .memory
                .memory_id
                .cmp(&right.revalidation.memory.memory_id)
                .then_with(|| {
                    left.revalidation
                        .memory
                        .revision
                        .cmp(&right.revalidation.memory.revision)
                })
        });
        candidates.truncate(MAX_RETRIEVAL_RESULTS);
        let batch = RetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query.as_bytes()),
            candidates,
        };
        let bytes = serde_json::to_vec(&(
            "hepta:cognitive:retrieval-observation:v2",
            &self.owner_agent_id,
            access.workspace_sha256(),
            &batch.query_sha256,
            request.now_unix_seconds,
            MAX_FTS_TERMS,
            MAX_RETRIEVAL_CHANNEL_CANDIDATES,
            MAX_RETRIEVAL_RESULTS,
            &generated.channels,
            &relation_evidence.values,
            relation_evidence.limit,
            &observed,
            observed.len() - batch.candidates.len(),
        ))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let observation = RetrievalObservation {
            batch,
            candidates: observed,
            channels: generated.channels,
            relations: relation_evidence.values,
            relation_limit: relation_evidence.limit,
            observation_sha256: Sha256Digest::for_bytes(&bytes),
        };
        transaction.commit().await.map_err(unavailable)?;
        Ok(observation)
    }

    pub(super) fn validate_retrieval_request(
        &self,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
    ) -> Result<String, CognitiveStoreError> {
        self.authorize(access, &CognitiveScope::AgentPrivate)?;
        if request.query.trim().is_empty() || request.query.len() > MAX_RETRIEVAL_QUERY_BYTES {
            return Err(CognitiveStoreError::Invalid(format!(
                "retrieval query must contain 1..={MAX_RETRIEVAL_QUERY_BYTES} bytes"
            )));
        }
        bounded_fts_query(&request.query).ok_or_else(|| {
            CognitiveStoreError::Invalid("retrieval query contains no searchable terms".to_string())
        })
    }

    pub(super) async fn generate_retrieval_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
        fts_query: &str,
    ) -> Result<GeneratedRetrieval, CognitiveStoreError> {
        let now = request.now_unix_seconds;
        let memory = self
            .memory_fts_channel_tx(transaction, access, fts_query, now)
            .await?;
        let seeds = self
            .entity_fts_channel_tx(transaction, access, fts_query, now)
            .await?;
        let entity = seeds
            .values
            .iter()
            .map(|seed| seed.memory.clone())
            .collect::<Vec<_>>();
        let graph = self
            .graph_channel_tx(transaction, &seeds.values, now)
            .await?;
        let recency = self
            .recency_channel_tx(
                transaction,
                access.workspace_sha256().map(Sha256Digest::as_str),
                now,
            )
            .await?;
        let mut ranked = BTreeMap::new();
        let mut channels = Vec::new();
        for (channel, keys, limit) in [
            (RetrievalChannel::MemoryFts, &memory.values, memory.limit),
            (RetrievalChannel::EntityFts, &entity, seeds.limit),
            (RetrievalChannel::GraphOneHop, &graph.values, graph.limit),
            (RetrievalChannel::Recency, &recency.values, recency.limit),
        ] {
            add_rrf_channel(&mut ranked, keys, channel);
            channels.push(RetrievalChannelObservation {
                channel,
                candidate_count: keys.iter().collect::<BTreeSet<_>>().len(),
                limit,
            });
        }
        let mut ranked = ranked.into_iter().collect::<Vec<_>>();
        ranked.sort_by(|left, right| {
            right
                .1
                .score
                .cmp(&left.1.score)
                .then_with(|| left.0.cmp(&right.0))
        });
        Ok(GeneratedRetrieval {
            ranked,
            channels,
            seeds: seeds.values,
        })
    }

    /// Resolve registered relation semantics from the same bounded graph seeds
    /// used by legacy one-hop retrieval. This is observation-only: it does not
    /// alter RRF ranking and ignores unregistered/free-form relation labels.
    async fn relation_evidence_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        seeds: &[EntitySeed],
        now: i64,
    ) -> Result<ChannelOutput<ObservedRetrievalRelation>, CognitiveStoreError> {
        let mut queried_canonical_entities = BTreeSet::new();
        let mut seen = BTreeSet::new();
        let mut result = Vec::new();
        let mut limit = RetrievalLimitObservation::Exhausted;
        'seeds: for seed in seeds {
            if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                limit = RetrievalLimitObservation::LimitReached;
                break;
            }
            if !queried_canonical_entities.insert((
                seed.projection_scope.clone(),
                seed.generation,
                seed.canonical_entity_id.clone(),
            )) {
                continue;
            }
            let remaining = MAX_RETRIEVAL_CHANNEL_CANDIDATES - result.len();
            let rows = sqlx::query(
                "WITH canonical_support_nodes AS (
                     SELECT node_id
                     FROM kg_projection_node_entities
                     WHERE projection_scope = ? AND generation = ?
                       AND canonical_entity_id = ?
                 )
                 SELECT DISTINCT e.edge_id, e.relation,
                        e.memory_id AS edge_memory_id,
                        e.memory_revision AS edge_memory_revision,
                        n.memory_id AS node_memory_id,
                        n.memory_revision AS node_memory_revision
                 FROM canonical_support_nodes s
                 JOIN kg_edges e
                   ON e.projection_scope = ? AND e.generation = ?
                  AND (e.from_node_id = s.node_id OR e.to_node_id = s.node_id)
                 JOIN kg_nodes n
                   ON n.projection_scope = e.projection_scope AND n.generation = e.generation
                  AND n.node_id = CASE WHEN e.from_node_id = s.node_id
                                       THEN e.to_node_id ELSE e.from_node_id END
                 JOIN memory_heads eh ON eh.memory_id = e.memory_id
                                     AND eh.revision = e.memory_revision
                 JOIN memory_heads nh ON nh.memory_id = n.memory_id
                                     AND nh.revision = n.memory_revision
                 JOIN memory_revisions er ON er.memory_id = e.memory_id
                                         AND er.revision = e.memory_revision
                 JOIN memory_revisions nr ON nr.memory_id = n.memory_id
                                         AND nr.revision = n.memory_revision
                 WHERE e.valid_from_unix_seconds <= ?
                   AND (e.valid_to_unix_seconds IS NULL OR ? < e.valid_to_unix_seconds)
                   AND n.valid_from_unix_seconds <= ?
                   AND (n.valid_to_unix_seconds IS NULL OR ? < n.valid_to_unix_seconds)
                   AND er.verification = 'verified' AND er.lifecycle = 'active'
                   AND nr.verification = 'verified' AND nr.lifecycle = 'active'
                   AND er.valid_from_unix_seconds <= ?
                   AND (er.valid_to_unix_seconds IS NULL OR ? < er.valid_to_unix_seconds)
                   AND nr.valid_from_unix_seconds <= ?
                   AND (nr.valid_to_unix_seconds IS NULL OR ? < nr.valid_to_unix_seconds)
                   AND lower(replace(replace(trim(e.relation), ' ', '_'), '-', '_'))
                       IN ('supports', 'contradicts', 'temporal_before', 'temporal_after',
                           'causes', 'enables', 'procedure_step')
                 ORDER BY e.edge_id, n.memory_id, n.memory_revision
                 LIMIT ?",
            )
            .bind(&seed.projection_scope)
            .bind(seed.generation)
            .bind(&seed.canonical_entity_id)
            .bind(&seed.projection_scope)
            .bind(seed.generation)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(now)
            .bind(i64::try_from(remaining).map_err(|_| {
                CognitiveStoreError::Invalid(
                    "relation evidence limit exceeds i64".to_string(),
                )
            })?)
            .fetch_all(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if rows.len() >= remaining {
                limit = RetrievalLimitObservation::LimitReached;
            }
            for row in rows {
                let relation: String = row.try_get("relation").map_err(unavailable)?;
                let Some(signal) = RetrievalRelationSignal::parse(&relation) else {
                    continue;
                };
                let edge_id: String = row.try_get("edge_id").map_err(unavailable)?;
                let support = decode_memory_key(
                    &row,
                    "edge_memory_id",
                    "edge_memory_revision",
                )?;
                let candidate = decode_memory_key(
                    &row,
                    "node_memory_id",
                    "node_memory_revision",
                )?;
                if !seen.insert((candidate.clone(), support.clone(), signal)) {
                    continue;
                }
                let group_bytes = serde_json::to_vec(&(
                    "hepta:cognitive:retrieval-relation-group:v1",
                    &seed.projection_scope,
                    seed.generation,
                    &edge_id,
                    signal.as_str(),
                    &support.memory_id,
                    support.revision,
                ))
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
                let support_bytes = serde_json::to_vec(&(
                    "hepta:cognitive:retrieval-relation-support:v2",
                    &group_bytes,
                    &candidate.memory_id,
                    candidate.revision,
                ))
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
                result.push(ObservedRetrievalRelation {
                    candidate: MemoryRevisionId {
                        memory_id: StableMemoryId::parse(candidate.memory_id)
                            .map_err(CognitiveStoreError::Corrupt)?,
                        revision: candidate.revision,
                    },
                    support_memory: MemoryRevisionId {
                        memory_id: StableMemoryId::parse(support.memory_id)
                            .map_err(CognitiveStoreError::Corrupt)?,
                        revision: support.revision,
                    },
                    signal,
                    support_sha256: Sha256Digest::for_bytes(&support_bytes),
                    relation_group_sha256: Sha256Digest::for_bytes(&group_bytes),
                });
                if result.len() >= MAX_RETRIEVAL_CHANNEL_CANDIDATES {
                    limit = RetrievalLimitObservation::LimitReached;
                    break 'seeds;
                }
            }
        }
        result.sort_by(|left, right| {
            left.candidate
                .memory_id
                .cmp(&right.candidate.memory_id)
                .then_with(|| left.candidate.revision.cmp(&right.candidate.revision))
                .then_with(|| left.signal.cmp(&right.signal))
                .then_with(|| left.support_memory.memory_id.cmp(&right.support_memory.memory_id))
                .then_with(|| left.support_memory.revision.cmp(&right.support_memory.revision))
        });
        Ok(ChannelOutput {
            values: result,
            limit,
        })
    }

    pub(super) async fn resolve_retrieval_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
        ranked: Vec<(MemoryKey, AggregatedRank)>,
        maximum_results: usize,
    ) -> Result<Vec<RetrievalCandidate>, CognitiveStoreError> {
        let mut candidates = Vec::with_capacity(maximum_results);
        for (key, rank) in ranked {
            if candidates.len() == maximum_results {
                break;
            }
            let memory_id =
                StableMemoryId::parse(key.memory_id).map_err(CognitiveStoreError::Corrupt)?;
            let explanation = self
                .explain_memory_head_tx(transaction, access, &memory_id)
                .await?;
            if explanation.memory.id.revision != key.revision
                || !eligible(&explanation.memory, request.now_unix_seconds)
            {
                continue;
            }
            candidates.push(RetrievalCandidate {
                memory: explanation.memory.clone(),
                reciprocal_rank_score: rank.score,
                channels: rank.channels.into_iter().collect(),
                revalidation: binding_from_explanation(&explanation),
            });
        }
        Ok(candidates)
    }
}

#[cfg(test)]
#[path = "cognitive_retrieval_observation_tests.rs"]
mod tests;
