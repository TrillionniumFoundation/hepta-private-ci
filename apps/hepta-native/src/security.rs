use std::collections::BTreeMap;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::error::ShellError;
use crate::model::PlatformAction;
use crate::model::SignedPlatformGrantV1;
use crate::model::validate_digest;
use crate::model::validate_stable_id;

const MAX_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Debug, Clone, Copy)]
pub struct PlatformGrantContext<'a> {
    pub session_id: &'a str,
    pub session_generation: u64,
    pub operation_id: &'a str,
    pub action: PlatformAction,
    pub payload_digest: &'a str,
    pub now_unix_ms: u64,
}

pub trait GrantVerifier: Send + Sync {
    fn verify_platform_grant(
        &self,
        grant: &SignedPlatformGrantV1,
        context: PlatformGrantContext<'_>,
    ) -> Result<(), ShellError>;
}

#[derive(Debug, Clone)]
pub struct TrustedKeySet {
    keys: BTreeMap<String, VerifyingKey>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct KeySetFile {
    schema: String,
    keys: BTreeMap<String, String>,
}

impl TrustedKeySet {
    pub fn from_path(path: &Path) -> Result<Self, ShellError> {
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(
                "trusted key set path must be absolute".to_owned(),
            ));
        }
        let file: KeySetFile = serde_json::from_slice(&std::fs::read(path)?)?;
        if file.schema != "hepta.native-trusted-keys.v1" || file.keys.is_empty() {
            return Err(ShellError::Security(
                "trusted native key set schema or key population is invalid".to_owned(),
            ));
        }
        let mut keys = BTreeMap::new();
        for (key_id, encoded) in file.keys {
            validate_stable_id(&key_id, "trusted key id")?;
            let decoded = STANDARD
                .decode(encoded)
                .map_err(|error| ShellError::Security(error.to_string()))?;
            let key_bytes: [u8; 32] = decoded.try_into().map_err(|_| {
                ShellError::Security("trusted Ed25519 public key must be 32 bytes".to_owned())
            })?;
            let key = VerifyingKey::from_bytes(&key_bytes)
                .map_err(|error| ShellError::Security(error.to_string()))?;
            keys.insert(key_id, key);
        }
        Ok(Self { keys })
    }

    pub fn verify_message(
        &self,
        key_id: &str,
        signature_base64: &str,
        message: &[u8],
    ) -> Result<(), ShellError> {
        validate_stable_id(key_id, "signing key id")?;
        let key = self
            .keys
            .get(key_id)
            .ok_or_else(|| ShellError::Security(format!("untrusted native signing key {key_id}")))?;
        let signature_bytes = STANDARD
            .decode(signature_base64)
            .map_err(|error| ShellError::Security(error.to_string()))?;
        let signature = Signature::from_slice(&signature_bytes)
            .map_err(|error| ShellError::Security(error.to_string()))?;
        key.verify(message, &signature)
            .map_err(|error| ShellError::Security(error.to_string()))
    }
}

impl GrantVerifier for TrustedKeySet {
    fn verify_platform_grant(
        &self,
        grant: &SignedPlatformGrantV1,
        context: PlatformGrantContext<'_>,
    ) -> Result<(), ShellError> {
        validate_stable_id(&grant.key_id, "grant.key_id")?;
        validate_stable_id(&grant.session_id, "grant.session_id")?;
        validate_stable_id(&grant.operation_id, "grant.operation_id")?;
        validate_digest(&grant.payload_digest, "grant.payload_digest")?;
        if grant.session_id != context.session_id
            || grant.session_generation != context.session_generation
            || grant.operation_id != context.operation_id
            || grant.action != context.action
            || grant.payload_digest != context.payload_digest
        {
            return Err(ShellError::Security(
                "platform grant is not bound to the current final operation".to_owned(),
            ));
        }
        if grant.expires_unix_ms < context.now_unix_ms {
            return Err(ShellError::Security("platform grant expired".to_owned()));
        }
        if grant.expires_unix_ms.saturating_sub(context.now_unix_ms) > 15 * 60 * 1000 + MAX_CLOCK_SKEW_MS {
            return Err(ShellError::Security(
                "platform grant lifetime exceeds the native short-lived ceiling".to_owned(),
            ));
        }
        self.verify_message(
            &grant.key_id,
            &grant.signature_base64,
            grant.signing_message().as_bytes(),
        )
    }
}

pub fn now_unix_ms() -> Result<u64, ShellError> {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| ShellError::State(error.to_string()))?;
    u64::try_from(duration.as_millis())
        .map_err(|_| ShellError::State("system clock exceeds u64 milliseconds".to_owned()))
}
