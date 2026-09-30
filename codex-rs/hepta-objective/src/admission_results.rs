use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProofV1;
use crate::ObjectiveAdmissionReceiptV1;
use crate::model::ObjectiveSourceEnvelope;

const PUBLICATION_BINDING_DOMAIN_V1: &[u8] = b"hepta.objective.publication-binding.v1";

/// Opaque admission capability consumed by native compilation.
///
/// This type is intentionally not `Clone`: one in-process authority value has
/// one consuming compile path. It contains the indexed-path native source,
/// request-local admission receipt and opaque proof as one inseparable value.
/// Durable retry semantics remain the destination journal's exact-key
/// idempotency responsibility.
#[derive(Debug, Eq, PartialEq)]
pub struct ValidatedObjectiveAdmissionV1 {
    source: ObjectiveSourceEnvelope,
    receipt: ObjectiveAdmissionReceiptV1,
    proof: ObjectiveAdmissionProofV1,
}

impl ValidatedObjectiveAdmissionV1 {
    pub(crate) fn new(
        source: ObjectiveSourceEnvelope,
        receipt: ObjectiveAdmissionReceiptV1,
        proof: ObjectiveAdmissionProofV1,
    ) -> Self {
        Self {
            source,
            receipt,
            proof,
        }
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        ObjectiveSourceEnvelope,
        ObjectiveAdmissionReceiptV1,
        ObjectiveAdmissionProofV1,
    ) {
        (self.source, self.receipt, self.proof)
    }

    #[must_use]
    pub const fn receipt(&self) -> &ObjectiveAdmissionReceiptV1 {
        &self.receipt
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }
}

/// Exact destination/run identity required before an authoritative compile may
/// cross into durable publication.
///
/// The destination digest identifies the registered destination-owner contract,
/// while run/predecessor/generation/fence bind the single append attempt. A zero
/// predecessor remains valid for the first record in a journal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePublicationBindingV1 {
    destination_owner_digest: Digest32,
    run_id: StableId,
    expected_predecessor: Digest32,
    generation: u64,
    fence_digest: Digest32,
    binding_digest: Digest32,
}

impl ObjectivePublicationBindingV1 {
    pub fn new(
        destination_owner_digest: Digest32,
        run_id: StableId,
        expected_predecessor: Digest32,
        generation: u64,
        fence_digest: Digest32,
    ) -> Result<Self, ObjectivePublicationBindingError> {
        if destination_owner_digest.is_zero() {
            return Err(ObjectivePublicationBindingError::DestinationOwner);
        }
        if generation == 0 {
            return Err(ObjectivePublicationBindingError::Generation);
        }
        if fence_digest.is_zero() {
            return Err(ObjectivePublicationBindingError::Fence);
        }
        let binding_digest = publication_binding_digest(
            destination_owner_digest,
            &run_id,
            expected_predecessor,
            generation,
            fence_digest,
        );
        Ok(Self {
            destination_owner_digest,
            run_id,
            expected_predecessor,
            generation,
            fence_digest,
            binding_digest,
        })
    }

    #[must_use]
    pub const fn destination_owner_digest(&self) -> Digest32 {
        self.destination_owner_digest
    }

    #[must_use]
    pub const fn run_id(&self) -> &StableId {
        &self.run_id
    }

    #[must_use]
    pub const fn expected_predecessor(&self) -> Digest32 {
        self.expected_predecessor
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn fence_digest(&self) -> Digest32 {
        self.fence_digest
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ObjectivePublicationBindingError {
    DestinationOwner,
    Generation,
    Fence,
}

impl fmt::Display for ObjectivePublicationBindingError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::DestinationOwner => "objective publication destination owner is invalid",
            Self::Generation => "objective publication generation is invalid",
            Self::Fence => "objective publication fence is invalid",
        })
    }
}

impl Error for ObjectivePublicationBindingError {}

#[derive(Debug, Eq, PartialEq)]
struct PublicationAuthorityV1 {
    compiler_contract_digest: Digest32,
    publication_binding_digest: Digest32,
}

impl PublicationAuthorityV1 {
    fn new(compiler_contract_digest: Digest32, publication_binding_digest: Digest32) -> Self {
        Self {
            compiler_contract_digest,
            publication_binding_digest,
        }
    }
}

/// Native compile outcome that remains inseparable from its admission proof.
///
/// It cannot expose its durable projection parts until the caller binds the
/// exact destination owner, run, predecessor, generation and fence.
#[derive(Debug, Eq, PartialEq)]
pub struct ProofBearingObjectiveCompileV1 {
    outcome: ObjectiveAdmissionOutcomeV1,
    proof: ObjectiveAdmissionProofV1,
}

