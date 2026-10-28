use std::net::TcpListener;
use std::net::TcpStream;
use std::sync::Arc;
use std::sync::mpsc;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::ProviderEffectAdapter;
use codex_hepta_contracts::ProviderEffectDispatch;
use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::ProviderEffectLookup;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::image;
use super::intent;
use super::super::MemoryCellMigrationProviderV9;
use super::super::MemoryCellMigrationReceiverV9;
use super::super::MemoryCellMigrationStoreV9;

fn accept(listener: &TcpListener) -> TcpStream {
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match listener.accept() {
            Ok((stream, _)) => return stream,
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock && Instant::now() < deadline => {
                std::thread::sleep(Duration::from_millis(2));
            }
            Err(error) => panic!("concurrent receiver accept: {error}"),
        }
    }
}

#[tokio::test]
async fn migration_v9_same_instance_serializes_duplicate_and_conflicting_publications() {
    for second_key in ["transfer", "contender"] {
        let directory = tempfile::tempdir().expect("concurrent receiver root");
        let root = directory.path().canonicalize().expect("canonical root");
        let image = image(&root, 1, None);
        let first_intent = intent(&image, "transfer");
        let second_intent = ProviderEffectIntent::new(ProviderEffectKey::for_logical_effect("memory:node-b", second_key).expect("key"), image.digest());
        let source = SigningKey::from_bytes(&[73; 32]);
        let target = SigningKey::from_bytes(&[79; 32]);
        let store = MemoryCellMigrationStoreV9::open(root.join("receiver"), image.manifest().clone()).expect("store");
        let receiver = Arc::new(MemoryCellMigrationReceiverV9::new(store, "memory:node-b".into(), source.verifying_key(), target.clone()).expect("receiver"));
        let listener = TcpListener::bind("127.0.0.1:0").expect("real concurrent TCP listener");
        listener.set_nonblocking(true).expect("bounded accepts");
        let adapter = MemoryCellMigrationProviderV9::new(listener.local_addr().expect("address"), "memory:node-b".into(), source, target.verifying_key()).expect("provider");
        let (prepared_tx, prepared_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        let (accepted_tx, accepted_rx) = mpsc::channel();
        let shared = Arc::clone(&receiver);
        let server = std::thread::spawn(move || {
            let stream = accept(&listener);
            let first_receiver = Arc::clone(&shared);
            let first_server = std::thread::spawn(move || first_receiver.serve_observed(stream, &mut |stage| {
                if stage == "prepared" {
                    prepared_tx.send(()).expect("prepared notification");
                    release_rx.recv_timeout(Duration::from_secs(5)).expect("release prepared first publication");
                }
            }).expect("first response"));
            let stream = accept(&listener);
            accepted_tx.send(()).expect("second connection accepted while first remains prepared");
            shared.serve_stream(stream).expect("second response");
            first_server.join().expect("first receiver joined");
        });
        let first_adapter = adapter.clone();
        let first_body = image.bytes().to_vec();
        let first_request = first_intent.clone();
        let first = tokio::spawn(async move { first_adapter.dispatch_with_payload(&first_request, &first_body).await });
        tokio::task::spawn_blocking(move || prepared_rx.recv_timeout(Duration::from_secs(5)).expect("first durable prepare")).await.expect("prepared waiter");
        let second_body = image.bytes().to_vec();
        let second_request = second_intent.clone();
        let mut second = tokio::spawn(async move { adapter.dispatch_with_payload(&second_request, &second_body).await });
        tokio::task::spawn_blocking(move || accepted_rx.recv_timeout(Duration::from_secs(5)).expect("second actual connection")).await.expect("second waiter");
        assert!(tokio::time::timeout(Duration::from_millis(100), &mut second).await.is_err(),
            "a shared receiver cannot publish over another call's prepared transaction");
        release_tx.send(()).expect("first commit may finish");
        let ProviderEffectDispatch::Ack(first_ack) = first.await.expect("first provider task") else { panic!("first completed") };
        let second_outcome = second.await.expect("second provider task");
        server.join().expect("receiver joined");
        drop(receiver);
        let store = MemoryCellMigrationStoreV9::open(root.join("receiver"), image.manifest().clone()).expect("unchanged complete current image");
        assert_eq!(store.lookup(&first_intent).expect("original status"), ProviderEffectLookup::Ack(first_ack.clone()));
        if second_key == "transfer" {
            assert_eq!(second_outcome, ProviderEffectDispatch::Ack(first_ack.clone()));
            assert_eq!(store.lookup(&second_intent).expect("duplicate status"), ProviderEffectLookup::Ack(first_ack));
        } else {
            assert_eq!(second_outcome, ProviderEffectDispatch::Unknown);
            assert_eq!(store.lookup(&second_intent).expect("contender absence"), ProviderEffectLookup::NotFound);
        }
        assert_eq!(std::fs::read_dir(root.join("receiver/transactions")).expect("transactions").count(), 1);
    }
}
