//! Authority-safe route binding for a DecisionCell split.
//!
//! The existing CNS host owns lifecycle and dispatch.  This adapter binds a
//! validated [`CellSplitV1`] to one concrete predecessor route and to one
//! concrete route for each child.  It deliberately does not evaluate route
//! predicates or publish topology: the owning router/governance path supplies
//! the predicate revision and the admitted successor host.  Once the host
//! cutover succeeds, the predecessor route is fenced by generation and route
//! identity before any child dispatch is accepted.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

use codex_hepta_types::CellParentDispositionV1;
use codex_hepta_types::CellSplitContractErrorV1;
use codex_hepta_types::CellSplitV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::PhaseLatencyHistogramV1;
use codex_hepta_types::PhaseLatencySnapshotV1;
use codex_hepta_types::{PhaseMetricEventV1, PhaseMetricKindV1, PhaseMetricSinkV1};
use codex_hepta_types::StableId;

use crate::CnsDeliveryV1;
use crate::CnsHierarchyError;
use crate::CnsOrganHostV1;
use crate::CnsRouteV1;
use crate::OrganRuntimeError;
use crate::OrganStateMigrationV1;

use super::cell_split_route_digest::cns_child_port_compatibility_digest_v1;
use super::cell_split_route_digest::cns_circuit_route_digest_v1;
use super::cell_split_route_digest::cns_organ_abi_set_digest_v1;
use super::cell_split_route_digest::cns_organ_input_port_digest_v1;
use super::cell_split_route_digest::cns_organ_termination_port_digest_v1;
use super::cell_split_route_digest::cns_route_port_binding_digest_v1;
use super::cell_split_route_fence::CellSplitRouteFenceReceiptV1;

/// Route owner reported in a dispatch receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitRouteOwnerV1 {
    Parent,
    Child(StableId),
}

/// Lifecycle phase enforced by the adapter.  Children become visible only
/// after the CNS host has started the successor and stopped the predecessor.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellSplitRoutePhaseV1 {
    ParentActive,
    ChildrenActive,
    Quarantined,
}

/// The concrete child route and its immutable cell routing identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitChildRouteV1 {
    pub child_cell_id: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
    pub route: CnsRouteV1,
}

/// Selection produced by the external route owner after evaluating a task.
/// The controller verifies every field against the admitted child before it
/// invokes the CNS handler; it does not pretend to be the predicate evaluator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitRouteSelectionV1 {
    pub child_cell_id: StableId,
    pub scope_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub fallback_route_digest: Digest32,
}

/// Receipt emitted after the underlying CNS host has completed a dispatch.
/// It is an observation, not runtime authority or a proof of external effect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitDispatchReceiptV1 {
    pub split_id: StableId,
    pub route_owner: CellSplitRouteOwnerV1,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub route_predicate_digest: Digest32,
    pub payload_digest: Digest32,
    pub delivery_count: usize,
    pub parent_route_fenced: bool,
    pub parent_route_fence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitRouteErrorV1 {
    Contract(CellSplitContractErrorV1),
    ParentRouteNotCurrent,
    ParentRouteOrgan,
    ParentRouteGeneration,
    ParentRoutePort,
    ParentAbi,
    CircuitRoute,
    CnsIdentity,
    ChildRouteCount,
    ChildRouteNotCurrent(StableId),
    ChildRouteOrgan(StableId),
    ChildRouteGeneration(StableId),
    ChildRoutePort(StableId),
    CandidateParentRoute(StableId),
    RoutePredicateMismatch(StableId),
    RouteSelectionMismatch(StableId),
    ParentDispatchUnavailable(CellSplitRoutePhaseV1),
    ChildDispatchUnavailable(CellSplitRoutePhaseV1),
    ParentRouteFenced,
    MissingRouteFence,
    RouteFenceMismatch,
    RestartReplayRequiresRetire,
    RestartGeneration,
    ParentRouteResurrected,
    TombstoneMismatch,
    Runtime(CnsHierarchyError),
    RuntimeOwner(OrganRuntimeError),
}

impl fmt::Display for CellSplitRouteErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellSplitRouteErrorV1 {}

impl From<CellSplitContractErrorV1> for CellSplitRouteErrorV1 {
    fn from(error: CellSplitContractErrorV1) -> Self {
        Self::Contract(error)
    }
}

