use std::future::Future;
use std::future::pending;
use std::future::poll_fn;
use std::pin::Pin;
use std::task::Poll;

use tokio::sync::oneshot;

use super::OpenPhase;
use super::SqliteStoreOpenDiagnostics;
use super::StoreRole;
use super::capture_open_trace;
use super::observe_store_open;
use super::record_open_phase;
use crate::OpenStoreError;
use crate::store_cipher::run_cipher_work;

#[tokio::test(flavor = "current_thread")]
async fn interleaved_roles_nested_scopes_and_calls_are_isolated() {
    let diagnostics = SqliteStoreOpenDiagnostics::default();
    let separate = SqliteStoreOpenDiagnostics::default();
    let (state_entered, wait_for_state) = oneshot::channel();
    let (crypto_entered, wait_for_crypto) = oneshot::channel();
    let shared = diagnostics.clone();
    let state: Pin<Box<dyn Future<Output = ()> + Send + '_>> =
        Box::pin(observe_store_open(Some(&shared), StoreRole::State, async {
            record_open_phase(OpenPhase::PathPrepare);
            state_entered.send(()).expect("state entered");
            wait_for_crypto.await.expect("crypto entered");
            record_open_phase(OpenPhase::Complete);
        }));
    let crypto = observe_store_open(Some(&diagnostics), StoreRole::Crypto, async {
        wait_for_state.await.expect("state entered");
        record_open_phase(OpenPhase::CipherWait);
        observe_store_open(Some(&separate), StoreRole::Media, async {
            record_open_phase(OpenPhase::MetadataRead);
        })
        .await;
        observe_store_open(/*diagnostics*/ None, StoreRole::Media, async {
            assert!(capture_open_trace().is_none());
            record_open_phase(OpenPhase::Migrations);
        })
        .await;
        assert_eq!(
            diagnostics.snapshot(),
            (
                ["path_prepare", "cipher_wait", "unobserved", "unobserved"],
                ["unobserved"; 4],
            )
        );
        record_open_phase(OpenPhase::Checkpoint);
        crypto_entered.send(()).expect("crypto entered");
    });
    tokio::join!(state, crypto);
    assert!(capture_open_trace().is_none());
    record_open_phase(OpenPhase::Migrations);
    assert_eq!(
        diagnostics.snapshot(),
        (["complete", "checkpoint", "unobserved", "unobserved"], ["unobserved"; 4])
    );
    assert_eq!(
        separate.snapshot(),
        (["unobserved", "unobserved", "unobserved", "metadata_read"], ["unobserved"; 4])
    );
}

#[tokio::test(flavor = "current_thread")]
async fn dropping_a_pending_scope_restores_context_and_scopes_its_destructor() {
    struct RecordOnDrop;
    impl Drop for RecordOnDrop {
        fn drop(&mut self) {
            record_open_phase(OpenPhase::Complete);
        }
    }

    let diagnostics = SqliteStoreOpenDiagnostics::default();
    let mut work = Box::pin(observe_store_open(Some(&diagnostics), StoreRole::State, async {
        let _record_on_drop = RecordOnDrop;
        record_open_phase(OpenPhase::CipherWait);
        pending::<()>().await;
    }));
    poll_fn(|context| {
        assert!(work.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    assert!(capture_open_trace().is_none());
    assert_eq!(
        diagnostics.snapshot(),
        (["cipher_wait", "unobserved", "unobserved", "unobserved"], ["unobserved"; 4])
    );
    drop(work);
    assert!(capture_open_trace().is_none());
    assert_eq!(
        diagnostics.snapshot(),
        (["complete", "unobserved", "unobserved", "unobserved"], ["unobserved"; 4])
    );
}

#[tokio::test(flavor = "current_thread")]
async fn worker_observation_preserves_returned_error_and_panic() {
    let returned = SqliteStoreOpenDiagnostics::default();
    let result = observe_store_open(
        Some(&returned),
        StoreRole::Crypto,
        run_cipher_work::<(), _>(|| {
            Err(OpenStoreError::InitCipher(matrix_sdk_store_encryption::Error::KdfMismatch))
        }),
    )
    .await;
    assert!(matches!(
        result,
        Err(OpenStoreError::InitCipher(matrix_sdk_store_encryption::Error::KdfMismatch))
    ));
    assert_eq!(
        returned.snapshot(),
        (["unobserved"; 4], ["unobserved", "returned", "unobserved", "unobserved"])
    );

    let panicked = SqliteStoreOpenDiagnostics::default();
    let result = observe_store_open(
        Some(&panicked),
        StoreRole::EventCache,
        run_cipher_work::<(), _>(|| panic!("controlled observed cipher panic")),
    )
    .await;
    assert!(matches!(result, Err(OpenStoreError::CipherTask(error)) if error.is_panic()));
    assert_eq!(
        panicked.snapshot(),
        (["unobserved"; 4], ["unobserved", "unobserved", "started", "unobserved"])
    );
}
