//! Real child-process termination at publication and control boundaries.
//!
//! These tests model process death and page-cache-visible writes. They do not
//! claim physical power-loss durability; that remains an externally signed
//! target-filesystem qualification.

use std::fmt::Write as _;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::ArtifactOwnerHostError;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::storage::encode_snapshot;
use crate::test_support::FixtureValue;

use super::TestDir;
use super::digest;
use super::id;
use super::key;
use super::lease;
use super::manifest;
use super::publish_request;
use super::scope;
use super::trust;

const CHILD_TEST_PREFIX: &str = "owner_service::tests::process::";

struct ChildGuard(Child);

impl Drop for ChildGuard {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum PublicationFaultPoint {
    BeforePayloadWrite,
    PayloadWrittenBeforeSync,
    PayloadDurable,
    RegistryWrittenBeforeSync,
    RegistryDurable,
    CurrentHeadWrittenBeforeRoute,
    RouteCommitted,
    Promoted,
}

impl PublicationFaultPoint {
    const ALL: [Self; 8] = [
        Self::BeforePayloadWrite,
        Self::PayloadWrittenBeforeSync,
        Self::PayloadDurable,
        Self::RegistryWrittenBeforeSync,
        Self::RegistryDurable,
        Self::CurrentHeadWrittenBeforeRoute,
        Self::RouteCommitted,
        Self::Promoted,
    ];

    const fn as_str(self) -> &'static str {
        match self {
            Self::BeforePayloadWrite => "before-payload-write",
            Self::PayloadWrittenBeforeSync => "payload-written-before-sync",
            Self::PayloadDurable => "payload-durable",
            Self::RegistryWrittenBeforeSync => "registry-written-before-sync",
            Self::RegistryDurable => "registry-durable",
            Self::CurrentHeadWrittenBeforeRoute => "current-head-written-before-route",
            Self::RouteCommitted => "route-committed",
            Self::Promoted => "promoted",
        }
    }

    fn parse(value: &str) -> Option<Self> {
        Self::ALL.into_iter().find(|point| point.as_str() == value)
    }

    const fn requires_current_anchor(self) -> bool {
        matches!(
            self,
            Self::CurrentHeadWrittenBeforeRoute | Self::RouteCommitted | Self::Promoted
        )
    }

    const fn is_terminal(self) -> bool {
        matches!(self, Self::Promoted)
    }
}

fn config(root: PathBuf) -> LearningArtifactOwnerServiceConfigV1 {
    config_with_withdrawals(root, DatasetWithdrawalRegistry::new_scoped(scope()))
}

fn config_with_withdrawals(
    root: PathBuf,
    withdrawals: DatasetWithdrawalRegistry,
) -> LearningArtifactOwnerServiceConfigV1 {
    let key = key();
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

fn frontier(count: usize) -> DatasetWithdrawalRegistry {
    let mut registry = DatasetWithdrawalRegistry::new_scoped(scope());
    for sequence in 0..count {
        registry
            .append(DatasetWithdrawalNoticeV1 {
                notice_id: id(&format!("notice-{sequence}")),
                dataset_digest: digest(&format!("dataset-{sequence}")),
                source_tombstone_digest: digest("tombstone"),
                authority_id: id("dataset-authority"),
                credential_chain_digest: digest("credential-chain"),
                signing_key_digest: digest("withdrawal-key"),
                authority_epoch: 1,
                issued_at: 10,
            })
            .fixture("append withdrawal notice");
    }
    registry
}

fn request_and_registry(
    service: &LearningArtifactOwnerService,
) -> (LearningArtifactPublishRequestV1, ArtifactRegistry) {
    let predecessor = service.registry().snapshot().head_digest;
    let withdrawals = service.withdrawal_registry();
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
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
    let request = publish_request(
        &key(),
        withdrawals,
        predecessor,
        staged.snapshot().head_digest,
    );
    (request, staged)
}

fn create_unsynced(path: &Path, bytes: &[u8]) -> File {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .fixture("create unsynced fault file");
    file.write_all(bytes).fixture("write unsynced fault bytes");
    file
}

fn payload_path(root: &Path, request: &LearningArtifactPublishRequestV1) -> PathBuf {
    let manifest = &request.admission.validated_manifest.manifest;
    root.join("store").join("payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.bytes_digest
    ))
}