impl From<CnsHierarchyError> for CellSplitRouteErrorV1 {
    fn from(error: CnsHierarchyError) -> Self {
        Self::Runtime(error)
    }
}

impl From<OrganRuntimeError> for CellSplitRouteErrorV1 {
    fn from(error: OrganRuntimeError) -> Self {
        Self::RuntimeOwner(error)
    }
}

/// Binds a typed split to the existing CNS host lifecycle.
///
/// `CellSplitRouteControllerV1` has no authority to select or publish a
/// candidate.  Callers must provide an independently admitted successor host
/// and concrete routes.  It only enforces the ordering and fencing invariants
/// at the dispatch boundary.
#[derive(Debug)]
pub struct CellSplitRouteControllerV1 {
    host: CnsOrganHostV1,
    split: CellSplitV1,
    parent_route: CnsRouteV1,
    children: BTreeMap<StableId, CellSplitChildRouteV1>,
    fence_receipt: Option<CellSplitRouteFenceReceiptV1>,
    phase: CellSplitRoutePhaseV1,
    cns_cutover_latency: PhaseLatencyHistogramV1,
    metrics: Option<Arc<dyn PhaseMetricSinkV1>>,
    failed_metrics: AtomicU64,
}

impl CellSplitRouteControllerV1 {
    /// Bind a split to the exact currently admitted parent route.
    pub fn new(
        host: CnsOrganHostV1,
        split: CellSplitV1,
        parent_route: CnsRouteV1,
    ) -> Result<Self, CellSplitRouteErrorV1> {
        split.validate_plan()?;
        validate_parent_route(&host, &split, &parent_route)?;
        Ok(Self {
            host,
            split,
            parent_route,
            children: BTreeMap::new(),
            fence_receipt: None,
            phase: CellSplitRoutePhaseV1::ParentActive,
            cns_cutover_latency: PhaseLatencyHistogramV1::default(),
            metrics: None,
            failed_metrics: AtomicU64::new(0),
        })
    }

    pub fn generation(&self) -> Generation {
        self.host.generation()
    }

    pub fn phase(&self) -> CellSplitRoutePhaseV1 {
        self.phase
    }

