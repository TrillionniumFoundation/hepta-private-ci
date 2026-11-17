use std::{sync::mpsc, thread};

use tokio::sync::oneshot;

use super::run_cipher_work;
use crate::OpenStoreError;

#[tokio::test(flavor = "current_thread")]
async fn cipher_work_yields_to_the_async_owner() {
    let async_thread = thread::current().id();
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let owner = tokio::spawn(async move {
        run_cipher_work(move || {
            assert_ne!(thread::current().id(), async_thread);
            entered_tx.send(()).expect("async owner still waiting");
            release_rx.recv().expect("async owner releases the worker");
            Ok(())
        })
        .await
    });

    entered_rx.await.expect("blocking worker entered");
    // The current-thread runtime must run this continuation while the worker waits.
    release_tx.send(()).expect("worker still waiting");
    owner.await.expect("async owner did not panic").expect("cipher work succeeded");
}

#[tokio::test(flavor = "current_thread")]
async fn cancelling_the_owner_does_not_run_its_write_continuation() {
    let async_thread = thread::current().id();
    let (entered_tx, entered_rx) = oneshot::channel();
    let (release_tx, release_rx) = mpsc::channel();
    let (finished_tx, finished_rx) = oneshot::channel();
    let (write_tx, write_rx) = oneshot::channel();
    let owner = tokio::spawn(async move {
        run_cipher_work(move || {
            assert_ne!(thread::current().id(), async_thread);
            entered_tx.send(()).expect("async owner still waiting");
            release_rx.recv().expect("test releases the detached worker");
            finished_tx.send(()).expect("test waits for worker completion");
            Ok(())
        })
        .await
        .expect("cipher work succeeded");
        // This stands for the async-only write after the worker result is joined.
        write_tx.send(()).expect("test observes the write continuation");
    });

    entered_rx.await.expect("blocking worker entered");
    owner.abort();
    assert!(owner.await.expect_err("async owner was cancelled").is_cancelled());
    release_tx.send(()).expect("started blocking work is not cancelled");
    finished_rx.await.expect("detached worker completed");
    assert!(write_rx.await.is_err(), "cancelled owner must not reach the write continuation");
}

#[tokio::test(flavor = "current_thread")]
async fn cipher_worker_panics_are_open_store_errors() {
    let result = run_cipher_work(|| -> Result<(), OpenStoreError> {
        panic!("controlled cipher worker panic");
    })
    .await;

    assert!(matches!(result, Err(OpenStoreError::CipherTask(error)) if error.is_panic()));
}

#[tokio::test(flavor = "current_thread")]
async fn cipher_errors_keep_their_original_variant() {
    let result = run_cipher_work(|| {
        Err::<(), _>(OpenStoreError::InitCipher(matrix_sdk_store_encryption::Error::KdfMismatch))
    })
    .await;

    assert!(matches!(
        result,
        Err(OpenStoreError::InitCipher(matrix_sdk_store_encryption::Error::KdfMismatch))
    ));
}
