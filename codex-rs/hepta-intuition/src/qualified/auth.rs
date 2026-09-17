use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::QualificationMacKeyV1;
use super::QualificationMacV1;
use super::QualifiedError;
use super::digest::push_id;

const HMAC_BLOCK_BYTES: usize = 64;
const PROFILE_SCOPE: &[u8] = b"hepta.intuition.qualification.policy-profile.v1";
const CALIBRATION_SCOPE: &[u8] = b"hepta.intuition.qualification.calibration.v1";
const OOD_SCOPE: &[u8] = b"hepta.intuition.qualification.ood.v1";
const COMPLETENESS_SCOPE: &[u8] = b"hepta.intuition.qualification.completeness.v1";
const SCORER_SCOPE: &[u8] = b"hepta.intuition.qualification.scorer-output.v1";

/// Issue an HMAC-SHA256 qualification envelope for a canonical payload digest.
/// The key must be obtained from the trusted qualification/scorer key store.
pub fn issue_qualification_mac_v1(
    key: &QualificationMacKeyV1,
    subject_id: StableId,
    scope_digest: Digest32,
    payload_digest: Digest32,
    generation: u64,
    valid_from_sequence: u64,
    expires_after_sequence: u64,
) -> Result<QualificationMacV1, QualifiedError> {
    if key.revoked {
        return Err(QualifiedError::AuthenticationKeyRevoked);
    }
    if scope_digest.is_zero() {
        return Err(QualifiedError::EmptyDigest("qualification scope"));
    }
    if payload_digest.is_zero() {
        return Err(QualifiedError::EmptyDigest("qualification payload"));
    }
    if valid_from_sequence > expires_after_sequence {
        return Err(QualifiedError::AuthenticationWindowInvalid);
    }
    let mut envelope = QualificationMacV1 {
        key_id: key.key_id.clone(),
        key_epoch: key.key_epoch,
        subject_id,
        scope_digest,
        payload_digest,
        generation,
        valid_from_sequence,
        expires_after_sequence,
        tag: Digest32::ZERO,
    };
    envelope.tag = hmac_sha256(&key.secret, &qualification_mac_preimage(&envelope)?);
    Ok(envelope)
}

#[must_use]
pub fn policy_profile_scope_digest_v1() -> Digest32 {
    Digest32::of_bytes(PROFILE_SCOPE)
}

#[must_use]
pub fn calibration_scope_digest_v1() -> Digest32 {
    Digest32::of_bytes(CALIBRATION_SCOPE)
}

#[must_use]
pub fn ood_scope_digest_v1() -> Digest32 {
    Digest32::of_bytes(OOD_SCOPE)
}

#[must_use]
pub fn completeness_scope_digest_v1() -> Digest32 {
    Digest32::of_bytes(COMPLETENESS_SCOPE)
}

#[must_use]
pub fn scorer_output_scope_digest_v1() -> Digest32 {
    Digest32::of_bytes(SCORER_SCOPE)
}

pub(crate) fn authenticate_mac(
    key: &QualificationMacKeyV1,
    envelope: &QualificationMacV1,
    expected_subject: &StableId,
    expected_scope: Digest32,
    expected_payload: Digest32,
    expected_generation: u64,
    sequence: u64,
) -> Result<Digest32, QualifiedError> {
    if key.revoked {
        return Err(QualifiedError::AuthenticationKeyRevoked);
    }
    if envelope.key_id != key.key_id || envelope.key_epoch != key.key_epoch {
        return Err(QualifiedError::AuthenticationKeyMismatch);
    }
    if &envelope.subject_id != expected_subject {
        return Err(QualifiedError::AuthenticationSubjectMismatch);
    }
    if envelope.scope_digest != expected_scope {
        return Err(QualifiedError::AuthenticationScopeMismatch);
    }
    if envelope.payload_digest != expected_payload {
        return Err(QualifiedError::AuthenticationPayloadMismatch);
    }
    if envelope.generation != expected_generation {
        return Err(QualifiedError::AuthenticationGenerationMismatch);
    }
    if envelope.valid_from_sequence > envelope.expires_after_sequence {
        return Err(QualifiedError::AuthenticationWindowInvalid);
    }
    if sequence < envelope.valid_from_sequence || sequence > envelope.expires_after_sequence {
        return Err(QualifiedError::AuthenticationExpired);
    }
    let expected_tag = hmac_sha256(&key.secret, &qualification_mac_preimage(envelope)?);
    if !constant_time_digest_eq(expected_tag, envelope.tag) {
        return Err(QualifiedError::AuthenticationTagMismatch);
    }

    let mut receipt = b"hepta.intuition.qualification-authentication.v1\0".to_vec();
    receipt.extend_from_slice(envelope.scope_digest.as_array());
    receipt.extend_from_slice(envelope.payload_digest.as_array());
    receipt.extend_from_slice(envelope.tag.as_array());
    receipt.extend_from_slice(&envelope.generation.to_be_bytes());
    receipt.extend_from_slice(&sequence.to_be_bytes());
    Ok(Digest32::of_bytes(&receipt))
}

fn qualification_mac_preimage(
    envelope: &QualificationMacV1,
) -> Result<Vec<u8>, QualifiedError> {
    let mut bytes = b"hepta.intuition.qualification-mac.v1\0".to_vec();
    push_id(&mut bytes, &envelope.key_id)?;
    bytes.extend_from_slice(&envelope.key_epoch.to_be_bytes());
    push_id(&mut bytes, &envelope.subject_id)?;
    bytes.extend_from_slice(envelope.scope_digest.as_array());
    bytes.extend_from_slice(envelope.payload_digest.as_array());
    bytes.extend_from_slice(&envelope.generation.to_be_bytes());
    bytes.extend_from_slice(&envelope.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&envelope.expires_after_sequence.to_be_bytes());
    Ok(bytes)
}

pub(crate) fn hmac_sha256(secret: &[u8; 32], message: &[u8]) -> Digest32 {
    let mut inner_pad = [0x36_u8; HMAC_BLOCK_BYTES];
    let mut outer_pad = [0x5c_u8; HMAC_BLOCK_BYTES];
    for (index, byte) in secret.iter().enumerate() {
        inner_pad[index] ^= *byte;
        outer_pad[index] ^= *byte;
    }

    let mut inner = Vec::with_capacity(HMAC_BLOCK_BYTES + message.len());
    inner.extend_from_slice(&inner_pad);
    inner.extend_from_slice(message);
    let inner_digest = Digest32::of_bytes(&inner);

    let mut outer = Vec::with_capacity(HMAC_BLOCK_BYTES + 32);
    outer.extend_from_slice(&outer_pad);
    outer.extend_from_slice(inner_digest.as_array());
    Digest32::of_bytes(&outer)
}

fn constant_time_digest_eq(left: Digest32, right: Digest32) -> bool {
    let mut different = 0_u8;
    for (left, right) in left.as_array().iter().zip(right.as_array().iter()) {
        different |= *left ^ *right;
    }
    different == 0
}
