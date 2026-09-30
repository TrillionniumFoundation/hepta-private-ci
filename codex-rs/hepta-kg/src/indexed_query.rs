//! Immutable, validated query view. Indexes are derived, never source truth.
//!
//! Owners must bind this view to their read transaction/source cut. It does not
//! prove that a historical generation is still current or grant any authority.

use super::*;
use crate::DEFAULT_QUERY_SUPPORT_WORK_V2;
use crate::KnowledgeCancellationV2;
use crate::KnowledgeOperationGuardV2;
use crate::KnowledgeQueryAdmissionErrorV2;
use crate::KnowledgeResourceErrorCodeV2;
use crate::KnowledgeResourceErrorV2;
use crate::MAX_QUERY_SUPPORT_WORK_V2;
use crate::measure_query_edge_bytes_v2;
use crate::measure_query_result_base_bytes_v2;

const SUPPORT_CHECKPOINT_INTERVAL: u64 = 64;

/// Charge before inspecting or copying. Exhaustion never yields a partial result
/// with a misleading exact omitted_count. Generation validation/index
/// construction is a separate cost.
fn charge_support_work(
    used: &mut u64,
    maximum: u64,
    amount: usize,
) -> Result<(), KnowledgeQueryAdmissionErrorV2> {
    let amount = u64::try_from(amount).unwrap_or(u64::MAX);
    let attempted = used.checked_add(amount).unwrap_or(u64::MAX);
    if attempted > maximum {
        return Err(KnowledgeQueryAdmissionErrorV2::BudgetExceeded {
            maximum_support_work: maximum,
            attempted_support_work: attempted,
        });
    }
    *used = attempted;
    Ok(())
}

fn charge_output_bytes(
    used: &mut u64,
    maximum: Option<u64>,
    amount: u64,
) -> Result<(), KnowledgeQueryAdmissionErrorV2> {
    let attempted = used.checked_add(amount).unwrap_or(u64::MAX);
    if maximum.is_some_and(|limit| attempted > limit) {
        return Err(KnowledgeResourceErrorV2::exceeded(
            KnowledgeResourceErrorCodeV2::QueryOutputBytesExceeded,
            attempted,
            maximum.unwrap_or(0),
            "query result bytes before payload clone",
        )
        .into());
    }
    *used = attempted;
    Ok(())
}

fn checkpoint_support_work(
    guard: &KnowledgeOperationGuardV2,
    used: u64,
    next_checkpoint: &mut u64,
) -> Result<(), KnowledgeQueryAdmissionErrorV2> {
    if used >= *next_checkpoint {
        guard.checkpoint()?;
        *next_checkpoint = used.saturating_add(SUPPORT_CHECKPOINT_INTERVAL);
    }
    Ok(())
}

/// An owned generation validated once and indexed without changing edge order.
///
/// No mutable generation reference or unchecked constructor is exposed. A caller
/// that changes the source cut must construct another view. Query-time temporal
/// visibility is recomputed for every request, not cached across clock cuts.
#[derive(Debug)]
pub struct VerifiedKnowledgeGenerationV2 {
    generation: KnowledgeGenerationV2,
    nodes: BTreeMap<StableId, usize>,
    adjacency: BTreeMap<StableId, Vec<usize>>,
    relation_kinds: BTreeSet<KnowledgeRelationKindV2>,
}

impl VerifiedKnowledgeGenerationV2 {
    pub fn new(generation: KnowledgeGenerationV2) -> Result<Self, KnowledgeGenerationErrorV2> {
        generation.validate()?;
        let nodes = generation
            .nodes
            .iter()
            .enumerate()
            .map(|(index, node)| (node.node_id.clone(), index))
            .collect();
        let mut adjacency = BTreeMap::<StableId, Vec<usize>>::new();
        let mut relation_kinds = BTreeSet::new();
        for (index, edge) in generation.edges.iter().enumerate() {
            adjacency
                .entry(edge.identity.source_node_id.clone())
                .or_default()
                .push(index);
            if edge.identity.target_node_id != edge.identity.source_node_id {
                adjacency
                    .entry(edge.identity.target_node_id.clone())
                    .or_default()
                    .push(index);
            }
            relation_kinds.insert(edge.identity.relation.clone());
        }
        Ok(Self {
            generation,
            nodes,
            adjacency,
            relation_kinds,
        })
    }

