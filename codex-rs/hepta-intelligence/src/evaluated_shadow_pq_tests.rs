//! Real PQ authentication and original product/ledger owners, with deterministic
//! proposal ports and an independently retained test frontier. Fixture bytes
//! and in-memory services do not establish model quality or deployment readiness.
use super::super::Ports;
use super::super::open_ledger_directory;
use super::super::witness_path;
use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

const PQ: LearningAuthenticationProfile = LearningAuthenticationProfile::MlDsa65V2;

// Kept outside the durable ledger and witness, and retained across their reopen.
// This tests the independent interface; it is not a production persistence host.
struct TestFrontier {
    binding: Digest32,
    current: Mutex<LearningTrustFrontier>,
    reads: AtomicUsize,
}

impl TestFrontier {
    fn new(trust: &ActivatedLearningTrustV1) -> Arc<Self> {
        Arc::new(Self {
            binding: digest("host-authorized-ledger"),
            current: Mutex::new(learning_trust_frontier(trust)),
            reads: AtomicUsize::new(0),
        })
    }
}

impl AuthorityFrontierStore<LearningTrustFrontier> for TestFrontier {
    fn load(&self, owner_id: &str) -> Result<LearningTrustFrontier, AuthorityTrustError> {
        if owner_id != format!("hepta-learning-trust:{}", self.binding) {
            return Err(AuthorityTrustError::Invalid);
        }
        self.reads.fetch_add(1, Ordering::Relaxed);
        self.current
            .lock()
            .map(|current| *current)
            .map_err(|_| AuthorityTrustError::Unavailable)
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &LearningTrustFrontier,
        next: &LearningTrustFrontier,
    ) -> Result<(), AuthorityTrustError> {
        if owner_id != format!("hepta-learning-trust:{}", self.binding) {
            return Err(AuthorityTrustError::Invalid);
        }
        let mut current = self
            .current
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)?;
        if *current != *expected
            || next.root_digest != expected.root_digest
            || Some(next.generation) != expected.generation.checked_add(1)
            || next.authority_epoch < expected.authority_epoch
        {
            return Err(AuthorityTrustError::Conflict);
        }
        *current = *next;
        Ok(())
    }
}

fn pq_ledger_at(
    path: &Path,
    trust: ActivatedLearningTrustV1,
    frontier: Arc<TestFrontier>,
) -> LedgerWriter {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    let ledger = DurableLedger::create_with_authentication_profile(
        file,
        frontier.binding,
        /*max_records*/ 1,
        PQ,
    )
    .unwrap();
    let witness = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(witness_path(path))
        .unwrap();
    let witness =
        LedgerWitnessStore::create_with_authentication_profile(witness, frontier.binding, PQ)
            .unwrap();
    let directory = open_ledger_directory(path.parent().unwrap());
    LedgerWriter::from_durable_with_trust_frontier(
        ledger, witness, trust, &directory, &directory, frontier,
    )
    .unwrap()
}

fn existing_file(path: &Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .unwrap()
}

fn classical_proof(evidence: &SignedLearningEvidenceV1, seed: u8) -> SignedLearningEvidenceV1 {
    let key = FixtureSigner::from_seed(LearningAuthenticationProfile::ClassicalV1, seed);
    let mut proof = evidence.clone();
    proof.signature = key.placeholder();
    proof.signature = key.sign(&proof.signing_bytes());
    // A real classic signature over the downgraded message, not random bytes.
    key.verification_key()
        .verify(&proof.signing_bytes(), &proof.signature)
        .unwrap();
    proof
}

