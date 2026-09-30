//! Owner-native observations of one bounded retrieval generator, not a registered
//! wire/ModulePort contract or proof of external completeness, freshness or delivery.
//! No authority or caller-supplied completeness assertion is accepted.

use super::*;

#[path = "cognitive_retrieval_proposition.rs"]
mod proposition;
#[path = "cognitive_retrieval_proposition_read.rs"]
mod proposition_read;

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
    pub channel_ranks: Vec<RetrievalChannelRank>,
}

/// Created only by the owner read API from one SQLite read transaction.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalObservation {
    batch: RetrievalBatch,
    candidates: Vec<ObservedRetrievalCandidate>,
    channels: Vec<RetrievalChannelObservation>,
    observation_sha256: Sha256Digest,
    proposition_claims: Vec<proposition::OwnerProposition>,
    observed_at: i64,
}

impl RetrievalObservation {
    pub fn batch(&self) -> &RetrievalBatch {
        &self.batch
    }
    /// Every eligible, revalidated output of the bounded generator, including
    /// those omitted from the legacy top-four batch.
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

    /// Digest-only audit surface for the complete owner-observed assertion set.
    pub fn proposition_evidence_digests(&self) -> Vec<codex_hepta_types::Digest32> {
        self.proposition_claims
            .iter()
            .map(proposition::OwnerProposition::evidence_digest)
            .collect()
    }

    pub(crate) fn admitted_proposition_conflicts(
        &self,
        admitted: &BTreeSet<(codex_hepta_types::StableId, codex_hepta_types::Revision)>,
    ) -> Result<BTreeSet<codex_hepta_types::Digest32>, CognitiveStoreError> {
        proposition::admitted_conflicts(&self.proposition_claims, admitted, self.observed_at)
            .map_err(|error| CognitiveStoreError::Corrupt(error.to_string()))
    }
}

pub(super) struct GeneratedRetrieval {
    pub(super) ranked: Vec<(MemoryKey, AggregatedRank)>,
    pub(super) channels: Vec<RetrievalChannelObservation>,
}

impl GeneratedRetrieval {
    pub(super) fn exhausted(&self) -> bool {
        self.channels
            .iter()
            .all(|channel| channel.limit == RetrievalLimitObservation::Exhausted)
    }
}

impl CognitiveStore {
    /// Observe all bounded generator outputs before final top-four truncation.
    /// Assertions and their exact sources are read in this same transaction.
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
                MAX_RETRIEVAL_OWNER_CHANNELS * MAX_RETRIEVAL_CHANNEL_CANDIDATES,
            )
            .await?;
        let mut observed = candidates
            .iter()
            .map(|candidate| ObservedRetrievalCandidate {
                revalidation: candidate.revalidation.clone(),
                reciprocal_rank_score: candidate.reciprocal_rank_score,
                channels: candidate.channels.clone(),
                channel_ranks: candidate.channel_ranks.clone(),
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
        let proposition_claims =
            proposition_read::read_assertions(&mut transaction, &self.owner_agent_id, &observed)
                .await?;
        candidates.truncate(MAX_RETRIEVAL_RESULTS);
        let batch = RetrievalBatch {
            query_sha256: Sha256Digest::for_bytes(request.query.as_bytes()),
            candidates,
        };
        let legacy_bytes = serde_json::to_vec(&(
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
        // Preserve existing no-assertion observation bytes. A v2 observation
        // binds the predecessor facts and *all* assertions, not only conflicts.
        let bytes = if proposition_claims.is_empty() {
            legacy_bytes
        } else {
            let evidence = proposition_claims
                .iter()
                .map(|claim| claim.evidence_digest().to_string())
                .collect::<Vec<_>>();
            serde_json::to_vec(&(
                "hepta:cognitive:retrieval-observation:v2",
                Sha256Digest::for_bytes(&legacy_bytes),
                evidence,
            ))
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
        };
        let observation = RetrievalObservation {
            batch,
            candidates: observed,
            channels: generated.channels,
            observation_sha256: Sha256Digest::for_bytes(&bytes),
            proposition_claims,
            observed_at: request.now_unix_seconds,
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
        self.generate_retrieval_scoped_tx(transaction, access, request, fts_query, None)
            .await
    }

    pub(super) async fn generate_retrieval_for_scope_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        request: &RetrievalRequest,
        fts_query: &str,
    ) -> Result<GeneratedRetrieval, CognitiveStoreError> {
        self.generate_retrieval_scoped_tx(transaction, access, request, fts_query, Some(scope))
            .await
    }

    async fn generate_retrieval_scoped_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        request: &RetrievalRequest,
        fts_query: &str,
        exact_scope: Option<&CognitiveScope>,
    ) -> Result<GeneratedRetrieval, CognitiveStoreError> {
        let now = request.now_unix_seconds;
        let memory = self
            .memory_fts_channel_scoped_tx(transaction, access, fts_query, now, exact_scope)
            .await?;
        let seeds = self
            .entity_fts_channel_scoped_tx(transaction, access, fts_query, now, exact_scope)
            .await?;
        let entity = seeds
            .values
            .iter()
            .map(|seed| seed.memory.clone())
            .collect::<Vec<_>>();
        let mut generations = RetrievalGenerations::new();
        let graph = self
            .graph_channel_tx(transaction, &seeds.values, &mut generations, now)
            .await?;
        let causal = self
            .typed_relation_channel_tx(
                transaction,
                &seeds.values,
                &mut generations,
                now,
                KgRelationSemanticV1::Causes,
            )
            .await?;
        let procedural = self
            .typed_relation_channel_tx(
                transaction,
                &seeds.values,
                &mut generations,
                now,
                KgRelationSemanticV1::ProcedureStep,
            )
            .await?;
        let contradiction = self
            .typed_relation_channel_tx(
                transaction,
                &seeds.values,
                &mut generations,
                now,
                KgRelationSemanticV1::Contradicts,
            )
            .await?;
        let recency = self
            .recency_channel_scoped_tx(
                transaction,
                access.workspace_sha256().map(Sha256Digest::as_str),
                now,
                exact_scope,
            )
            .await?;
        let mut ranked = BTreeMap::new();
        let mut channels = Vec::new();
        for (channel, keys, limit) in [
            (RetrievalChannel::MemoryFts, &memory.values, memory.limit),
            (RetrievalChannel::EntityFts, &entity, seeds.limit),
            (RetrievalChannel::GraphOneHop, &graph.values, graph.limit),
            (RetrievalChannel::Recency, &recency.values, recency.limit),
            (RetrievalChannel::Causal, &causal.values, causal.limit),
            (
                RetrievalChannel::Procedural,
                &procedural.values,
                procedural.limit,
            ),
            (
                RetrievalChannel::ContradictionSupport,
                &contradiction.values,
                contradiction.limit,
            ),
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
            let channel_ranks = rank
                .ranks
                .into_iter()
                .map(|(channel, rank)| RetrievalChannelRank { channel, rank })
                .collect();
            candidates.push(RetrievalCandidate {
                memory: explanation.memory.clone(),
                reciprocal_rank_score: rank.score,
                channels: rank.channels.into_iter().collect(),
                channel_ranks,
                revalidation: binding_from_explanation(&explanation),
            });
        }
        Ok(candidates)
    }
}

#[cfg(test)]
#[path = "cognitive_retrieval_observation_tests.rs"]
mod tests;
