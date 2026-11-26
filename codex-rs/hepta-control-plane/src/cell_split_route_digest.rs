use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CnsOrganHostV1;
use crate::CnsRouteV1;
use crate::FallbackTerminal;
use crate::OrganRole;

use super::cell_split_route::CellSplitDispatchReceiptV1;
use super::cell_split_route::CellSplitRouteErrorV1;
use super::cell_split_route::CellSplitRouteOwnerV1;

impl CellSplitDispatchReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.cns.cell-dispatch-receipt.v1\0".to_vec();
        push_id(&mut bytes, &self.split_id);
        match &self.route_owner {
            CellSplitRouteOwnerV1::Parent => bytes.push(0),
            CellSplitRouteOwnerV1::Child(child) => {
                bytes.push(1);
                push_id(&mut bytes, child);
            }
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.route_predicate_digest.as_array());
        bytes.extend_from_slice(self.payload_digest.as_array());
        bytes.extend_from_slice(&(self.delivery_count as u64).to_be_bytes());
        bytes.push(u8::from(self.parent_route_fenced));
        bytes.extend_from_slice(self.parent_route_fence_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

/// Canonical digest of the concrete CNS route identity used by the binding.
pub fn cns_route_digest_v1(route: &CnsRouteV1) -> Digest32 {
    let mut bytes = b"hepta.cns.cell-route.v1\0".to_vec();
    push_id(&mut bytes, &route.cns);
    bytes.extend_from_slice(&route.generation.get().to_be_bytes());
    bytes.extend_from_slice(route.hierarchy_digest.as_array());
    push_id(&mut bytes, &route.source.system);
    push_id(&mut bytes, &route.source.organ);
    push_id(&mut bytes, &route.source.driver);
    bytes.extend_from_slice(&(route.output_port as u64).to_be_bytes());
    bytes.extend_from_slice(&(route.targets.len() as u64).to_be_bytes());
    for target in &route.targets {
        push_id(&mut bytes, &target.system);
        push_id(&mut bytes, &target.organ);
        push_id(&mut bytes, &target.driver);
    }
    Digest32::of_bytes(&bytes)
}

/// Digest the route together with the actual target input-port indices held by
/// `OrganHostV1`. This is the ABI-bound form used for a cell split port
/// contract; callers cannot substitute a route with the same target identities
/// but a different input-port wiring.
pub fn cns_route_port_binding_digest_v1(
    host: &CnsOrganHostV1,
    route: &CnsRouteV1,
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let mut bytes = b"hepta.cns.cell-route-port-binding.v1\0".to_vec();
    bytes.extend_from_slice(cns_route_digest_v1(route).as_array());
    let ports = host
        .host
        .route_target_ports(route.generation, &route.source.organ, route.output_port)
        .map_err(CellSplitRouteErrorV1::RuntimeOwner)?;
    bytes.extend_from_slice(&(ports.len() as u64).to_be_bytes());
    for (target, input_port) in ports {
        push_id(&mut bytes, &target);
        bytes.extend_from_slice(&(input_port as u64).to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_organ_input_port_digest_v1(
    host: &CnsOrganHostV1,
    organ: &StableId,
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let abi = host
        .host
        .abi()
        .into_iter()
        .find(|value| &value.id == organ)
        .ok_or_else(|| CellSplitRouteErrorV1::ChildRouteOrgan(organ.clone()))?;
    let mut bytes = b"hepta.cns.organ-input-ports.v1\0".to_vec();
    push_id(&mut bytes, &abi.id);
    bytes.extend_from_slice(&abi.generation.get().to_be_bytes());
    bytes.extend_from_slice(&(abi.input_ports.len() as u64).to_be_bytes());
    for port in abi.input_ports {
        push_id(&mut bytes, &port);
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_organ_termination_port_digest_v1(
    host: &CnsOrganHostV1,
    organ: &StableId,
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let abi = host
        .host
        .abi()
        .into_iter()
        .find(|value| &value.id == organ)
        .ok_or_else(|| CellSplitRouteErrorV1::ChildRouteOrgan(organ.clone()))?;
    let mut bytes = b"hepta.cns.organ-termination-port.v1\0".to_vec();
    push_id(&mut bytes, &abi.id);
    encode_fallback(&mut bytes, &abi.fallback);
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_organ_abi_digest_v1(
    host: &CnsOrganHostV1,
    organ: &StableId,
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let abi = host
        .host
        .abi()
        .into_iter()
        .find(|value| &value.id == organ)
        .ok_or_else(|| CellSplitRouteErrorV1::ChildRouteOrgan(organ.clone()))?;
    let mut bytes = b"hepta.cns.organ-abi.v1\0".to_vec();
    push_id(&mut bytes, &abi.id);
    bytes.extend_from_slice(&abi.generation.get().to_be_bytes());
    bytes.push(match abi.role {
        OrganRole::Cognitive => 0,
        OrganRole::LocalSafety => 1,
        OrganRole::Other => 2,
    });
    bytes.extend_from_slice(&(abi.input_ports.len() as u64).to_be_bytes());
    for port in abi.input_ports {
        push_id(&mut bytes, &port);
    }
    bytes.extend_from_slice(&(abi.output_ports.len() as u64).to_be_bytes());
    for port in abi.output_ports {
        push_id(&mut bytes, &port);
    }
    bytes.extend_from_slice(&(abi.effect_scope.len() as u64).to_be_bytes());
    for scope in abi.effect_scope {
        push_id(&mut bytes, &scope);
    }
    encode_fallback(&mut bytes, &abi.fallback);
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_child_port_compatibility_digest_v1(
    host: &CnsOrganHostV1,
    route: &CnsRouteV1,
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let mut bytes = b"hepta.cns.child-port-compatibility.v1\0".to_vec();
    bytes.extend_from_slice(cns_organ_abi_digest_v1(host, &route.source.organ)?.as_array());
    bytes.extend_from_slice(cns_route_port_binding_digest_v1(host, route)?.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_organ_abi_set_digest_v1(
    host: &CnsOrganHostV1,
    organs: &[StableId],
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let mut digests = organs
        .iter()
        .map(|organ| cns_organ_abi_digest_v1(host, organ).map(|digest| (organ.clone(), digest)))
        .collect::<Result<Vec<_>, _>>()?;
    digests.sort_by(|left, right| left.0.cmp(&right.0));
    let mut bytes = b"hepta.cns.organ-abi-set.v1\0".to_vec();
    for (organ, digest) in digests {
        push_id(&mut bytes, &organ);
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn cns_circuit_route_digest_v1(
    host: &CnsOrganHostV1,
    routes: &[CnsRouteV1],
) -> Result<Digest32, CellSplitRouteErrorV1> {
    let mut digests = routes
        .iter()
        .map(|route| cns_route_port_binding_digest_v1(host, route))
        .collect::<Result<Vec<_>, _>>()?;
    digests.sort();
    let mut bytes = b"hepta.cns.circuit-routes.v1\0".to_vec();
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn encode_fallback(bytes: &mut Vec<u8>, fallback: &FallbackTerminal) {
    match fallback {
        FallbackTerminal::None => bytes.push(0),
        FallbackTerminal::SafeState(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        FallbackTerminal::HumanTakeover(digest) => {
            bytes.push(2);
            bytes.extend_from_slice(digest.as_array());
        }
    }
}

pub(super) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}