    pub fn generation(&self) -> &KnowledgeGenerationV2 {
        &self.generation
    }

    pub fn relation_kinds(&self) -> &BTreeSet<KnowledgeRelationKindV2> {
        &self.relation_kinds
    }

    pub fn query_relations(
        &self,
        query: KnowledgeRelationQueryV2,
    ) -> Result<KnowledgeRelationResultV2, KnowledgeGenerationErrorV2> {
        self.query_relations_with_work(query)
            .map(|(result, _work)| result)
    }

    /// Reports selection work only: validation counters are zero because the
    /// sealed constructor already performed complete generation validation.
    /// Exact omitted_count still requires inspecting all incident matches.
    pub fn query_relations_with_work(
        &self,
        query: KnowledgeRelationQueryV2,
    ) -> Result<(KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2), KnowledgeGenerationErrorV2>
    {
        self.query_relations_with_work_budget(query, DEFAULT_QUERY_SUPPORT_WORK_V2)
    }

    /// Backward-compatible budgeted query surface.
    ///
    /// Invalid budgets, runtime exhaustion and operation-guard failures retain
    /// the historical `InvalidQueryLimit` error. New external callers should use
    /// [`Self::query_relations_external_guarded`] for exact classification.
    pub fn query_relations_with_work_budget(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: u64,
    ) -> Result<(KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2), KnowledgeGenerationErrorV2>
    {
        match self.query_relations_external(query, Some(maximum_support_work)) {
            Ok(result) => Ok(result),
            Err(KnowledgeQueryAdmissionErrorV2::Query(error)) => Err(error),
            Err(KnowledgeQueryAdmissionErrorV2::InvalidBudget { .. })
            | Err(KnowledgeQueryAdmissionErrorV2::BudgetExceeded { .. })
            | Err(KnowledgeQueryAdmissionErrorV2::Resource(_)) => {
                Err(KnowledgeGenerationErrorV2::InvalidQueryLimit)
            }
        }
    }

    /// The bounded external query contract without a caller-owned guard.
    ///
    /// This retains the existing API while using an unbounded, uncancelled guard.
    /// Product owners should call [`Self::query_relations_external_guarded`].
    pub fn query_relations_external(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: Option<u64>,
    ) -> Result<
        (KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2),
        KnowledgeQueryAdmissionErrorV2,
    > {
        let guard = KnowledgeOperationGuardV2::unbounded(KnowledgeCancellationV2::default());
        self.query_relations_external_guarded(query, maximum_support_work, &guard)
    }

    /// The bounded external query contract with a real operation boundary.
    ///
    /// `None` selects [`DEFAULT_QUERY_SUPPORT_WORK_V2`]. A caller may lower the
    /// budget but cannot raise [`MAX_QUERY_SUPPORT_WORK_V2`]. A successful empty
    /// result is `Ok`; exhausted work is `BudgetExceeded`; invalid admission is
    /// `InvalidBudget`; deadline/cancellation failures are `Resource`. No branch
    /// returns a partial success. The guard is checked before admission, while
    /// collecting incident indexes, per edge, periodically during support scans,
    /// before bulk support copies and before returning the terminal result.
    pub fn query_relations_external_guarded(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: Option<u64>,
        guard: &KnowledgeOperationGuardV2,
    ) -> Result<
        (KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2),
        KnowledgeQueryAdmissionErrorV2,
    > {
        guard.checkpoint()?;
        let maximum_support_work = maximum_support_work.unwrap_or(DEFAULT_QUERY_SUPPORT_WORK_V2);
        if maximum_support_work == 0 || maximum_support_work > MAX_QUERY_SUPPORT_WORK_V2 {
            return Err(KnowledgeQueryAdmissionErrorV2::InvalidBudget {
                requested_support_work: maximum_support_work,
                maximum_support_work: MAX_QUERY_SUPPORT_WORK_V2,
            });
        }
        self.query_relations_with_admitted_budget(query, maximum_support_work, None, guard)
    }