    pub fn with_metrics_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metrics = Some(sink);
        self
    }

    pub fn production_metrics_ready(&self) -> bool {
        self.metrics.as_ref().is_some_and(|sink| sink.healthy())
            && self.failed_metrics.load(Ordering::Acquire) == 0
    }

    pub fn flush_production_metrics(&self) -> bool {
        let Some(sink) = &self.metrics else { return false; };
        if sink.flush().is_err() {
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return false;
        }
        self.production_metrics_ready()
    }

    fn report_cutover(
        &self, started: Instant, operation: Digest32, succeeded: bool,
    ) {
        if let Some(sink) = &self.metrics {
            if sink.record(PhaseMetricEventV1 {
                scope_digest: Digest32::of_bytes(self.split.split_id.as_str().as_bytes()),
                operation_digest: operation,
                phase: PhaseMetricKindV1::Cns,
                latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
                succeeded,
            }).is_err() {
                self.failed_metrics.fetch_add(1, Ordering::Release);
            }
        }
    }

    pub fn cns_latency_observations(&self) -> PhaseLatencySnapshotV1 {
        self.cns_cutover_latency.snapshot()
    }

    pub fn parent_route(&self) -> &CnsRouteV1 {
        &self.parent_route
    }

    pub fn host(&self) -> &CnsOrganHostV1 {
        &self.host
    }

    pub fn route_fence_receipt(&self) -> Option<&CellSplitRouteFenceReceiptV1> {
        self.fence_receipt.as_ref()
    }

    pub fn child_route(&self, child_cell_id: &StableId) -> Option<&CellSplitChildRouteV1> {
        self.children.get(child_cell_id)
    }

    pub fn start_all(&mut self) -> Result<(), CellSplitRouteErrorV1> {
        if let Err(error) = self
            .host
            .start_all()
            .map_err(CellSplitRouteErrorV1::Runtime)
        {
            self.phase = CellSplitRoutePhaseV1::Quarantined;
            return Err(error);
        }
        Ok(())
    }

    /// Dispatch through the parent while the split is still pending.
    pub fn dispatch_parent_once(
        &mut self,
        route: &CnsRouteV1,
        payload: &[u8],
    ) -> Result<(Vec<CnsDeliveryV1>, CellSplitDispatchReceiptV1), CellSplitRouteErrorV1> {
        if self.phase != CellSplitRoutePhaseV1::ParentActive {
            return Err(CellSplitRouteErrorV1::ParentDispatchUnavailable(self.phase));
        }
        if route != &self.parent_route {
            return Err(CellSplitRouteErrorV1::ParentRouteFenced);
        }
        let deliveries = self
            .host
            .dispatch_once(route, payload)
            .map_err(CellSplitRouteErrorV1::Runtime)?;
        let receipt = CellSplitDispatchReceiptV1 {
            split_id: self.split.split_id.clone(),
            route_owner: CellSplitRouteOwnerV1::Parent,
            generation: route.generation,
            scope_digest: self.split.parent_scope_digest,
            route_predicate_digest: Digest32::ZERO,
            payload_digest: Digest32::of_bytes(payload),
            delivery_count: deliveries.len(),
            parent_route_fenced: false,
            parent_route_fence_digest: Digest32::ZERO,
        };
        Ok((deliveries, receipt))
    }

    /// Activate all child routes through the existing generation cutover.
    ///
    /// The candidate is started and the predecessor is stopped by
    /// `CnsOrganHostV1`.  Child routes are stored only after that method
    /// succeeds, so a failed candidate can never receive dispatch.
    pub fn activate_children(
        &mut self,
        expected: Generation,
        next: CnsOrganHostV1,
        child_routes: Vec<CnsRouteV1>,
    ) -> Result<(), CellSplitRouteErrorV1> {
        self.split.validate()?;
        self.validate_child_routes(&next, &child_routes)?;
        let children = self.bind_child_routes(child_routes)?;
        let fence = CellSplitRouteFenceReceiptV1::new(&self.split, &self.parent_route)?;
        let started = Instant::now();
        let cutover = self.cns_cutover_latency.time_result(|| {
            self.host
                .replace_read_only_generation(expected, next)
                .map_err(CellSplitRouteErrorV1::Runtime)
        });
        self.report_cutover(started, fence.fence_digest, cutover.is_ok());
        if let Err(error) = cutover {
            self.phase = CellSplitRoutePhaseV1::Quarantined;
            return Err(error);
        }
        self.children = children;
        self.fence_receipt = Some(fence);
        self.phase = CellSplitRoutePhaseV1::ChildrenActive;
        Ok(())
    }

    /// Variant used when the authoritative state owner must migrate state
    /// before CNS publishes the successor generation.
    pub fn activate_children_with_migration<M: OrganStateMigrationV1 + ?Sized>(
        &mut self,
        expected: Generation,
        next: CnsOrganHostV1,
        child_routes: Vec<CnsRouteV1>,
        migration: &mut M,
    ) -> Result<(), CellSplitRouteErrorV1> {
        self.split.validate()?;
        self.validate_child_routes(&next, &child_routes)?;
        let children = self.bind_child_routes(child_routes)?;
        let fence = CellSplitRouteFenceReceiptV1::new(&self.split, &self.parent_route)?;
        let started = Instant::now();
        let cutover = self.cns_cutover_latency.time_result(|| {
            self.host
                .replace_read_only_generation_with_migration(expected, next, migration)
                .map_err(CellSplitRouteErrorV1::Runtime)
        });
        self.report_cutover(started, fence.fence_digest, cutover.is_ok());
        if let Err(error) = cutover {
            self.phase = CellSplitRoutePhaseV1::Quarantined;
            return Err(error);
        }
        self.children = children;
        self.fence_receipt = Some(fence);
        self.phase = CellSplitRoutePhaseV1::ChildrenActive;
        Ok(())
    }

    /// Dispatch through an activated child after the route owner has selected
    /// its admitted predicate revision.
    pub fn dispatch_child_once(
        &mut self,
        selection: &CellSplitRouteSelectionV1,
        route: &CnsRouteV1,
        payload: &[u8],
    ) -> Result<(Vec<CnsDeliveryV1>, CellSplitDispatchReceiptV1), CellSplitRouteErrorV1> {
        if self.phase != CellSplitRoutePhaseV1::ChildrenActive {
            return Err(CellSplitRouteErrorV1::ChildDispatchUnavailable(self.phase));
        }
        let child = self.children.get(&selection.child_cell_id).ok_or_else(|| {
            CellSplitRouteErrorV1::ChildRouteNotCurrent(selection.child_cell_id.clone())
        })?;
        if route != &child.route {
            return Err(CellSplitRouteErrorV1::ParentRouteFenced);
        }
        if selection.scope_digest != child.scope_digest
            || selection.fallback_route_digest != child.fallback_route_digest
        {
            return Err(CellSplitRouteErrorV1::RouteSelectionMismatch(
                selection.child_cell_id.clone(),
            ));
        }
        if selection.route_predicate_digest != child.route_predicate_digest {
            return Err(CellSplitRouteErrorV1::RoutePredicateMismatch(
                selection.child_cell_id.clone(),
            ));
        }
        let deliveries = self
            .host
            .dispatch_once(route, payload)
            .map_err(CellSplitRouteErrorV1::Runtime)?;
        let receipt = CellSplitDispatchReceiptV1 {
            split_id: self.split.split_id.clone(),
            route_owner: CellSplitRouteOwnerV1::Child(selection.child_cell_id.clone()),
            generation: route.generation,
            scope_digest: child.scope_digest,
            route_predicate_digest: selection.route_predicate_digest,
            payload_digest: Digest32::of_bytes(payload),
            delivery_count: deliveries.len(),
            parent_route_fenced: true,
            parent_route_fence_digest: self
                .fence_receipt
                .as_ref()
                .ok_or(CellSplitRouteErrorV1::MissingRouteFence)?
                .fence_digest,
        };
        Ok((deliveries, receipt))
    }

    fn validate_child_routes(
        &self,
        next: &CnsOrganHostV1,
        child_routes: &[CnsRouteV1],
    ) -> Result<(), CellSplitRouteErrorV1> {
        if self.host.generation() != self.split.predecessor_generation
            || next.generation() != self.split.successor_generation
        {
            return Err(CellSplitRouteErrorV1::ParentRouteGeneration);
        }
        if self.host.cns != next.cns {
            return Err(CellSplitRouteErrorV1::CnsIdentity);
        }
        if child_routes.len() != self.split.children.len() {
            return Err(CellSplitRouteErrorV1::ChildRouteCount);
        }
        if self.split.retirement.disposition == CellParentDispositionV1::Retire
            && (next
                .routes
                .keys()
                .any(|(organ, _)| organ == &self.split.organ_id)
                || next
                    .statuses()
                    .iter()
                    .any(|status| status.id.as_str() == self.split.organ_id.as_str()))
        {
            return Err(CellSplitRouteErrorV1::CandidateParentRoute(
                self.split.parent_cell_id.clone(),
            ));
        }
        if cns_organ_input_port_digest_v1(&self.host, &self.split.organ_id)?
            != self.split.ports.parent_input_port_digest
        {
            return Err(CellSplitRouteErrorV1::ParentAbi);
        }
        let child_ids = self
            .split
            .children
            .iter()
            .map(|child| child.child_cell_id.clone())
            .collect::<Vec<_>>();
        if cns_organ_abi_set_digest_v1(next, &child_ids)? != self.split.ports.abi_digest {
            return Err(CellSplitRouteErrorV1::ParentAbi);
        }
        if cns_circuit_route_digest_v1(next, child_routes)? != self.split.ports.circuit_route_digest
        {
            return Err(CellSplitRouteErrorV1::CircuitRoute);
        }
        let mut seen_children = BTreeSet::new();
        for route in child_routes {
            let child = self
                .split
                .children
                .iter()
                .find(|child| child.child_cell_id == route.source.organ)
                .ok_or_else(|| {
                    CellSplitRouteErrorV1::ChildRouteOrgan(route.source.organ.clone())
                })?;
            if route.generation != self.split.successor_generation {
                return Err(CellSplitRouteErrorV1::ChildRouteGeneration(
                    child.child_cell_id.clone(),
                ));
            }
            if !seen_children.insert(child.child_cell_id.clone()) {
                return Err(CellSplitRouteErrorV1::ChildRouteNotCurrent(
                    child.child_cell_id.clone(),
                ));
            }
            if cns_route_port_binding_digest_v1(next, route)?
                != self.child_output_digest(child.child_cell_id.clone())?
            {
                return Err(CellSplitRouteErrorV1::ChildRoutePort(
                    child.child_cell_id.clone(),
                ));
            }
            let binding = self.child_port_binding(&child.child_cell_id)?;
            if cns_organ_input_port_digest_v1(next, &child.child_cell_id)?
                != binding.input_port_digest
                || cns_organ_termination_port_digest_v1(next, &child.child_cell_id)?
                    != binding.termination_port_digest
                || cns_child_port_compatibility_digest_v1(next, route)?
                    != binding.compatibility_digest
            {
                return Err(CellSplitRouteErrorV1::ChildRoutePort(
                    child.child_cell_id.clone(),
                ));
            }
            let expected = next
                .routes
                .get(&(route.source.organ.clone(), route.output_port))
                .ok_or_else(|| {
                    CellSplitRouteErrorV1::ChildRouteNotCurrent(child.child_cell_id.clone())
                })?;
            if expected != route {
                return Err(CellSplitRouteErrorV1::ChildRouteNotCurrent(
                    child.child_cell_id.clone(),
                ));
            }
        }
        if seen_children.len() != self.split.children.len()
            || self
                .split
                .children
                .iter()
                .any(|child| !seen_children.contains(&child.child_cell_id))
        {
            return Err(CellSplitRouteErrorV1::ChildRouteCount);
        }
        Ok(())
    }

    fn child_output_digest(
        &self,
        child_cell_id: StableId,
    ) -> Result<Digest32, CellSplitRouteErrorV1> {
        self.split
            .ports
            .children
            .iter()
            .find(|binding| binding.child_cell_id == child_cell_id)
            .map(|binding| binding.output_port_digest)
            .ok_or(CellSplitRouteErrorV1::ChildRouteNotCurrent(child_cell_id))
    }

    fn child_port_binding(
        &self,
        child_cell_id: &StableId,
    ) -> Result<&codex_hepta_types::CellChildPortBindingV1, CellSplitRouteErrorV1> {
        self.split
            .ports
            .children
            .iter()
            .find(|binding| &binding.child_cell_id == child_cell_id)
            .ok_or_else(|| CellSplitRouteErrorV1::ChildRouteNotCurrent(child_cell_id.clone()))
    }

    fn bind_child_routes(
        &self,
        child_routes: Vec<CnsRouteV1>,
    ) -> Result<BTreeMap<StableId, CellSplitChildRouteV1>, CellSplitRouteErrorV1> {
        child_routes
            .into_iter()
            .map(|route| {
                let child = self
                    .split
                    .children
                    .iter()
                    .find(|child| child.child_cell_id == route.source.organ)
                    .ok_or_else(|| {
                        CellSplitRouteErrorV1::ChildRouteOrgan(route.source.organ.clone())
                    })?;
                Ok((
                    child.child_cell_id.clone(),
                    CellSplitChildRouteV1 {
                        child_cell_id: child.child_cell_id.clone(),
                        generation: child.child_generation,
                        scope_digest: child.child_scope_digest,
                        route_predicate_digest: child.route_predicate_digest,
                        fallback_route_digest: child.fallback_route_digest,
                        route,
                    },
                ))
            })
            .collect()
    }
}

fn validate_parent_route(
    host: &CnsOrganHostV1,
    split: &CellSplitV1,
    route: &CnsRouteV1,
) -> Result<(), CellSplitRouteErrorV1> {
    if host.generation() != split.predecessor_generation
        || route.generation != split.predecessor_generation
    {
        return Err(CellSplitRouteErrorV1::ParentRouteGeneration);
    }
    if route.source.organ != split.organ_id {
        return Err(CellSplitRouteErrorV1::ParentRouteOrgan);
    }
    let expected = host
        .routes
        .get(&(route.source.organ.clone(), route.output_port))
        .ok_or(CellSplitRouteErrorV1::ParentRouteNotCurrent)?;
    if expected != route {
        return Err(CellSplitRouteErrorV1::ParentRouteNotCurrent);
    }
    if cns_route_port_binding_digest_v1(host, route)? != split.ports.parent_output_port_digest {
        return Err(CellSplitRouteErrorV1::ParentRoutePort);
    }
    Ok(())
}

#[cfg(test)]
#[path = "cell_split_route_tests.rs"]
mod tests;
