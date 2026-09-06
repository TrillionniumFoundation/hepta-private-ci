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
            "hepta:cognitive:retrieval-observation:v1",
            &self.owner_agent_id,
            access.workspace_sha256(),
            &batch.query_sha256,
            request.now_unix_seconds,
            MAX_FTS_TERMS,
            MAX_RETRIEVAL_CHANNEL_CANDIDATES,
            MAX_RETRIEVAL_RESULTS,
            &generated.channels,
            &observed,
            observed.len() - batch.candidates.len(),
        ))
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let observation = RetrievalObservation {
            batch,
            candidates: observed,
            channels: generated.channels,
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
        Ok(GeneratedRetrieval { ranked, channels })
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
