//! Canonical FIPS 204 ML-DSA-65 message authentication shared with Trillionnium.
//!
//! RustCrypto is the sole acceptance backend. The key-ID domain, strict SPKI,
//! pure signing mode, empty context and message bound match Chain's `pq_auth`.
//! Versioned Hepta application domains remain inside the signed message.
//! Cryptographic validity alone grants no role, replay exception or FinalUse.

use std::fmt;

use ml_dsa::KeyInit;
use ml_dsa::Keypair;
use ml_dsa::MlDsa65;
use ml_dsa::Signature;
use ml_dsa::Signer;
use ml_dsa::SigningKey;
use ml_dsa::Verifier;
use ml_dsa::VerifyingKey;
use sha2::Digest;
use sha2::Sha256;
use zeroize::Zeroizing;

pub const ML_DSA_65_SIGNATURE_BYTES: usize = 3_309;
pub const ML_DSA_65_PUBLIC_KEY_BYTES: usize = 1_952;
pub const ML_DSA_65_SPKI_BYTES: usize = 1_974;
pub const PQ_MAX_MESSAGE_BYTES: usize = 65_536;
const SPKI_PREFIX: [u8; 22] = [
    0x30, 0x82, 0x07, 0xb2, 0x30, 0x0b, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x03,
    0x12, 0x03, 0x82, 0x07, 0xa1, 0x00,
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PqNativeError {
    KeyAlgorithm,
    KeyPin,
    SignatureRejected,
}

impl fmt::Display for PqNativeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for PqNativeError {}

pub fn ml_dsa_65_key_id_from_spki(spki: &[u8]) -> Result<[u8; 32], PqNativeError> {
    if spki.len() != ML_DSA_65_SPKI_BYTES || !spki.starts_with(&SPKI_PREFIX) {
        return Err(PqNativeError::KeyAlgorithm);
    }
    let mut digest = Sha256::new();
    digest.update(b"TRNM/PoN/PQKey/v1\0");
    digest.update(spki);
    Ok(digest.finalize().into())
}

/// Only a real verification creates this observation; it carries no authority.
pub struct PqMessageObservation<'a> {
    message: &'a [u8],
    signer_key_id: [u8; 32],
}

impl<'a> PqMessageObservation<'a> {
    pub fn authenticated_message(&self) -> &'a [u8] {
        self.message
    }
    pub fn signer_key_id(&self) -> &[u8; 32] {
        &self.signer_key_id
    }
}

pub struct PqNativeVerifier {
    key: VerifyingKey<MlDsa65>,
    spki: [u8; ML_DSA_65_SPKI_BYTES],
    key_id: [u8; 32],
}

impl PqNativeVerifier {
    pub fn from_pinned_spki(spki: &[u8], expected_key_id: [u8; 32]) -> Result<Self, PqNativeError> {
        let key_id = ml_dsa_65_key_id_from_spki(spki)?;
        if key_id != expected_key_id {
            return Err(PqNativeError::KeyPin);
        }
        let key = VerifyingKey::<MlDsa65>::new_from_slice(&spki[SPKI_PREFIX.len()..])
            .map_err(|_| PqNativeError::KeyAlgorithm)?;
        let mut fixed_spki = [0; ML_DSA_65_SPKI_BYTES];
        fixed_spki.copy_from_slice(spki);
        Ok(Self {
            key,
            spki: fixed_spki,
            key_id,
        })
    }

    pub fn public_key_id(&self) -> [u8; 32] {
        self.key_id
    }

    pub fn public_spki(&self) -> &[u8; ML_DSA_65_SPKI_BYTES] {
        &self.spki
    }

    pub fn verify_exact_message<'a>(
        &self,
        message: &'a [u8],
        signature: &[u8],
    ) -> Result<PqMessageObservation<'a>, PqNativeError> {
        if message.len() > PQ_MAX_MESSAGE_BYTES || signature.len() != ML_DSA_65_SIGNATURE_BYTES {
            return Err(PqNativeError::SignatureRejected);
        }
        let signature = Signature::<MlDsa65>::try_from(signature)
            .map_err(|_| PqNativeError::SignatureRejected)?;
        self.key
            .verify(message, &signature)
            .map_err(|_| PqNativeError::SignatureRejected)?;
        Ok(PqMessageObservation {
            message,
            signer_key_id: self.key_id,
        })
    }
}

/// An owned secret, supplied by a custody owner. There is no implicit key
/// generation, secret export, fallback signer or HSM qualification claim.
pub struct PqNativeSigningKey {
    key: SigningKey<MlDsa65>,
    verifier: PqNativeVerifier,
}

impl PqNativeSigningKey {
    pub fn public_spki_from_seed(seed: &Zeroizing<[u8; 32]>) -> [u8; ML_DSA_65_SPKI_BYTES] {
        let expanded_seed = Zeroizing::new(ml_dsa::Seed::from(**seed));
        let key = SigningKey::<MlDsa65>::from_seed(&expanded_seed);
        public_spki(&key)
    }

    pub fn from_owned_seed(
        seed: Zeroizing<[u8; 32]>,
        expected_key_id: [u8; 32],
    ) -> Result<Self, PqNativeError> {
        let key = SigningKey::<MlDsa65>::new_from_slice(seed.as_ref())
            .map_err(|_| PqNativeError::KeyAlgorithm)?;
        drop(seed);
        let verifier = PqNativeVerifier::from_pinned_spki(&public_spki(&key), expected_key_id)?;
        Ok(Self { key, verifier })
    }

    pub fn public_key_id(&self) -> [u8; 32] {
        self.verifier.key_id
    }

    pub fn public_spki(&self) -> &[u8; ML_DSA_65_SPKI_BYTES] {
        &self.verifier.spki
    }

    pub fn sign_exact_message(
        &self,
        message: &[u8],
    ) -> Result<[u8; ML_DSA_65_SIGNATURE_BYTES], PqNativeError> {
        if message.len() > PQ_MAX_MESSAGE_BYTES {
            return Err(PqNativeError::SignatureRejected);
        }
        let signature: Signature<MlDsa65> = self
            .key
            .try_sign(message)
            .map_err(|_| PqNativeError::SignatureRejected)?;
        let mut result = [0; ML_DSA_65_SIGNATURE_BYTES];
        result.copy_from_slice(&signature.encode());
        self.verifier.verify_exact_message(message, &result)?;
        Ok(result)
    }
}

fn public_spki(key: &SigningKey<MlDsa65>) -> [u8; ML_DSA_65_SPKI_BYTES] {
    let mut spki = [0; ML_DSA_65_SPKI_BYTES];
    spki[..SPKI_PREFIX.len()].copy_from_slice(&SPKI_PREFIX);
    spki[SPKI_PREFIX.len()..].copy_from_slice(&key.verifying_key().encode());
    spki
}
