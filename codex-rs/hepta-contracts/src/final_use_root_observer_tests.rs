use std::collections::BTreeSet;
use std::io::BufRead;
use std::io::BufReader;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::process::CommandExt;
use std::process::Child;
use std::process::ChildStdin;
use std::process::ChildStdout;
use std::process::Command;
use std::process::Stdio;
use std::sync::Mutex;
use std::sync::atomic::AtomicUsize;

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use super::*;
use crate::AuthorityClock;
use crate::AuthorityTrustError;
use crate::FinalUseAuthority;
use crate::FinalUseGrant;
use crate::claim_final_use;
use crate::dispatch_final_use_with_witness;

const CONSUMER_UID: u32 = 65534;
const SIGNER: &str = "root-observer-fixture";
const CHILD: &str = "final_use::store::root_observer::tests::original_non_root_consumer_process";

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(2_000)
    }
}

// Component fixture only. The Root test keeps this anchor separate from the
// child state; it is not a qualification of a production frontier backend.
struct Frontier {
    value: Mutex<FinalUseFrontier>,
    reads: AtomicUsize,
    change_at: AtomicUsize,
}
impl Frontier {
    fn new(value: FinalUseFrontier) -> Self {
        Self {
            value: Mutex::new(value),
            reads: AtomicUsize::new(0),
            change_at: AtomicUsize::new(usize::MAX),
        }
    }
}
impl AuthorityFrontierStore<FinalUseFrontier> for Frontier {
    fn load(&self, _owner_id: &str) -> Result<FinalUseFrontier, AuthorityTrustError> {
        let count = self.reads.fetch_add(1, Ordering::SeqCst) + 1;
        let mut value = self.value.lock().unwrap();
        if count == self.change_at.load(Ordering::SeqCst) {
            value.state_sha256[0] ^= 1;
        }
        Ok(*value)
    }

    fn compare_and_set(
        &self,
        _owner_id: &str,
        expected: &FinalUseFrontier,
        next: &FinalUseFrontier,
    ) -> Result<(), AuthorityTrustError> {
        let mut value = self.value.lock().unwrap();
        if *value != *expected {
            return Err(AuthorityTrustError::Conflict);
        }
        *value = *next;
        Ok(())
    }
}

fn issuer_keys() -> Vec<FinalUseIssuerTrustKey> {
    vec![FinalUseIssuerTrustKey {
        key_id: "fixture-key".into(),
        verifying_key: SigningKey::from_bytes(&[81; 32]).verifying_key().to_bytes(),
        not_before_authority_epoch: 1,
        not_after_authority_epoch: 4,
    }]
}

#[derive(Deserialize, Serialize)]
struct OriginalRecord {
    signed: SignedFinalUseGrant,
    witness: VerifiedUseTokenWitnessV1,
    head: FinalUseRevocations,
    frontier: FinalUseFrontier,
}

#[test]
#[ignore = "child process of the Root-only original consumer fixture"]
fn original_non_root_consumer_process() {
    assert_eq!(rustix::process::geteuid().as_raw(), CONSUMER_UID);
    let directory = PathBuf::from(std::env::var_os("HEPTA_ROOT_OBSERVER_FIXTURE").unwrap());
    let mut head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let frontier = Arc::new(Frontier::new(FinalUseFrontier::for_initial_head(&head).unwrap()));
    assert!(matches!(RootFinalUseObserverV1::open_original(
        &directory, CONSUMER_UID, SIGNER.into(), issuer_keys(), frontier.clone(),
    ), Err(FinalUseError::UnsafeStateDirectory)));
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 0);
    let authority = FinalUseAuthority::open_state_dir_with_issuer_keys(
        &directory,
        SIGNER.into(),
        issuer_keys(),
        head.clone(),
        Arc::new(Clock),
        frontier,
    ).unwrap();
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: SIGNER.into(),
        authority_epoch: 1,
        grant_id: "original-dispatch".into(),
        nonce: [82; 32],
        binding: FinalUseBinding {
            subject_id: "consumer".into(),
            destination_id: "current".into(),
            request_sha256: [83; 32],
            scope_sha256: [84; 32],
            payload_sha256: [85; 32],
        },
        not_before_unix_ms: 1_000,
        expires_at_unix_ms: 3_000,
    };
    let signed = SignedFinalUseGrant {
        signature: SigningKey::from_bytes(&[81; 32]).sign(&grant.signing_bytes().unwrap()).to_bytes().to_vec(),
        grant,
    };
    let token = claim_final_use(&authority, &signed, &signed.grant.binding).unwrap();
    let ((), witness) = dispatch_final_use_with_witness(
        &authority, token, &signed.grant.binding, |_| (),
    ).unwrap();
    loop {
        let record = OriginalRecord {
            signed: signed.clone(),
            witness: witness.clone(),
            head: head.clone(),
            frontier: authority.current_external_frontier().unwrap(),
        };
        println!("ROOT_OBSERVER_FIXTURE {}", serde_json::to_string(&record).unwrap());
        std::io::stdout().flush().unwrap();
        let mut command = String::new();
        std::io::stdin().read_line(&mut command).unwrap();
        match command.trim() {
            "revoke" => {
                head.revision += 1;
                head.revoked_grant_ids.insert(signed.grant.grant_id.clone());
                authority.update_revocations(head.clone()).unwrap();
            }
            "stop" | "" => break,
            other => panic!("unexpected fixture command: {other}"),
        }
    }
}

