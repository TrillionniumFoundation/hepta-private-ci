//! Real child-process crash cuts through the registered TLS/AuthBus/JSON path.
//! The provider is a synthetic TLS fixture, not the external HeptaBao service.
use super::*;
use std::io::Write;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::Instant;

use crate::{
    BaoConsumerObservationV1, BaoFinalUseHost, BaoProductHostError, DurableLeaseRegistryV1,
    RegisteredBaoConsumer,
};
use codex_hepta_contracts::{
    FinalUseApprovalVerifier, FinalUseRevocationFeedVerifier, SystemAuthorityClock,
};

#[derive(serde::Deserialize, serde::Serialize)]
struct RecoveryInputs {
    database: PathBuf,
    checkpoint: PathBuf,
    authority: PathBuf,
    registry: PathBuf,
    outcome: PathBuf,
}

fn write_private(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let mut file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    let parent = path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "private file has no parent",
        )
    })?;
    std::fs::File::open(parent)?.sync_all()
}

#[tokio::test]
#[ignore = "subprocess fixture entered only by registered_saga_sigkill_matrix"]
async fn child_process() {
    let root = PathBuf::from(std::env::var_os("HEPTA_BAO_TEST_ROOT").unwrap());
    let (endpoint, ca, _server) = server(200, body(), || async {}).await.unwrap();
    let client = BaoClient::new(
        &endpoint,
        ca.as_bytes(),
        BaoToken::new("synthetic-crash-fixture-token".into()).unwrap(),
        Duration::from_secs(10),
    )
    .unwrap();
    let mut request = read_request();
    request.consumer_configuration_sha256 = Some([93; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let (database, checkpoint, authbus, mut evidence, admission) =
        authbus_host_with_lifetime(180_000, &client, &request, now)
            .await
            .unwrap();
    let (authority, grant, authority_root) = product_grant(&client, &request).unwrap();
    let (registry_root, registry) = product_registry().unwrap();
    let outcome = root.join("consumer-outcome.json");
    let callback_outcome = outcome.clone();
    let (host, approval) = registered_product_host(
        authority,
        &grant,
        Arc::new(move |operation, digest, secret| {
            std::assert_eq!(secret, SECRET.as_bytes());
            let bytes = serde_json::to_vec(&(operation, digest)).map_err(|_| ())?;
            write_private(&callback_outcome, &bytes).map_err(|_| ())?;
            Ok(())
        }),
        Arc::new(|_, _| Ok(BaoConsumerObservationV1::Unknown)),
        [93; 32],
    )
    .unwrap();
    let inputs = RecoveryInputs {
        database: database.path().join("authbus-authority.sqlite"),
        checkpoint: checkpoint.path().join("authbus-authority-checkpoint.json"),
        authority: authority_root.path().to_path_buf(),
        registry: registry_root.path().join("owner.json"),
        outcome,
    };
    write_private(
        &root.join("inputs.json"),
        &serde_json::to_vec(&inputs).unwrap(),
    )
    .unwrap();
    let result = host
        .consume_kv_v2_with_authbus(
            &client,
            &authbus,
            &registry,
            crate::BaoApprovedReadV1 {
                admission: &admission,
                grant: &grant,
                approval: &approval,
                request: &request,
            },
            &mut evidence,
        )
        .await;
    panic!("requested crash boundary was never reached: {result:?}");
}

fn post_dispatch_without_receipt(cut: &str) -> bool {
    matches!(
        cut,
        "dispatch_fence.after"
            | "local_fence.before"
            | "local_fence.after"
            | "provider_response.before"
            | "provider_response.after"
            | "delivery_preparation.before"
    )
}

fn consumer_effect_recorded(cut: &str) -> bool {
    matches!(
        cut,
        "consumer_ack.before"
            | "consumer_ack.after"
            | "consumer_entry.after"
            | "settlement.before"
            | "settlement.after"
            | "local_terminal.before"
            | "local_terminal.after"
    )
}

#[tokio::test]
async fn registered_saga_sigkill_matrix() {
    for cut in crate::saga_crash::CUTS {
        let root = tempfile::tempdir().unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        let log = std::fs::File::create(root.path().join("child.log")).unwrap();
        let mut child = Command::new(std::env::current_exe().unwrap())
            .args([
                "--exact",
                "https_consumer::tests::saga_crash_tests::child_process",
                "--ignored",
                "--nocapture",
                "--test-threads=1",
            ])
            .env("HEPTA_BAO_TEST_ROOT", root.path())
            .env("HEPTA_BAO_TEST_CUT", cut)
            .env("TMPDIR", root.path())
            .stdout(Stdio::from(log.try_clone().unwrap()))
            .stderr(Stdio::from(log))
            .spawn()
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(30);
        while !root.path().join("at-cut").is_file() {
            if let Some(status) = child.try_wait().unwrap() {
                let log = std::fs::read_to_string(root.path().join("child.log")).unwrap();
                panic!("child exited before {cut}: {status}; {log}");
            }
            if Instant::now() >= deadline {
                child.kill().unwrap();
                child.wait().unwrap();
                panic!("child failed to reach {cut}");
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        child.kill().unwrap();
        let status = child.wait().unwrap();
        use std::os::unix::process::ExitStatusExt;
        std::assert_eq!(status.signal(), Some(9));

        let inputs: RecoveryInputs =
            serde_json::from_slice(&std::fs::read(root.path().join("inputs.json")).unwrap())
                .unwrap();
        // Recovery intentionally has no BaoClient and cannot redispatch.
        let registry = Mutex::new(DurableLeaseRegistryV1::open(&inputs.registry).unwrap());
        let raw = AuthBusAuthorityStore::open(&inputs.database).await.unwrap();
        let last_time = raw.last_trusted_time().await.unwrap().unwrap();
        drop(raw);
        let authbus =
            AuthBusAuthorityHost::open(&inputs.database, inputs.checkpoint, "bao-product-owner")
                .await
                .unwrap();
        let mut evidence = AuthBusEvidence::new(last_time.wall_time_ms());
        evidence.revision = last_time.source_revision();
        let issuer = SigningKey::from_bytes(&[71; 32]);
        let authority = FinalUseAuthority::open_state_dir(
            &inputs.authority,
            "owner".into(),
            issuer.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 3,
                revision: 2,
                revoked_grant_ids: Default::default(),
            },
        )
        .unwrap();
        let observed_path = inputs.outcome.clone();
        let host = BaoFinalUseHost::new(
            authority,
            FinalUseApprovalVerifier::new(
                "bao-test-approver".into(),
                SigningKey::from_bytes(&[91; 32]).verifying_key().to_bytes(),
            )
            .unwrap(),
            FinalUseRevocationFeedVerifier::new(
                "bao-test-distributor".into(),
                SigningKey::from_bytes(&[92; 32]).verifying_key().to_bytes(),
            )
            .unwrap(),
            Arc::new(SystemAuthorityClock),
            [RegisteredBaoConsumer::for_operations(
                "model-provider".into(),
                [93; 32],
                Arc::new(|_, _, _| panic!("recovery reentered consumer")),
                Arc::new(
                    move |operation, digest| match std::fs::read(&observed_path) {
                        Ok(bytes) => {
                            let recorded: (String, [u8; 32]) =
                                serde_json::from_slice(&bytes).map_err(|_| ())?;
                            if recorded != (operation.to_owned(), digest) {
                                return Err(());
                            }
                            Ok(BaoConsumerObservationV1::Succeeded)
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                            let proof = serde_json::to_vec(&(
                                "fixture-exclusive-negative",
                                operation,
                                digest,
                            ))
                            .map_err(|_| ())?;
                            Ok(BaoConsumerObservationV1::NotAppliedWithEvidence {
                                evidence_sha256: Digest32::of_bytes(&proof).into_array(),
                            })
                        }
                        Err(_) => Err(()),
                    },
                ),
            )
            .unwrap()],
        )
        .unwrap();
        let operation = "operation:bao-product";
        let result = host
            .reconcile_consumption(&authbus, &registry, operation, &mut evidence)
            .await;

        if *cut == "claim.before" {
            assert!(matches!(
                result,
                Err(BaoProductHostError::Store(
                    crate::LeaseRegistryErrorV1::OperationNotFound
                ))
            ));
            assert!(
                authbus
                    .reservation_by_operation(&StableId::new(operation).unwrap())
                    .await
                    .unwrap()
                    .is_none()
            );
            continue;
        }

        let row = registry
            .lock()
            .unwrap()
            .consumption_result(operation)
            .unwrap();
        if post_dispatch_without_receipt(cut) {
            assert!(matches!(
                result,
                Err(BaoProductHostError::OutcomePending(_))
            ));
            assert!(!row.state.is_terminal(), "{cut}: {row:?}");
            assert!(row.state.has_dispatch_fence(), "{cut}: {row:?}");
            assert!(row.receipt.is_none(), "{cut}: {row:?}");
            let diagnostics = registry.lock().unwrap().diagnostics().unwrap();
            std::assert_eq!(diagnostics.post_dispatch_without_receipt, 1, "{cut}");
            std::assert_eq!(diagnostics.pending_quota_amount, 1, "{cut}");
            let quota = authbus
                .quota_snapshot(&StableId::new("quota:bao-read").unwrap())
                .await
                .unwrap();
            std::assert_eq!((quota.available, quota.reserved, quota.consumed), (0, 1, 0));
            let original = row.clone();
            let retry = host
                .reconcile_consumption(&authbus, &registry, operation, &mut evidence)
                .await;
            assert!(matches!(retry, Err(BaoProductHostError::OutcomePending(_))));
            std::assert_eq!(
                registry
                    .lock()
                    .unwrap()
                    .consumption_result(operation)
                    .unwrap(),
                original
            );
            continue;
        }

        if consumer_effect_recorded(cut) {
            std::assert_eq!(
                row.state,
                crate::BaoConsumptionStateV1::Succeeded,
                "{cut}: {result:?}"
            );
            assert!(result.is_ok(), "{cut}: {result:?}");
        } else {
            std::assert_eq!(
                row.state,
                crate::BaoConsumptionStateV1::Failed,
                "{cut}: {result:?}"
            );
            assert!(matches!(
                result,
                Err(BaoProductHostError::TerminalFailure(_))
            ));
        }
        let original = row.clone();
        let _ = host
            .reconcile_consumption(&authbus, &registry, operation, &mut evidence)
            .await;
        std::assert_eq!(
            registry
                .lock()
                .unwrap()
                .consumption_result(operation)
                .unwrap(),
            original
        );
        let quota = authbus
            .quota_snapshot(&StableId::new("quota:bao-read").unwrap())
            .await
            .unwrap();
        std::assert_eq!(quota.reserved, 0, "orphan reservation after {cut}");
        std::assert_eq!(quota.available + quota.consumed, 1);
    }
}
