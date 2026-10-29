//! Blocking store work retains its transaction owner across asynchronous cancellation.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::mpsc;
use std::thread::ThreadId;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use codex_config::types::AuthKeyringBackendKind;
use codex_keyring_store::CredentialStoreError;
use codex_keyring_store::KeyringStore;
use oauth2::AccessToken;
use oauth2::TokenResponse;
use pretty_assertions::assert_eq;
use rmcp::transport::auth::InMemoryCredentialStore;
use tokio::sync::oneshot;
use tokio::time::timeout;
use wiremock::Mock;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

use super::MockKeyringStore;
use super::authorization_manager_for;
use super::test_context;
use crate::oauth::KEYRING_SERVICE;
use crate::oauth::OAuthPersistor;
use crate::oauth::ResolvedOAuthCredentialStore;
use crate::oauth::StoredOAuthTokens;
use crate::oauth::WrappedOAuthTokenResponse;
use crate::oauth::compute_store_key;
use crate::oauth::install_tokens_in_manager;
use crate::oauth::normalized_oauth_credentials;

const WAIT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StoreOperation {
    Load,
    Save,
    Delete,
}

#[derive(Debug)]
struct StoreGate {
    operation: StoreOperation,
    entered: oneshot::Sender<()>,
    release: mpsc::Receiver<()>,
}

#[derive(Clone, Debug)]
struct BlockingStore {
    inner: MockKeyringStore,
    runtime_thread: ThreadId,
    gate: Arc<Mutex<Option<StoreGate>>>,
    calls: Arc<Mutex<Vec<StoreOperation>>>,
}

impl BlockingStore {
    fn gated(
        initial: &StoredOAuthTokens,
        operation: StoreOperation,
    ) -> Result<(Self, oneshot::Receiver<()>, mpsc::Sender<()>)> {
        let inner = MockKeyringStore::default();
        let key = compute_store_key(&initial.server_name, &initial.url)?;
        inner.save(KEYRING_SERVICE, &key, &serde_json::to_string(initial)?)?;
        let (entered, receiver) = oneshot::channel();
        let (release, waiting) = mpsc::channel();
        Ok((
            Self {
                inner,
                runtime_thread: std::thread::current().id(),
                gate: Arc::new(Mutex::new(Some(StoreGate {
                    operation,
                    entered,
                    release: waiting,
                }))),
                calls: Arc::new(Mutex::new(Vec::new())),
            },
            receiver,
            release,
        ))
    }

    fn enter(&self, operation: StoreOperation) {
        assert_ne!(
            std::thread::current().id(),
            self.runtime_thread,
            "credential I/O must leave the current-thread executor"
        );
        self.calls.lock().expect("calls lock").push(operation);
        let gate = {
            let mut guard = self.gate.lock().expect("store gate lock");
            if guard
                .as_ref()
                .is_some_and(|gate| gate.operation == operation)
            {
                guard.take()
            } else {
                None
            }
        };
        if let Some(gate) = gate {
            gate.entered.send(()).expect("signal blocking store entry");
            gate.release
                .recv_timeout(WAIT)
                .expect("release blocking store operation");
        }
    }

    fn stored(&self, initial: &StoredOAuthTokens) -> Result<Option<StoredOAuthTokens>> {
        let key = compute_store_key(&initial.server_name, &initial.url)?;
        self.inner
            .saved_value(&key)
            .map(|value| serde_json::from_str(&value).context("decode committed credentials"))
            .transpose()
    }
}

impl KeyringStore for BlockingStore {
    fn load(&self, service: &str, account: &str) -> Result<Option<String>, CredentialStoreError> {
        self.enter(StoreOperation::Load);
        self.inner.load(service, account)
    }

    fn save(&self, service: &str, account: &str, value: &str) -> Result<(), CredentialStoreError> {
        self.enter(StoreOperation::Save);
        self.inner.save(service, account, value)
    }

    fn delete(&self, service: &str, account: &str) -> Result<bool, CredentialStoreError> {
        self.enter(StoreOperation::Delete);
        self.inner.delete(service, account)
    }
}

async fn persistor_for_keyring(initial: &StoredOAuthTokens) -> Result<OAuthPersistor> {
    Ok(OAuthPersistor::new(
        initial.server_name.clone(),
        initial.url.clone(),
        authorization_manager_for(initial).await?,
        ResolvedOAuthCredentialStore::Keyring(AuthKeyringBackendKind::Direct),
        Some(initial.clone()),
    ))
}