struct Consumer {
    _root: tempfile::TempDir,
    directory: PathBuf,
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    original: OriginalRecord,
    frontier: Arc<Frontier>,
}

impl Consumer {
    fn start() -> Self {
        assert_eq!(rustix::process::geteuid().as_raw(), 0, "requires actual uid 0");
        let root = tempfile::tempdir().unwrap();
        std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o711)).unwrap();
        let binary = root.path().join("consumer-test");
        std::fs::copy(std::env::current_exe().unwrap(), &binary).unwrap();
        std::fs::set_permissions(&binary, std::fs::Permissions::from_mode(0o755)).unwrap();
        let directory = root.path().join("consumer");
        std::fs::create_dir(&directory).unwrap();
        std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::os::unix::fs::chown(&directory, Some(CONSUMER_UID), Some(CONSUMER_UID)).unwrap();
        let mut child = Command::new(binary)
            .args(["--exact", CHILD, "--ignored", "--nocapture"])
            .env("HEPTA_ROOT_OBSERVER_FIXTURE", &directory)
            .uid(CONSUMER_UID)
            .gid(CONSUMER_UID)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn().unwrap();
        let input = child.stdin.take().unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let original = read_record(&mut output);
        let frontier = Arc::new(Frontier::new(original.frontier));
        Self { _root: root, directory, child, input, output, original, frontier }
    }

    fn observer(&self) -> RootFinalUseObserverV1 {
        RootFinalUseObserverV1::open_original(
            &self.directory, CONSUMER_UID, SIGNER.into(), issuer_keys(), self.frontier.clone(),
        ).unwrap()
    }

    fn verify(&self, observer: &RootFinalUseObserverV1) -> Result<FinalUseRevocations, FinalUseError> {
        observer.verify_original_retained_use(
            &self.original.signed, &self.original.signed.grant.binding, &self.original.witness,
        )
    }

    fn bytes(&self) -> Vec<Vec<u8>> {
        ["authority.lock", "authority.json", "authority.claims"].iter()
            .map(|name| std::fs::read(self.directory.join(name)).unwrap()).collect()
    }
}

impl Drop for Consumer {
    fn drop(&mut self) {
        let _ = self.input.write_all(b"stop\n");
        let _ = self.input.flush();
        let _ = self.child.wait();
    }
}

fn read_record(output: &mut BufReader<ChildStdout>) -> OriginalRecord {
    loop {
        let mut line = String::new();
        assert_ne!(output.read_line(&mut line).unwrap(), 0, "consumer exited before original readback");
        if let Some(record) = line.trim().split_once("ROOT_OBSERVER_FIXTURE ").map(|(_, record)| record) {
            return serde_json::from_str(record).unwrap();
        }
    }
}

#[test]
fn root_observer_rejects_root_consumer_without_creating_state() {
    let directory = tempfile::tempdir().unwrap();
    let frontier = FinalUseFrontier { authority_epoch: 1, revocation_revision: 1, state_sha256: [1; 32] };
    let result = RootFinalUseObserverV1::open_original(
        directory.path(), /*consumer_uid*/ 0, SIGNER.into(), issuer_keys(), Arc::new(Frontier::new(frontier)),
    );
    assert!(matches!(result, Err(FinalUseError::UnsafeStateDirectory)));
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0);
}

