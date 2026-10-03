//! Tab-scoped login metadata with encrypted Matrix SDK IndexedDB state.
//! Reload retains this tab's session. Closing it normally clears credentials;
//! browser session restoration policies may retain sessionStorage. This is not
//! a credential vault and does not protect against same-origin script compromise.
//! The IndexedDB passphrase is accessible to same-origin scripts too; encryption
//! is not an XSS defense. No secrets are exported or logged by this adapter.
//! We do not prune IndexedDB stores on startup: another tab may still own them.
//! Orphan ciphertext requires explicit browser site-data cleanup, not guesses.
use super::{ClientSessionPersisted, FullSessionPersisted};
use super::browser_storage::{self as storage, StorageKind::Session};
use anyhow::{anyhow, bail};
use matrix_sdk::{
    Client,
    ruma::OwnedUserId,
};

const CURRENT_SESSION: &str = "matrix-session";

fn load() -> anyhow::Result<Option<FullSessionPersisted>> {
    storage::read(Session, CURRENT_SESSION)?
        .map(|json| serde_json::from_str(&json).map_err(Into::into))
        .transpose()
}

pub async fn most_recent_user_id() -> Option<OwnedUserId> {
    match load() {
        Ok(session) => session.map(|session| session.user_session.meta.user_id),
        Err(_) => {
            // Malformed metadata must not retain credentials for later retries.
            // Access denial may prevent removal; never fall back to another store.
            let _ = storage::remove(Session, CURRENT_SESSION);
            None
        }
    }
}

pub async fn cleanup_orphan_db_dirs() {
    // No filesystem and no authority to delete another tab's encrypted store.
}

pub async fn restore_session(
    user_id: Option<OwnedUserId>,
) -> anyhow::Result<(Client, Option<String>)> {
    let epoch = crate::sliding_sync::runtime::origin_epoch();
    let result = restore_saved_session(user_id).await;
    if result.is_err() && epoch == crate::sliding_sync::runtime::current_epoch() {
        // A failed restore must not leave tokens available for an accidental retry.
        storage::remove(Session, CURRENT_SESSION)?;
    }
    result
}

async fn restore_saved_session(user_id: Option<OwnedUserId>) -> anyhow::Result<(Client, Option<String>)> {
    ensure_current_authority()?;
    let session = load()?.ok_or_else(|| anyhow!("No login session in this browser tab"))?;
    if user_id
        .as_deref()
        .is_some_and(|expected| expected.as_str() != session.user_session.meta.user_id.as_str())
    {
        bail!("Saved browser session belongs to a different account");
    }
    let client = crate::sliding_sync::base_client_builder(
        &session.client_session.db_path,
        &session.client_session.passphrase,
    )
    .homeserver_url(session.client_session.homeserver)
    .build()
    .await.map_err(|error| anyhow!(error.to_string()))?;
    ensure_current_authority()?;
    client.set_sliding_sync_version(session.sliding_sync_version.into());
    client.restore_session(session.user_session).await.map_err(|error| anyhow!(error.to_string()))?;
    ensure_current_authority()?;
    Ok((client, session.sync_token))
}

pub async fn save_session(
    client: &Client,
    client_session: ClientSessionPersisted,
) -> anyhow::Result<()> {
    ensure_current_authority()?;
    let user_session = client
        .matrix_auth()
        .session()
        .ok_or_else(|| anyhow!("No authenticated Matrix session to persist"))?;
    let session = FullSessionPersisted {
        client_session,
        user_session,
        sync_token: None,
        sliding_sync_version: client.sliding_sync_version().into(),
    };
    let serialized = serde_json::to_string(&session)?;
    // Clear the old account even if storing the new login fails.
    ensure_current_authority()?;
    storage::remove(Session, CURRENT_SESSION)?;
    storage::write(Session, CURRENT_SESSION, &serialized)
}

pub async fn delete_latest_user_id() -> anyhow::Result<bool> {
    // Remove the tokens too, so reload cannot restore a logged-out account.
    storage::remove(Session, CURRENT_SESSION)
}

#[cfg(test)]
mod tests {
    use super::*;
    use wasm_bindgen_test::wasm_bindgen_test;

    #[wasm_bindgen_test]
    async fn malformed_restore_clears_metadata_without_contacting_a_server() {
        // Run only in the isolated browser test origin, with synthetic metadata.
        storage::write(Session, CURRENT_SESSION, "invalid-synthetic-json").unwrap();
        assert!(restore_session(None).await.is_err());
        assert_eq!(storage::read(Session, CURRENT_SESSION).unwrap(), None);
    }

    #[wasm_bindgen_test]
    async fn stale_restore_cannot_remove_newer_account_metadata() {
        let previous = crate::ui_dispatch::current_epoch();
        crate::ui_dispatch::advance_epoch();
        storage::write(Session, CURRENT_SESSION, "newer-synthetic-session").unwrap();
        let result = crate::ui_dispatch::scope_epoch(previous, restore_session(None)).await;
        assert!(result.is_err());
        assert_eq!(storage::read(Session, CURRENT_SESSION).unwrap().as_deref(), Some("newer-synthetic-session"));
        storage::remove(Session, CURRENT_SESSION).unwrap();
    }

    #[wasm_bindgen_test]
    async fn logout_removes_the_entire_session_record() {
        storage::write(Session, CURRENT_SESSION, "synthetic-test-record").unwrap();
        assert!(delete_latest_user_id().await.unwrap());
        assert_eq!(storage::read(Session, CURRENT_SESSION).unwrap(), None);
    }
}

fn ensure_current_authority() -> anyhow::Result<()> {
    if crate::sliding_sync::runtime::origin_epoch() != crate::sliding_sync::runtime::current_epoch() {
        bail!("Browser account operation was cancelled before persistence");
    }
    Ok(())
}