fn start_legacy_persistence(
    persistor: OAuthPersistor,
    store: BlockingStore,
) -> (tokio::task::JoinHandle<Result<()>>, oneshot::Receiver<()>) {
    let (started, receiver) = oneshot::channel();
    let task = tokio::spawn(async move {
        started.send(()).expect("signal legacy hook first poll");
        persistor.persist_if_needed_in(&store).await
    });
    (task, receiver)
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "the test compares the manager snapshot while holding its normal async guard"
)]
async fn assert_committed(
    persistor: &OAuthPersistor,
    store: &BlockingStore,
    initial: &StoredOAuthTokens,
    access_token: &str,
) -> Result<()> {
    let guard = timeout(WAIT, persistor.inner.authorization_manager.lock()).await?;
    let (client_id, response) = guard.get_credentials().await?;
    let stored = store.stored(initial)?.expect("committed credential");
    let mut response = response.expect("manager credential");
    let mut stored_response = stored.token_response.0.clone();
    response.set_expires_in(None);
    stored_response.set_expires_in(None);
    assert_eq!(
        (client_id, WrappedOAuthTokenResponse(response)),
        (
            stored.client_id.clone(),
            WrappedOAuthTokenResponse(stored_response)
        )
    );
    assert_eq!(
        persistor.stored_credentials().await,
        normalized_oauth_credentials(Some(&stored))
    );
    assert_eq!(
        stored.token_response.0.access_token().secret(),
        access_token
    );
    Ok(())
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "test setup installs manager credentials under its normal async guard"
)]
#[tokio::test(flavor = "current_thread")]
async fn cancelled_save_and_delete_keep_manager_fenced_until_store_commit() -> Result<()> {
    for operation in [StoreOperation::Save, StoreOperation::Delete] {
        let (_env, _server, initial) = test_context().await?;
        let persistor = persistor_for_keyring(&initial).await?;
        let (store, entered, release) = BlockingStore::gated(&initial, operation)?;
        {
            let mut manager = persistor.inner.authorization_manager.lock().await;
            match operation {
                StoreOperation::Save => {
                    let mut updated = initial.clone();
                    updated.token_response.0.set_access_token(AccessToken::new(
                        "legacy-updated-access-token".to_string(),
                    ));
                    install_tokens_in_manager(&mut manager, &updated).await?;
                }
                StoreOperation::Delete => {
                    manager.set_credential_store(InMemoryCredentialStore::new());
                }
                StoreOperation::Load => unreachable!("this test exercises mutations"),
            }
        }
        let (caller, started) = start_legacy_persistence(persistor.clone(), store.clone());
        timeout(WAIT, started).await??;
        timeout(WAIT, entered).await??;
        caller.abort();
        assert!(caller.await.expect_err("caller cancelled").is_cancelled());
        assert!(persistor.inner.authorization_manager.try_lock().is_err());
        assert!(persistor.inner.last_credentials.try_lock().is_err());
        release.send(())?;
        match operation {
            StoreOperation::Save => {
                assert_committed(&persistor, &store, &initial, "legacy-updated-access-token")
                    .await?;
            }
            StoreOperation::Delete => {
                let _manager = timeout(WAIT, persistor.inner.authorization_manager.lock()).await?;
                assert_eq!(store.stored(&initial)?, None);
                assert_eq!(persistor.stored_credentials().await, None);
            }
            StoreOperation::Load => unreachable!("this test exercises mutations"),
        }
        assert_eq!(*store.calls.lock().expect("calls lock"), vec![operation]);
    }
    Ok(())
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "a held manager guard deterministically pauses the legacy transaction before admission"
)]
#[tokio::test(flavor = "current_thread")]
async fn cancelled_legacy_caller_waiting_for_manager_still_commits() -> Result<()> {
    let (_env, _server, initial) = test_context().await?;
    let persistor = persistor_for_keyring(&initial).await?;
    let (store, entered, release) = BlockingStore::gated(&initial, StoreOperation::Save)?;
    let mut manager = persistor.inner.authorization_manager.lock().await;
    let mut updated = initial.clone();
    updated
        .token_response
        .0
        .set_access_token(AccessToken::new("queued-legacy-access-token".to_string()));
    install_tokens_in_manager(&mut manager, &updated).await?;
    let (caller, started) = start_legacy_persistence(persistor.clone(), store.clone());
    timeout(WAIT, started).await??;
    caller.abort();
    assert!(caller.await.expect_err("caller cancelled").is_cancelled());
    drop(manager);
    timeout(WAIT, entered).await??;
    assert!(persistor.inner.authorization_manager.try_lock().is_err());
    release.send(())?;
    assert_committed(&persistor, &store, &initial, "queued-legacy-access-token").await
}