fn registry_path(root: &Path, staged: &ArtifactRegistry) -> (PathBuf, Vec<u8>) {
    let bytes = encode_snapshot(staged, digest("binding")).fixture("encode registry snapshot");
    let head = staged.snapshot().head_digest;
    let file_digest = Digest32::of_bytes(&bytes);
    (
        root.join("store")
            .join("registries")
            .join(format!("{head}-{file_digest}.snapshot")),
        bytes,
    )
}

fn signed_head_path(root: &Path, signed: &SignedCurrentArtifactHeadV1) -> PathBuf {
    root.join("store").join("heads").join(format!(
        "{}-{}.head",
        signed.witness.generation.get(),
        Digest32::of_bytes(&signed.signing_bytes())
    ))
}

fn encode_signed_head(signed: &SignedCurrentArtifactHeadV1) -> Vec<u8> {
    format!(
        concat!(
            "HEPTA-ARTIFACT-CURRENT-HEAD-V1\n{}\n{}\n{}\n{}\n{}\n{}\n",
            "{}\n{}\n{}\n{}\n{}\n{}\n"
        ),
        signed.withdrawal_scope_digest,
        signed.binding,
        signed.witness.registry_id,
        signed.witness.generation.get(),
        signed.witness.head_digest,
        signed.witness.predecessor_head_digest,
        signed.witness.authority_epoch,
        signed.witness.signer_id,
        signed.witness.signing_key_digest,
        signed.witness.issued_at,
        signed.witness.expires_at,
        encode_hex(&signed.signature),
    )
    .into_bytes()
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(&mut value, "{byte:02x}");
    }
    value
}

fn write_barrier(root: &Path, label: &str) {
    let mut barrier = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(root.join("ready"))
        .fixture("barrier");
    barrier
        .write_all(label.as_bytes())
        .fixture("barrier write");
    barrier.sync_all().fixture("barrier sync");
}

fn child(test_name: &str, root: &Path, extra: &[(&str, &str)]) -> ChildGuard {
    let mut command = Command::new(std::env::current_exe().fixture("test executable"));
    command
        .args(["--exact", &format!("{CHILD_TEST_PREFIX}{test_name}"), "--nocapture"])
        .env("HEPTA_ARTIFACT_CRASH_TEST_ROOT", root)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit());
    for (name, value) in extra {
        command.env(name, value);
    }
    ChildGuard(command.spawn().fixture("spawn crash worker"))
}

fn wait_for_barrier(child: &mut ChildGuard, root: &Path, expected: &str) {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        if fs::read(root.join("ready")).is_ok_and(|bytes| bytes == expected.as_bytes()) {
            return;
        }
        assert!(child.0.try_wait().fixture("worker status").is_none());
        assert!(Instant::now() < deadline, "worker did not reach {expected}");
        thread::sleep(Duration::from_millis(5));
    }
}

fn kill(child: &mut ChildGuard) {
    child.0.kill().fixture("SIGKILL worker");
    assert!(!child.0.wait().fixture("reap worker").success());
}

fn count_files(path: &Path, extension: &str) -> usize {
    fs::read_dir(path)
        .fixture("read artifact directory")
        .filter_map(Result::ok)
        .filter(|entry| {
            entry.path().extension().and_then(|value| value.to_str()) == Some(extension)
        })
        .count()
}

