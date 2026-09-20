//! Immutable hierarchy and local routing for the existing read-only organ host.
//!
//! This module neither loads code nor issues authority. Driver identities name
//! reviewed, compiled-in handlers. Their digests are host catalog bindings, not
//! machine-code attestations or sandbox guarantees. Domain state stays with its
//! existing owner, and the underlying host retains all lifecycle checks.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CompiledOrganHandlerV2;
use crate::HostedOrganStatusV1;
use crate::OrganDeliveryV1;
use crate::OrganGraphsV1;
use crate::OrganHostV1;
use crate::OrganRuntimeError;
use crate::OrganWireError;

/// One system's primary membership in an immutable execution hierarchy.
/// Cross-system dataflow remains in the existing body graph, not this tree.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganSystemV1 {
    pub id: StableId,
    pub organs: Vec<StableId>,
}

/// A selected driver instance for one organ; implementations may be shared,
/// but instance identities are unique within this process-local host.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganDriverBindingV1 {
    pub organ: StableId,
    pub driver: StableId,
    pub implementation_digest: Digest32,
}

/// Host-supplied structure. Membership alone grants no execution permission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CnsHierarchyV1 {
    pub cns: StableId,
    pub generation: Generation,
    pub body_graph_digest: Digest32,
    pub systems: Vec<OrganSystemV1>,
    pub drivers: Vec<OrganDriverBindingV1>,
}

/// An independently supplied compiled catalog entry, checked before callbacks.
#[derive(Debug)]
pub struct CompiledOrganDriverV1 {
    pub binding: OrganDriverBindingV1,
    pub compiled: CompiledOrganHandlerV2,
}

/// The complete local identity below the CNS level.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganPathV1 {
    pub system: StableId,
    pub organ: StableId,
    pub driver: StableId,
}

/// A cached one-hop route. The host compares the entire value before dispatch,
/// including every destination, so a stale or edited route cannot be reused.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CnsRouteV1 {
    pub cns: StableId,
    pub generation: Generation,
    pub hierarchy_digest: Digest32,
    pub source: OrganPathV1,
    pub output_port: usize,
    pub targets: Vec<OrganPathV1>,
}

/// Existing execution result plus its immutable hierarchy provenance.
/// This does not convert a read-only result into an external-effect receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CnsDeliveryV1 {
    pub cns: StableId,
    pub generation: Generation,
    pub hierarchy_digest: Digest32,
    pub source: OrganPathV1,
    pub target: OrganPathV1,
    pub execution: OrganDeliveryV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CnsHierarchyError {
    Bounds,
    GraphBinding,
    CnsIdentity,
    Membership,
    DriverBinding,
    UnknownRoute,
    RouteMismatch,
    Wire(OrganWireError),
    Runtime(OrganRuntimeError),
}

impl fmt::Display for CnsHierarchyError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CnsHierarchyError {}

impl CnsHierarchyV1 {
    pub(crate) fn bind(
        &self,
        graph: &OrganGraphsV1,
        graph_digest: Digest32,
        catalog: &[CompiledOrganDriverV1],
    ) -> Result<BTreeMap<(StableId, usize), CnsRouteV1>, CnsHierarchyError> {
        use CnsHierarchyError as E;
        graph
            .validate()
            .map_err(|error| E::Wire(OrganWireError::Graph(error)))?;
        let count = graph.organs.len();
        if self.systems.is_empty()
            || self.systems.len() > 32
            || self.drivers.len() != count
            || catalog.len() != count
            || self
                .systems
                .iter()
                .any(|system| system.organs.is_empty() || system.organs.len() > count)
        {
            return Err(E::Bounds);
        }
        if self.generation != graph.generation
            || self.body_graph_digest.is_zero()
            || self.body_graph_digest != graph_digest
        {
            return Err(E::GraphBinding);
        }
        let mut system_ids = BTreeSet::new();
        let mut memberships = BTreeMap::new();
        for system in &self.systems {
            if !system_ids.insert(&system.id) {
                return Err(E::Membership);
            }
            for organ in &system.organs {
                if memberships
                    .insert(organ.clone(), system.id.clone())
                    .is_some()
                {
                    return Err(E::Membership);
                }
            }
        }
        if memberships.len() != count
            || graph
                .organs
                .iter()
                .any(|node| !memberships.contains_key(&node.id))
        {
            return Err(E::Membership);
        }
        let mut bindings = BTreeMap::new();
        let mut driver_ids = BTreeSet::new();
        for binding in &self.drivers {
            if binding.implementation_digest.is_zero()
                || !memberships.contains_key(&binding.organ)
                || !driver_ids.insert(&binding.driver)
                || bindings.insert(binding.organ.clone(), binding).is_some()
            {
                return Err(E::DriverBinding);
            }
        }
        let mut catalog_organs = BTreeSet::new();
        for entry in catalog {
            if !catalog_organs.insert(&entry.binding.organ)
                || bindings.get(&entry.binding.organ).copied() != Some(&entry.binding)
                || entry.compiled.handler.id() != &entry.binding.organ
            {
                return Err(E::DriverBinding);
            }
        }
        // Sorted membership and length-prefixed identities make the digest
        // independent of declaration order without ambiguous concatenation.
        let mut bytes = b"hepta.cns-hierarchy.v1\0".to_vec();
        append_id(&mut bytes, &self.cns);
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(graph_digest.as_array());
        bytes.extend_from_slice(&(count as u64).to_be_bytes());
        let mut paths = BTreeMap::new();
        for (organ, system) in memberships {
            let binding = bindings.get(&organ).ok_or(E::DriverBinding)?;
            append_id(&mut bytes, &organ);
            append_id(&mut bytes, &system);
            append_id(&mut bytes, &binding.driver);
            bytes.extend_from_slice(binding.implementation_digest.as_array());
            paths.insert(
                organ.clone(),
                OrganPathV1 {
                    system,
                    organ,
                    driver: binding.driver.clone(),
                },
            );
        }
        let hierarchy_digest = Digest32::of_bytes(&bytes);
        let mut routes: BTreeMap<(StableId, usize), CnsRouteV1> = BTreeMap::new();
        for link in &graph.runtime {
            let source = paths
                .get(&graph.organs[link.output.organ].id)
                .ok_or(E::Membership)?;
            let target = paths
                .get(&graph.organs[link.input.organ].id)
                .ok_or(E::Membership)?;
            routes
                .entry((source.organ.clone(), link.output.port))
                .or_insert_with(|| CnsRouteV1 {
                    cns: self.cns.clone(),
                    generation: self.generation,
                    hierarchy_digest,
                    source: source.clone(),
                    output_port: link.output.port,
                    targets: Vec::new(),
                })
                .targets
                .push(target.clone());
        }
        Ok(routes)
    }
}

