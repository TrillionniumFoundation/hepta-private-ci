use keyring_core::Entry;
use keyring_core::Error as KeyringError;
use std::error::Error;
use std::fmt;
use std::fmt::Debug;
use std::sync::OnceLock;
use tracing::trace;

#[derive(Debug)]
pub enum CredentialStoreError {
    Other(KeyringError),
}

impl CredentialStoreError {
    pub fn new(error: KeyringError) -> Self {
        Self::Other(error)
    }

    pub fn message(&self) -> String {
        match self {
            Self::Other(error) => error.to_string(),
        }
    }

    pub fn into_error(self) -> KeyringError {
        match self {
            Self::Other(error) => error,
        }
    }
}

impl fmt::Display for CredentialStoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Other(error) => write!(f, "{error}"),
        }
    }
}

impl Error for CredentialStoreError {}

/// Shared credential store abstraction for keyring-backed implementations.
pub trait KeyringStore: Debug + Send + Sync {
    fn load(&self, service: &str, account: &str) -> Result<Option<String>, CredentialStoreError>;
    fn save(&self, service: &str, account: &str, value: &str) -> Result<(), CredentialStoreError>;
    fn delete(&self, service: &str, account: &str) -> Result<bool, CredentialStoreError>;
}

#[derive(Debug, Clone, Copy)]
pub struct DefaultKeyringStore;

fn initialize_default_store() -> Result<(), String> {
    #[cfg(any(target_os = "linux", target_os = "freebsd", target_os = "openbsd"))]
    {
        let store = dbus_secret_service_keyring_store::Store::new()
            .map_err(|error| error.to_string())?;
        keyring_core::set_default_store(store);
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    {
        let store = apple_native_keyring_store::keychain::Store::new()
            .map_err(|error| error.to_string())?;
        keyring_core::set_default_store(store);
        return Ok(());
    }

    #[cfg(target_os = "windows")]
    {
        let store = windows_native_keyring_store::Store::new()
            .map_err(|error| error.to_string())?;
        keyring_core::set_default_store(store);
        return Ok(());
    }

    #[cfg(not(any(
        target_os = "linux",
        target_os = "freebsd",
        target_os = "openbsd",
        target_os = "macos",
        target_os = "windows",
    )))]
    {
        Err("no native keyring provider is configured for this target".to_string())
    }
}

fn ensure_default_store() -> Result<(), CredentialStoreError> {
    static INIT: OnceLock<Result<(), String>> = OnceLock::new();
    match INIT.get_or_init(initialize_default_store) {
        Ok(()) => Ok(()),
        Err(message) => Err(CredentialStoreError::new(KeyringError::NoStorageAccess(
            Box::new(std::io::Error::other(message.clone())),
        ))),
    }
}


impl KeyringStore for DefaultKeyringStore {
    fn load(&self, service: &str, account: &str) -> Result<Option<String>, CredentialStoreError> {
        trace!("keyring.load start, service={service}, account={account}");
        ensure_default_store()?;
        let entry = Entry::new(service, account).map_err(CredentialStoreError::new)?;
        match entry.get_password() {
            Ok(password) => {
                trace!("keyring.load success, service={service}, account={account}");
                Ok(Some(password))
            }
            Err(KeyringError::NoEntry) => {
                trace!("keyring.load no entry, service={service}, account={account}");
                Ok(None)
            }
            Err(error) => {
                trace!("keyring.load error, service={service}, account={account}, error={error}");
                Err(CredentialStoreError::new(error))
            }
        }
    }

    fn save(&self, service: &str, account: &str, value: &str) -> Result<(), CredentialStoreError> {
        trace!(
            "keyring.save start, service={service}, account={account}, value_len={}",
            value.len()
        );
        ensure_default_store()?;
        let entry = Entry::new(service, account).map_err(CredentialStoreError::new)?;
        match entry.set_password(value) {
            Ok(()) => {
                trace!("keyring.save success, service={service}, account={account}");
                Ok(())
            }
            Err(error) => {
                trace!("keyring.save error, service={service}, account={account}, error={error}");
                Err(CredentialStoreError::new(error))
            }
        }
    }

