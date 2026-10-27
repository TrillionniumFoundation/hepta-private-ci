//! Source-owner revalidation for typed parametric memory readouts.

use codex_hepta_cognitive_types::MemoryReadStatusV1;
use codex_hepta_cognitive_types::MemoryReadoutV1;
use codex_hepta_cognitive_types::MemoryRequestV1;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_cognitive_types::hnmf::HnmfContractError;

/// Implemented by the existing source owner. Callers must check real current
/// scope, entity and revocation state; a caller-supplied digest alone is not
/// authentication. The complete request is available to the owning verifier.
pub trait MemorySourceVerifierV1 {
    fn verify_current_source(
        &self,
        request: &MemoryRequestV1,
        source: ContractDigestV1,
        snapshot: ContractDigestV1,
    ) -> Result<(), HnmfContractError>;
}

/// Checks source dependencies without upgrading a model prediction to a fact.
pub fn revalidate_memory_readout_v1(
    request: &MemoryRequestV1,
    readout: &MemoryReadoutV1,
    generation: ContractGenerationV1,
    snapshot: ContractDigestV1,
    verifier: &impl MemorySourceVerifierV1,
) -> Result<(), HnmfContractError> {
    request.validate()?;
    readout.validate()?;
    if request.query_id != readout.query_id
        || readout.generation != generation
        || readout.snapshot_digest != snapshot
        || readout.hops > request.max_hops
        || readout.cell_digests.len() > usize::from(request.max_cells)
    {
        return Err(HnmfContractError::Conflict("memory request/snapshot binding"));
    }
    if readout.status != MemoryReadStatusV1::Ok {
        return Err(HnmfContractError::Invalid("memory result unavailable"));
    }
    for source in &readout.source_ids {
        verifier.verify_current_source(request, *source, snapshot)?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "memory_cell_tests.rs"]
mod tests;
