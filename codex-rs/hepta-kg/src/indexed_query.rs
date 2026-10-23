//! Immutable, validated query view. Indexes are derived, never source truth.
//!
//! Owners must bind this view to their read transaction/source cut. It does not
//! prove that a historical generation is still current or grant any authority.

use super::*;

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
        if query.seed_node_ids.len() > MAX_KNOWLEDGE_NODES_V2
            || query.relation_kinds.len() > MAX_KNOWLEDGE_EDGES_V2
        {
            return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit);
        }
        if query.generation_digest != self.generation.generation_digest {
            return Err(KnowledgeGenerationErrorV2::DigestMismatch(
                "query_generation",
            ));
        }
        ensure_unique_ids("query_seed", &query.seed_node_ids)?;
        let seeds = query.seed_node_ids.iter().cloned().collect::<BTreeSet<_>>();
        let mut kinds = BTreeSet::new();
        for kind in &query.relation_kinds {
            if !kinds.insert(kind.clone()) {
                return Err(KnowledgeGenerationErrorV2::DuplicateRelationKind);
            }
        }
        let maximum = usize::try_from(query.maximum_edges).unwrap_or(usize::MAX);
        if maximum == 0 || maximum > MAX_KNOWLEDGE_EDGES_V2 {
            return Err(KnowledgeGenerationErrorV2::InvalidQueryLimit);
        }
        let request_digest = compute_query_request_digest(&query, &seeds, &kinds);
        // Sorted original positions preserve the reference full-scan ordering,
        // including self-loops and edges reached from multiple seeds.
        let incident = seeds
            .iter()
            .filter_map(|seed| self.adjacency.get(seed))
            .flat_map(|indices| indices.iter().copied())
            .collect::<BTreeSet<_>>();
        let mut work = KnowledgeRelationQueryWorkV2::default();
        let mut visible_nodes = BTreeMap::<&StableId, bool>::new();
        let mut edges = Vec::new();
        let mut omitted_count = 0_u32;
        for index in incident {
            let edge = &self.generation.edges[index];
            work.relation_edges_scanned += 1;
            if !kinds.is_empty() && !kinds.contains(&edge.identity.relation) {
                continue;
            }
            if let Some(at) = query.valid_at_unix_seconds {
                let mut endpoints_visible = true;
                for node_id in [&edge.identity.source_node_id, &edge.identity.target_node_id] {
                    let visible = *visible_nodes.entry(node_id).or_insert_with(|| {
                        work.visibility_nodes_scanned += 1;
                        self.generation.nodes[self.nodes[node_id]]
                            .supports
                            .iter()
                            .any(|support| {
                                work.visibility_supports_inspected += 1;
                                support.visible_at(at)
                            })
                    });
                    if !visible {
                        endpoints_visible = false;
                        break;
                    }
                }
                if !endpoints_visible {
                    continue;
                }
            }
            // Once the output is full, count visibility without cloning payload.
            if edges.len() == maximum {
                let visible = query.valid_at_unix_seconds.is_none_or(|at| {
                    edge.supports.iter().any(|support| {
                        work.relation_supports_inspected += 1;
                        support.visible_at(at)
                    })
                });
                if visible {
                    omitted_count += 1;
                    work.matching_edges += 1;
                    work.omitted_edges += 1;
                }
                continue;
            }
            let supports = match query.valid_at_unix_seconds {
                Some(at) => edge
                    .supports
                    .iter()
                    .filter(|support| {
                        work.relation_supports_inspected += 1;
                        support.visible_at(at)
                    })
                    .cloned()
                    .collect::<Vec<_>>(),
                None => edge.supports.clone(),
            };
            if supports.is_empty() {
                continue;
            }
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
        Ok((result, work))
    }
}