    pub(crate) fn query_relations_external_guarded_with_output_limit(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: Option<u64>,
        maximum_output_bytes: u64,
        guard: &KnowledgeOperationGuardV2,
    ) -> Result<
        (KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2),
        KnowledgeQueryAdmissionErrorV2,
    > {
        guard.checkpoint()?;
        let maximum_support_work = maximum_support_work.unwrap_or(DEFAULT_QUERY_SUPPORT_WORK_V2);
        if maximum_support_work == 0 || maximum_support_work > MAX_QUERY_SUPPORT_WORK_V2 {
            return Err(KnowledgeQueryAdmissionErrorV2::InvalidBudget {
                requested_support_work: maximum_support_work,
                maximum_support_work: MAX_QUERY_SUPPORT_WORK_V2,
            });
        }
        self.query_relations_with_admitted_budget(
            query,
            maximum_support_work,
            Some(maximum_output_bytes),
            guard,
        )
    }

    fn query_relations_with_admitted_budget(
        &self,
        query: KnowledgeRelationQueryV2,
        maximum_support_work: u64,
        maximum_output_bytes: Option<u64>,
        guard: &KnowledgeOperationGuardV2,
    ) -> Result<
        (KnowledgeRelationResultV2, KnowledgeRelationQueryWorkV2),
        KnowledgeQueryAdmissionErrorV2,
    > {
        guard.checkpoint()?;
        if query.generation_digest != self.generation.generation_digest {
            return Err(KnowledgeGenerationErrorV2::DigestMismatch("query_generation").into());
        }
        if query.seed_node_ids.len() > MAX_KNOWLEDGE_NODES_V2
            || query.relation_kinds.len() > MAX_KNOWLEDGE_EDGES_V2
        {
            return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit.into());
        }
        ensure_unique_ids("query_seed", &query.seed_node_ids)?;
        let seeds = query.seed_node_ids.iter().cloned().collect::<BTreeSet<_>>();
        let mut kinds = BTreeSet::new();
        for kind in &query.relation_kinds {
            if !kinds.insert(kind.clone()) {
                return Err(KnowledgeGenerationErrorV2::DuplicateRelationKind.into());
            }
        }
        let maximum = usize::try_from(query.maximum_edges).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_KNOWLEDGE_EDGES_V2 {
            return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit.into());
        }
        let request_digest = compute_query_request_digest(&query, &seeds, &kinds);
        let mut output_bytes = 0_u64;
        charge_output_bytes(
            &mut output_bytes,
            maximum_output_bytes,
            measure_query_result_base_bytes_v2(&query.query_id),
        )?;
        // A validated generation bounds this set by MAX_KNOWLEDGE_EDGES_V2;
        // undirected adjacency visits each edge at most twice. Sorted original
        // positions preserve reference ordering and deduplicate self-loops and
        // edges reached from multiple seeds.
        let mut incident = BTreeSet::new();
        for seed in &seeds {
            guard.checkpoint()?;
            if let Some(indices) = self.adjacency.get(seed) {
                incident.extend(indices.iter().copied());
            }
        }
        let mut work = KnowledgeRelationQueryWorkV2::default();
        let mut support_work = 0_u64;
        let mut next_support_checkpoint = SUPPORT_CHECKPOINT_INTERVAL;
        let mut visible_nodes = BTreeMap::<&StableId, bool>::new();
        let mut edges = Vec::new();
        let mut omitted_count = 0_u32;
        for index in incident {
            guard.checkpoint()?;
            let edge = &self.generation.edges[index];
            work.relation_edges_scanned += 1;
            if !kinds.is_empty() && !kinds.contains(&edge.identity.relation) {
                continue;
            }
            if let Some(at) = query.valid_at_unix_seconds {
                let mut endpoints_visible = true;
                for node_id in [&edge.identity.source_node_id, &edge.identity.target_node_id] {
                    let visible = match visible_nodes.entry(node_id) {
                        std::collections::btree_map::Entry::Occupied(entry) => *entry.get(),
                        std::collections::btree_map::Entry::Vacant(entry) => {
                            work.visibility_nodes_scanned += 1;
                            let mut visible = false;
                            for support in &self.generation.nodes[self.nodes[node_id]].supports {
                                charge_support_work(&mut support_work, maximum_support_work, 1)?;
                                checkpoint_support_work(
                                    guard,
                                    support_work,
                                    &mut next_support_checkpoint,
                                )?;
                                work.visibility_supports_inspected += 1;
                                if support.visible_at(at) {
                                    visible = true;
                                    break;
                                }
                            }
                            entry.insert(visible);
                            visible
                        }
                    };
                    if !visible {
                        endpoints_visible = false;
                        break;
                    }
                }
                if !endpoints_visible {
                    continue;
                }
            }
            // Once output is full, inspect visibility without copying payload.
            if edges.len() == maximum {
                let mut visible = query.valid_at_unix_seconds.is_none();
                if let Some(at) = query.valid_at_unix_seconds {
                    for support in &edge.supports {
                        charge_support_work(&mut support_work, maximum_support_work, 1)?;
                        checkpoint_support_work(guard, support_work, &mut next_support_checkpoint)?;
                        work.relation_supports_inspected += 1;
                        if support.visible_at(at) {
                            visible = true;
                            break;
                        }
                    }
                }
                if visible {
                    omitted_count += 1;
                    work.matching_edges += 1;
                    work.omitted_edges += 1;
                }
                continue;
            }
            let selected_supports = match query.valid_at_unix_seconds {
                Some(at) => {
                    let mut selected = Vec::new();
                    for support in &edge.supports {
                        charge_support_work(&mut support_work, maximum_support_work, 1)?;
                        checkpoint_support_work(guard, support_work, &mut next_support_checkpoint)?;
                        work.relation_supports_inspected += 1;
                        if support.visible_at(at) {
                            charge_support_work(&mut support_work, maximum_support_work, 1)?;
                            checkpoint_support_work(
                                guard,
                                support_work,
                                &mut next_support_checkpoint,
                            )?;
                            selected.push(support);
                        }
                    }
                    selected
                }
                None => {
                    charge_support_work(
                        &mut support_work,
                        maximum_support_work,
                        edge.supports.len(),
                    )?;
                    checkpoint_support_work(guard, support_work, &mut next_support_checkpoint)?;
                    edge.supports.iter().collect::<Vec<_>>()
                }
            };
            if selected_supports.is_empty() {
                continue;
            }
            charge_output_bytes(
                &mut output_bytes,
                maximum_output_bytes,
                measure_query_edge_bytes_v2(edge, &selected_supports),
            )?;
            guard.checkpoint()?;
            let supports = selected_supports.into_iter().cloned().collect::<Vec<_>>();
            work.matching_edges += 1;
            work.selected_edges_cloned += 1;
            work.selected_supports_cloned += saturating_u64(supports.len());
            edges.push(KnowledgeEdgeV2 {
                identity: edge.identity.clone(),
                confidence: edge.confidence,
                validity_digest: edge.validity_digest,
                supports,
            });
        }
        guard.checkpoint()?;
        let mut result = KnowledgeRelationResultV2 {
            query_id: query.query_id,
            generation_digest: self.generation.generation_digest,
            valid_at_unix_seconds: query.valid_at_unix_seconds,
            request_digest,
            edges,
            omitted_count,
            result_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        result.result_digest = compute_query_result_digest(&result);
        guard.checkpoint()?;
        Ok((result, work))
    }
}

#[cfg(test)]
#[path = "indexed_query_budget_tests.rs"]
mod budget_tests;
