//! Canonical parameter identity for a fixed graph with private Cell bundles.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_contracts::Sha256Digest;

use crate::CircuitCellBindingV1;
use crate::CircuitCellErrorV1;
use crate::circuit_cell_binding::MAX_CIRCUIT_CELL_BINDINGS;
use crate::circuit_cell_binding::push_text;

/// Pin this digest as the Circuit parameter bundle before calling
/// `CircuitCellRegistryV1::new_with_bundle_manifest`. Each unique Cell ID binds
/// its immutable bundle and complete definition, including weights, encoder,
/// private head, state schema, calibration and resource limits. Ordering of
/// graph bindings has no effect; reuse of an identical Cell across graph slots
/// contributes once. A conflicting Cell identity or duplicate slot is invalid.
///
/// The registry separately validates complete graph coverage and route policy.
/// This content identity neither authenticates artifacts nor authorizes their
/// installation; those duties remain with the existing owners.
pub fn circuit_cell_bundle_manifest_digest_v1(
    bindings: &[CircuitCellBindingV1],
) -> Result<Sha256Digest, CircuitCellErrorV1> {
    if !(1..=MAX_CIRCUIT_CELL_BINDINGS).contains(&bindings.len()) {
        return Err(CircuitCellErrorV1::InvalidBinding);
    }
    let mut slots = BTreeSet::new();
    let mut cells = BTreeMap::new();
    for binding in bindings {
        if !slots.insert((binding.program_id.as_str(), binding.node_id.as_str())) {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
        let entry = (binding.cell.bundle_digest, binding.cell.semantic_digest()?);
        if cells
            .insert(binding.cell.cell_id.as_str(), entry)
            .is_some_and(|previous| previous != entry)
        {
            return Err(CircuitCellErrorV1::InvalidBinding);
        }
    }
    let mut bytes = b"hepta.circuit.cell-bundle-manifest.v1\0".to_vec();
    bytes.extend_from_slice(&(cells.len() as u32).to_be_bytes());
    for (cell_id, (bundle, definition)) in cells {
        push_text(&mut bytes, cell_id);
        bytes.extend_from_slice(bundle.as_array());
        bytes.extend_from_slice(definition.as_array());
    }
    Ok(Sha256Digest::for_bytes(&bytes))
}

#[cfg(test)]
#[path = "circuit_cell_bundle_manifest_tests.rs"]
mod tests;
