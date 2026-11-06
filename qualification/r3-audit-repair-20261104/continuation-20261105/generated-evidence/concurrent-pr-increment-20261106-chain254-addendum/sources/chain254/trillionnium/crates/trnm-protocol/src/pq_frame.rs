//! Strict native TPQ1 research wire preflight; **not** a signature verifier.
//!
//! No value returned by this module is an authenticated identity, a verified
//! transaction, VerifiedWork, authorization, final-use or release capability.
//! A separately reviewed ML-DSA-65 verifier and state/nonce owner MUST follow.
//! This module deliberately does not alter the installed legacy PoN wire.
use sha2::{Digest, Sha256, Sha384};

pub const TPQ1_UNSIGNED_BYTES: usize = 176;
pub const ML_DSA_65_SIGNATURE_BYTES: usize = 3_309;
pub const ML_DSA_65_PUBLIC_KEY_BYTES: usize = 1_952;
pub const ML_DSA_65_SPKI_BYTES: usize = 1_974;
// Strict DER SPKI: SEQUENCE(1970), SEQUENCE(id-ml-dsa-65 OID), BIT STRING(1953).
// This checks framing/algorithm identity only; it is NOT ML-DSA public-key validation.
pub(crate) const ML_DSA_65_SPKI_PREFIX: [u8; 22] = [
    0x30, 0x82, 0x07, 0xb2, 0x30, 0x0b, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x03,
    0x12, 0x03, 0x82, 0x07, 0xa1, 0x00,
];
pub(crate) const PUBLIC_KEY_ID_DOMAIN: &[u8] = b"TRNM/PoN/PQKey/v1\0";
pub const TPQ1_SIGNED_BYTES: usize = TPQ1_UNSIGNED_BYTES + 2 + ML_DSA_65_SIGNATURE_BYTES;
pub const TPQ1_MAX_PAYLOAD_BYTES: usize = 64 * 1024 * 1024;
pub(crate) const DOMAIN: &[u8] = b"TRNM/PoN/PQAuth/ML-DSA-65/v1\0";
pub(crate) const PAYLOAD_TAG: &[u8] = b"payload\0";
pub(crate) const TPQ1_MAGIC: &[u8; 4] = b"TPQ1";
pub(crate) const TPQ1_VERSION: u8 = 1;
pub(crate) const TPQ1_ALGORITHM: u8 = 0x65;
pub(crate) const FIRST_PURPOSE: u8 = 1;
pub(crate) const LAST_PURPOSE: u8 = 6;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PqFrameError {
    FrameLength,
    HeaderVersionAlgorithm,
    PurposeOrReserved,
    ContextOrIdentity,
    LifetimeOrSequence,
    Expired,
    PayloadSize,
    PayloadDigest,
    SignatureLength,
    PublicKeyDer,
}

/// Independently pinned caller expectations. In particular, the key ID does
/// not come from the untrusted frame; the future crypto owner must derive it
/// from a strict ML-DSA-65 SPKI public key before using this preflight.
#[derive(Debug, Clone)]
pub struct PqFrameExpectation<'a> {
    pub purpose: u8,
    pub network: [u8; 32],
    pub owner_context: [u8; 32],
    pub signer_key_id: [u8; 32],
    pub owner_generation: u64,
    pub operation_sequence: u64,
    pub expires_at: u64,
    pub now: u64,
    pub payload: &'a [u8],
}

/// These are UNVERIFIED bytes; never use this as a boolean proof of signature,
/// chain authority, user permission, model quality or state transition.
#[derive(Debug)]
pub struct UnverifiedPqFrame<'a> {
    statement: &'a [u8],
    signature: &'a [u8],
}

impl<'a> UnverifiedPqFrame<'a> {
    pub fn unsigned_statement(&self) -> &'a [u8] {
        self.statement
    }

    pub fn unverified_signature(&self) -> &'a [u8] {
        self.signature
    }
}

fn u64_at(input: &[u8], start: usize) -> u64 {
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&input[start..start + 8]);
    u64::from_be_bytes(bytes)
}