#[test]
fn phase_worker() {
    let Some(root) = std::env::var_os("HEPTA_ARTIFACT_CRASH_TEST_ROOT") else {
        return;
    };
    let point = PublicationFaultPoint::parse(
        &std::env::var("HEPTA_ARTIFACT_CRASH_TEST_POINT").fixture("fault point"),
    )
    .fixture("known fault point");
    let root = PathBuf::from(root);
    let service = LearningArtifactOwnerService::open(config(root.join("store")))
        .fixture("worker service");
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
    let mut unsynced_side_effect: Option<File> = None;

    match point {
        PublicationFaultPoint::BeforePayloadWrite => {}
        PublicationFaultPoint::PayloadWrittenBeforeSync => {
            unsynced_side_effect = Some(create_unsynced(&payload_path(&root, &request), &request.payload));
        }
        PublicationFaultPoint::PayloadDurable => {
            service
                .host
                .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                .fixture("payload");
        }
        PublicationFaultPoint::RegistryWrittenBeforeSync => {
            service
                .host
                .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                .fixture("payload");
            let (path, bytes) = registry_path(&root, &staged);
            unsynced_side_effect = Some(create_unsynced(&path, &bytes));
        }
        PublicationFaultPoint::RegistryDurable => {
            service
                .host
                .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                .fixture("payload");
            service
                .host
                .ensure_registry_durable(
                    &mut transaction,
                    &staged,
                    withdrawals,
                    digest("binding"),
                    20,
                )
                .fixture("registry");
        }
        PublicationFaultPoint::CurrentHeadWrittenBeforeRoute => {
            service
                .host
                .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                .fixture("payload");
            service
                .host
                .ensure_registry_durable(
                    &mut transaction,
                    &staged,
                    withdrawals,
                    digest("binding"),
                    20,
                )
                .fixture("registry");
            unsynced_side_effect = Some(create_unsynced(
                &signed_head_path(&root, &request.signed_current_head),
                &encode_signed_head(&request.signed_current_head),
            ));
        }
        PublicationFaultPoint::RouteCommitted | PublicationFaultPoint::Promoted => {
            service
                .host
                .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                .fixture("payload");
            service
                .host
                .ensure_registry_durable(
                    &mut transaction,
                    &staged,
                    withdrawals,
                    digest("binding"),
                    20,
                )
                .fixture("registry");
            service
                .host
                .ensure_witness_durable(
                    &mut transaction,
                    &request.signed_current_head,
                    withdrawals,
                    20,
                )
                .fixture("witness and route");
            service
                .host
                .current_registry_view(20)
                .fixture("route resolves exact registry");
            if point == PublicationFaultPoint::Promoted {
                service
                    .host
                    .acknowledge(&mut transaction, withdrawals, 20)
                    .fixture("promote");
            }
        }
    }

    write_barrier(&root, point.as_str());
    let _keep_unsynced_handle_open = unsynced_side_effect;
    thread::sleep(Duration::from_secs(30));
    panic!("parent did not terminate the phase worker");
}

#[test]
fn recovery_worker() {
    let Some(root) = std::env::var_os("HEPTA_ARTIFACT_CRASH_TEST_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let service = LearningArtifactOwnerService::open(config(root.join("store")))
        .fixture("open pending service for recovery");
    assert_eq!(service.recovery_required(), Some(&id("operation")));
    let recovery = service
        .host
        .recover_publication(&id("operation"))
        .fixture("recover checkpoint")
        .fixture("pending checkpoint");
    assert!(recovery.requires_exact_snapshot);
    write_barrier(&root, "during-recovery");
    thread::sleep(Duration::from_secs(30));
    panic!("parent did not terminate the recovery worker");
}

#[test]
fn withdrawal_worker() {
    let Some(root) = std::env::var_os("HEPTA_ARTIFACT_CRASH_TEST_ROOT") else {
        return;
    };
    let root = PathBuf::from(root);
    let store = root.join("store");
    let mut service = LearningArtifactOwnerService::open(config_with_withdrawals(
        store.clone(),
        frontier(0),
    ))
    .fixture("withdrawal worker service");
    let orphan = store.join("writer/withdrawal-floor-v1/0001.v1");
    let open_orphan = create_unsynced(&orphan, b"partial-withdrawal-floor");
    assert!(service.install_withdrawal_frontier(frontier(1)).is_err());
    assert!(!service.withdrawal_frontier_is_durable());
    assert!(matches!(
        service.current_registry_view(20),
        Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown)
    ));
    write_barrier(&root, "during-withdrawal-update");
    let _keep_partial_floor_open = open_orphan;
    thread::sleep(Duration::from_secs(30));
    panic!("parent did not terminate the withdrawal worker");
}

