use keyring_core::Error as KeyringError;
use std::sync::LazyLock;

// Keep the process-wide initialization behavior of the original keyring facade.
// Explicitly installed stores retain precedence over the platform default.
static DEFAULT_STORE_RESULT: LazyLock<Result<(), KeyringError>> = LazyLock::new(|| {
    if keyring_core::get_default_store().is_some() {
        return Ok(());
    }

    #[cfg(target_os = "macos")]
    let store = apple_native_keyring_store::keychain::Store::new()?;
    #[cfg(target_os = "windows")]
    let store = windows_native_keyring_store::Store::new()?;
    #[cfg(all(
        unix,
        not(any(target_os = "macos", target_os = "ios", target_os = "android"))
    ))]
    let store = dbus_secret_service_keyring_store::Store::new()?;

    #[cfg(all(any(unix, windows), not(any(target_os = "ios", target_os = "android"))))]
    {
        keyring_core::set_default_store(store);
        Ok(())
    }
    #[cfg(not(all(any(unix, windows), not(any(target_os = "ios", target_os = "android")))))]
    Err(KeyringError::Invalid(
        "platform".to_string(),
        "must be macOS, Windows, or a non-iOS, non-Android Unix variant".to_string(),
    ))
});

pub(crate) fn ensure_default_store() -> Result<(), KeyringError> {
    if keyring_core::get_default_store().is_some() {
        return Ok(());
    }
    DEFAULT_STORE_RESULT
        .as_ref()
        .map(|_| ())
        .map_err(|error| KeyringError::Invalid("default_store".to_string(), error.to_string()))
}