/// The exact v1 Python research payload commitment:
/// SHA384(DOMAIN || "payload\0" || BE64(len) || payload).
pub fn payload_commitment(payload: &[u8]) -> Result<[u8; 48], PqFrameError> {
    if payload.len() > TPQ1_MAX_PAYLOAD_BYTES {
        return Err(PqFrameError::PayloadSize);
    }
    let mut h = Sha384::new();
    h.update(DOMAIN);
    h.update(PAYLOAD_TAG);
    h.update((payload.len() as u64).to_be_bytes());
    h.update(payload);
    Ok(h.finalize().into())
}

/// Derive the reference identity from one exact ML-DSA-65 DER SPKI.
///
/// Restrict both the ASN.1 structure and OID before hashing: this rejects
/// alternative algorithms, optional parameters, non-minimal length encodings,
/// padding changes, truncation and appended bytes. The 1,952 key bytes are
/// NOT checked for cryptographic validity here; a real ML-DSA-65 verifier
/// remains mandatory before any trust or authorization can be established.
pub fn ml_dsa_65_key_id_from_spki(spki: &[u8]) -> Result<[u8; 32], PqFrameError> {
    if spki.len() != ML_DSA_65_SPKI_BYTES || !spki.starts_with(&ML_DSA_65_SPKI_PREFIX) {
        return Err(PqFrameError::PublicKeyDer);
    }
    let mut digest = Sha256::new();
    digest.update(PUBLIC_KEY_ID_DOMAIN);
    digest.update(spki);
    Ok(digest.finalize().into())
}

/// Reject malformed/unbound TPQ1 before invoking an independently implemented
/// ML-DSA-65 verifier. Success is NEVER signature verification. Keeping this
/// result unverified avoids a forged Boolean being converted to an authority.
pub fn preflight_unverified<'a>(
    bytes: &'a [u8],
    expected: &PqFrameExpectation<'_>,
) -> Result<UnverifiedPqFrame<'a>, PqFrameError> {
    if bytes.len() != TPQ1_SIGNED_BYTES {
        return Err(PqFrameError::FrameLength);
    }
    if &bytes[..4] != TPQ1_MAGIC || bytes[4] != TPQ1_VERSION || bytes[5] != TPQ1_ALGORITHM {
        return Err(PqFrameError::HeaderVersionAlgorithm);
    }
    if !(FIRST_PURPOSE..=LAST_PURPOSE).contains(&bytes[6])
        || bytes[6] != expected.purpose
        || bytes[7] != 0
    {
        return Err(PqFrameError::PurposeOrReserved);
    }
    if &bytes[8..40] != expected.network.as_slice()
        || &bytes[40..72] != expected.owner_context.as_slice()
        || &bytes[72..104] != expected.signer_key_id.as_slice()
    {
        return Err(PqFrameError::ContextOrIdentity);
    }
    let generation = u64_at(bytes, 104);
    let sequence = u64_at(bytes, 112);
    let expiry = u64_at(bytes, 120);
    if generation == 0
        || sequence == 0
        || expiry == 0
        || generation != expected.owner_generation
        || sequence != expected.operation_sequence
        || expiry != expected.expires_at
    {
        return Err(PqFrameError::LifetimeOrSequence);
    }
    if expected.now > expiry {
        return Err(PqFrameError::Expired);
    }
    if &bytes[128..176] != payload_commitment(expected.payload)?.as_slice() {
        return Err(PqFrameError::PayloadDigest);
    }
    let len = u16::from_be_bytes([bytes[176], bytes[177]]) as usize;
    if len != ML_DSA_65_SIGNATURE_BYTES {
        return Err(PqFrameError::SignatureLength);
    }
    Ok(UnverifiedPqFrame {
        statement: &bytes[..TPQ1_UNSIGNED_BYTES],
        signature: &bytes[TPQ1_UNSIGNED_BYTES + 2..],
    })
}

