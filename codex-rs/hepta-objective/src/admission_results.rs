use codex_hepta_types::Digest32;

use crate::AdmittedObjectiveV1;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProofV1;
use crate::ObjectiveAdmissionReceiptV1;

/// Opaque admission capability consumed by native compilation.
///
/// This type is intentionally not `Clone`: one in-process authority value has
/// one consuming compile path. Durable retry semantics remain the destination
/// journal's exact-key idempotency responsibility.
#[derive(Debug, Eq, PartialEq)]
pub struct ValidatedObjectiveAdmissionV1 {
    admitted: AdmittedObjectiveV1,
    proof: ObjectiveAdmissionProofV1,
}

impl ValidatedObjectiveAdmissionV1 {
    pub(crate) fn new(admitted: AdmittedObjectiveV1, proof: ObjectiveAdmissionProofV1) -> Self {
        Self { admitted, proof }
    }

    pub(crate) fn into_parts(self) -> (AdmittedObjectiveV1, ObjectiveAdmissionProofV1) {
        (self.admitted, self.proof)
    }

    #[must_use]
    pub fn receipt(&self) -> &ObjectiveAdmissionReceiptV1 {
        self.admitted.receipt()
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }
}

#[derive(Debug, Eq, PartialEq)]
struct PublicationAuthorityV1 {
    compiler_contract_digest: Digest32,
}

impl PublicationAuthorityV1 {
    fn new(compiler_contract_digest: Digest32) -> Self {
        Self {
            compiler_contract_digest,
        }
    }
}

/// Native compile outcome that remains inseparable from its admission proof and
/// a private, non-cloneable publication token.
#[derive(Debug, Eq, PartialEq)]
pub struct ProofBearingObjectiveCompileV1 {
    outcome: ObjectiveAdmissionOutcomeV1,
    proof: ObjectiveAdmissionProofV1,
    publication_authority: PublicationAuthorityV1,
}

impl ProofBearingObjectiveCompileV1 {
    pub(crate) fn new(
        outcome: ObjectiveAdmissionOutcomeV1,
        proof: ObjectiveAdmissionProofV1,
    ) -> Self {
        let publication_authority = PublicationAuthorityV1::new(proof.compiler_contract_digest());
        Self {
            outcome,
            proof,
            publication_authority,
        }
    }

    #[must_use]
    pub const fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
        &self.outcome
    }

    #[must_use]
    pub const fn proof(&self) -> &ObjectiveAdmissionProofV1 {
        &self.proof
    }

    /// Consume the in-process publication token and return the durable
    /// projection inputs. Destination journals still enforce duplicate-exact
    /// idempotency and same-key/different-proof conflict rejection.
    #[must_use]
    pub fn into_parts(self) -> (ObjectiveAdmissionOutcomeV1, ObjectiveAdmissionProofV1) {
        let Self {
            outcome,
            proof,
            publication_authority: _,
        } = self;
        (outcome, proof)
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
