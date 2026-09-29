//! Protocol projection from an opaque authoritative compile result.
//!
//! This is part of the existing objective compiler publication path. It does
//! not authenticate a new request or grant effect authority. The product owner
//! still rechecks current trust, deadlines, generation and fence at final use.

use crate::ObjectiveFunctionV1Artifact;
use crate::ObjectiveFunctionV1Error;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ProofBearingObjectiveCompileV1;
use crate::ValidatedAdmissionProfileV1;
use crate::validated_admission::source_envelope_proof_digest;

/// Encode only an outcome that the authoritative compiler paired with its proof.
///
/// Complete source-envelope identity is rebound, including metadata absent from
/// the native semantic digest. The existing strict projection and wire decoder
/// remain mandatory. Unlike the compatibility encoder, this entrypoint does not
/// admit or solve the same objective a second time.
pub fn encode_proof_bearing_objective_function_v1(
    proof_bearing: &ProofBearingObjectiveCompileV1,
    source: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
) -> Result<ObjectiveFunctionV1Artifact, ObjectiveFunctionV1Error> {
    let proof = proof_bearing.proof();
    let outcome = proof_bearing.outcome();
    if source_envelope_proof_digest(source)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("proof source structure"))?
        != proof.source_envelope_digest()
        || source.intent_digest != outcome.receipt.intent_digest
        || profile.profile_digest() != proof.profile_digest()
        || outcome.receipt.profile_digest != proof.profile_digest()
        || outcome.receipt.admitted_source_digest != proof.admitted_source_digest()
    {
        return Err(ObjectiveFunctionV1Error::ProjectionMismatch(
            "opaque admission proof binding",
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
