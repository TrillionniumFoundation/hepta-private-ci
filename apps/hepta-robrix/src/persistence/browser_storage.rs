//! Browser storage boundary. Secrets are tab-scoped, never localStorage.
//! Storage failure is an error: never silently replace a saved account.
use anyhow::{anyhow, Result};

pub(crate) enum StorageKind {
    Session,
    Layout,
}

fn storage(kind: StorageKind) -> Result<web_sys::Storage> {
    let window = web_sys::window().ok_or_else(|| anyhow!("Browser window unavailable"))?;
    let store = match kind {
        StorageKind::Session => window.session_storage(),
        StorageKind::Layout => window.local_storage(),
    }
    .map_err(|_| anyhow!("Browser storage access denied"))?;
    store.ok_or_else(|| anyhow!("Browser storage unavailable"))
}

pub(crate) fn read(kind: StorageKind, key: &str) -> Result<Option<String>> {
    storage(kind)?
        .get_item(&format!("hepta-robrix/v1/{key}"))
        .map_err(|_| anyhow!("Failed to read browser storage"))
}
pub(crate) fn write(kind: StorageKind, key: &str, value: &str) -> Result<()> {
    storage(kind)?
        .set_item(&format!("hepta-robrix/v1/{key}"), value)
        .map_err(|_| anyhow!("Failed to write browser storage (quota or access denied)"))
}
pub(crate) fn remove(kind: StorageKind, key: &str) -> Result<bool> {
    let store = storage(kind)?;
    let key = format!("hepta-robrix/v1/{key}");
    let present = store
        .get_item(&key)
        .map_err(|_| anyhow!("Failed to read browser storage"))?
        .is_some();
    store
        .remove_item(&key)
        .map_err(|_| anyhow!("Failed to remove browser storage"))?;
    Ok(present)
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_bindgen_test::wasm_bindgen_test;
    wasm_bindgen_test::wasm_bindgen_test_configure!(run_in_browser);

    #[wasm_bindgen_test]
    fn session_roundtrip_is_isolated_from_layout_storage_and_cleared() {
        // Synthetic values only; this does not access an actual Matrix account.
        let key = "tests/session-roundtrip";
        write(StorageKind::Session, key, "synthetic-session").unwrap();
        assert_eq!(read(StorageKind::Session, key).unwrap().as_deref(), Some("synthetic-session"));
        assert_eq!(read(StorageKind::Layout, key).unwrap(), None);
        assert!(remove(StorageKind::Session, key).unwrap());
        assert_eq!(read(StorageKind::Session, key).unwrap(), None);
        assert!(!remove(StorageKind::Session, key).unwrap());
    }
}
