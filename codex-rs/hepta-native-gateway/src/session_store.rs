use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_keyring_store::KeyringStore;
use serde::Deserialize;
use serde::Serialize;

const KEYRING_SERVICE: &str = "hepta-native";
const MAX_OPAQUE_REFERENCE_BYTES: usize = 8 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct StoredSessionReferenceV1 {
    schema: String,
    endpoint_id: String,
    session_id: String,
    generation: u64,
    opaque_reference: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpaqueSessionReference {
    pub endpoint_id: StableId,
    pub session_id: StableId,
    pub generation: Generation,
    pub opaque_reference: String,
}

#[derive(Debug)]
pub enum SessionStoreError {
    InvalidOpaqueReference,
    InvalidStoredReference,
    Keyring(String),
    Serialization(String),
}

impl fmt::Display for SessionStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for SessionStoreError {}

#[derive(Debug)]
pub struct SessionReferenceStore<S: KeyringStore> {
    store: S,
    account: String,
}

impl<S: KeyringStore> SessionReferenceStore<S> {
    pub fn new(store: S, account: impl Into<String>) -> Result<Self, SessionStoreError> {
        let account = account.into();
        if account.is_empty() || account.len() > 128 {
            return Err(SessionStoreError::InvalidStoredReference);
        }
        Ok(Self { store, account })
    }

    pub fn save(&self, reference: &OpaqueSessionReference) -> Result<(), SessionStoreError> {
        validate_opaque(&reference.opaque_reference)?;
        let stored = StoredSessionReferenceV1 {
            schema: "hepta.native.session-reference.v1".to_string(),
            endpoint_id: reference.endpoint_id.to_string(),
            session_id: reference.session_id.to_string(),
            generation: reference.generation.get(),
            opaque_reference: reference.opaque_reference.clone(),
        };
        let encoded = serde_json::to_string(&stored)
            .map_err(|error| SessionStoreError::Serialization(error.to_string()))?;
        self.store
            .save(KEYRING_SERVICE, &self.account, &encoded)
            .map_err(|error| SessionStoreError::Keyring(error.to_string()))
    }

    pub fn load(&self) -> Result<Option<OpaqueSessionReference>, SessionStoreError> {
        let Some(encoded) = self
            .store
            .load(KEYRING_SERVICE, &self.account)
            .map_err(|error| SessionStoreError::Keyring(error.to_string()))?
        else {
            return Ok(None);
        };
        let stored: StoredSessionReferenceV1 = serde_json::from_str(&encoded)
            .map_err(|error| SessionStoreError::Serialization(error.to_string()))?;
        if stored.schema != "hepta.native.session-reference.v1" {
            return Err(SessionStoreError::InvalidStoredReference);
        }
        validate_opaque(&stored.opaque_reference)?;
        let endpoint_id = StableId::new(stored.endpoint_id)
            .map_err(|_| SessionStoreError::InvalidStoredReference)?;
        let session_id = StableId::new(stored.session_id)
            .map_err(|_| SessionStoreError::InvalidStoredReference)?;
        let generation = Generation::new(stored.generation)
            .map_err(|_| SessionStoreError::InvalidStoredReference)?;
        Ok(Some(OpaqueSessionReference {
            endpoint_id,
            session_id,
            generation,
            opaque_reference: stored.opaque_reference,
        }))
    }

    pub fn clear(&self) -> Result<bool, SessionStoreError> {
        self.store
            .delete(KEYRING_SERVICE, &self.account)
            .map_err(|error| SessionStoreError::Keyring(error.to_string()))
    }
}

fn validate_opaque(value: &str) -> Result<(), SessionStoreError> {
    if value.is_empty() || value.len() > MAX_OPAQUE_REFERENCE_BYTES || value.contains('\0') {
        return Err(SessionStoreError::InvalidOpaqueReference);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use codex_keyring_store::tests::MockKeyringStore;

    use super::*;

    fn stable(value: &str) -> StableId {
        StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error}"))
    }

    #[test]
    fn keyring_round_trip_preserves_only_opaque_reference_and_fence() {
        let keyring = MockKeyringStore::default();
        let store = SessionReferenceStore::new(keyring.clone(), "primary")
            .unwrap_or_else(|error| panic!("store: {error}"));
        let reference = OpaqueSessionReference {
            endpoint_id: stable("runtime.local"),
            session_id: stable("session.9"),
            generation: Generation::new(9)
                .unwrap_or_else(|error| panic!("generation: {error}")),
            opaque_reference: "opaque-keychain-owned-reference".to_string(),
        };
        store
            .save(&reference)
            .unwrap_or_else(|error| panic!("save: {error}"));
        assert_eq!(
            store
                .load()
                .unwrap_or_else(|error| panic!("load: {error}")),
            Some(reference)
        );
        assert!(store.clear().unwrap_or(false));
        assert_eq!(store.load().unwrap_or(None), None);
    }

    #[test]
    fn malformed_or_oversize_opaque_reference_is_rejected() {
        let store = SessionReferenceStore::new(MockKeyringStore::default(), "primary")
            .unwrap_or_else(|error| panic!("store: {error}"));
        let reference = OpaqueSessionReference {
            endpoint_id: stable("runtime.local"),
            session_id: stable("session.1"),
            generation: Generation::new(1)
                .unwrap_or_else(|error| panic!("generation: {error}")),
            opaque_reference: "x".repeat(MAX_OPAQUE_REFERENCE_BYTES + 1),
        };
        assert!(matches!(
            store.save(&reference),
            Err(SessionStoreError::InvalidOpaqueReference)
        ));
    }
}
