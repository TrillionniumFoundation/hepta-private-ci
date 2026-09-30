//! Protocol projection from an opaque authoritative publication value.
//!
//! This is part of the existing objective compiler publication path. It does
//! not authenticate a new request or grant effect authority. The product owner
//! still rechecks current trust, deadlines, generation and fence at final use.

use crate::BoundObjectivePublicationV1;
use crate::ObjectiveAdmissionOutcomeV1;
use crate::ObjectiveAdmissionProofV1;
use crate::ObjectiveFunctionV1Artifact;
use crate::ObjectiveFunctionV1Error;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ValidatedAdmissionProfileV1;
use crate::admission_proof::source_envelope_proof_digest_v1;

mod sealed {
    use super::*;

    pub trait ProjectionInputV1 {
        fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1;
        fn proof(&self) -> &ObjectiveAdmissionProofV1;
        fn has_valid_publication_binding(&self) -> bool;
    }

    impl ProjectionInputV1 for BoundObjectivePublicationV1 {
        fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
            self.outcome()
        }

        fn proof(&self) -> &ObjectiveAdmissionProofV1 {
            self.proof()
        }

        fn has_valid_publication_binding(&self) -> bool {
            let binding = self.binding();
            !binding.destination_owner_digest().is_zero()
                && binding.generation() != 0
                && !binding.fence_digest().is_zero()
                && !binding.binding_digest().is_zero()
        }
    }

    // Unit-test-only support keeps the existing phase-isolation measurement
    // fixture able to measure protocol work separately. This implementation is
    // not present in normal or downstream product builds.
    #[cfg(test)]
    impl ProjectionInputV1 for crate::ProofBearingObjectiveCompileV1 {
        fn outcome(&self) -> &ObjectiveAdmissionOutcomeV1 {
            self.outcome()
        }

        fn proof(&self) -> &ObjectiveAdmissionProofV1 {
            self.proof()
        }

        fn has_valid_publication_binding(&self) -> bool {
            true
        }
    }
}

/// Sealed input accepted by the proof-bound encoder.
///
/// In product builds only `BoundObjectivePublicationV1` implements this trait.
/// The sealed trait prevents downstream crates from inventing another input that
/// bypasses the destination/run binding.
pub trait ObjectiveProjectionInputV1: sealed::ProjectionInputV1 {}

impl ObjectiveProjectionInputV1 for BoundObjectivePublicationV1 {}

#[cfg(test)]
impl ObjectiveProjectionInputV1 for crate::ProofBearingObjectiveCompileV1 {}

/// Encode only an outcome that the authoritative compiler paired with its proof
/// and that has been bound to one exact destination-owned publication attempt.
///
/// Complete source-envelope identity is rebound, including metadata absent from
/// the native semantic digest. The existing strict projection and wire decoder
/// remain mandatory. Unlike the compatibility encoder, this entrypoint does not
/// admit or solve the same objective a second time.
pub fn encode_proof_bearing_objective_function_v1<T>(
    publication: &T,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error>
where
    T: ObjectiveProjectionInputV1 + ?Sized,
{
    let proof = sealed::ProjectionInputV1::proof(publication);
    let outcome = sealed::ProjectionInputV1::outcome(publication);
    if source_envelope_proof_digest_v1(source)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("proof source structure"))?
        != proof.source_envelope_digest()
        || source.intent_digest != outcome.receipt.intent_digest
        || profile.profile_digest() != proof.profile_digest()
        || outcome.receipt.profile_digest != proof.profile_digest()
        || outcome.receipt.admitted_source_digest != proof.admitted_source_digest()
        || !sealed::ProjectionInputV1::has_valid_publication_binding(publication)
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "opaque admission and publication binding",
        ));
    }
    let compiled = outcome.compile_result.as_ref().map_err(|_| {
        ObjectiveFunctionV1Error::ProjectionMismatch("compiled/conflict disposition")
    })?;
    // Deliberately retain all native/source/receipt and canonical-wire
    // validation. Static profile validation and its exact digest come only from
    // the opaque validated profile; no caller-controlled skip flag exists.
    crate::objective_function_v1::encode_validated_profile_objective_function_v1(
        compiled,
        source,
        profile,
        &outcome.receipt,
    )
}

#[cfg(test)]
#[path = "proof_projection_tests.rs"]
mod tests;
