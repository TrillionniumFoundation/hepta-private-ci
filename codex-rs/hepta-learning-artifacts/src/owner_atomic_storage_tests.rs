use super::tests::*;
use super::*;

use crate::DatasetWithdrawalNoticeV1;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

#[test]
fn rejected_registry_frontier_leaves_no_snapshot_or_phase_change() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        20,
    )
    .fixture("owner");
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload durable");
    let before = transaction.snapshot();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawn-before-snapshot"),
            dataset_digest: digest("dataset"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("credential-chain"),
            signing_key_digest: digest("withdrawal-key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .fixture("withdrawal");
    assert!(
        owner
            .ensure_registry_durable(
                &mut transaction,
                &registry,
                &withdrawals,
                digest("binding"),
                21,
            )
            .is_err()
    );
    assert_eq!(transaction.snapshot(), before);
    assert_eq!(
        fs::read_dir(directory.0.join("registries"))
            .fixture("registries")
            .count(),
        0
    );
}

// A file-size limit interrupts the real write before it can finish. This avoids
// timing-dependent polling and proves that the no-replace final path never
// exposes a partial write. Directory fsync and this fault primitive are Unix
// specific; other hosts keep their separate power-loss qualification gate.
#[cfg(unix)]
#[test]
fn interrupted_large_record_never_reserves_the_final_path() {
    use std::process::Command;

    let directory = TestDir::new();
    let target = directory.0.join("payloads/interrupted.bin");
    fs::create_dir_all(target.parent().fixture("parent")).fixture("payload directory");
    let executable = std::env::current_exe().fixture("test executable");
    let status = Command::new("sh")
        .arg("-c")
        .arg("ulimit -c 0; ulimit -f 1; exec \"$@\"")
        .arg("atomic-storage-worker")
        .arg(executable)
        .args([
            "--exact",
            "owner_host::atomic_storage_tests::interrupted_atomic_record_worker",
            "--ignored",
            "--nocapture",
        ])
        .env("HEPTA_ATOMIC_RECORD_TARGET", &target)
        .status()
        .fixture("interrupted worker");
    assert!(!status.success());
    assert!(!target.exists());
    let bytes = vec![7; 64 * 1024];
    records::write_record_with_limit(&target, &bytes, bytes.len()).fixture("retry full record");
    assert_eq!(fs::read(&target).fixture("complete final bytes"), bytes);
}

#[cfg(unix)]
#[test]
#[ignore = "subprocess fixture invoked only under a file-size fault"]
fn interrupted_atomic_record_worker() {
    let target = std::env::var_os("HEPTA_ATOMIC_RECORD_TARGET").fixture("worker target");
    let bytes = vec![7; 64 * 1024];
    records::write_record_with_limit(Path::new(&target), &bytes, bytes.len())
        .fixture("write interrupted record");
}
