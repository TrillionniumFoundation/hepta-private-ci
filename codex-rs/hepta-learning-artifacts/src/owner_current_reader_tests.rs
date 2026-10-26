//! Synthetic owner-store contracts; no production enrollment or model evidence.

use super::tests::TestDir;
use super::tests::digest;
use super::tests::id;
use super::tests::lease;
use super::tests::manifest;
use super::tests::signed_head;
use super::tests::signer;
use super::tests::trust;
use super::tests::withdrawal_scope;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureError;
use crate::test_support::FixtureValue;

fn publish_next(
    owner: &LearningArtifactOwnerHost,
    withdrawals: &DatasetWithdrawalRegistry,
    registry: &mut ArtifactRegistry,
    name: &str,
    generation: u64,
    now: u64,
) -> SignedCurrentArtifactHeadV1 {
    let predecessor = registry.snapshot().head_digest;
    let mut candidate = manifest();
    candidate.artifact_id = id(name);
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        candidate,
        now,
    )
    .fixture("admit candidate");
    let mut transaction = owner
        .begin_publication(
            id(&format!("operation-{name}")),
            admission,
            withdrawals,
            registry,
            predecessor,
            now,
        )
        .fixture("begin publication");
    owner
        .stage_compatibility_registration(&transaction, registry, now)
        .fixture("register candidate");
    owner
        .ensure_payload_durable(&mut transaction, registry, b"payload", now)
        .fixture("durable payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            registry,
            withdrawals,
            digest("binding"),
            now,
        )
        .fixture("durable registry");
    let key = signer();
    let mut head = signed_head(
        &key,
        withdrawals.scope_digest().fixture("withdrawal scope"),
        registry.snapshot().head_digest,
    );
    head.witness.generation = Generation::new(generation).fixture("head generation");
    head.witness.predecessor_head_digest = predecessor;
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    owner
        .ensure_witness_durable(&mut transaction, &head, withdrawals, now)
        .fixture("durable current head");
    owner
        .acknowledge(&mut transaction, withdrawals, now)
        .fixture("acknowledge publication");
    head
}

fn store_files(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut files = BTreeMap::new();
    for directory in [
        "writer",
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
    ] {
        for entry in fs::read_dir(root.join(directory)).fixture("list owner store") {
            let entry = entry.fixture("owner store entry");
            // Windows may deny a data read of the live owner's locked file.
            let bytes = if directory == "writer" {
                entry
                    .metadata()
                    .fixture("writer metadata")
                    .len()
                    .to_be_bytes()
                    .to_vec()
            } else {
                fs::read(entry.path()).fixture("read owner store file")
            };
            files.insert(entry.path(), bytes);
        }
    }
    files
}

#[test]
fn current_reader_reads_while_owner_retains_exclusive_writer_fence() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let now = 20;
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), now)
            .fixture("live owner");
    let mut registry = ArtifactRegistry::new();
    let head = publish_next(
        &owner,
        &withdrawals,
        &mut registry,
        "candidate",
        /*generation*/ 1,
        now,
    );
    let before = store_files(&directory.0);
    let reader =
        ArtifactOwnerCurrentReaderV1::open_existing(&directory.0, trust(&key, scope), head, now)
            .fixture("read alongside the owner");
    let actual = reader.current_registry_view(now).fixture("fresh read");
    let expected = owner.current_registry_view(now).fixture("owner view");
    assert_eq!(actual.receipt(), expected.receipt());
    assert_eq!(actual.registry().snapshot(), expected.registry().snapshot());
    assert_eq!(store_files(&directory.0), before);
    assert!(matches!(
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), now)
            .fixture_error("a second writer remains fenced"),
        ArtifactOwnerHostError::WriterFenceBusy
    ));
    drop(owner);
    LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), now)
        .fixture("the reader holds no writer fence");
}

#[test]
fn current_reader_follows_head_advance_and_keeps_independent_floor() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let now = 20;
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), now)
            .fixture("live owner");
    let mut registry = ArtifactRegistry::new();
    let first = publish_next(
        &owner,
        &withdrawals,
        &mut registry,
        "candidate",
        /*generation*/ 1,
        now,
    );
    let reader =
        ArtifactOwnerCurrentReaderV1::open_existing(&directory.0, trust(&key, scope), first, now)
            .fixture("initial reader");
    let loaded = reader.current_registry_view(now).fixture("initial current");
    let second = publish_next(
        &owner,
        &withdrawals,
        &mut registry,
        "unrelated",
        /*generation*/ 2,
        now,
    );
    let advanced = reader
        .current_registry_view(now)
        .fixture("discover newer current");
    assert_eq!(advanced.registry().snapshot(), registry.snapshot());
    assert_ne!(advanced.receipt(), loaded.receipt());
    let anchored = ArtifactOwnerCurrentReaderV1::open_existing(
        &directory.0,
        trust(&key, scope),
        second.clone(),
        now,
    )
    .fixture("independently retained newer floor");
    fs::remove_file(owner.signed_head_record_path(&second)).fixture("simulate restored old heads");
    assert!(matches!(
        anchored
            .current_registry_view(now)
            .fixture_error("old backup cannot satisfy floor"),
        ArtifactOwnerHostError::CurrentHeadRollback
    ));
}

#[test]
fn current_reader_rejects_revoked_expired_or_unbacked_current() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let now = 20;
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), now)
            .fixture("live owner");
    let mut registry = ArtifactRegistry::new();
    let head = publish_next(
        &owner,
        &withdrawals,
        &mut registry,
        "candidate",
        /*generation*/ 1,
        now,
    );
    let reader = ArtifactOwnerCurrentReaderV1::open_existing(
        &directory.0,
        trust(&key, scope),
        head.clone(),
        now,
    )
    .fixture("reader");
    let mut revoked = trust(&key, scope);
    revoked.head_signers[0].revoked_at = Some(25);
    assert!(matches!(
        ArtifactOwnerCurrentReaderV1::open_existing(&directory.0, revoked, head, /*now*/ 30)
            .fixture_error("revoked current signer"),
        ArtifactOwnerHostError::SignerRevoked
    ));
    assert!(matches!(
        reader
            .current_registry_view(/*now*/ 1_001)
            .fixture_error("expired current head"),
        ArtifactOwnerHostError::CurrentHeadExpired
    ));
    let receipt = reader
        .current_registry_view(now)
        .fixture("valid current")
        .receipt();
    let snapshot = directory.0.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest,
    ));
    fs::remove_file(snapshot).fixture("remove current snapshot");
    assert!(reader.current_registry_view(now).is_err());
}

#[test]
fn current_reader_does_not_initialize_a_missing_owner() {
    let directory = TestDir::new();
    let missing = directory.0.join("not-enrolled");
    let key = signer();
    let scope = withdrawal_scope().digest();
    let head = signed_head(&key, scope, digest("uninstalled-head"));
    assert!(
        ArtifactOwnerCurrentReaderV1::open_existing(
            &missing,
            trust(&key, scope),
            head,
            /*now*/ 20,
        )
        .is_err()
    );
    assert!(!missing.exists());
}
