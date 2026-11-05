use super::*;
use crate::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn binding() -> Digest32 {
    digest("committed-reconciliation-ledger")
}

#[derive(Clone, Copy)]
enum Source {
    Generator,
    Observer,
}

fn signer(source: Source) -> (TrustedLearningSignerV1, SigningKey) {
    let (name, seed, role) = match source {
        Source::Generator => ("generator", 1, LearningEvidenceRoleV1::Generator),
        Source::Observer => ("observer", 2, LearningEvidenceRoleV1::Observer),
    };
    let key = SigningKey::from_bytes(&[seed; 32]);
    let signer = TrustedLearningSignerV1 {
        principal: AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("scope"),
            authority_epoch: 7,
            authenticated_at: 10,
            expires_at: 200,
        },
        controller_id: id(&format!("{name}-controller")),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    };
    (signer, key)
}

fn activated_trust(now: u64) -> ActivatedLearningTrustV1 {
    let root_key = SigningKey::from_bytes(&[99; 32]);
    let root = LearningTrustRootV1 {
        root_id: id("root"),
        scope_digest: digest("scope"),
        verifying_key: root_key.verifying_key().to_bytes(),
        valid_from: 1,
        expires_at: 300,
        revoked_at: None,
    };
    let mut distribution = SignedLearningTrustDistributionV1 {
        distribution: LearningTrustDistributionV1 {
            distribution_id: id("trust"),
            generation: 1,
            effective_at: 20,
            trust: LearningEvidenceTrustV1 {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
                authority_epoch: 7,
                signers: vec![signer(Source::Generator).0, signer(Source::Observer).0],
            },
        },
        root_id: root.root_id.clone(),
        issued_at: 15,
        expires_at: 200,
        signature: [0; 64],
    };
    distribution.signature = root_key
        .sign(&distribution.signing_bytes().unwrap())
        .to_bytes();
    activate_learning_trust(&root, distribution, /*previous*/ None, now).unwrap()
}