/// Preflight a TPQ1 frame against a caller-pinned actual DER SPKI,
/// rather than trusting a key ID copied from an untrusted frame.
///
/// The caller must independently authenticate expected (including the key ID)
/// and supply the nominated public key out-of-band. Neither this check nor the
/// simpler preflight_unverified verifies a signature, signer possession,
/// nonce consumption, or any Chain/Hepta authority.
pub fn preflight_unverified_with_spki<'a>(
    bytes: &'a [u8],
    expected: &PqFrameExpectation<'_>,
    pinned_spki: &[u8],
) -> Result<UnverifiedPqFrame<'a>, PqFrameError> {
    let actual_key_id = ml_dsa_65_key_id_from_spki(pinned_spki)?;
    if actual_key_id != expected.signer_key_id {
        return Err(PqFrameError::ContextOrIdentity);
    }
    preflight_unverified(bytes, expected)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn case<'a>(payload: &'a [u8]) -> (Vec<u8>, PqFrameExpectation<'a>) {
        let e = PqFrameExpectation {
            purpose: 4,
            network: [1; 32],
            owner_context: [2; 32],
            signer_key_id: [3; 32],
            owner_generation: 7,
            operation_sequence: 19,
            expires_at: 4000,
            now: 3999,
            payload,
        };
        let mut v = vec![0xab; TPQ1_SIGNED_BYTES];
        v[..4].copy_from_slice(b"TPQ1");
        v[4] = 1;
        v[5] = 0x65;
        v[6] = e.purpose;
        v[7] = 0;
        v[8..40].copy_from_slice(&e.network);
        v[40..72].copy_from_slice(&e.owner_context);
        v[72..104].copy_from_slice(&e.signer_key_id);
        v[104..112].copy_from_slice(&e.owner_generation.to_be_bytes());
        v[112..120].copy_from_slice(&e.operation_sequence.to_be_bytes());
        v[120..128].copy_from_slice(&e.expires_at.to_be_bytes());
        v[128..176].copy_from_slice(&payload_commitment(payload).unwrap());
        v[176..178].copy_from_slice(&(ML_DSA_65_SIGNATURE_BYTES as u16).to_be_bytes());
        (v, e)
    }

    #[test]
    fn entire_statement_has_one_exact_canonical_preflight_binding() {
        let (v, e) = case(b"public Cell release manifest hash and consent");
        let checked = preflight_unverified(&v, &e).unwrap();
        assert_eq!(checked.unsigned_statement().len(), 176);
        assert_eq!(checked.unverified_signature().len(), 3309);
        for idx in 0..TPQ1_UNSIGNED_BYTES {
            let mut mutated = v.clone();
            mutated[idx] ^= 1;
            assert!(
                preflight_unverified(&mutated, &e).is_err(),
                "field byte {idx}"
            );
        }
    }

    #[test]
    fn zero_lifetimes_bad_length_and_classical_downgrade_reject() {
        let (v, e) = case(b"test");
        for end in [0, 175, 3486, 3488] {
            let mut bad = v.clone();
            bad.resize(end, 0);
            assert_eq!(
                preflight_unverified(&bad, &e).unwrap_err(),
                PqFrameError::FrameLength
            );
        }
        let mut bad = v.clone();
        bad[5] = 0x19; // Ed25519 is not a PQ signature algorithm.
        assert_eq!(
            preflight_unverified(&bad, &e).unwrap_err(),
            PqFrameError::HeaderVersionAlgorithm
        );
        for range in [104..112, 112..120, 120..128] {
            let mut bad = v.clone();
            bad[range].fill(0);
            assert_eq!(
                preflight_unverified(&bad, &e).unwrap_err(),
                PqFrameError::LifetimeOrSequence
            );
        }
    }

    #[test]
    fn stale_payload_and_signature_size_refuse() {
        let (v, mut e) = case(b"test");
        e.now = 4001;
        assert_eq!(
            preflight_unverified(&v, &e).unwrap_err(),
            PqFrameError::Expired
        );
        e.now = 3999;
        e.payload = b"other";
        assert_eq!(
            preflight_unverified(&v, &e).unwrap_err(),
            PqFrameError::PayloadDigest
        );
        e.payload = b"test";
        let mut bad = v.clone();
        bad[176] = 0;
        assert_eq!(
            preflight_unverified(&bad, &e).unwrap_err(),
            PqFrameError::SignatureLength
        );
    }

    #[test]
    fn unverified_signature_change_never_grants_authority() {
        let (v, e) = case(b"test");
        let mut fake = v.clone();
        fake[178] ^= 1;
        let a = preflight_unverified(&v, &e).unwrap();
        let b = preflight_unverified(&fake, &e).unwrap();
        assert_ne!(a.unverified_signature(), b.unverified_signature());
        // Both are merely unverified frames: no cryptographic success is offered.
    }

    #[test]
    fn sha384_payload_commitment_matches_independent_python_oracle() {
        let payload = b"public Cell release manifest hash and consent";
        let digest = payload_commitment(payload).unwrap();
        assert_eq!(
            hex::encode(digest),
            "2ceb9c0f29a40392386f5644c998adedaf5ae91f46b2faff977a66ad8153cbfe2bc62af16fd4125e7f516fc09a1382e4"
        );
    }

    fn spki_with_payload_byte(value: u8) -> Vec<u8> {
        let mut result = ML_DSA_65_SPKI_PREFIX.to_vec();
        result.extend_from_slice(&vec![value; ML_DSA_65_PUBLIC_KEY_BYTES]);
        result
    }

    #[test]
    fn pinned_mldsa_spki_identity_matches_independent_sha256_vector() {
        let spki = spki_with_payload_byte(0x42);
        assert_eq!(spki.len(), ML_DSA_65_SPKI_BYTES);
        let id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
        assert_eq!(
            hex::encode(id),
            "afc295d8a2307875be792894d57b195f2f9513ede37ac98162232d2a09ca0989"
        );
        let (mut frame, mut expected) = case(b"pinned model");
        expected.signer_key_id = id;
        frame[72..104].copy_from_slice(&id);
        let unverified = preflight_unverified_with_spki(&frame, &expected, &spki).unwrap();
        assert_eq!(unverified.unsigned_statement().len(), TPQ1_UNSIGNED_BYTES);
        assert_eq!(
            unverified.unverified_signature().len(),
            ML_DSA_65_SIGNATURE_BYTES
        );

        // A second structurally well-formed key cannot substitute for the pinned key.
        let alternative = spki_with_payload_byte(0);
        assert_eq!(
            preflight_unverified_with_spki(&frame, &expected, &alternative).unwrap_err(),
            PqFrameError::ContextOrIdentity
        );
        frame[178..].fill(0);
        // Even an all-zero alleged signature passes syntax-only preflight:
        // cryptographic verification must still run before trust is granted.
        assert!(preflight_unverified_with_spki(&frame, &expected, &spki).is_ok());
    }

    #[test]
    fn malformed_spki_or_classical_key_never_binds_pq_identity() {
        let good = spki_with_payload_byte(0x42);
        let mut variants = vec![
            good[..good.len() - 1].to_vec(),
            [good.as_slice(), &[0]].concat(),
            [good.as_slice(), &[0x30, 0]].concat(),
        ];
        for index in [0usize, 3, 15, 20, 21] {
            let mut changed = good.clone();
            changed[index] ^= 1;
            variants.push(changed);
        }
        // Ed25519's SPKI shape and OID differ fundamentally from ML-DSA.
        variants.push(vec![0x30, 0x2a, 0x30, 5, 6, 3, 0x2b, 0x65, 0x70]);
        for der in variants {
            assert_eq!(
                ml_dsa_65_key_id_from_spki(&der).unwrap_err(),
                PqFrameError::PublicKeyDer
            );
        }
    }

    #[test]
    fn old_devnet_transaction_size_cannot_hold_pq_signature() {
        const {
            assert!(TPQ1_SIGNED_BYTES > 2048);
            assert!(ML_DSA_65_SIGNATURE_BYTES > 2048);
        }
    }
}
