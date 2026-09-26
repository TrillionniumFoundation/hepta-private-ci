#![allow(clippy::unwrap_used)]
//! Separate-process recovery: only paths and independently retained pins cross
//! the process boundary. No training candidate or model is passed to the child.
use super::current_artifacts::Artifacts;
use super::*;
use codex_hepta_agentd::AgentdSharedReplayHostV1;
use codex_hepta_agentd::SharedTerminalCellError;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::FederationConsumerAccess;
use codex_hepta_paths::HeptaFleetRoot;
use std::path::PathBuf;
use std::sync::Arc;

#[tokio::test]
#[ignore = "invoked in a separate process by the shared terminal owner test"]
async fn restore_only_from_durable_owners() {
    let case: serde_json::Value = serde_json::from_slice(
        &std::fs::read(std::env::var_os("HEPTA_SHARED_RESTORE_CASE").unwrap()).unwrap(),
    )
    .unwrap();
    let field = |name: &str| case[name].as_str().unwrap().to_owned();
    let ledger_fixture = std::mem::ManuallyDrop::new(Fixture {
        root: PathBuf::from(field("ledger_root")),
    });
    let frontier = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: case["ledger_sequence"].as_u64().unwrap(),
            chain_digest: field("ledger_head").parse().unwrap(),
        },
        segment: None,
        sealed: false,
    };
    let mut ledger = ledger_fixture.recover_writer(64, frontier);
    if std::env::var("HEPTA_SHARED_RESTORE_EXPECT").as_deref() == Ok("trust-changed") {
        // The child receives the new root-authorized distribution independently
        // of the old artifact files; old recovered bundles cannot select it away.
        super::support::rotate_trust(&mut ledger);
    }
    let artifacts = Artifacts::open(&PathBuf::from(field("artifact_root")), None);
    // This pin was retained outside the artifact files before process exit.
    assert_eq!(
        artifacts.head().witness.head_digest.to_string(),
        field("artifact_head")
    );
    let fleet = HeptaFleetRoot::parse(PathBuf::from(field("fleet_root")))
        .unwrap()
        .layout();
    let source = Arc::new(
        CognitiveStore::open(&fleet.agent(&AgentId::parse(field("owner_id")).unwrap()))
            .await
            .unwrap(),
    );
    let receiver = AgentId::parse(field("receiver_id")).unwrap();
    let consumer = FederationConsumerAccess::new(
        receiver.clone(),
        Sha256Digest::parse(field("workspace")).unwrap(),
    );
    let host = AgentdSharedReplayHostV1::new(source, consumer, "domain.terminal".into(), receiver)
        .unwrap()
        .with_artifact_owner(Arc::clone(&artifacts.owner), artifacts.selector.clone());
    let pin = field("selection_digest").parse().unwrap();
    let result = host.restore(&ledger, pin, 50).await;
    match std::env::var("HEPTA_SHARED_RESTORE_EXPECT").as_deref() {
        Ok("trust-changed") => assert!(matches!(
            result,
            Err(SharedTerminalCellError::Binding(
                "current learning trust changed"
            ))
        )),
        Ok("source-withdrawn") => {
            assert!(matches!(result, Err(SharedTerminalCellError::Source(_))))
        }
        Ok("selection-withdrawn") => assert!(matches!(
            result,
            Err(SharedTerminalCellError::Binding(
                "selected descriptor unavailable"
            ))
        )),
        _ => {
            let mut model = result.unwrap();
            let prediction = host
                .predict(
                    &mut model,
                    &ledger,
                    &id("single-approved-state"),
                    &id("read"),
                    50,
                )
                .await
                .unwrap();
            assert_eq!(prediction.value.raw(), case["value_raw"].as_i64().unwrap());
            assert!(!prediction.authority.grants_any());
        }
    }
}

pub(super) fn child(case: &std::path::Path, expectation: &str) {
    let result = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "shared_process_tests::restore_only_from_durable_owners",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_SHARED_RESTORE_CASE", case)
        .env("HEPTA_SHARED_RESTORE_EXPECT", expectation)
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "recovery child failed: {}\n{}",
        String::from_utf8_lossy(&result.stdout),
        String::from_utf8_lossy(&result.stderr)
    );
}