fn sign(writer: &LedgerWriter, source: Source, payload: &[u8]) -> SignedLearningEvidenceV1 {
    let (signer, key) = signer(source);
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("evidence-{}", signer.principal.principal_id)),
        principal_id: signer.principal.principal_id,
        role: signer.roles[0],
        trust_digest: writer.verifier().trust_digest(),
        scope_digest: digest("scope"),
        objective_digest: digest("objective"),
        authority_epoch: 7,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let fixture = Self(std::env::temp_dir().join(format!(
            "hepta-committed-reconciliation-{}-{serial}",
            std::process::id()
        )));
        fs::create_dir(&fixture.0).unwrap();
        File::create(fixture.0.join("ledger")).unwrap();
        File::create(fixture.0.join("witness")).unwrap();
        drop(DurableLedger::create(fixture.file("ledger"), binding(), /*max_records*/ 16).unwrap());
        drop(LedgerWitnessStore::create(fixture.file("witness"), binding()).unwrap());
        fixture
    }

    fn file(&self, name: &str) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.0.join(name))
            .unwrap()
    }

    fn reopen(&self, witness: File, now: u64) -> LedgerWriter {
        let witness = LedgerWitnessStore::recover(witness, binding()).unwrap();
        let anchor = witness.frontier().unwrap().anchor;
        let recovery = if anchor.sequence == 0 {
            LedgerRecovery::Unacknowledged
        } else {
            LedgerRecovery::Acknowledged(anchor)
        };
        let ledger = DurableLedger::recover(
            self.file("ledger"),
            binding(),
            /*max_records*/ 16,
            recovery,
        )
        .unwrap();
        #[cfg(windows)]
        let directory = {
            use std::os::windows::fs::OpenOptionsExt;
            OpenOptions::new()
                .read(true)
                .write(true)
                .custom_flags(0x0200_0000)
                .open(&self.0)
                .unwrap()
        };
        #[cfg(not(windows))]
        let directory = File::open(&self.0).unwrap();
        LedgerWriter::from_durable(
            ledger,
            witness,
            activated_trust(now),
            &directory,
            &directory,
        )
        .unwrap()
    }

    fn lengths(&self) -> (u64, u64) {
        (
            fs::metadata(self.0.join("ledger")).unwrap().len(),
            fs::metadata(self.0.join("witness")).unwrap().len(),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn append_fact(
    writer: &mut LedgerWriter,
    source: Source,
    predecessor: Digest32,
    now: u64,
) -> Result<AppendReceipt, ProductionLedgerError> {
    match source {
        Source::Generator => {
            let candidates = vec![id("action"), id("abstain")];
            let request = ProductionDecisionV2 {
                record_id: id("decision"),
                episode_id: id("episode"),
                run_snapshot_digest: digest("run"),
                objective_digest: digest("objective"),
                policy_digest: digest("policy"),
                candidate_ids: candidates.clone(),
                selected_candidate_id: id("action"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompletenessReceiptV1 {
                    set_id: id("candidate-set"),
                    state_digest: digest("state"),
                    generator_id: id("generator"),
                    generator_code_digest: digest("generator-code"),
                    grammar_digest: digest("grammar"),
                    hard_filter_digest: digest("filter"),
                    truncation_digest: digest("truncation"),
                    candidates_digest: candidate_ids_digest_v2(&candidates),
                    candidate_count: 2,
                    omitted_count_bound: 0,
                    canonical_order_digest: candidate_order_digest_v2(&candidates),
                    complete_for_generator: true,
                },
                support_digest: digest("decision-support"),
            };
            let proof = sign(
                writer,
                source,
                &decision_signing_payload_v2(&request).unwrap(),
            );
            writer.append_decision(predecessor, request, &proof, now)
        }
        Source::Observer => {
            let request = AuthenticatedOutcomeV1 {
                record_id: id("outcome"),
                outcome_id: id("observation"),
                episode_id: id("episode"),
                observer: signer(source).0.principal,
                observed_at: Some(40),
                value: Some(FixedQ32::from_raw(1)),
                unit_profile_digest: digest("units"),
                support_digest: digest("outcome-support"),
                watermark: OutcomeWatermarkV1 {
                    latest_observable_at: 45,
                    expected_delay_profile_digest: digest("delay"),
                    terminality: OutcomeTerminalityV1::Terminal,
                    censoring_reason: None,
                    correction_predecessor: None,
                    finalized_at: Some(46),
                },
            };
            let proof = sign(writer, source, &outcome_signing_payload_v2(&request));
            writer.append_outcome(predecessor, request, &proof, now)
        }
    }
}

fn reference(record: &LedgerRecord) -> CommittedLearningAppendV1 {
    CommittedLearningAppendV1 {
        ledger_binding: binding(),
        record_id: record.event.record_id().clone(),
        event_digest: record.event_digest,
        predecessor_chain_digest: record.predecessor_chain_digest,
    }
}

fn assert_lost_ack_recovery(source: Source) {
    let fixture = Fixture::new();
    let predecessor = match source {
        Source::Generator => Digest32::ZERO,
        Source::Observer => {
            let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 50);
            append_fact(
                &mut writer,
                Source::Generator,
                Digest32::ZERO,
                /*now*/ 50,
            )
            .unwrap()
            .chain_digest
        }
    };
    // Inject failure at the witness write boundary. The real ledger append and
    // sync still finish, and the existing witness file and lock never change.
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 50);
    writer.witness.fail_next_advance_write_for_test();
    let receipt = match append_fact(&mut writer, source, predecessor, /*now*/ 50) {
        Err(ProductionLedgerError::IndeterminateAfterLedgerCommit { receipt, .. }) => receipt,
        result => panic!("expected committed ledger and failed witness: {result:?}"),
    };
    let snapshot = writer.snapshot().unwrap();
    let lengths = fixture.lengths();
    let pending = reference(snapshot.records().last().unwrap());
    assert!(matches!(
        writer.reconcile_committed_append(&pending),
        Err(ProductionLedgerError::Durable(DurableLedgerError::Poisoned))
    ));
    drop(writer);

    // Trust is freshly activated at the recovery time; only the old proof expired.
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 91);
    assert!(matches!(
        append_fact(&mut writer, source, predecessor, /*now*/ 91),
        Err(ProductionLedgerError::Evidence(
            SignedEvidenceError::ValidityWindow
        ))
    ));
    assert_eq!(writer.snapshot().unwrap(), snapshot);
    assert_eq!(fixture.lengths(), lengths);
    if let Source::Observer = source {
        assert!(matches!(
            writer.reconcile_committed_append(&reference(&snapshot.records()[0])),
            Err(ProductionLedgerError::WitnessLag)
        ));
    }
    let expected = AppendReceipt {
        disposition: AppendDisposition::IdempotentReplay,
        ..receipt
    };
    assert_eq!(
        writer.reconcile_committed_append(&pending).unwrap(),
        expected
    );
    assert_eq!(
        writer.witness_frontier().unwrap().anchor,
        LedgerAnchor {
            sequence: expected.sequence.get(),
            chain_digest: expected.chain_digest
        }
    );
    assert_eq!(writer.snapshot().unwrap(), snapshot);
    let witnessed_lengths = fixture.lengths();
    assert_eq!(witnessed_lengths.0, lengths.0);
    assert_eq!(
        writer.reconcile_committed_append(&pending).unwrap(),
        expected
    );
    assert_eq!(fixture.lengths(), witnessed_lengths);
    drop(writer);
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 91);
    assert_eq!(
        writer.reconcile_committed_append(&pending).unwrap(),
        expected
    );
    assert_eq!(writer.snapshot().unwrap(), snapshot);
    assert_eq!(fixture.lengths(), witnessed_lengths);
}

