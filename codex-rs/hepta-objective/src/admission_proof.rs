use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmittedObjectiveV1;
use crate::ObjectiveAdmissionContextV1;
use crate::ObjectiveAdmissionError;
use crate::ObjectiveSourceAuthenticationV1;
use crate::ObjectiveSourceEnvelopeV1;
use crate::ObjectiveSourceTrustV1;
use crate::ValidatedAdmissionProfileV1;
use crate::canonical_objective_intent_digest_v1;

const COMPILER_CONTRACT_V1: &[u8] = b"hepta.objective.compiler.contract.v1:indexed-profile:conservative-ms-deadline:proof-bearing-admission";

#[must_use]
pub(crate) fn compiler_contract_digest_v1() -> Digest32 {
    Digest32::of_bytes(COMPILER_CONTRACT_V1)
}

/// Provenance bound to one authenticated admission and native compile.
///
/// Fields are private so downstream code cannot construct a proof from a set of
/// mutually consistent but independently forged receipts. The proof is
/// evidence, not publication authority; authority remains in the non-cloneable
/// compile result owned by `admission_results`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObjectiveAdmissionProofV1 {
    source_envelope_digest: Digest32,
    profile_digest: Digest32,
    authentication_context_digest: Digest32,
    compiler_contract_digest: Digest32,
    admitted_source_digest: Digest32,
    proof_digest: Digest32,
}

impl ObjectiveAdmissionProofV1 {
    #[must_use]
    pub const fn source_envelope_digest(&self) -> Digest32 {
        self.source_envelope_digest
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub const fn authentication_context_digest(&self) -> Digest32 {
        self.authentication_context_digest
    }

    #[must_use]
    pub const fn compiler_contract_digest(&self) -> Digest32 {
        self.compiler_contract_digest
    }

    #[must_use]
    pub const fn admitted_source_digest(&self) -> Digest32 {
        self.admitted_source_digest
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    /// Frozen V1 integrity bytes for the destination-owned RunStart journal.
    /// Returning bytes does not expose a constructor for this opaque proof and
    /// does not grant source authentication, publication or effect authority.
    #[must_use]
    pub fn canonical_bytes(&self) -> Vec<u8> {
        canonical_admission_proof_bytes([
            self.source_envelope_digest,
            self.profile_digest,
            self.authentication_context_digest,
            self.compiler_contract_digest,
            self.admitted_source_digest,
        ])
    }

    /// Verify every bound digest and the domain-separated proof digest before a
    /// persistence owner accepts this proof projection.
    #[must_use]
    pub fn verify_integrity(&self) -> bool {
        !self.source_envelope_digest.is_zero()
            && !self.profile_digest.is_zero()
            && !self.authentication_context_digest.is_zero()
            && !self.compiler_contract_digest.is_zero()
            && !self.admitted_source_digest.is_zero()
            && self.proof_digest
                == Digest32::of_bytes(&canonical_admission_proof_bytes([
                    self.source_envelope_digest,
                    self.profile_digest,
                    self.authentication_context_digest,
                    self.compiler_contract_digest,
                    self.admitted_source_digest,
                ]))
    }
}

pub(crate) fn build_admission_proof_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
    profile: &ValidatedAdmissionProfileV1,
    context: &ObjectiveAdmissionContextV1,
    admitted: &AdmittedObjectiveV1,
) -> Result<ObjectiveAdmissionProofV1, ObjectiveAdmissionError> {
    let source_envelope_digest = source_envelope_proof_digest_v1(envelope)?;
    let authentication_context_digest = authentication_context_digest_v1(context);
    let compiler_contract_digest = compiler_contract_digest_v1();
    let admitted_source_digest = admitted.receipt().admitted_source_digest;
    let proof_digest = Digest32::of_bytes(&canonical_admission_proof_bytes([
        source_envelope_digest,
        profile.profile_digest(),
        authentication_context_digest,
        compiler_contract_digest,
        admitted_source_digest,
    ]));
    Ok(ObjectiveAdmissionProofV1 {
        source_envelope_digest,
        profile_digest: profile.profile_digest(),
        authentication_context_digest,
        compiler_contract_digest,
        admitted_source_digest,
        proof_digest,
    })
}

fn canonical_admission_proof_bytes(digests: [Digest32; 5]) -> Vec<u8> {
    let mut bytes = b"hepta.objective.admission-proof.v1".to_vec();
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

pub(crate) fn source_envelope_proof_digest_v1(
    envelope: &ObjectiveSourceEnvelopeV1,
) -> Result<Digest32, ObjectiveAdmissionError> {
    let intent_digest = canonical_objective_intent_digest_v1(envelope)?;
    let mut bytes = b"hepta.objective.source-envelope-proof.v1".to_vec();
    push_text(&mut bytes, &envelope.request_id);
    push_digest(&mut bytes, envelope.principal_scope_digest);
    push_digest(&mut bytes, intent_digest);
    push_digest(&mut bytes, envelope.input_schema_digest);
    push_text(&mut bytes, &envelope.locale);
    push_text(&mut bytes, &envelope.observed_at);
    match &envelope.deadline {
        Some(deadline) => {
            bytes.push(1);
            push_text(&mut bytes, deadline);
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

fn authentication_context_digest_v1(context: &ObjectiveAdmissionContextV1) -> Digest32 {
    let mut bytes = b"hepta.objective.authentication-context.v1".to_vec();
    bytes.extend_from_slice(&context.revision.get().to_be_bytes());
    bytes.extend_from_slice(&context.now_unix_micros.to_be_bytes());
    push_digest(&mut bytes, context.selected_profile_digest);
    match &context.source_authentication {
        ObjectiveSourceAuthenticationV1::Principal {
            principal_scope_digest,
            source_digest,
        } => {
            bytes.push(1);
            push_digest(&mut bytes, *principal_scope_digest);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::TrustedSystem {
            source_identity,
            source_digest,
        } => {
            bytes.push(2);
            push_id(&mut bytes, source_identity);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::AuthorizedAdapter {
            source_identity,
            source_digest,
        } => {
            bytes.push(3);
            push_id(&mut bytes, source_identity);
            push_digest(&mut bytes, *source_digest);
        }
        ObjectiveSourceAuthenticationV1::UntrustedEvidence { source_digest } => {
            bytes.push(4);
            push_digest(&mut bytes, *source_digest);
        }
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let len = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}
