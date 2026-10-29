//! Disposable keys for the existing qualification fixture, never host keys.
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use codex_hepta_learning_ledger::LearningAuthenticationProfile;
use codex_hepta_learning_ledger::LearningSignature;
use codex_hepta_learning_ledger::LearningVerificationKey;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) enum FixtureSigner {
    Classical(Box<SigningKey>),
    Pq(Box<PqNativeSigningKey>),
}

impl FixtureSigner {
    pub(super) fn from_seed(profile: LearningAuthenticationProfile, seed: u8) -> Self {
        match profile {
            LearningAuthenticationProfile::ClassicalV1 => {
                Self::Classical(Box::new(SigningKey::from_bytes(&[seed; 32])))
            }
            LearningAuthenticationProfile::MlDsa65V2 => {
                let seed = [seed; 32].into();
                let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
                let key_id = ml_dsa_65_key_id_from_spki(&spki).unwrap();
                Self::Pq(Box::new(
                    PqNativeSigningKey::from_owned_seed(seed, key_id).unwrap(),
                ))
            }
        }
    }

    pub(super) fn verification_key(&self) -> LearningVerificationKey {
        match self {
            Self::Classical(key) => key.verifying_key().to_bytes().into(),
            Self::Pq(key) => LearningVerificationKey::MlDsa65V2(key.public_spki().to_vec()),
        }
    }

    pub(super) fn placeholder(&self) -> LearningSignature {
        match self {
            Self::Classical(_) => [0; 64].into(),
            Self::Pq(_) => LearningSignature::MlDsa65V2(Vec::new()),
        }
    }

    pub(super) fn sign(&self, message: &[u8]) -> LearningSignature {
        match self {
            Self::Classical(key) => key.sign(message).to_bytes().into(),
            Self::Pq(key) => {
                LearningSignature::MlDsa65V2(key.sign_exact_message(message).unwrap().to_vec())
            }
        }
    }
}
