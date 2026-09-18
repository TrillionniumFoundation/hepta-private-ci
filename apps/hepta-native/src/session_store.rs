use codex_keyring_store::DefaultKeyringStore;
use codex_keyring_store::KeyringStore;
use serde::Deserialize;
use serde::Serialize;

use crate::error::ShellError;
use crate::model::SessionIncarnation;
use crate::model::validate_digest;
use crate::model::validate_stable_id;

const SERVICE: &str = "hepta.native.session.v1";

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
