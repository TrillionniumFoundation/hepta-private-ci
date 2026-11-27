//! Immutable, validated query view. Indexes are derived, never source truth.
//!
//! Owners must bind this view to their read transaction/source cut. It does not
//! prove that a historical generation is still current or grant any authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use super::KnowledgeGenerationErrorV2;
use super::KnowledgeGenerationV2;
use super::KnowledgeRelationKindV2;
use super::KnowledgeRelationQueryV2;
use super::KnowledgeRelationQueryWorkV2;
use super::KnowledgeRelationResultV2;
use super::StableId;
use super::assemble_relation_query_result;
use super::collect_relation_query_edges;
use super::relation_query_plan;

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
        let plan = relation_query_plan(self.generation.generation_digest, &query)?;
        // Preserve generation ordering and visit self-loops or edges reached
        // from both seeds only once.
        let incident = plan
            .seeds
            .iter()
            .filter_map(|seed| self.adjacency.get(seed))
            .flat_map(|indices| indices.iter().copied())
            .collect::<BTreeSet<_>>();
        let mut work = KnowledgeRelationQueryWorkV2::default();
        let mut visible_nodes = BTreeMap::<&StableId, bool>::new();
        let (edges, omitted_count) = collect_relation_query_edges::<true>(
            incident
                .into_iter()
                .map(|index| &self.generation.edges[index]),
            |edge, work| {
                if !plan.relation_kinds.is_empty()
                    && !plan.relation_kinds.contains(&edge.identity.relation)
                {
                    return false;
                }
                query.valid_at_unix_seconds.is_none_or(|at| {
                    [&edge.identity.source_node_id, &edge.identity.target_node_id]
                        .into_iter()
                        .all(|node_id| {
                            *visible_nodes.entry(node_id).or_insert_with(|| {
                                work.visibility_nodes_scanned += 1;
                                self.generation.nodes[self.nodes[node_id]]
                                    .supports
                                    .iter()
                                    .any(|support| {
                                        work.visibility_supports_inspected += 1;
                                        support.visible_at(at)
                                    })
                            })
                        })
                })
            },
            query.valid_at_unix_seconds,
            plan.maximum_edges,
            &mut work,
        );
        Ok((
            assemble_relation_query_result(
                query,
                self.generation.generation_digest,
                plan.request_digest,
                edges,
                omitted_count,
            ),
            work,
        ))
    }
}
