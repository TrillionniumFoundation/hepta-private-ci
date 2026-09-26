#![cfg(target_os = "linux")]

use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME;
use codex_hepta_evidence::EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY;
use codex_hepta_evidence::EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION;
use codex_hepta_evidence::EvidenceFrontierBackend;
use codex_hepta_evidence::EvidenceFrontierBackendError;
use codex_hepta_evidence::EvidenceFrontierBackendIdentityV1;
use codex_hepta_evidence::EvidenceRecoveryFrontierSignatureV2;
use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;
use codex_hepta_evidence::LockedFileEvidenceFrontierBackend;
use codex_hepta_evidence::evidence_recovery_ledger_root_v2;

const CHILD_MARKER: &str = "KERNEL_EVIDENCE_MULTIPROCESS_CHILD";
const BACKEND_ROOT: &str = "KERNEL_EVIDENCE_MULTIPROCESS_BACKEND";
const LOCAL_ROOT: &str = "KERNEL_EVIDENCE_MULTIPROCESS_LOCAL";
const GATE_PATH: &str = "KERNEL_EVIDENCE_MULTIPROCESS_GATE";
const READY_PATH: &str = "KERNEL_EVIDENCE_MULTIPROCESS_READY";
const RESULT_PATH: &str = "KERNEL_EVIDENCE_MULTIPROCESS_RESULT";
const WORKERS: usize = 8;

fn frontier(
    generation: u64,
    backend_identity_sha256: Sha256Digest,
) -> EvidenceRecoveryFrontierV2 {
    let snapshot = EvidenceRecoverySnapshotV1 {
        schema_version: 1,
        database_lineage: EVIDENCE_DATABASE_LINEAGE.to_string(),
        migration_set_sha256: Sha256Digest::for_bytes(b"migrations"),
        qualification_max_seq: generation,
        qualification_frontier_sha256: Sha256Digest::for_bytes(
            format!("qualification-{generation}").as_bytes(),
        ),
        authbus_replay_frontier_sha256: Sha256Digest::for_bytes(b"replay"),
    };
    EvidenceRecoveryFrontierV2 {
        schema_version: EVIDENCE_RECOVERY_FRONTIER_V2_SCHEMA_VERSION,
        store_id: "store:kernel-evidence-multiprocess".to_string(),
        frontier_generation: generation,
        ledger_root_sha256: evidence_recovery_ledger_root_v2(&snapshot),
        snapshot,
        issuer_trust_registry_sha256: Sha256Digest::for_bytes(b"issuer-trust"),
        frontier_signer_registry_sha256: Sha256Digest::for_bytes(b"signer-trust"),
        backend_identity_sha256,
        build_artifact_sha256: Sha256Digest::for_bytes(b"build"),
        qualification_receipt_sha256: Sha256Digest::for_bytes(b"qualification-receipt"),
        backup_publication_sha256: Sha256Digest::for_bytes(b"backup"),
        source_commit: "a".repeat(40),
        source_tree: "b".repeat(40),
        created_at_unix_ms: 1_900_000_000_001,
        signer_policy_generation: 2,
        signatures: vec![EvidenceRecoveryFrontierSignatureV2 {
            signer_principal_id: "issuer:recovery".to_string(),
            signer_key_epoch: 2,
            signature_hex: "11".repeat(64),
        }],
    }
}

fn required_path(name: &str) -> PathBuf {
    PathBuf::from(std::env::var_os(name).unwrap_or_else(|| panic!("missing {name}")))
}

#[test]
fn multiprocess_child() {
    if std::env::var_os(CHILD_MARKER).is_none() {
        return;
    }
    let backend_root = required_path(BACKEND_ROOT);
    let local_root = required_path(LOCAL_ROOT);
    let gate = required_path(GATE_PATH);
    let ready = required_path(READY_PATH);
    let result_path = required_path(RESULT_PATH);
    let identity_bytes = fs::read(
        backend_root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME),
    )
    .expect("read backend identity");
    let identity_sha256 = Sha256Digest::for_bytes(&identity_bytes);
    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &backend_root,
        identity_sha256.clone(),
        &local_root,
    )
    .expect("open external backend in child");
    fs::write(&ready, b"ready").expect("publish child readiness");

    let deadline = Instant::now() + Duration::from_secs(15);
    while !gate.is_file() {
        assert!(Instant::now() < deadline, "timed out waiting for contention gate");
        thread::sleep(Duration::from_millis(5));
    }
    let outcome = match backend.compare_and_swap(
        "store:kernel-evidence-multiprocess",
        None,
        &frontier(1, identity_sha256),
    ) {
        Ok(_) => "success",
        Err(EvidenceFrontierBackendError::Conflict {
            expected: None,
            actual: Some(1),
        }) => "conflict",
        Err(error) => panic!("unexpected multiprocess CAS result: {error}"),
    };
    fs::write(result_path, outcome.as_bytes()).expect("publish child outcome");
}

