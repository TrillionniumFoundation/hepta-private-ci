use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use super::*;
use crate::native_memory_test_support::execution;
use crate::native_memory_test_support::fixture;

#[tokio::test]
async fn native_memory_rejects_receipt_substitution() {
    let f = fixture().await;
    let e = execution(&f);
    verify_execution(&f.config, &f.admission, &e.request_sha256, &e).unwrap();
    let mutations: Vec<fn(&mut NativeMemoryExecutionV1)> = vec![
        |e| e.query_digest = Digest32::of_bytes(b"other key").to_string(),
        |e| e.source_binding_digest = Digest32::of_bytes(b"old source").to_string(),
        |e| e.request_sha256 = Digest32::of_bytes(b"replayed request").to_string(),
        |e| e.prompt.push_str(" invented answer"),
        |e| e.question.push_str(" injected question"),
        |e| e.pins.adapter_sha256 = Digest32::of_bytes(b"other adapter").to_string(),
        |e| e.pins.runtime_digest = Digest32::of_bytes(b"other worker").to_string(),
        |e| e.generated_token_ids = vec![1; 17],
        |e| e.facts_received = true,
        |e| e.adapter_enabled = false,
        |e| e.base_unchanged = false,
    ];
    for mutate in mutations {
        let mut changed = e.clone();
        mutate(&mut changed);
        assert!(verify_execution(&f.config, &f.admission, &e.request_sha256, &changed).is_err());
    }
}

#[tokio::test]
async fn native_memory_wrong_neuron_features_never_dispatch() {
    let f = fixture().await;
    let count = Arc::new(AtomicU64::new(0));
    let mut port = NativeMemoryModelPort::new(
        f.writer,
        f.admission,
        f.config,
        tokio::runtime::Handle::current(),
        Arc::clone(&count),
        tokio_util::sync::CancellationToken::new(),
    )
    .unwrap();
    let mut request = port.request();
    request.feature_vector_q24[0] += 1;
    assert!(matches!(
        port.execute(&request),
        Err(NeuronModelError::Rejected)
    ));
    assert!(count.load(Ordering::SeqCst) == 0);
    drop(f.temp);
}

#[tokio::test]
async fn native_memory_revoked_source_authority_never_dispatches_model() {
    let f = fixture().await;
    let count = Arc::new(AtomicU64::new(0));
    let mut port = NativeMemoryModelPort::new(
        f.writer,
        f.admission,
        f.config,
        tokio::runtime::Handle::current(),
        Arc::clone(&count),
        tokio_util::sync::CancellationToken::new(),
    )
    .unwrap();
    f.verifier.0.store(true, Ordering::SeqCst);
    let request = port.request();
    let result = tokio::task::spawn_blocking(move || port.execute(&request))
        .await
        .unwrap();
    assert!(matches!(result, Err(NeuronModelError::Rejected)));
    assert!(count.load(Ordering::SeqCst) == 0);
    drop(f.temp);
}
