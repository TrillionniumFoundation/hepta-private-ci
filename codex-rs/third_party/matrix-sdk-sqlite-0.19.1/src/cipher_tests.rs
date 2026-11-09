use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    time::Duration,
};

use base64::Engine as _;
use similar_asserts::assert_eq;
use tokio::sync::oneshot;
use zeroize::Zeroizing;

use super::{open, run};
use crate::{Base64Variant, OpenStoreError, Secret};

#[tokio::test]
async fn fresh_ciphers_reopen_without_replacing_their_export() {
    let secrets = [
        Secret::PassPhrase(Zeroizing::new("human passphrase fixture".to_owned())),
        Secret::Key(Zeroizing::new(vec![7; 32])),
        Secret::HighEntropyPassPhrase {
            key: Zeroizing::new(vec![8; 32]),
            base64_variant: Base64Variant::Padded,
        },
        Secret::HighEntropyPassPhrase {
            key: Zeroizing::new(vec![9; 32]),
            base64_variant: Base64Variant::Unpadded,
        },
    ];
    for secret in secrets {
        let (cipher, export) = open(secret.clone(), None).await.unwrap();
        assert!(export.is_some());
        let ciphertext = cipher.encrypt_value(&"original content").unwrap();
        let (restored, replacement) = open(secret, export).await.unwrap();
        assert!(replacement.is_none());
        assert_eq!(
            restored.decrypt_value::<String>(&ciphertext).unwrap(),
            "original content"
        );
    }
}

#[tokio::test]
async fn both_legacy_base64_passphrases_migrate_without_changing_cipher_keys() {
    for base64_variant in [Base64Variant::Padded, Base64Variant::Unpadded] {
        let key = vec![11; 32];
        let passphrase = match base64_variant {
            Base64Variant::Padded => base64::prelude::BASE64_STANDARD.encode(&key),
            Base64Variant::Unpadded => vodozemac::base64_encode(&key),
        };
        let (original, legacy_export) =
            open(Secret::PassPhrase(Zeroizing::new(passphrase)), None).await.unwrap();
        let ciphertext = original.encrypt_value(&"retained legacy content").unwrap();
        let secret = Secret::HighEntropyPassPhrase {
            key: Zeroizing::new(key),
            base64_variant,
        };
        let (migrated, replacement) = open(secret.clone(), legacy_export).await.unwrap();
        assert!(replacement.is_some());
        assert_eq!(
            migrated.decrypt_value::<String>(&ciphertext).unwrap(),
            "retained legacy content"
        );
        let (reopened, second_replacement) = open(secret, replacement).await.unwrap();
        assert!(second_replacement.is_none());
        assert_eq!(
            reopened.decrypt_value::<String>(&ciphertext).unwrap(),
            "retained legacy content"
        );
    }
}

#[tokio::test]
async fn cipher_errors_keep_their_original_classification() {
    let (_, export) = open(Secret::Key(Zeroizing::new(vec![17; 32])), None).await.unwrap();
    let error = open(Secret::PassPhrase(Zeroizing::new("wrong mechanism".to_owned())), export)
        .await
        .err()
        .expect("passphrase import cannot accept a key export");
    assert!(matches!(
        error,
        OpenStoreError::InitCipher(matrix_sdk_store_encryption::Error::KdfMismatch)
    ));
}

#[tokio::test]
async fn worker_panic_is_a_join_failure_not_a_cipher_error() {
    let error = run::<()>(|| panic!("cipher worker fixture")).await.unwrap_err();
    match error {
        OpenStoreError::CipherTask(error) => assert!(error.is_panic()),
        error => panic!("unexpected worker error: {error:?}"),
    }
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_owner_cannot_publish_after_blocking_work_finishes() {
    let (started, observed_start) = oneshot::channel();
    let (finished, observed_finish) = oneshot::channel();
    let (release, wait_for_release) = mpsc::sync_channel(1);
    let published = Arc::new(AtomicBool::new(false));
    let owner_publication = published.clone();
    let owner = tokio::spawn(async move {
        run(move || {
            started.send(()).unwrap();
            // This also detects accidentally running CPU work on the only
            // async thread: that regression cannot receive a release in time.
            wait_for_release.recv_timeout(Duration::from_secs(5)).unwrap();
            finished.send(()).unwrap();
            Ok(())
        })
        .await
        .unwrap();
        owner_publication.store(true, Ordering::SeqCst);
    });
    observed_start.await.unwrap();
    owner.abort();
    assert!(owner.await.unwrap_err().is_cancelled());
    release.send(()).unwrap();
    observed_finish.await.unwrap();
    assert!(!published.load(Ordering::SeqCst));
}
