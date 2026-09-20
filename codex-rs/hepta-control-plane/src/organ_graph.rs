//! Bounded, versioned graph validation. Evidence references are not admissions.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganRole {
    Cognitive,
    LocalSafety,
    Other,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FallbackTerminal {
    None,
    SafeState(Digest32),
    HumanTakeover(Digest32),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganNodeV1 {
    pub id: StableId,
    pub owner: StableId,
    pub role: OrganRole,
    pub inputs: Vec<StableId>,
    pub outputs: Vec<StableId>,
    pub effect_scope: BTreeSet<StableId>,
    pub terminal: FallbackTerminal,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct OrganEdge {
    pub from: usize,
    pub to: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OutputPort {
    pub organ: usize,
    pub port: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct InputPort {
    pub organ: usize,
    pub port: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DataflowTiming {
    Buffered,
    Synchronous,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeLinkV1 {
    pub output: OutputPort,
    pub input: InputPort,
    pub timing: DataflowTiming,
}

/// Binds declared bounds and evidence to exactly one runtime SCC and generation.
/// Validation checks structural completeness, not the truth of stability claims.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeedbackProfileV1 {
    pub members: BTreeSet<usize>,
    pub reference_generation: Generation,
    pub period_ns: u64,
    pub delay_ns: u64,
    pub jitter_ns: u64,
    pub queue_capacity: u32,
    pub max_gain_q24: u64,
    pub saturation_q24: u64,
    pub gains_and_saturation: Digest32,
    pub operating_region: Digest32,
    pub stability_analysis: Digest32,
    pub perturbation_tests: Digest32,
    pub exit_organ: usize,
}

/// Process and host membership describes correlated failure, never precedence.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FailureDomainV1 {
    pub organ: usize,
    pub process: StableId,
    pub host: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganGraphsV1 {
    pub generation: Generation,
    pub organs: Vec<OrganNodeV1>,
    pub initialization: Vec<OrganEdge>,
    pub runtime: Vec<RuntimeLinkV1>,
    pub feedback: Vec<FeedbackProfileV1>,
    pub fallback: Vec<OrganEdge>,
    pub failure_domains: Vec<FailureDomainV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedOrganGraphsV1 {
    pub initialization_order: Vec<usize>,
    pub fallback_order: Vec<usize>,
    pub feedback_components: Vec<BTreeSet<usize>>,
    pub host_failure_sets: BTreeMap<StableId, BTreeSet<usize>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OrganGraphError {
    Bounds,
    DuplicateIdentity,
    InvalidEdge,
    InitializationCycle,
    PortMismatch,
    DuplicateInput,
    CentralSafetyDependency,
    FeedbackProfile,
    FallbackCycle,
    UnsafeFallback,
    FailureDomain,
}

impl OrganGraphsV1 {
    pub fn validate(&self) -> Result<ValidatedOrganGraphsV1, OrganGraphError> {
        use OrganGraphError as E;
        let n = self.organs.len();
        if n == 0
            || n > 128
            || self.initialization.len() > 1024
            || self.runtime.len() > 1024
            || self.fallback.len() > 1024
            || self.feedback.len() > n
            || self.failure_domains.len() != n
            || self.feedback.iter().any(|p| p.members.len() > n)
            || self
                .organs
                .iter()
                .any(|o| o.inputs.len() > 32 || o.outputs.len() > 32 || o.effect_scope.len() > 32)
        {
            return Err(E::Bounds);
        }
        if self
            .organs
            .iter()
            .map(|o| &o.id)
            .collect::<BTreeSet<_>>()
            .len()
            != n
        {
            return Err(E::DuplicateIdentity);
        }
        let initialization_order = dag_order(n, &self.initialization, E::InitializationCycle)?;
        let fallback_order = dag_order(n, &self.fallback, E::FallbackCycle)?;
        for node in &self.organs {
            match node.terminal {
                FallbackTerminal::None => {}
                FallbackTerminal::SafeState(digest) | FallbackTerminal::HumanTakeover(digest) => {
                    if digest.is_zero() {
                        return Err(E::UnsafeFallback);
                    }
                }
            }
        }
        for (i, organ) in self.organs.iter().enumerate() {
            let edges: Vec<_> = self.fallback.iter().filter(|e| e.from == i).collect();
            if edges.is_empty() == matches!(organ.terminal, FallbackTerminal::None)
                || edges.iter().any(|e| {
                    !self.organs[e.to]
                        .effect_scope
                        .is_subset(&organ.effect_scope)
                })
            {
                return Err(E::UnsafeFallback);
            }
        }
        let mut reach = vec![vec![false; n]; n];
        let mut synchronous = reach.clone();
        let mut inputs = BTreeSet::new();
        for link in &self.runtime {
            let source = self
                .organs
                .get(link.output.organ)
                .and_then(|o| o.outputs.get(link.output.port));
            let target = self
                .organs
                .get(link.input.organ)
                .and_then(|o| o.inputs.get(link.input.port));
            if source.is_none() || source != target {
                return Err(E::PortMismatch);
            }
            if !inputs.insert((link.input.organ, link.input.port)) {
                return Err(E::DuplicateInput);
            }
            reach[link.output.organ][link.input.organ] = true;
            synchronous[link.output.organ][link.input.organ] |=
                link.timing == DataflowTiming::Synchronous;
        }
        if inputs.len() != self.organs.iter().map(|o| o.inputs.len()).sum::<usize>() {
            return Err(E::PortMismatch);
        }
        close_reachability(&mut reach);
        close_reachability(&mut synchronous);
        for (source, paths) in synchronous.iter().enumerate() {
            if self.organs[source].role == OrganRole::Cognitive
                && paths.iter().enumerate().any(|(target, reachable)| {
                    *reachable && self.organs[target].role == OrganRole::LocalSafety
                })
            {
                return Err(E::CentralSafetyDependency);
            }
        }
        let mut seen: BTreeSet<usize> = BTreeSet::new();
        let mut feedback_components = Vec::new();
        let mut fallback_reach = vec![vec![false; n]; n];
        for edge in &self.fallback {
            fallback_reach[edge.from][edge.to] = true;
        }
        close_reachability(&mut fallback_reach);
        for (i, paths) in reach.iter().enumerate() {
            if !paths[i] || seen.contains(&i) {
                continue;
            }
            let members: BTreeSet<_> = (0..n).filter(|&j| paths[j] && reach[j][i]).collect();
            let profiles: Vec<_> = self
                .feedback
                .iter()
                .filter(|p| p.members == members)
                .collect();
            if profiles.len() != 1 {
                return Err(E::FeedbackProfile);
            }
            let p = profiles[0];
            if p.reference_generation != self.generation
                || p.period_ns == 0
                || p.delay_ns
                    .checked_add(p.jitter_ns)
                    .is_none_or(|delay| delay > p.period_ns)
                || p.queue_capacity == 0
                || p.queue_capacity > 4096
                || p.max_gain_q24 == 0
                || p.saturation_q24 == 0
                || p.gains_and_saturation.is_zero()
                || p.operating_region.is_zero()
                || p.stability_analysis.is_zero()
                || p.perturbation_tests.is_zero()
                || self
                    .organs
                    .get(p.exit_organ)
                    .is_none_or(|o| matches!(o.terminal, FallbackTerminal::None))
                || members.contains(&p.exit_organ)
            {
                return Err(E::FeedbackProfile);
            }
            // An exit must be reachable through the separately validated fallback DAG.
            if members
                .iter()
                .any(|&member| !fallback_reach[member][p.exit_organ])
            {
                return Err(E::FeedbackProfile);
            }
            seen.extend(&members);
            feedback_components.push(members);
        }
        if feedback_components.len() != self.feedback.len() {
            return Err(E::FeedbackProfile);
        }
        let mut assigned = BTreeSet::new();
        let mut processes = BTreeMap::new();
        let mut host_failure_sets: BTreeMap<StableId, BTreeSet<usize>> = BTreeMap::new();
        for domain in &self.failure_domains {
            if domain.organ >= n
                || !assigned.insert(domain.organ)
                || processes
                    .insert(&domain.process, &domain.host)
                    .is_some_and(|host| host != &domain.host)
            {
                return Err(E::FailureDomain);
            }
            host_failure_sets
                .entry(domain.host.clone())
                .or_default()
                .insert(domain.organ);
        }
        Ok(ValidatedOrganGraphsV1 {
            initialization_order,
            fallback_order,
            feedback_components,
            host_failure_sets,
        })
    }
}

fn dag_order(
    n: usize,
    edges: &[OrganEdge],
    cycle: OrganGraphError,
) -> Result<Vec<usize>, OrganGraphError> {
    let mut incoming = vec![0; n];
    let mut unique = BTreeSet::new();
    for edge in edges {
        if edge.from >= n || edge.to >= n || !unique.insert(*edge) {
            return Err(OrganGraphError::InvalidEdge);
        }
        incoming[edge.to] += 1;
    }
    let mut ready: BTreeSet<_> = (0..n).filter(|&i| incoming[i] == 0).collect();
    let mut order = Vec::with_capacity(n);
    while let Some(node) = ready.pop_first() {
        order.push(node);
        for edge in edges.iter().filter(|e| e.from == node) {
            incoming[edge.to] -= 1;
            if incoming[edge.to] == 0 {
                ready.insert(edge.to);
            }
        }
    }
    if order.len() == n {
        Ok(order)
    } else {
        Err(cycle)
    }
}

fn close_reachability(reach: &mut [Vec<bool>]) {
    for k in 0..reach.len() {
        for i in 0..reach.len() {
            for j in 0..reach.len() {
                reach[i][j] |= reach[i][k] && reach[k][j];
            }
        }
    }
}

#[cfg(test)]
#[path = "organ_graph_tests.rs"]
mod tests;