#[test]
#[ignore = "requires actual Root and a separate non-Root consumer process"]
fn root_observer_reads_live_original_and_rejects_revocation_without_claiming() {
    let mut consumer = Consumer::start();
    let before = consumer.bytes();
    let empty = consumer._root.path().join("empty-consumer");
    std::fs::create_dir(&empty).unwrap();
    std::fs::set_permissions(&empty, std::fs::Permissions::from_mode(0o700)).unwrap();
    std::os::unix::fs::chown(&empty, Some(CONSUMER_UID), Some(CONSUMER_UID)).unwrap();
    assert!(matches!(RootFinalUseObserverV1::open_original(
        &empty, CONSUMER_UID, SIGNER.into(), issuer_keys(), consumer.frontier.clone(),
    ), Err(FinalUseError::Unavailable)));
    assert_eq!(std::fs::read_dir(&empty).unwrap().count(), 0);
    let mut different_trust = issuer_keys();
    different_trust[0].key_id = "different-enrollment".into();
    assert!(matches!(RootFinalUseObserverV1::open_original(
        &consumer.directory, CONSUMER_UID, SIGNER.into(), different_trust, consumer.frontier.clone(),
    ), Err(FinalUseError::InvalidTrust)));
    let observer = consumer.observer();
    assert_eq!((observer.consumer_uid(), observer.signer_id()), (CONSUMER_UID, SIGNER));
    let original_state: StoredV3 = serde_json::from_slice(&before[1]).unwrap();
    assert_eq!(original_state.trust, StoreTrust::IssuerKeyRing(observer.issuer_trust_digest()));
    assert_eq!(consumer.verify(&observer), Ok(consumer.original.head.clone()));
    let mut unconsumed = consumer.original.signed.clone();
    unconsumed.grant.nonce = [91; 32];
    unconsumed.signature = SigningKey::from_bytes(&[81; 32])
        .sign(&unconsumed.grant.signing_bytes().unwrap()).to_bytes().to_vec();
    assert_eq!(observer.verify_original_retained_use(&unconsumed, &unconsumed.grant.binding, &consumer.original.witness), Err(FinalUseError::InvalidGrant));
    unconsumed.signature[0] ^= 1;
    assert_eq!(observer.verify_original_retained_use(&unconsumed, &unconsumed.grant.binding, &consumer.original.witness), Err(FinalUseError::InvalidSignature));
    let mut wrong_entry = consumer.original.witness.clone();
    wrong_entry.verified_at_unix_ms = consumer.original.signed.grant.expires_at_unix_ms;
    assert_eq!(observer.verify_original_retained_use(&consumer.original.signed, &consumer.original.signed.grant.binding, &wrong_entry), Err(FinalUseError::BindingMismatch));
    assert_eq!(consumer.verify(&observer), Ok(consumer.original.head.clone()));
    assert_eq!(consumer.bytes(), before);
    consumer.input.write_all(b"revoke\n").unwrap();
    consumer.input.flush().unwrap();
    consumer.original = read_record(&mut consumer.output);
    *consumer.frontier.value.lock().unwrap() = consumer.original.frontier;
    assert_eq!(consumer.verify(&observer), Err(FinalUseError::Unavailable));
    let after = consumer.bytes();
    assert_eq!(consumer.verify(&consumer.observer()), Err(FinalUseError::Revoked));
    assert_eq!(consumer.bytes(), after);
}

#[test]
#[ignore = "requires actual Root and a separate non-Root consumer process"]
fn root_observer_fences_partial_rollback_schema_and_replaced_original_files() {
    let consumer = Consumer::start();
    let original = consumer.bytes();
    #[derive(Debug, Copy, Clone)]
    enum Mutation { Partial, Rollback, Schema, Replace, Frontier }
    for mutation in [Mutation::Partial, Mutation::Rollback, Mutation::Schema, Mutation::Replace, Mutation::Frontier] {
        let observer = consumer.observer();
        let claims = consumer.directory.join("authority.claims");
        let snapshot = consumer.directory.join("authority.json");
        let saved = consumer.directory.join("saved.claims");
        match mutation {
            Mutation::Partial => {
                let mut bytes = original[2].clone();
                bytes.push(1);
                std::fs::write(&claims, bytes).unwrap();
            }
            Mutation::Rollback => std::fs::write(&claims, []).unwrap(),
            Mutation::Schema => {
                let mut value: serde_json::Value = serde_json::from_slice(&original[1]).unwrap();
                value["schema"] = serde_json::json!(2);
                std::fs::write(&snapshot, serde_json::to_vec(&value).unwrap()).unwrap();
            }
            Mutation::Replace => {
                std::fs::rename(&claims, &saved).unwrap();
                std::fs::write(&claims, &original[2]).unwrap();
                std::fs::set_permissions(&claims, std::fs::Permissions::from_mode(0o600)).unwrap();
                std::os::unix::fs::chown(&claims, Some(CONSUMER_UID), Some(CONSUMER_UID)).unwrap();
            }
            Mutation::Frontier => consumer.frontier.change_at.store(
                consumer.frontier.reads.load(Ordering::SeqCst) + 2, Ordering::SeqCst,
            ),
        }
        let changed = consumer.bytes();
        let expected = match mutation {
            Mutation::Partial | Mutation::Schema => FinalUseError::InvalidTrust,
            Mutation::Rollback | Mutation::Frontier => FinalUseError::AntiRollbackViolation,
            Mutation::Replace => FinalUseError::Unavailable,
        };
        assert_eq!(consumer.verify(&observer), Err(expected), "accepted {mutation:?}");
        assert_eq!(consumer.bytes(), changed, "observer repaired {mutation:?}");
        if matches!(mutation, Mutation::Replace) {
            std::fs::remove_file(&claims).unwrap();
            std::fs::rename(&saved, &claims).unwrap();
        } else {
            std::fs::write(&claims, &original[2]).unwrap();
        }
        std::fs::write(&snapshot, &original[1]).unwrap();
        *consumer.frontier.value.lock().unwrap() = consumer.original.frontier;
        assert_eq!(consumer.verify(&observer), Err(FinalUseError::Unavailable));
        assert_eq!(consumer.verify(&consumer.observer()), Ok(consumer.original.head.clone()));
    }
}