#[test]
fn committed_decision_recovers_after_lost_ack_expiry_and_reopen() {
    assert_lost_ack_recovery(Source::Generator);
}

#[test]
fn committed_outcome_recovers_after_lost_ack_expiry_and_reopen() {
    assert_lost_ack_recovery(Source::Observer);
}

#[test]
fn mismatched_or_missing_committed_reference_never_writes() {
    let fixture = Fixture::new();
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 50);
    let missing = CommittedLearningAppendV1 {
        ledger_binding: binding(),
        record_id: id("decision"),
        event_digest: digest("absent"),
        predecessor_chain_digest: Digest32::ZERO,
    };
    let empty = writer.snapshot().unwrap();
    let empty_lengths = fixture.lengths();
    assert!(matches!(
        writer.reconcile_committed_append(&missing),
        Err(ProductionLedgerError::Binding(_))
    ));
    assert_eq!(writer.snapshot().unwrap(), empty);
    assert_eq!(fixture.lengths(), empty_lengths);
    append_fact(
        &mut writer,
        Source::Generator,
        Digest32::ZERO,
        /*now*/ 50,
    )
    .unwrap();
    let snapshot = writer.snapshot().unwrap();
    let lengths = fixture.lengths();
    let expected = reference(&snapshot.records()[0]);
    for mismatch in [
        CommittedLearningAppendV1 {
            ledger_binding: digest("another-ledger"),
            ..expected.clone()
        },
        CommittedLearningAppendV1 {
            record_id: id("another-record"),
            ..expected.clone()
        },
        CommittedLearningAppendV1 {
            event_digest: digest("another-event"),
            ..expected.clone()
        },
        CommittedLearningAppendV1 {
            predecessor_chain_digest: digest("another-predecessor"),
            ..expected
        },
    ] {
        assert!(matches!(
            writer.reconcile_committed_append(&mismatch),
            Err(ProductionLedgerError::Binding(_))
        ));
        assert_eq!(writer.snapshot().unwrap(), snapshot);
        assert_eq!(fixture.lengths(), lengths);
    }
}

#[test]
fn reconciliation_neither_revives_revoked_decision_nor_admits_other_event_kinds() {
    let fixture = Fixture::new();
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 50);
    let receipt = append_fact(
        &mut writer,
        Source::Generator,
        Digest32::ZERO,
        /*now*/ 50,
    )
    .unwrap();
    writer
        .verify_active_decision_binding(&id("decision"), &id("episode"))
        .unwrap();
    writer
        .commit(
            receipt.chain_digest,
            LedgerEvent::Revocation(Revocation {
                record_id: id("revocation"),
                target_record_id: id("decision"),
                authority_id: id("revocation-owner"),
                reason_digest: digest("revoked"),
            }),
        )
        .unwrap();
    drop(writer);
    let mut writer = fixture.reopen(fixture.file("witness"), /*now*/ 91);
    let snapshot = writer.snapshot().unwrap();
    let lengths = fixture.lengths();
    assert!(
        writer
            .verify_active_decision_binding(&id("decision"), &id("episode"))
            .is_err()
    );
    assert!(matches!(
        writer.reconcile_committed_append(&reference(&snapshot.records()[1])),
        Err(ProductionLedgerError::Binding(_))
    ));
    assert_eq!(
        writer
            .reconcile_committed_append(&reference(&snapshot.records()[0]))
            .unwrap(),
        AppendReceipt {
            disposition: AppendDisposition::IdempotentReplay,
            ..receipt
        }
    );
    assert!(
        writer
            .verify_active_decision_binding(&id("decision"), &id("episode"))
            .is_err()
    );
    assert_eq!(writer.snapshot().unwrap(), snapshot);
    assert_eq!(fixture.lengths(), lengths);
}
