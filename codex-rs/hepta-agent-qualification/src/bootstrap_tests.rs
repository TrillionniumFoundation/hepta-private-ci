#![allow(
    clippy::expect_used,
    reason = "private bootstrap timing fixtures fail loudly"
)]

use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use std::future;
use std::sync::Arc;

fn evidence() -> (tempfile::TempDir, Arc<Evidence>) {
    let temp = tempfile::tempdir().expect("private fixture parent");
    let evidence =
        Evidence::create(&temp.path().join("fresh-bootstrap")).expect("new private evidence");
    (temp, evidence)
}

fn ids() -> (StableId, StableId) {
    (
        StableId::new("bootstrap-fixture-run").expect("run"),
        StableId::new("bootstrap-fixture-turn").expect("turn"),
    )
}

#[tokio::test]
async fn ready_owner_is_returned_only_with_its_private_startup_receipt() {
    let (_temp, evidence) = evidence();
    let (run, turn) = ids();
    let ready = observe(
        &evidence,
        &run,
        &turn,
        Duration::from_secs(1),
        future::ready(Ok::<_, anyhow::Error>("original owner")),
    )
    .await
    .expect("bounded bootstrap succeeds");
    assert_eq!(ready.owner, "original owner");
    let bytes = std::fs::read(evidence.directory().join("policy-bootstrap-result.json"))
        .expect("ready receipt already durable");
    assert_eq!(ready.evidence_digest, Digest32::of_bytes(&bytes));
    let result: Value = serde_json::from_slice(&bytes).expect("receipt JSON");
    assert_eq!(result["status"], "ready");
    assert_eq!(result["run_id"], run.as_str());
    assert_eq!(result["turn_id"], turn.as_str());
    assert_eq!(result["generation_binding_created"], false);
    assert_eq!(result["provider_attempt_admitted"], false);
    assert_eq!(result["provider_transport_invoked"], false);
    assert!(!evidence.directory().join("encoded-request.json").exists());
}

#[tokio::test]
async fn timed_out_bootstrap_retains_pre_dispatch_failure_without_returning_an_owner() {
    let (_temp, evidence) = evidence();
    let (run, turn) = ids();
    let result = observe(
        &evidence,
        &run,
        &turn,
        Duration::from_millis(1),
        future::pending::<Result<()>>(),
    )
    .await;
    assert!(matches!(
        result
            .as_ref()
            .err()
            .and_then(anyhow::Error::downcast_ref::<BootstrapFailure>),
        Some(BootstrapFailure::Deadline)
    ));
    let receipt: Value = serde_json::from_slice(
        &std::fs::read(evidence.directory().join("policy-bootstrap-result.json"))
            .expect("failure receipt"),
    )
    .expect("receipt JSON");
    assert_eq!(receipt["status"], "deadline");
    assert_eq!(receipt["provider_transport_invoked"], false);
    assert!(!evidence.directory().join("admission.json").exists());
}

#[tokio::test]
async fn setup_failure_keeps_static_diagnostics_and_never_yields_a_ready_owner() {
    let (_temp, evidence) = evidence();
    let (run, turn) = ids();
    let result = observe(
        &evidence,
        &run,
        &turn,
        Duration::from_secs(1),
        future::ready(Err::<(), _>(anyhow::anyhow!(
            "PRIVATE_SETUP_FAILURE_FIXTURE"
        ))),
    )
    .await;
    let error = result.err().expect("setup failure");
    assert!(matches!(
        error.downcast_ref::<BootstrapFailure>(),
        Some(BootstrapFailure::Setup)
    ));
    assert!(!error.to_string().contains("PRIVATE_SETUP_FAILURE_FIXTURE"));
    let bytes = std::fs::read(evidence.directory().join("policy-bootstrap-result.json"))
        .expect("failure receipt");
    assert!(
        !String::from_utf8(bytes)
            .expect("JSON")
            .contains("PRIVATE_SETUP_FAILURE_FIXTURE")
    );
}
