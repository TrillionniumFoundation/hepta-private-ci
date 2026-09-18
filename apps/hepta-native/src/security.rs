use crate::journal::JournalError;
use crate::journal::NonceJournal;
use crate::now_unix_ms;
use crate::types::GrantBinding;
use crate::types::SignedPlatformGrant;
use crate::validate_digest;
use crate::validate_stable_id;
use base64::Engine as _;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore as _;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use thiserror::Error;

const DOMAIN: &[u8] = b"hepta.ui.native.platform-grant.v1\0";
const MAX_GRANT_LIFETIME_MS: u64 = 5 * 60 * 1000;
const KEYRING_SERVICE: &str = "hepta.native";
const PLATFORM_KEYRING_ACCOUNT: &str = "platform-grant-public-key-v1";

#[derive(Debug, Error)]
pub enum GrantError {
    #[error("platform effect authority is not configured")]
    Unavailable,
    #[error("platform grant is malformed")]
    Invalid,
    #[error("platform grant trust root does not match")]
    TrustMismatch,
    #[error("platform grant binding does not match the final request")]
    BindingMismatch,
    #[error("platform grant signature is invalid")]
    InvalidSignature,
    #[error("platform grant is not currently valid")]
    TimeWindow,
    #[error("platform grant nonce has already been consumed")]
    Replay,
    #[error("platform authority journal failed: {0}")]
    Journal(#[from] JournalError),
}

#[derive(Clone)]
pub struct GrantVerifier {
    signer_id: String,
    key_id: String,
    key: VerifyingKey,
    nonces: NonceJournal,
}

impl std::fmt::Debug for GrantVerifier {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("GrantVerifier")
            .field("signer_id", &self.signer_id)
            .field("key_id", &self.key_id)
            .field("key", &"[PINNED]")
            .finish()
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredTrustRoot {
    signer_id: String,
    key_id: String,
    public_key_b64: String,
}

impl GrantVerifier {
    pub fn new(
        signer_id: String,
        key_id: String,
        public_key: [u8; 32],
        nonce_path: std::path::PathBuf,
    ) -> Result<Self, GrantError> {
        if !validate_stable_id(&signer_id) || !validate_stable_id(&key_id) {
            return Err(GrantError::Invalid);
        }
        let key = VerifyingKey::from_bytes(&public_key).map_err(|_| GrantError::Invalid)?;
        if key.is_weak() {
            return Err(GrantError::Invalid);
        }
        Ok(Self {
            signer_id,
            key_id,
            key,
            nonces: NonceJournal::open(nonce_path)?,
        })
    }

    pub fn load(state_root: &Path) -> Result<Option<Self>, GrantError> {
        let trust = if let Ok(public_key_b64) =
            std::env::var("HEPTA_NATIVE_PLATFORM_GRANT_PUBLIC_KEY_B64")
        {
            Some(StoredTrustRoot {
                signer_id: std::env::var("HEPTA_NATIVE_PLATFORM_GRANT_SIGNER_ID")
                    .map_err(|_| GrantError::Invalid)?,
                key_id: std::env::var("HEPTA_NATIVE_PLATFORM_GRANT_KEY_ID")
                    .map_err(|_| GrantError::Invalid)?,
                public_key_b64,
            })
        } else {
            let store = DefaultKeyringStore;
            match store.load(KEYRING_SERVICE, PLATFORM_KEYRING_ACCOUNT) {
                Ok(Some(value)) => {
                    Some(serde_json::from_str(&value).map_err(|_| GrantError::Invalid)?)
                }
                Ok(None) | Err(_) => None,
            }
        };
        let Some(trust) = trust else {
            return Ok(None);
        };
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(trust.public_key_b64)
            .map_err(|_| GrantError::Invalid)?;
        let key: [u8; 32] = bytes.try_into().map_err(|_| GrantError::Invalid)?;
        Self::new(
            trust.signer_id,
            trust.key_id,
            key,
            state_root.join("platform-grant-nonces.log"),
        )
        .map(Some)
    }

    pub fn claim(
        &self,
        signed: &SignedPlatformGrant,
        expected: &GrantBinding,
    ) -> Result<(), GrantError> {
        let grant = &signed.grant;
        if grant.schema_version != 1
            || grant.signer_id != self.signer_id
            || grant.key_id != self.key_id
            || !validate_stable_id(&grant.grant_id)
            || !validate_stable_id(&grant.nonce)
            || !validate_digest(&grant.binding.resource_digest)
            || !validate_digest(&grant.binding.payload_digest)
            || grant.expires_at_unix_ms <= grant.not_before_unix_ms
            || grant.expires_at_unix_ms - grant.not_before_unix_ms > MAX_GRANT_LIFETIME_MS
        {
            return Err(GrantError::Invalid);
        }
        if &grant.binding != expected {
            return Err(GrantError::BindingMismatch);
        }
        let now = now_unix_ms().map_err(|_| GrantError::TimeWindow)?;
        if now < grant.not_before_unix_ms || now >= grant.expires_at_unix_ms {
            return Err(GrantError::TimeWindow);
        }
        let signature_bytes = base64::engine::general_purpose::STANDARD
            .decode(&signed.signature_b64)
            .map_err(|_| GrantError::InvalidSignature)?;
        let signature =
            Signature::from_slice(&signature_bytes).map_err(|_| GrantError::InvalidSignature)?;
        let message = grant_signing_bytes(grant).map_err(|_| GrantError::Invalid)?;
        self.key
            .verify_strict(&message, &signature)
            .map_err(|_| GrantError::InvalidSignature)?;
        if !self.nonces.claim(&grant.nonce)? {
            return Err(GrantError::Replay);
        }
        Ok(())
    }

    pub fn signer_id(&self) -> &str {
        &self.signer_id
    }

    pub fn key_id(&self) -> &str {
        &self.key_id
    }
}

pub fn grant_signing_bytes(
    grant: &crate::types::PlatformGrant,
) -> Result<Vec<u8>, serde_json::Error> {
    let binding = &grant.binding;
    let message = format!(
        "schema_version={}\nsigner_id={}\nkey_id={}\ngrant_id={}\nnonce={}\nsession_id={}\nsession_generation={}\noperation_id={}\naction={}\nresource_digest={}\npayload_digest={}\nnot_before_unix_ms={}\nexpires_at_unix_ms={}\n",
        grant.schema_version,
        grant.signer_id,
        grant.key_id,
        grant.grant_id,
        grant.nonce,
        binding.session_id,
        binding.session_generation,
        binding.operation_id,
        binding.action.as_str(),
        binding.resource_digest,
        binding.payload_digest,
        grant.not_before_unix_ms,
        grant.expires_at_unix_ms,
    );
    let mut bytes = DOMAIN.to_vec();
    bytes.extend(message.as_bytes());
    Ok(bytes)
}