#[test]
fn publication_fault_matrix_reconciles_exactly_and_preserves_writer_exclusion() {
    for point in PublicationFaultPoint::ALL {
        let directory = TestDir::new();
        let store = directory.0.join("store");
        fs::create_dir(&store).fixture("store directory");
        let service = LearningArtifactOwnerService::open(config(store.clone())).fixture("preview");
        let (request, _) = request_and_registry(&service);
        drop(service);

        let mut child = child(
            "phase_worker",
            &directory.0,
            &[("HEPTA_ARTIFACT_CRASH_TEST_POINT", point.as_str())],
        );
        wait_for_barrier(&mut child, &directory.0, point.as_str());
        assert!(matches!(
            LearningArtifactOwnerService::open(config(store.clone())),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::WriterFenceBusy
            ))
        ));
        kill(&mut child);

        let mut recovery_config = config(store.clone());
        if point.requires_current_anchor() {
            recovery_config.required_current_head = Some(request.signed_current_head.clone());
        }
        let mut recovered =
            LearningArtifactOwnerService::open(recovery_config).fixture("reopen after crash");
        if !point.is_terminal() {
            assert_eq!(
                recovered.recovery_required(),
                Some(&request.operation_id)
            );
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
        assert_eq!(
            recovered
                .publish(request.clone())
                .fixture("terminal retry"),
            receipt
        );
        assert!(recovered.recovery_required().is_none());
        assert_eq!(
            recovered
                .current_registry_view(20)
                .fixture("ready current view")
                .receipt()
                .head_digest,
            receipt.registry_head_digest
        );
        assert_eq!(count_files(&store.join("payloads"), "bin"), 1);
        assert_eq!(count_files(&store.join("registries"), "snapshot"), 1);
        assert_eq!(count_files(&store.join("witnesses"), "witness"), 1);
        assert_eq!(count_files(&store.join("heads"), "head"), 1);
        assert_eq!(count_files(&store.join("transactions"), "checkpoint"), 5);
    }
}

#[test]
fn recovery_can_crash_repeatedly_without_becoming_not_started() {
    let directory = TestDir::new();
    let store = directory.0.join("store");
    fs::create_dir(&store).fixture("store directory");
    let service = LearningArtifactOwnerService::open(config(store.clone())).fixture("preview");
    let (request, _) = request_and_registry(&service);
    drop(service);

    let mut writer = child(
        "phase_worker",
        &directory.0,
        &[(
            "HEPTA_ARTIFACT_CRASH_TEST_POINT",
            PublicationFaultPoint::RegistryDurable.as_str(),
        )],
    );
    wait_for_barrier(
        &mut writer,
        &directory.0,
        PublicationFaultPoint::RegistryDurable.as_str(),
    );
    kill(&mut writer);
    fs::remove_file(directory.0.join("ready")).fixture("clear first barrier");

    let mut recovery = child("recovery_worker", &directory.0, &[]);
    wait_for_barrier(&mut recovery, &directory.0, "during-recovery");
    assert!(matches!(
        LearningArtifactOwnerService::open(config(store.clone())),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::WriterFenceBusy
        ))
    ));
    kill(&mut recovery);

    let mut final_service =
        LearningArtifactOwnerService::open(config(store)).fixture("second recovery open");
    assert_eq!(
        final_service.recovery_required(),
        Some(&request.operation_id)
    );
    let receipt = final_service
        .publish(request)
        .fixture("exact recovery after repeated process death");
    assert_eq!(
        final_service
            .current_registry_view(20)
            .fixture("current after repeated recovery")
            .receipt()
            .head_digest,
        receipt.registry_head_digest
    );
}

#[test]
fn interrupted_withdrawal_update_never_reopens_an_older_frontier() {
    let directory = TestDir::new();
    let store = directory.0.join("store");
    fs::create_dir(&store).fixture("store directory");
    let mut child = child("withdrawal_worker", &directory.0, &[]);
    wait_for_barrier(
        &mut child,
        &directory.0,
        "during-withdrawal-update",
    );
    kill(&mut child);

    assert!(LearningArtifactOwnerService::open(config_with_withdrawals(
        store.clone(),
        frontier(0),
    ))
    .is_err());
    assert!(LearningArtifactOwnerService::open(config_with_withdrawals(
        store,
        frontier(1),
    ))
    .is_err());
}
