//! Real child-process termination at each publication boundary.
//!
//! SIGKILL tests process-crash recovery, not filesystem power-loss durability.

use std::io::Write;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use super::*;

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn config(root: PathBuf) -> LearningArtifactOwnerServiceConfigV1 {
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    LearningArtifactOwnerServiceConfigV1 {
        root,
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 20,
    }
}

fn request_and_registry(
    service: &LearningArtifactOwnerService,
) -> (LearningArtifactPublishRequestV1, ArtifactRegistry) {
    let predecessor = service.registry().snapshot().head_digest;
    let withdrawals = service.withdrawal_registry();
    let admission =
        admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest(), 20)
            .fixture("admission");
    let mut staged = service.registry().clone();
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
        withdrawals,
        &staged,
        predecessor,
        20,
    )
    .fixture("preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("preview registration");
    let request = publish_request(&key(), withdrawals, predecessor, staged.snapshot().head_digest);
    (request, staged)
}

#[test]
fn phase_worker() {
    let Some(root) = std::env::var_os("HEPTA_ARTIFACT_CRASH_TEST_ROOT") else {
        return;
    };
    let phase = std::env::var("HEPTA_ARTIFACT_CRASH_TEST_PHASE")
        .fixture("phase")
        .parse::<u8>()
        .fixture("phase number");
    assert!(phase <= 4);
    let root = PathBuf::from(root);
    let service =
        LearningArtifactOwnerService::open(config(root.join("store"))).fixture("worker service");
    let (request, staged) = request_and_registry(&service);
    let withdrawals = service.withdrawal_registry();
    let mut transaction = service
        .host
        .begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            withdrawals,
            service.registry(),
            request.expected_registry_predecessor_head,
            20,
        )
        .fixture("prepare");
    if phase >= 1 {
        service
            .host
            .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
            .fixture("payload");
    }
    if phase >= 2 {
        service
            .host
            .ensure_registry_durable(&mut transaction, &staged, withdrawals, digest("binding"), 20)
            .fixture("registry");
    }
    if phase >= 3 {
        service
            .host
            .ensure_witness_durable(&mut transaction, &request.signed_current_head, withdrawals, 20)
            .fixture("witness");
    }
    if phase == 4 {
        service
            .host
            .acknowledge(&mut transaction, withdrawals, 20)
            .fixture("acknowledge");
    }
    let mut barrier = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join("ready"))
        .fixture("barrier");
    barrier.write_all(&[phase]).fixture("barrier write");
    barrier.sync_all().fixture("barrier sync");
    // Bounded watchdog; the parent must terminate us while the writer lease
    // is held. Normal return is a test failure, never a graceful crash model.
    thread::sleep(Duration::from_secs(30));
    panic!("parent did not terminate the phase worker");
}

#[test]
fn sigkill_every_durable_phase_reconciles_exactly_and_preserves_writer_exclusion() {
    for phase in 0u8..=4 {
        let directory = TestDir::new();
        let store = directory.0.join("store");
        fs::create_dir(&store).fixture("store directory");
        // Retain the independently computed expected request outside the child.
        let service = LearningArtifactOwnerService::open(config(store.clone())).fixture("preview");
        let (request, _) = request_and_registry(&service);
        drop(service);
        let mut child = ChildGuard(
            Command::new(std::env::current_exe().fixture("test executable"))
                .args([
                    "--exact",
                    "owner_service::tests::process::phase_worker",
                    "--nocapture",
                ])
                .env("HEPTA_ARTIFACT_CRASH_TEST_ROOT", &directory.0)
                .env("HEPTA_ARTIFACT_CRASH_TEST_PHASE", phase.to_string())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::inherit())
                .spawn()
                .fixture("spawn phase worker"),
        );
        let deadline = Instant::now() + Duration::from_secs(10);
        loop {
            if fs::read(directory.0.join("ready")).is_ok_and(|bytes| bytes == [phase]) {
                break;
            }
            assert!(child.0.try_wait().fixture("worker status").is_none());
            assert!(Instant::now() < deadline, "phase worker did not reach barrier");
            thread::sleep(Duration::from_millis(5));
        }
        assert!(matches!(
            LearningArtifactOwnerService::open(config(store.clone())),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::WriterFenceBusy
            ))
        ));
        child.0.kill().fixture("SIGKILL worker");
        assert!(!child.0.wait().fixture("reap worker").success());
        let mut recovery_config = config(store);
        if phase >= 3 {
            recovery_config.required_current_head = Some(request.signed_current_head.clone());
        }
        let mut recovered = LearningArtifactOwnerService::open(recovery_config).fixture("reopen");
        if phase < 4 {
            assert_eq!(recovered.recovery_required(), Some(&request.operation_id));
            assert!(matches!(
                recovered.current_registry_view(20),
                Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
            ));
        }
        let mut drifted = request.clone();
        drifted.payload[0] ^= 1;
        assert!(recovered.publish(drifted).is_err());
        let receipt = recovered
            .publish(request.clone())
            .fixture("resume exact publication");
        assert_eq!(
            receipt.registry_head_digest,
            request.signed_current_head.witness.head_digest
        );
        assert_eq!(recovered.publish(request).fixture("terminal retry"), receipt);
        assert!(recovered.recovery_required().is_none());
        assert_eq!(
            recovered
                .current_registry_view(20)
                .fixture("ready current view")
                .receipt()
                .head_digest,
            receipt.registry_head_digest
        );
    }
}
