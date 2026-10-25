//! Stable enrollment of a concrete run, owner proofs and monotonic clock domain.

use crate::NativeMemoryError;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

/// Created by the host from checked owner proofs. This identity is not a lease:
/// the context authority must still revalidate those proofs at every use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeMemoryContextBindingV1 {
    run_id: StableId,
    digest: Digest32,
}

impl NativeMemoryContextBindingV1 {
    pub(crate) fn from_checked_owners(
        run_id: StableId,
        objective_proof: Digest32,
        ndu_proof: Digest32,
        clock_domain: Digest32,
    ) -> Result<Self, NativeMemoryError> {
        if [objective_proof, ndu_proof, clock_domain]
            .iter()
            .any(|v| v.is_zero())
        {
            return Err(NativeMemoryError::Rejected(
                "incomplete current-owner binding".into(),
            ));
        }
        let raw = run_id.as_str().as_bytes();
        let digest = Digest32::of_parts(&[
            b"hepta.memory-cell.current-owner-binding.v1",
            &(raw.len() as u32).to_be_bytes(),
            raw,
            objective_proof.as_array(),
            ndu_proof.as_array(),
            clock_domain.as_array(),
        ]);
        Ok(Self { run_id, digest })
    }

    pub fn run_id(&self) -> &StableId {
        &self.run_id
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }
}