#[test]
fn eight_process_first_generation_contention_has_one_durable_winner() {
    let shared_memory = Path::new("/dev/shm");
    if !shared_memory.is_dir() {
        eprintln!("skipping: /dev/shm is unavailable");
        return;
    }

    let external_parent = tempfile::tempdir().expect("external temporary parent");
    let local = tempfile::Builder::new()
        .prefix("kernel-evidence-local-")
        .tempdir_in(shared_memory)
        .expect("local rollback root in shared memory");
    if fs::metadata(external_parent.path())
        .expect("external metadata")
        .dev()
        == fs::metadata(local.path()).expect("local metadata").dev()
    {
        eprintln!("skipping: external and local test roots share one device");
        return;
    }

    let backend_root = external_parent.path().join("backend");
    let journals = backend_root.join(EVIDENCE_FRONTIER_BACKEND_JOURNAL_DIRECTORY);
    fs::create_dir(&backend_root).expect("create backend root");
    fs::create_dir(&journals).expect("create journal root");
    fs::set_permissions(&backend_root, fs::Permissions::from_mode(0o700))
        .expect("protect backend root");
    fs::set_permissions(&journals, fs::Permissions::from_mode(0o700))
        .expect("protect journal root");
    fs::set_permissions(local.path(), fs::Permissions::from_mode(0o700))
        .expect("protect local root");

    let identity = EvidenceFrontierBackendIdentityV1 {
        schema_version: 1,
        backend_id: "backend:kernel-evidence-multiprocess".to_string(),
        authority_id: "authority:kernel-evidence-multiprocess".to_string(),
        authority_generation: 1,
        storage_class: "external_monotonic_cas".to_string(),
    };
    let identity_bytes = serde_json::to_vec(&identity).expect("serialize backend identity");
    let identity_path = backend_root.join(EVIDENCE_FRONTIER_BACKEND_IDENTITY_FILENAME);
    fs::write(&identity_path, &identity_bytes).expect("write backend identity");
    fs::set_permissions(&identity_path, fs::Permissions::from_mode(0o600))
        .expect("protect backend identity");

    let synchronization = tempfile::tempdir().expect("synchronization root");
    let ready_root = synchronization.path().join("ready");
    let result_root = synchronization.path().join("results");
    let gate = synchronization.path().join("go");
    fs::create_dir(&ready_root).expect("create readiness root");
    fs::create_dir(&result_root).expect("create result root");

    let executable = std::env::current_exe().expect("resolve integration-test executable");
    let started = Instant::now();
    let mut children = Vec::with_capacity(WORKERS);
    for worker in 0..WORKERS {
        let child = Command::new(&executable)
            .args([
                "--exact",
                "multiprocess_child",
                "--nocapture",
                "--test-threads=1",
            ])
            .env(CHILD_MARKER, "1")
            .env(BACKEND_ROOT, &backend_root)
            .env(LOCAL_ROOT, local.path())
            .env(GATE_PATH, &gate)
            .env(READY_PATH, ready_root.join(worker.to_string()))
            .env(RESULT_PATH, result_root.join(worker.to_string()))
            .spawn()
            .expect("spawn competing publisher");
        children.push(child);
    }

    let readiness_deadline = Instant::now() + Duration::from_secs(20);
    loop {
        let ready = fs::read_dir(&ready_root)
            .expect("read readiness root")
            .count();
        if ready == WORKERS {
            break;
        }
        assert!(
            Instant::now() < readiness_deadline,
            "timed out waiting for {WORKERS} publisher processes; observed {ready}"
        );
        thread::sleep(Duration::from_millis(10));
    }
    fs::write(&gate, b"go").expect("release contention gate");
    for child in &mut children {
        let status = child.wait().expect("wait for publisher process");
        assert!(status.success(), "publisher process failed: {status}");
    }

    let mut successes = 0_usize;
    let mut conflicts = 0_usize;
    for worker in 0..WORKERS {
        match fs::read_to_string(result_root.join(worker.to_string()))
            .expect("read publisher outcome")
            .as_str()
        {
            "success" => successes += 1,
            "conflict" => conflicts += 1,
            outcome => panic!("unexpected publisher outcome: {outcome}"),
        }
    }
    assert_eq!((successes, conflicts), (1, WORKERS - 1));

    let identity_sha256 = Sha256Digest::for_bytes(&identity_bytes);
    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &backend_root,
        identity_sha256,
        local.path(),
    )
    .expect("reopen external backend after contention");
    let latest = backend
        .get_latest("store:kernel-evidence-multiprocess")
        .expect("read durable winner")
        .expect("one frontier was published");
    assert_eq!(latest.frontier_generation, 1);

    println!(
        "kernel_evidence_multiprocess_contention={{\"workers\":{WORKERS},\"successes\":{successes},\"conflicts\":{conflicts},\"elapsedMs\":{}}}",
        started.elapsed().as_millis()
    );
}
