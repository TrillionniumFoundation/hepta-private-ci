use crate::{
    ContractError, Digest32, EventId, MAX_CUE_SEEDS, MAX_GRAPH_HOPS, MAX_SUBGRAPH_NODES,
    MemoryEvent, NodeId, PrincipalScope,
};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AssociativeSubgraph {
    pub nodes: BTreeSet<NodeId>,
    pub readable_events: BTreeSet<EventId>,
    pub hops_executed: u8,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ContractLedger {
    events: BTreeMap<EventId, MemoryEvent>,
    source_to_events: BTreeMap<Digest32, BTreeSet<EventId>>,
    revoked_sources: BTreeSet<Digest32>,
    node_support: BTreeMap<NodeId, BTreeSet<EventId>>,
    adjacency: BTreeMap<NodeId, BTreeSet<NodeId>>,
}

impl ContractLedger {
    pub fn append_event(&mut self, event: MemoryEvent) -> Result<(), ContractError> {
        event.validate()?;
        if let Some(existing) = self.events.get(&event.event_id) {
            return if existing == &event {
                Ok(())
            } else {
                Err(ContractError::Conflict(
                    "event identity reused with different content",
                ))
            };
        }
        for source in &event.provenance {
            self.source_to_events
                .entry(source.source_sha256.clone())
                .or_default()
                .insert(event.event_id);
        }
        self.events.insert(event.event_id, event);
        Ok(())
    }

    pub fn bind_node(
        &mut self,
        node_id: NodeId,
        support_events: BTreeSet<EventId>,
    ) -> Result<(), ContractError> {
        if node_id == 0 || support_events.is_empty() || support_events.len() > 64 {
            return Err(ContractError::BoundExceeded("node support"));
        }
        if support_events
            .iter()
            .any(|event_id| !self.events.contains_key(event_id))
        {
            return Err(ContractError::Missing("node support event"));
        }
        if let Some(existing) = self.node_support.get(&node_id) {
            return if existing == &support_events {
                Ok(())
            } else {
                Err(ContractError::Conflict(
                    "node identity reused with different support",
                ))
            };
        }
        self.node_support.insert(node_id, support_events);
        self.adjacency.entry(node_id).or_default();
        Ok(())
    }

    pub fn connect(&mut self, source: NodeId, target: NodeId) -> Result<(), ContractError> {
        if source == 0 || target == 0 || source == target {
            return Err(ContractError::Invalid(
                "edge endpoints must be distinct non-zero ids",
            ));
        }
        if !self.node_support.contains_key(&source) || !self.node_support.contains_key(&target) {
            return Err(ContractError::Missing("edge endpoint"));
        }
        self.adjacency.entry(source).or_default().insert(target);
        self.adjacency.entry(target).or_default();
        Ok(())
    }

    pub fn revoke_source(&mut self, source_sha256: Digest32) -> BTreeSet<EventId> {
        let affected = self
            .source_to_events
            .get(&source_sha256)
            .cloned()
            .unwrap_or_default();
        self.revoked_sources.insert(source_sha256);
        affected
    }

    pub fn readable_event(
        &self,
        event_id: EventId,
        principal: &PrincipalScope,
        now_unix_ms: i64,
    ) -> Option<&MemoryEvent> {
        self.events
            .get(&event_id)
            .filter(|event| event.is_readable(principal, now_unix_ms, &self.revoked_sources))
    }

    pub fn expand_associative_subgraph(
        &self,
        seed_nodes: &BTreeSet<NodeId>,
        principal: &PrincipalScope,
        now_unix_ms: i64,
        maximum_hops: u8,
        maximum_nodes: usize,
    ) -> Result<AssociativeSubgraph, ContractError> {
        principal.validate()?;
        if seed_nodes.is_empty()
            || seed_nodes.len() > MAX_CUE_SEEDS
            || seed_nodes.contains(&0)
            || maximum_hops == 0
            || maximum_hops > MAX_GRAPH_HOPS
            || maximum_nodes == 0
            || maximum_nodes > MAX_SUBGRAPH_NODES
        {
            return Err(ContractError::BoundExceeded("subgraph request"));
        }
        if seed_nodes
            .iter()
            .any(|node_id| !self.node_support.contains_key(node_id))
        {
            return Err(ContractError::Missing("seed node"));
        }
        let mut nodes = BTreeSet::new();
        let mut queue = VecDeque::new();
        for node_id in seed_nodes {
            if self.node_has_readable_support(*node_id, principal, now_unix_ms) {
                nodes.insert(*node_id);
                queue.push_back((*node_id, 0_u8));
            }
        }
        let mut hops_executed = 0_u8;
        while let Some((node_id, depth)) = queue.pop_front() {
            hops_executed = hops_executed.max(depth);
            if depth == maximum_hops {
                continue;
            }
            for neighbor in self
                .adjacency
                .get(&node_id)
                .into_iter()
                .flat_map(|neighbors| neighbors.iter())
            {
                if nodes.len() >= maximum_nodes {
                    break;
                }
                if nodes.contains(neighbor)
                    || !self.node_has_readable_support(*neighbor, principal, now_unix_ms)
                {
                    continue;
                }
                nodes.insert(*neighbor);
                queue.push_back((*neighbor, depth + 1));
            }
        }
        let readable_events = nodes
            .iter()
            .flat_map(|node_id| {
                self.node_support
                    .get(node_id)
                    .into_iter()
                    .flat_map(|events| events.iter())
            })
            .filter(|event_id| {
                self.readable_event(**event_id, principal, now_unix_ms)
                    .is_some()
            })
            .copied()
            .collect();
        Ok(AssociativeSubgraph {
            nodes,
            readable_events,
            hops_executed,
        })
    }

    fn node_has_readable_support(
        &self,
        node_id: NodeId,
        principal: &PrincipalScope,
        now_unix_ms: i64,
    ) -> bool {
        self.node_support.get(&node_id).is_some_and(|events| {
            events.iter().any(|event_id| {
                self.readable_event(*event_id, principal, now_unix_ms)
                    .is_some()
            })
        })
    }
}
