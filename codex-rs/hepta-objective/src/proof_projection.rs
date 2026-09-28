//! Protocol projection from an opaque authoritative compile result.
//!
//! This is part of the existing objective compiler publication path. It does
//! not authenticate a new request or grant effect authority. The product owner
//! still rechecks current trust, deadlines, generation and fence at final use.

use codex_hepta_types::Digest32;

use crate::ObjectiveFunctionV1Artifact;
use crate::ObjectiveFunctionV1Error;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourceTrustV1;
use crate::ProofBearingObjectiveCompileV1;
use crate::ValidatedAdmissionProfileV1;
use crate::canonical_objective_intent_digest_v1;

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
    if source_envelope_proof_digest(source)? != proof.source_envelope_digest()
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
    // Deliberately retain all native/source/profile/receipt and canonical-wire
    // validation. The removed work is duplicate admission and feasibility, not
    // authorization or validation of arbitrary caller-created receipts.
    crate::objective_function_v1::encode_objective_function_v1(
        compiled,
        source,
        profile.profile(),
        &outcome.receipt,
    )
}

fn source_envelope_proof_digest(
    envelope: &ObjectiveSourceEnvelopeV1,
) -> Result<Digest32, ObjectiveFunctionV1Error> {
    // Exact source-envelope-proof.v1 framing, shared by the authoritative proof
    // contract. Successful parity tests exercise this framing against proofs
    // issued by validated_admission, not self-generated expected digests.
    let intent = canonical_objective_intent_digest_v1(envelope)
        .map_err(|_| ObjectiveFunctionV1Error::ProjectionMismatch("proof source structure"))?;
    let mut bytes = b"hepta.objective.source-envelope-proof.v1".to_vec();
    push_text(&mut bytes, &envelope.request_id)?;
    bytes.extend_from_slice(envelope.principal_scope_digest.as_array());
    bytes.extend_from_slice(intent.as_array());
    bytes.extend_from_slice(envelope.input_schema_digest.as_array());
    push_text(&mut bytes, &envelope.locale)?;
    push_text(&mut bytes, &envelope.observed_at)?;
    match &envelope.deadline {
        Some(deadline) => {
            bytes.push(1);
            push_text(&mut bytes, deadline)?;
        }
        None => bytes.push(0),
    }
    bytes.push(match envelope.source_trust_class {
        ObjectiveSourceTrustV1::Principal => 1,
        ObjectiveSourceTrustV1::TrustedSystem => 2,
        ObjectiveSourceTrustV1::AuthorizedAdapter => 3,
        ObjectiveSourceTrustV1::UntrustedEvidence => 4,
    });
    Ok(Digest32::of_bytes(&bytes))
}

fn push_text(bytes: &mut Vec<u8>, text: &str) -> Result<(), ObjectiveFunctionV1Error> {
    let length = u32::try_from(text.len()).map_err(|_| ObjectiveFunctionV1Error::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(text.as_bytes());
    Ok(())
}

#[cfg(test)]
#[path = "proof_projection_tests.rs"]
mod tests;