    fn delete(&self, service: &str, account: &str) -> Result<bool, CredentialStoreError> {
        trace!("keyring.delete start, service={service}, account={account}");
        ensure_default_store()?;
        let entry = Entry::new(service, account).map_err(CredentialStoreError::new)?;
        match entry.delete_credential() {
            Ok(()) => {
                trace!("keyring.delete success, service={service}, account={account}");
                Ok(true)
            }
            Err(KeyringError::NoEntry) => {
                trace!("keyring.delete no entry, service={service}, account={account}");
                Ok(false)
            }
            Err(error) => {
                trace!("keyring.delete error, service={service}, account={account}, error={error}");
                Err(CredentialStoreError::new(error))
            }
        }
    }
}

pub mod tests {
    use super::CredentialStoreError;
    use super::KeyringStore;
    use keyring_core::Error as KeyringError;
    use std::collections::HashMap;
    use std::sync::Arc;
    use std::sync::Mutex;
    use std::sync::PoisonError;

    #[derive(Debug, Default)]
    struct MockCredentialState {
        value: Option<String>,
        error: Option<KeyringError>,
    }

    #[derive(Default, Debug)]
    pub struct MockCredential {
        state: Mutex<MockCredentialState>,
    }

    impl MockCredential {
        fn get_password(&self) -> Result<String, KeyringError> {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(error) = state.error.take() {
                return Err(error);
            }
            state.value.clone().ok_or(KeyringError::NoEntry)
        }

        fn set_password(&self, value: &str) -> Result<(), KeyringError> {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(error) = state.error.take() {
                return Err(error);
            }
            state.value = Some(value.to_string());
            Ok(())
        }

        fn delete_credential(&self) -> Result<(), KeyringError> {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(error) = state.error.take() {
                return Err(error);
            }
            match state.value.take() {
                Some(_) => Ok(()),
                None => Err(KeyringError::NoEntry),
            }
        }

        fn set_error(&self, error: KeyringError) {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            state.error = Some(error);
        }
    }

    #[derive(Default, Clone, Debug)]
    pub struct MockKeyringStore {
        credentials: Arc<Mutex<HashMap<String, Arc<MockCredential>>>>,
    }

    impl MockKeyringStore {
        pub fn credential(&self, account: &str) -> Arc<MockCredential> {
            let mut guard = self
                .credentials
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            guard
                .entry(account.to_string())
                .or_insert_with(|| Arc::new(MockCredential::default()))
                .clone()
        }

        pub fn saved_value(&self, account: &str) -> Option<String> {
            let credential = {
                let guard = self
                    .credentials
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner);
                guard.get(account).cloned()
            }?;
            credential.get_password().ok()
        }

        pub fn set_error(&self, account: &str, error: KeyringError) {
            let credential = self.credential(account);
            credential.set_error(error);
        }

        pub fn contains(&self, account: &str) -> bool {
            let guard = self
                .credentials
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            guard.contains_key(account)
        }
    }

    impl KeyringStore for MockKeyringStore {
        fn load(
            &self,
            _service: &str,
            account: &str,
        ) -> Result<Option<String>, CredentialStoreError> {
            let credential = {
                let guard = self
                    .credentials
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner);
                guard.get(account).cloned()
            };

            let Some(credential) = credential else {
                return Ok(None);
            };

            match credential.get_password() {
                Ok(password) => Ok(Some(password)),
                Err(KeyringError::NoEntry) => Ok(None),
                Err(error) => Err(CredentialStoreError::new(error)),
            }
        }

        fn save(
            &self,
            _service: &str,
            account: &str,
            value: &str,
        ) -> Result<(), CredentialStoreError> {
            let credential = self.credential(account);
            credential
                .set_password(value)
                .map_err(CredentialStoreError::new)
        }

        fn delete(&self, _service: &str, account: &str) -> Result<bool, CredentialStoreError> {
            let credential = {
                let guard = self
                    .credentials
                    .lock()
                    .unwrap_or_else(PoisonError::into_inner);
                guard.get(account).cloned()
            };

            let Some(credential) = credential else {
                return Ok(false);
            };

            let removed = match credential.delete_credential() {
                Ok(()) => Ok(true),
                Err(KeyringError::NoEntry) => Ok(false),
                Err(error) => Err(CredentialStoreError::new(error)),
            }?;

            let mut guard = self
                .credentials
                .lock()
                .unwrap_or_else(PoisonError::into_inner);
            guard.remove(account);
            Ok(removed)
        }
    }
}