#[test]
fn pq_qualification_reaches_durable_shadow_and_exact_replay_in_its_own_history() {
    // with_profile uses root activation before the original qualification runner.
    // The opaque receipt is produced by qualify_and_persist, never fabricated.
    let fixture = Fixture::with_profile(PQ);
    let classic = Fixture::new();
    let trust = fixture.trust_activation();
    let classic_trust = classic.trust_activation();
    let (root, distribution) = signed_trust_distribution(&fixture.trust);
    assert_eq!(root.verifying_key.profile(), PQ);
    assert_eq!(distribution.signature.profile(), PQ);
    assert_eq!(distribution.signature.len(), 3309);
    assert_eq!(fixture.verifier.authentication_profile(), PQ);
    assert_eq!(fixture.candidate_evidence.signature.profile(), PQ);
    assert_eq!(fixture.decision_evidence.signature.profile(), PQ);
    assert!(
        fixture
            .trust
            .signers
            .iter()
            .all(|signer| signer.verifying_key.profile() == PQ)
    );
    assert_eq!(trust.root_id(), classic_trust.root_id());
    assert_eq!(trust.distribution_id(), classic_trust.distribution_id());
    assert_ne!(trust.root_digest(), classic_trust.root_digest());
    assert_ne!(
        trust.distribution_digest(),
        classic_trust.distribution_digest()
    );
    assert_ne!(
        trust.verifier().trust_digest(),
        classic_trust.verifier().trust_digest()
    );
    assert_eq!(
        fixture.qualification.decision.trust_digest,
        trust.verifier().trust_digest()
    );
    fixture.qualification.validate_integrity().unwrap();

    let classic_root_key =
        FixtureSigner::from_seed(LearningAuthenticationProfile::ClassicalV1, /*seed*/ 99);
    let mut wrong_root = root.clone();
    wrong_root.verifying_key = classic_root_key.verification_key();
    assert!(matches!(
        activate_learning_trust(
            &wrong_root,
            distribution.clone(),
            /*previous*/ None,
            /*now*/ 50
        ),
        Err(LearningTrustDistributionError::InvalidRoot)
    ));
    let mut downgraded_distribution = distribution;
    downgraded_distribution.signature =
        classic_root_key.sign(&downgraded_distribution.signing_bytes().unwrap());
    assert!(matches!(
        activate_learning_trust(
            &root,
            downgraded_distribution,
            /*previous*/ None,
            /*now*/ 50
        ),
        Err(LearningTrustDistributionError::InvalidSignature)
    ));

    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("pq-ledger");
    let frontier = TestFrontier::new(&trust);
    let mut writer = pq_ledger_at(&path, trust.clone(), frontier.clone());
    let mut ports = Ports::new(&fixture);
    let receipt =
        run_evaluated_shadow_v1(fixture.request(), &mut writer, &mut ports, /*now*/ 50).unwrap();
    let append = receipt.learning.as_ref().unwrap();
    assert_eq!(append.disposition, AppendDisposition::Appended);
    assert_eq!(ports.calls.len(), 7);
    assert_eq!(
        receipt.pipeline.disposition,
        PipelineDispositionV1::DispatchProposed
    );
    assert_eq!(receipt.pipeline.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(writer.verifier().authentication_profile(), PQ);
    assert_eq!(writer.snapshot().unwrap().authentication_profile(), PQ);
    assert_eq!(
        writer.trust_distribution_digest(),
        trust.distribution_digest()
    );
    let expected_records = writer.records().unwrap();
    let LedgerEvent::AuthenticatedDecisionV2(decision) = &expected_records[0].event else {
        panic!("the original product writer must append an authenticated Decision")
    };
    assert_eq!(decision.record_id, fixture.run.run_id);
    assert_eq!(decision.selected_candidate_id, id("action"));
    let recovery = LedgerRecovery::Acknowledged(LedgerAnchor {
        sequence: append.sequence.get(),
        chain_digest: append.chain_digest,
    });
    drop(writer);
    let ledger_bytes = fs::read(&path).unwrap();
    let witness_bytes = fs::read(witness_path(&path)).unwrap();
    assert_eq!(&ledger_bytes[..8], b"HEPTLP02");
    assert_eq!(&witness_bytes[..8], b"HEPTWP02");
    assert!(matches!(
        DurableLedger::recover(
            existing_file(&path),
            frontier.binding,
            /*max_records*/ 1,
            recovery
        ),
        Err(DurableLedgerError::Corrupt)
    ));
    assert!(matches!(
        LedgerWitnessStore::recover(existing_file(&witness_path(&path)), frontier.binding),
        Err(DurableLedgerError::BindingMismatch)
    ));
    let ledger = DurableLedger::recover_with_authentication_profile(
        existing_file(&path),
        frontier.binding,
        /*max_records*/ 1,
        recovery,
        PQ,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover_with_authentication_profile(
        existing_file(&witness_path(&path)),
        frontier.binding,
        PQ,
    )
    .unwrap();
    let parent = open_ledger_directory(directory.path());
    let mut reopened = LedgerWriter::from_durable_with_trust_frontier(
        ledger,
        witness,
        trust,
        &parent,
        &parent,
        frontier.clone(),
    )
    .unwrap();
    let mut replay_ports = Ports::new(&fixture);
    let mut replay = run_evaluated_shadow_v1(
        fixture.request(),
        &mut reopened,
        &mut replay_ports,
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(
        replay.learning.as_ref().unwrap().disposition,
        AppendDisposition::IdempotentReplay
    );
    replay.learning.as_mut().unwrap().disposition = AppendDisposition::Appended;
    assert_eq!(replay, receipt);
    assert_eq!(reopened.records().unwrap(), expected_records);
    assert!(frontier.reads.load(Ordering::Relaxed) > 0);
    drop(reopened);
    assert_eq!(fs::read(&path).unwrap(), ledger_bytes);
    assert_eq!(fs::read(witness_path(&path)).unwrap(), witness_bytes);
}

#[test]
fn pq_candidate_and_generator_proofs_cannot_bypass_verification_via_exact_replay() {
    let fixture = Fixture::with_profile(PQ);
    let trust = fixture.trust_activation();
    let frontier = TestFrontier::new(&trust);
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("pq-ledger");
    let mut writer = pq_ledger_at(&path, trust, frontier.clone());
    run_evaluated_shadow_v1(
        fixture.request(),
        &mut writer,
        &mut Ports::new(&fixture),
        /*now*/ 50,
    )
    .unwrap();
    let expected_records = writer.records().unwrap();
    let ledger_bytes = fs::read(&path).unwrap();
    let witness_bytes = fs::read(witness_path(&path)).unwrap();
    let mut bad_candidate = fixture.candidate_evidence.clone();
    bad_candidate.signature[0] ^= 1;
    let mut bad_generator = fixture.decision_evidence.clone();
    bad_generator.signature[0] ^= 1;
    let cases = [
        (bad_candidate, fixture.decision_evidence.clone()),
        (
            classical_proof(&fixture.candidate_evidence, /*seed*/ 22),
            fixture.decision_evidence.clone(),
        ),
        (fixture.candidate_evidence.clone(), bad_generator),
        (
            fixture.candidate_evidence.clone(),
            classical_proof(&fixture.decision_evidence, /*seed*/ 11),
        ),
    ];
    for (candidate, generator) in cases {
        let mut request = fixture.request();
        request.candidate_evidence = &candidate;
        request.decision_evidence = generator;
        let mut ports = Ports::new(&fixture);
        assert!(matches!(
            run_evaluated_shadow_v1(request, &mut writer, &mut ports, /*now*/ 50),
            Err(EvaluatedShadowError::Evidence(
                SignedEvidenceError::InvalidSignature
            ))
        ));
        assert!(ports.calls.is_empty());
        assert_eq!(writer.records().unwrap(), expected_records);
        assert_eq!(fs::read(&path).unwrap(), ledger_bytes);
        assert_eq!(fs::read(witness_path(&path)).unwrap(), witness_bytes);
    }
    // A retained independent floor change also invalidates an otherwise exact
    // replay before ports run; the old local files cannot restore its authority.
    frontier.current.lock().unwrap().generation += 1;
    let mut ports = Ports::new(&fixture);
    assert!(
        run_evaluated_shadow_v1(fixture.request(), &mut writer, &mut ports, /*now*/ 50,).is_err()
    );
    assert!(ports.calls.is_empty());
    assert_eq!(writer.records().unwrap(), expected_records);
    assert_eq!(fs::read(&path).unwrap(), ledger_bytes);
    assert_eq!(fs::read(witness_path(&path)).unwrap(), witness_bytes);
}
