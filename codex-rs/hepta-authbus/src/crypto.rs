//! Algorithm selection belongs to the trusted owner; verification never retries.

use codex_hepta_contracts::pq_auth::ML_DSA_65_SIGNATURE_BYTES;
use codex_hepta_contracts::pq_auth::ML_DSA_65_SPKI_BYTES;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::VerifyingKey;

use crate::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AuthBusAlgorithm {
    Ed25519V1,
    MlDsa65V2,
}

impl AuthBusAlgorithm {
    pub fn from_schema_version(version: u32) -> Result<Self, Error> {
        match version {
            1 => Ok(Self::Ed25519V1),
            2 => Ok(Self::MlDsa65V2),
            _ => Err(Error::InvalidSignature),
        }
    }

    pub fn schema_version(self) -> u32 {
        match self {
            Self::Ed25519V1 => 1,
            Self::MlDsa65V2 => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthBusVerifyingKey {
    Ed25519(VerifyingKey),
    MlDsa65(Box<[u8; ML_DSA_65_SPKI_BYTES]>),
}

impl From<VerifyingKey> for AuthBusVerifyingKey {
    fn from(value: VerifyingKey) -> Self {
        Self::Ed25519(value)
    }
}

impl AuthBusVerifyingKey {
    pub fn from_bytes(algorithm: AuthBusAlgorithm, bytes: &[u8]) -> Result<Self, Error> {
        match algorithm {
            AuthBusAlgorithm::Ed25519V1 => {
                let bytes = bytes.try_into().map_err(|_| Error::InvalidSignature)?;
                VerifyingKey::from_bytes(bytes)
                    .map(Self::Ed25519)
                    .map_err(|_| Error::InvalidSignature)
            }
            AuthBusAlgorithm::MlDsa65V2 => Self::from_pq_spki(bytes),
        }
    }

    pub fn from_pq_spki(spki: &[u8]) -> Result<Self, Error> {
        let key_id = ml_dsa_65_key_id_from_spki(spki).map_err(|_| Error::InvalidSignature)?;
        PqNativeVerifier::from_pinned_spki(spki, key_id).map_err(|_| Error::InvalidSignature)?;
        let spki = spki.try_into().map_err(|_| Error::InvalidSignature)?;
        Ok(Self::MlDsa65(Box::new(spki)))
    }

    pub fn algorithm(&self) -> AuthBusAlgorithm {
        match self {
            Self::Ed25519(_) => AuthBusAlgorithm::Ed25519V1,
            Self::MlDsa65(_) => AuthBusAlgorithm::MlDsa65V2,
        }
    }

    pub fn as_bytes(&self) -> &[u8] {
        match self {
            Self::Ed25519(key) => key.as_bytes(),
            Self::MlDsa65(spki) => spki.as_slice(),
        }
    }

    pub fn to_bytes(&self) -> Vec<u8> {
        self.as_bytes().to_vec()
    }

    pub(crate) fn verify(&self, message: &[u8], signature: &AuthBusSignature) -> Result<(), Error> {
        match (self, signature) {
            (Self::Ed25519(key), AuthBusSignature::Ed25519(bytes)) => key
                .verify_strict(message, &ed25519_dalek::Signature::from_bytes(bytes))
                .map_err(|_| Error::InvalidSignature),
            (Self::MlDsa65(spki), AuthBusSignature::MlDsa65(bytes)) => {
                let key_id = ml_dsa_65_key_id_from_spki(spki.as_slice())
                    .map_err(|_| Error::InvalidSignature)?;
                PqNativeVerifier::from_pinned_spki(spki.as_slice(), key_id)
                    .map_err(|_| Error::InvalidSignature)?
                    .verify_exact_message(message, bytes.as_slice())
                    .map_err(|_| Error::InvalidSignature)?;
                Ok(())
            }
            _ => Err(Error::InvalidSignature),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AuthBusSignature {
    Ed25519([u8; 64]),
    MlDsa65(Box<[u8; ML_DSA_65_SIGNATURE_BYTES]>),
}

impl From<[u8; 64]> for AuthBusSignature {
    fn from(value: [u8; 64]) -> Self {
        Self::Ed25519(value)
    }
}

impl From<[u8; ML_DSA_65_SIGNATURE_BYTES]> for AuthBusSignature {
    fn from(value: [u8; ML_DSA_65_SIGNATURE_BYTES]) -> Self {
        Self::MlDsa65(Box::new(value))
    }
}

impl AuthBusSignature {
    pub fn from_bytes(algorithm: AuthBusAlgorithm, bytes: &[u8]) -> Result<Self, Error> {
        match algorithm {
            AuthBusAlgorithm::Ed25519V1 => Ok(Self::Ed25519(
                bytes.try_into().map_err(|_| Error::InvalidSignature)?,
            )),
            AuthBusAlgorithm::MlDsa65V2 => Ok(Self::MlDsa65(Box::new(
                bytes.try_into().map_err(|_| Error::InvalidSignature)?,
            ))),
        }
    }

    pub fn algorithm(&self) -> AuthBusAlgorithm {
        match self {
            Self::Ed25519(_) => AuthBusAlgorithm::Ed25519V1,
            Self::MlDsa65(_) => AuthBusAlgorithm::MlDsa65V2,
        }
    }

    pub fn as_slice(&self) -> &[u8] {
        match self {
            Self::Ed25519(bytes) => bytes,
            Self::MlDsa65(bytes) => bytes.as_slice(),
        }
    }
}

impl std::ops::Deref for AuthBusSignature {
    type Target = [u8];

    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}

impl std::ops::DerefMut for AuthBusSignature {
    fn deref_mut(&mut self) -> &mut Self::Target {
        match self {
            Self::Ed25519(bytes) => bytes,
            Self::MlDsa65(bytes) => bytes.as_mut_slice(),
        }
    }
}

#[cfg(test)]
#[path = "crypto_tests.rs"]
mod tests;
