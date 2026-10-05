use std::fs::File;
use std::fs::OpenOptions;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_learning_ledger::ActivatedLearningTrustV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::RetrievalAssignmentFact;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use tokio::sync::Notify;

use super::CognitiveRetrievalLearningSink;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn trusted(
    name: &str,
    controller: &str,
    seed: u8,
    role: LearningEvidenceRoleV1,
) -> TrustedLearningSignerV1 {
    let key = SigningKey::from_bytes(&[seed; 32]);
    TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 100,
        },
        controller_id: id(controller),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    }
}

fn activated_trust() -> ActivatedLearningTrustV1 {
    let trust = LearningEvidenceTrustV1 {
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        signers: vec![
            trusted(
                "generator",
                "generator-controller",
                1,
                LearningEvidenceRoleV1::Generator,
            ),
            trusted(
                "observer",
                "observer-controller",
                2,
                LearningEvidenceRoleV1::Observer,
            ),
            trusted(
                "allocator",
                "allocator-controller",
                3,
                LearningEvidenceRoleV1::CreditAllocator,
            ),
            trusted(
                "evaluator",
                "evaluator-controller",
                4,
                LearningEvidenceRoleV1::Evaluator,
            ),
            trusted(
                "privacy-owner",
                "privacy-controller",
                5,
                LearningEvidenceRoleV1::UnlearningAuthority,
            ),
        ],
    };
    let key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("learning-root"),
        scope_digest: digest("scope"),
        verifying_key: key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 200,
        revoked_at: None,
    };
    let mut signed = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust-distribution"),
            generation: 1,
            effective_at: 20,
            trust,
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 90,
        signature: [0; 64],
    };
    signed.signature = key
        .sign(&signed.signing_bytes().expect("signing bytes"))
        .to_bytes();
    activate_learning_trust(&root, signed, None, 50).expect("activate trust")
}

pub(crate) fn sink() -> (tempfile::TempDir, CognitiveRetrievalLearningSink) {
    let temp = tempfile::tempdir().expect("temp");
    let binding = digest("agentd-retrieval-learning");
    let ledger_path = temp.path().join("learning.ledger");
    let witness_path = temp.path().join("learning.witness");
    let ledger_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&ledger_path)
        .expect("ledger file");
    let witness_file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(&witness_path)
        .expect("witness file");
    let ledger = DurableLedger::create(ledger_file, binding, 128).expect("ledger");
    let witness = LedgerWitnessStore::create(witness_file, binding).expect("witness");
    let ledger_directory = File::open(temp.path()).expect("ledger directory");
    let witness_directory = File::open(temp.path()).expect("witness directory");
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        activated_trust(),
        &ledger_directory,
        &witness_directory,
    )
    .expect("product writer");
    (temp, CognitiveRetrievalLearningSink::new(writer))
}

pub(crate) fn assignments(sink: &CognitiveRetrievalLearningSink) -> Vec<RetrievalAssignmentFact> {
    sink.writer
        .lock()
        .expect("learning writer lock")
        .snapshot()
        .expect("durable learning snapshot")
        .records()
        .iter()
        .map(|record| {
            let LedgerEvent::RetrievalAssignment(assignment) = &record.event else {
                panic!("context attempt must record only a retrieval assignment");
            };
            assignment.clone()
        })
        .collect()
}

pub(crate) struct GatedSink {
    pub(crate) sink: Arc<CognitiveRetrievalLearningSink>,
    pub(crate) append_entered: Arc<Notify>,
    release: Arc<Notify>,
    holder: tokio::task::JoinHandle<()>,
}

impl GatedSink {
    pub(crate) async fn release(self) {
        self.release.notify_one();
        self.holder
            .await
            .expect("release the real ledger writer lock");
    }
}

pub(crate) async fn gated_sink() -> (tempfile::TempDir, GatedSink) {
    let (temp, mut sink) = sink();
    let append_entered = Arc::new(Notify::new());
    sink.append_entered = Some(Arc::clone(&append_entered));
    let sink = Arc::new(sink);
    let held = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let held_signal = Arc::clone(&held);
    let release_signal = Arc::clone(&release);
    let blocked_sink = Arc::clone(&sink);
    let holder = tokio::task::spawn_blocking(move || {
        let _writer = blocked_sink.writer.lock().expect("real ledger writer lock");
        held_signal.notify_one();
        tokio::runtime::Handle::current()
            .block_on(tokio::time::timeout(
                Duration::from_secs(20),
                release_signal.notified(),
            ))
            .expect("the controlled learning writer must be released");
    });
    tokio::time::timeout(Duration::from_secs(10), held.notified())
        .await
        .expect("hold the real learning writer before starting the context read");
    (
        temp,
        GatedSink {
            sink,
            append_entered,
            release,
            holder,
        },
    )
}