impl ProofBearingObjectiveCompileV1 {
    pub(crate) fn new(
        outcome: ObjectiveAdmissionOutcomeV1,
        proof: ObjectiveAdmissionProofV1,
    ) -> Self {
        Self { outcome, proof }
    }

    #[must_use]
    pub const fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }

    /// Consume the authoritative compile and bind its private publication token
    /// to one exact destination-owned append attempt.
    #[must_use]
    pub fn bind_publication(
        self,
        binding: ObjectivePublicationBindingV1,
    ) -> BoundObjectivePublicationV1 {
        let publication_authority = PublicationAuthorityV1::new(
            self.proof.compiler_contract_digest(),
            binding.binding_digest(),
        );
        BoundObjectivePublicationV1 {
            outcome: self.outcome,
            proof: self.proof,
            binding,
            publication_authority,
        }
    }
}

/// Single-use authoritative projection bound to one destination/run append.
///
/// This value is intentionally not `Clone`. Consuming it exposes the immutable
/// compile/proof/binding tuple exactly once; the destination journal still owns
/// duplicate-exact idempotency and same-key/different-content conflict fencing.
#[derive(Debug, Eq, PartialEq)]
pub struct BoundObjectivePublicationV1 {
    outcome: ObjectiveAdmissionOutcomeV1,
    proof: ObjectiveAdmissionProofV1,
    binding: ObjectivePublicationBindingV1,
    publication_authority: PublicationAuthorityV1,
}

impl BoundObjectivePublicationV1 {
    #[must_use]
    pub const fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }

    #[must_use]
    pub const fn binding(&self) -> &ObjectivePublicationBindingV1 {
        &self.binding
    }

    #[must_use]
    pub fn into_parts(
        self,
    ) -> (
        ObjectiveAdmissionOutcomeV1,
        ObjectiveAdmissionProofV1,
        ObjectivePublicationBindingV1,
    ) {
        let Self {
            outcome,
            proof,
            binding,
            publication_authority: _,
        } = self;
        (outcome, proof, binding)
    }
}

/// Strict diagnostic result. It deliberately contains no admission proof and no
/// publication token, and therefore cannot be converted into authoritative
/// publication without a fresh owner-controlled admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectivePreflightReportV1 {
    outcome: ObjectiveAdmissionOutcomeV1,
    source_envelope_digest: Digest32,
    profile_digest: Digest32,
    compiler_contract_digest: Digest32,
}

impl ObjectivePreflightReportV1 {
    pub(crate) fn new(
        outcome: ObjectiveAdmissionOutcomeV1,
        source_envelope_digest: Digest32,
        profile_digest: Digest32,
        compiler_contract_digest: Digest32,
    ) -> Self {
        Self {
            outcome,
            source_envelope_digest,
            profile_digest,
            compiler_contract_digest,
        }
    }

    #[must_use]
    pub const fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn source_envelope_digest(&self) -> Digest32 {
        self.source_envelope_digest
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub const fn compiler_contract_digest(&self) -> Digest32 {
        self.compiler_contract_digest
    }

    #[must_use]
    pub fn into_outcome(self) -> ObjectiveAdmissionOutcomeV1 {
        self.outcome
    }
}

// Compatibility for the existing native-outcome regression: the types remain
// distinct and only their diagnostic/native identities are compared.
impl PartialEq<ProofBearingObjectiveCompileV1> for ObjectivePreflightReportV1 {
    fn eq(&self, other: &ProofBearingObjectiveCompileV1) -> bool {
        self.outcome == *other.outcome()
            && self.source_envelope_digest == other.proof().source_envelope_digest()
            && self.profile_digest == other.proof().profile_digest()
            && self.compiler_contract_digest == other.proof().compiler_contract_digest()
    }
}

impl PartialEq<ObjectivePreflightReportV1> for ProofBearingObjectiveCompileV1 {
    fn eq(&self, other: &ObjectivePreflightReportV1) -> bool {
        other == self
    }
}

fn publication_binding_digest(
    destination_owner_digest: Digest32,
    run_id: &StableId,
    expected_predecessor: Digest32,
    generation: u64,
    fence_digest: Digest32,
) -> Digest32 {
    let run_id_bytes = run_id.as_str().as_bytes();
    let run_id_len = u32::try_from(run_id_bytes.len()).unwrap_or(u32::MAX);
    let mut bytes = PUBLICATION_BINDING_DOMAIN_V1.to_vec();
    bytes.extend_from_slice(destination_owner_digest.as_array());
    bytes.extend_from_slice(&run_id_len.to_be_bytes());
    bytes.extend_from_slice(run_id_bytes);
    bytes.extend_from_slice(expected_predecessor.as_array());
    bytes.extend_from_slice(&generation.to_be_bytes());
    bytes.extend_from_slice(fence_digest.as_array());
    Digest32::of_bytes(&bytes)
}