fn append_id(bytes: &mut Vec<u8>, identity: &StableId) {
    let value = identity.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

/// A hierarchy-aware facade over the existing single-generation, read-only
/// host. Construction is available only through a verified compiled body graph.
/// It adds neither a worker thread, a state store, nor a second effect path.
#[derive(Debug)]
pub struct CnsOrganHostV1 {
    pub(crate) cns: StableId,
    pub(crate) host: OrganHostV1,
    pub(crate) routes: BTreeMap<(StableId, usize), CnsRouteV1>,
}

impl CnsOrganHostV1 {
    pub fn generation(&self) -> Generation {
        self.host.generation()
    }

    pub fn statuses(&self) -> Vec<HostedOrganStatusV1> {
        self.host.statuses()
    }

    pub fn start_all(&mut self) -> Result<(), CnsHierarchyError> {
        self.host.start_all().map_err(CnsHierarchyError::Runtime)
    }

    pub fn stop_all(&mut self) -> Result<(), CnsHierarchyError> {
        self.host.stop_all().map_err(CnsHierarchyError::Runtime)
    }

    /// Replace the composition without giving up its hierarchy binding.
    /// The candidate must be an independently admitted, registered successor
    /// under the same CNS identity. No new runtime or effect authority is issued.
    ///
    /// Candidate validation/start failure leaves the predecessor and its routes
    /// unchanged. If predecessor cleanup fails, its stopped/quarantined states
    /// remain visible under the old identity. Routes advance only after the
    /// existing host completes cutover successfully, under exclusive access.
    pub fn replace_read_only_generation(
        &mut self,
        expected: Generation,
        next: Self,
    ) -> Result<(), CnsHierarchyError> {
        if self.cns != next.cns {
            return Err(CnsHierarchyError::CnsIdentity);
        }
        let Self { host, routes, .. } = next;
        self.host
            .replace_admitted_read_only_generation(expected, host)
            .map_err(CnsHierarchyError::Runtime)?;
        self.routes = routes;
        Ok(())
    }

    pub fn route(
        &self,
        system: &StableId,
        organ: &StableId,
        output_port: usize,
    ) -> Result<CnsRouteV1, CnsHierarchyError> {
        let route = self
            .routes
            .get(&(organ.clone(), output_port))
            .ok_or(CnsHierarchyError::UnknownRoute)?;
        if &route.source.system != system {
            return Err(CnsHierarchyError::RouteMismatch);
        }
        Ok(route.clone())
    }

    pub fn dispatch_once(
        &mut self,
        route: &CnsRouteV1,
        payload: &[u8],
    ) -> Result<Vec<CnsDeliveryV1>, CnsHierarchyError> {
        let expected = self
            .routes
            .get(&(route.source.organ.clone(), route.output_port))
            .ok_or(CnsHierarchyError::UnknownRoute)?;
        if expected != route {
            return Err(CnsHierarchyError::RouteMismatch);
        }
        let deliveries = self
            .host
            .dispatch_once(
                route.generation,
                &route.source.organ,
                route.output_port,
                payload,
            )
            .map_err(CnsHierarchyError::Runtime)?;
        deliveries
            .into_iter()
            .map(|execution| {
                let target = route
                    .targets
                    .iter()
                    .find(|path| path.organ == execution.target)
                    .ok_or(CnsHierarchyError::RouteMismatch)?;
                Ok(CnsDeliveryV1 {
                    cns: route.cns.clone(),
                    generation: route.generation,
                    hierarchy_digest: route.hierarchy_digest,
                    source: route.source.clone(),
                    target: target.clone(),
                    execution,
                })
            })
            .collect()
    }
}

#[cfg(test)]
#[path = "organ_hierarchy_tests.rs"]
mod tests;
