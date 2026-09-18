use base64::Engine as _;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::SessionIncarnation;
use crate::model::sha256_hex;
use crate::model::validate_digest;
use crate::model::validate_stable_id;
use zeroize::Zeroize as _;

const SERVICE: &str = "hepta.native.session.v1";
const GATEWAY_SERVICE: &str = "hepta.native.gateway.v1";
const MIN_GATEWAY_TOKEN_BYTES: usize = 32;
const MAX_GATEWAY_TOKEN_BYTES: usize = 256;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StoredSessionReference {
    pub session: SessionIncarnation,
    pub manifest_digest: String,
}

#[derive(Debug, Clone)]
pub struct SessionReferenceStore<S = DefaultKeyringStore> {
    keyring: S,
}

impl Default for SessionReferenceStore<DefaultKeyringStore> {
    fn default() -> Self {
        Self {
            keyring: DefaultKeyringStore,
        }
    }
}

impl<S: KeyringStore> SessionReferenceStore<S> {
    pub fn new(keyring: S) -> Self {
        Self { keyring }
    }

    pub fn load(&self, endpoint_id: &str) -> Result<Option<StoredSessionReference>, ShellError> {
        validate_stable_id(endpoint_id, "endpoint_id")?;
        let Some(value) = self
            .keyring
            .load(SERVICE, endpoint_id)
            .map_err(|error| ShellError::Security(error.to_string()))?
        else {
            return Ok(None);
        };
        let stored: StoredSessionReference = serde_json::from_str(&value)?;
        stored.session.validate()?;
        validate_digest(&stored.manifest_digest, "stored manifest digest")?;
        if stored.session.endpoint_id != endpoint_id {
            return Err(ShellError::Security(
                "keyring session reference endpoint mismatch".to_owned(),
            ));
        }
        Ok(Some(stored))
    }

    pub fn save(
        &self,
        session: &SessionIncarnation,
        manifest_digest: &str,
    ) -> Result<(), ShellError> {
        session.validate()?;
        validate_digest(manifest_digest, "manifest_digest")?;
        let value = serde_json::to_string(&StoredSessionReference {
            session: session.clone(),
            manifest_digest: manifest_digest.to_owned(),
        })?;
        self.keyring
            .save(SERVICE, &session.endpoint_id, &value)
            .map_err(|error| ShellError::Security(error.to_string()))
    }

    pub fn delete(&self, endpoint_id: &str) -> Result<bool, ShellError> {
        validate_stable_id(endpoint_id, "endpoint_id")?;
        self.keyring
            .delete(SERVICE, endpoint_id)
            .map_err(|error| ShellError::Security(error.to_string()))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GatewayCredentialProvisionReceipt {
    pub account: String,
    pub token_digest: String,
}

#[derive(Debug, Clone)]
pub struct GatewayCredentialStore<S = DefaultKeyringStore> {
    keyring: S,
}

impl Default for GatewayCredentialStore<DefaultKeyringStore> {
    fn default() -> Self {
        Self {
            keyring: DefaultKeyringStore,
        }
    }
}

impl<S: KeyringStore> GatewayCredentialStore<S> {
    pub fn new(keyring: S) -> Self {
        Self { keyring }
    }

    pub fn provision_random(
        &self,
        account: &str,
    ) -> Result<GatewayCredentialProvisionReceipt, ShellError> {
        validate_stable_id(account, "gateway credential account")?;
        let mut bytes = [0_u8; 32];
        getrandom::fill(&mut bytes)
            .map_err(|error| ShellError::Security(format!("generate gateway capability: {error}")))?;
        let mut token = URL_SAFE_NO_PAD.encode(bytes);
        bytes.zeroize();
        validate_gateway_token(&token)?;
        let token_digest = sha256_hex(token.as_bytes());
        let save_result = self
            .keyring
            .save(GATEWAY_SERVICE, account, &token)
            .map_err(|error| ShellError::Security(error.to_string()));
        token.zeroize();
        save_result?;
        Ok(GatewayCredentialProvisionReceipt {
            account: account.to_owned(),
            token_digest,
        })
    }

    pub fn delete(&self, account: &str) -> Result<bool, ShellError> {
        validate_stable_id(account, "gateway credential account")?;
        self.keyring
            .delete(GATEWAY_SERVICE, account)
            .map_err(|error| ShellError::Security(error.to_string()))
    }

    pub fn load(&self, account: &str) -> Result<String, ShellError> {
        validate_stable_id(account, "gateway credential account")?;
        let token = self
            .keyring
            .load(GATEWAY_SERVICE, account)
            .map_err(|error| ShellError::Security(error.to_string()))?
            .ok_or_else(|| {
                ShellError::Security("native gateway keyring capability is missing".to_owned())
            })?;
        validate_gateway_token(&token)?;
        Ok(token)
    }
}

fn validate_gateway_token(value: &str) -> Result<(), ShellError> {
    if value.len() < MIN_GATEWAY_TOKEN_BYTES
        || value.len() > MAX_GATEWAY_TOKEN_BYTES
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(byte, b'-' | b'.' | b'_' | b'~' | b'+' | b'/' | b'=')
        })
    {
        return Err(ShellError::Security(
            "native gateway bearer capability has invalid syntax or length".to_owned(),
        ));
    }
    Ok(())
}
