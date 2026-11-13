//! Private, full data projection of the original immutable registry. The
//! decode path can only call the existing validating registry constructor.

use super::*;
use crate::circuit_task::CircuitTaskErrorV1 as Error;
use crate::circuit_task::root_bootstrap_codec::{Reader, Writer};
use crate::circuit_task::root_bootstrap_cell;

pub(crate) fn encode(registry: &CircuitCellRegistryV1) -> Result<Vec<u8>, Error> {
    let mut out = Writer::new(b"HCRTRGY1");
    out.json(&registry.definition)?;
    out.count(registry.bindings.len(), 16)?;
    for binding in &registry.bindings {
        out.text(&binding.program_id)?;
        out.text(&binding.node_id)?;
        root_bootstrap_cell::encode(&mut out, &binding.cell)?;
        out.count(binding.routes.len(), 256)?;
        for route in &binding.routes {
            out.id(&route.candidate_id)?;
            out.json(&route.outcome)?;
            out.count(route.selected_edges.len(), 256)?;
            for edge in &route.selected_edges { out.text(edge)?; }
        }
    }
    Ok(out.finish())
}

pub(crate) fn decode(bytes: &[u8]) -> Result<CircuitCellRegistryV1, Error> {
    let mut input = Reader::new(bytes, b"HCRTRGY1")?;
    let definition = input.json()?;
    let mut bindings = Vec::new();
    for _ in 0..input.count(16)? {
        let program_id = input.text()?;
        let node_id = input.text()?;
        let cell = root_bootstrap_cell::decode(&mut input)?;
        let mut routes = Vec::new();
        for _ in 0..input.count(256)? {
            let candidate_id = input.id()?;
            let outcome = input.json()?;
            let mut selected_edges = Vec::new();
            for _ in 0..input.count(256)? { selected_edges.push(input.text()?); }
            routes.push(CircuitCellRouteV1 { candidate_id, outcome, selected_edges });
        }
        bindings.push(CircuitCellBindingV1 { program_id, node_id, cell, routes });
    }
    input.end()?;
    let registry = CircuitCellRegistryV1::new(definition, bindings)?;
    if encode(&registry)? != bytes { return Err(Error::InvalidBinding); }
    Ok(registry)
}