#[tokio::test(flavor = "current_thread")]
async fn authoritative_load_fences_legacy_snapshot_until_fresh_credential_is_installed()
-> Result<()> {
    let (_env, server, initial) = test_context().await?;
    Mock::given(method("POST"))
        .and(path("/oauth/token"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&server)
        .await;
    let mut fresh = initial.clone();
    fresh.expires_at = Some(u64::MAX);
    fresh
        .token_response
        .0
        .set_access_token(AccessToken::new("another-process-access-token".to_string()));
    let (store, entered, release) = BlockingStore::gated(&fresh, StoreOperation::Load)?;
    let persistor = persistor_for_keyring(&initial).await?;
    let refresh = tokio::spawn({
        let persistor = persistor.clone();
        let store = store.clone();
        async move { persistor.refresh_if_needed_in(&store, WAIT).await }
    });
    timeout(WAIT, entered).await??;
    assert!(persistor.inner.authorization_manager.try_lock().is_err());
    let (legacy, started) = start_legacy_persistence(persistor.clone(), store.clone());
    timeout(WAIT, started).await??;
    assert!(!legacy.is_finished());
    release.send(())?;
    timeout(WAIT, refresh).await???;
    timeout(WAIT, legacy).await???;
    assert_committed(&persistor, &store, &initial, "another-process-access-token").await?;
    assert_eq!(
        *store.calls.lock().expect("calls lock"),
        vec![StoreOperation::Load]
    );
    server.verify().await;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn failed_blocking_refresh_save_restores_the_previous_manager_credential() -> Result<()> {
    let (_env, server, initial) = test_context().await?;
    Mock::given(method("POST"))
        .and(path("/oauth/token"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "access_token": "not-committed-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        })))
        .expect(1)
        .mount(&server)
        .await;
    let persistor = persistor_for_keyring(&initial).await?;
    let (store, entered, release) = BlockingStore::gated(&initial, StoreOperation::Save)?;
    let refresh = tokio::spawn({
        let persistor = persistor.clone();
        let store = store.clone();
        async move { persistor.refresh_if_needed_in(&store, WAIT).await }
    });
    timeout(WAIT, entered).await??;
    let key = compute_store_key(&initial.server_name, &initial.url)?;
    store.inner.set_error(
        &key,
        keyring::Error::Invalid("save".into(), "injected".into()),
    );
    release.send(())?;
    timeout(WAIT, refresh)
        .await??
        .expect_err("store failure must be surfaced");
    assert_committed(
        &persistor,
        &store,
        &initial,
        initial.token_response.0.access_token().secret(),
    )
    .await?;
    server.verify().await;
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn failed_blocking_delete_preserves_the_cache_for_a_real_retry() -> Result<()> {
    let (_env, _server, initial) = test_context().await?;
    let persistor = persistor_for_keyring(&initial).await?;
    persistor
        .inner
        .authorization_manager
        .lock()
        .await
        .set_credential_store(InMemoryCredentialStore::new());
    let (store, entered, release) = BlockingStore::gated(&initial, StoreOperation::Delete)?;
    let (caller, started) = start_legacy_persistence(persistor.clone(), store.clone());
    timeout(WAIT, started).await??;
    timeout(WAIT, entered).await??;
    let key = compute_store_key(&initial.server_name, &initial.url)?;
    store.inner.set_error(
        &key,
        keyring::Error::Invalid("delete".into(), "injected".into()),
    );
    release.send(())?;
    timeout(WAIT, caller)
        .await??
        .expect_err("deletion failure must be surfaced");
    assert_eq!(store.stored(&initial)?, Some(initial.clone()));
    assert_eq!(
        persistor.stored_credentials().await,
        normalized_oauth_credentials(Some(&initial))
    );
    timeout(WAIT, persistor.persist_if_needed_in(&store)).await??;
    assert_eq!(store.stored(&initial)?, None);
    assert_eq!(persistor.stored_credentials().await, None);
    assert_eq!(
        *store.calls.lock().expect("calls lock"),
        vec![StoreOperation::Delete, StoreOperation::Delete]
    );
    Ok(())
}
