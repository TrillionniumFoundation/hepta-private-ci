//! Independent test producer for the actual classic and PQ Agentd wire routes.

use anyhow::Result;
use codex_hepta_agentd::AuthBusTextIngress;
use codex_hepta_agentd::authbus_text_claims;
use codex_hepta_agentd::sign_authbus_text_pq;
use codex_hepta_authbus::AuthBusAlgorithm;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::pq_auth::PqNativeSigningKey;
use codex_hepta_contracts::pq_auth::ml_dsa_65_key_id_from_spki;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) enum NativeSigner {
    Classic(Box<SigningKey>),
    Pq(Box<PqNativeSigningKey>),
}

impl NativeSigner {
    pub(super) fn new(seed: u8, algorithm: AuthBusAlgorithm) -> Result<Self> {
        Ok(match algorithm {
            AuthBusAlgorithm::Ed25519V1 => {
                Self::Classic(Box::new(SigningKey::from_bytes(&[seed; 32])))
            }
            AuthBusAlgorithm::MlDsa65V2 => {
                let seed = [seed; 32].into();
                let spki = PqNativeSigningKey::public_spki_from_seed(&seed);
                Self::Pq(Box::new(PqNativeSigningKey::from_owned_seed(
                    seed,
                    ml_dsa_65_key_id_from_spki(&spki)?,
                )?))
            }
        })
    }

    pub(super) fn algorithm(&self) -> AuthBusAlgorithm {
        match self {
            Self::Classic(_) => AuthBusAlgorithm::Ed25519V1,
            Self::Pq(_) => AuthBusAlgorithm::MlDsa65V2,
        }
    }

    pub(super) fn public_key_hex(&self) -> String {
        match self {
            Self::Classic(key) => super::hex(key.verifying_key().as_bytes()),
            Self::Pq(key) => super::hex(key.public_spki()),
        }
    }

    pub(super) fn sign(&self, owner: &AgentId, request: &mut AuthBusTextIngress) -> Result<()> {
        match self {
            Self::Classic(key) => {
                request.signature_hex = super::hex(
                    &key.sign(&authbus_text_claims(owner, request)?.signing_bytes())
                        .to_bytes(),
                );
            }
            Self::Pq(key) => sign_authbus_text_pq(owner, request, key)?,
        }
        Ok(())
    }
}
