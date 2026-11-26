use super::*;
use crate::LaneFStageV1;
use crate::PipelineDispositionV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;

#[path = "evaluated_shadow_test_support.rs"]
mod support;
use support::Fixture;
use support::digest;
use support::id;

fn directory(root: &std::path::Path) -> std::fs::File {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(root)
            .expect("flushable fixture directory")
    }
    #[cfg(not(windows))]
    std::fs::File::open(root).expect("flushable fixture directory")
}

struct Ports {
    calls: Vec<LaneFStageV1>,
    intuition: CalibratedIntuitionReceiptV1,
    fail_context: bool,
}
impl Ports {
    fn new(fixture: &Fixture) -> Self {
        Self {
            calls: vec![],
            intuition: decide_calibrated_v2(fixture.intuition.clone()).unwrap(),
            fail_context: false,
        }
    }
    fn call(
        &mut self,
        input: &PortInputV1,
        producer: &str,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.calls.push(input.stage);
        if self.fail_context && input.stage == LaneFStageV1::ContextCompiled {
            return Err(PortFailureV1 {
                class: PortFailureClassV1::Unavailable,
                evidence_digest: digest("context unavailable"),
            });
        }
        let (output_digest, decision) = if input.stage == LaneFStageV1::IntuitionDecided {
            (
                self.intuition.receipt_digest,
                match self.intuition.disposition {
                    CalibratedDispositionV1::Selected(_) => PortDecisionV1::Continue,
                    CalibratedDispositionV1::Abstained(_) => PortDecisionV1::Abstain,
                    CalibratedDispositionV1::SlowPath(_) => PortDecisionV1::SlowPath,
                },
            )
        } else {
            (digest(producer), PortDecisionV1::Continue)
        };
        Ok(PortReceiptV1 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest,
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}
impl LaneFShadowPortsV1 for Ports {
    fn validate_objective(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "objective.compiler")
    }
    fn build_legal_set(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "intelligence.control")
    }
    fn collect_neural_signal(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "neuron.runtime")
    }
    fn build_prompt_portfolio(
        &mut self,
        input: &PortInputV1,
    ) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "prompt.optimizer")
    }
    fn decide_intuition(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "intuition.policy")
    }
    fn compile_context(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "context.compiler")
    }
    fn propose_dispatch(&mut self, input: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        self.call(input, "runtime.agentd")
    }
    fn record_learning(&mut self, _: &PortInputV1) -> Result<PortReceiptV1, PortFailureV1> {
        panic!("a host proposal digest must never substitute for the durable append")
    }
}
fn witness_path(path: &std::path::Path) -> std::path::PathBuf {
    path.with_extension("witness")
}

fn ledger_at(path: &std::path::Path, fixture: &Fixture) -> LedgerWriter {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    let ledger = DurableLedger::create(
        file,
        digest("host-authorized-ledger"),
        /*max_records*/ 1,
    )
    .unwrap();
    let witness = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(witness_path(path))
        .unwrap();
    let witness = LedgerWitnessStore::create(witness, digest("host-authorized-ledger")).unwrap();
    let ledger_directory = directory(path.parent().unwrap());
    let witness_directory = directory(path.parent().unwrap());
    LedgerWriter::from_durable(
        ledger,
        witness,
        fixture.trust_activation(),
        &ledger_directory,
        &witness_directory,
    )
    .unwrap()
}

fn capture_and_reopen(
    ledger: LedgerWriter,
    path: &std::path::Path,
    fixture: &Fixture,
    max_records: usize,
) -> (LedgerWriter, Vec<u8>, Vec<u8>) {
    let anchor = ledger.witness_frontier().unwrap().anchor;
    drop(ledger);
    let ledger_bytes = fs::read(path).unwrap();
    let witness_bytes = fs::read(witness_path(path)).unwrap();
    let recovery = if anchor.sequence == 0 {
        LedgerRecovery::Unacknowledged
    } else {
        LedgerRecovery::Acknowledged(anchor)
    };
    let ledger = DurableLedger::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .unwrap(),
        digest("host-authorized-ledger"),
        max_records,
        recovery,
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(witness_path(path))
            .unwrap(),
        digest("host-authorized-ledger"),
    )
    .unwrap();
    let ledger_directory = directory(path.parent().unwrap());
    let witness_directory = directory(path.parent().unwrap());
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        fixture.trust_activation(),
        &ledger_directory,
        &witness_directory,
    )
    .unwrap();
    (writer, ledger_bytes, witness_bytes)
}

#[test]
fn durable_stage_records_a_decision_and_retries_after_reopen_without_new_bytes() {
    let fixture = Fixture::new();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("ledger");
    let mut ledger = ledger_at(&path, &fixture);
    let mut ports = Ports::new(&fixture);
    let receipt =
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50).unwrap();
    let append = receipt.learning.unwrap();
    assert_eq!(append.disposition, AppendDisposition::Appended);
    assert_eq!(ports.calls.len(), 7);
    assert_eq!(
        receipt.pipeline.disposition,
        PipelineDispositionV1::DispatchProposed
    );
    assert_eq!(
        receipt.pipeline.stages.last().unwrap().output_digest,
        append.chain_digest
    );
    assert_eq!(receipt.pipeline.authority, AuthorityPosture::DENY_ALL);
    let expected_records = ledger.records().unwrap().to_vec();
    let LedgerEvent::AuthenticatedDecisionV2(decision) = &expected_records[0].event else {
        panic!("only an authenticated production Decision")
    };
    assert_eq!(decision.record_id, fixture.run.run_id);
    assert_eq!(decision.selected_candidate_id, id("action"));
    assert_eq!(decision.selected_propensity, ProbabilityQ32::ONE);
    let (mut reopened, original_bytes, original_witness) =
        capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
    assert_eq!(reopened.records().unwrap(), expected_records);
    let replay = run_evaluated_shadow_v1(
        fixture.request(),
        &mut reopened,
        &mut ports,
        /*now*/ 50,
    )
    .unwrap();
    let mut replay_append = replay.learning.unwrap();
    assert_eq!(
        replay_append.disposition,
        AppendDisposition::IdempotentReplay
    );
    replay_append.disposition = AppendDisposition::Appended;
    assert_eq!(replay_append, append);
    assert_eq!(replay.pipeline, receipt.pipeline);
    let (mut reopened, replay_bytes, replay_witness) =
        capture_and_reopen(reopened, &path, &fixture, /*max_records*/ 1);
    assert_eq!(replay_bytes, original_bytes);
    assert_eq!(replay_witness, original_witness);
    let mut drift = fixture.request();
    drift.intuition.sequence += 1;
    drift.decision_evidence =
        fixture.decision_evidence_for(&drift.run, &drift.intuition, &drift.episode_id);
    ports.intuition = decide_calibrated_v2(drift.intuition.clone()).unwrap();
    assert!(matches!(
        run_evaluated_shadow_v1(drift, &mut reopened, &mut ports, /*now*/ 50),
        Err(EvaluatedShadowError::Ledger(
            ProductionLedgerError::Durable(DurableLedgerError::Semantic(_))
        ))
    ));
    let (_, drift_bytes, drift_witness) =
        capture_and_reopen(reopened, &path, &fixture, /*max_records*/ 1);
    assert_eq!(drift_bytes, original_bytes);
    assert_eq!(drift_witness, original_witness);
}

#[test]
fn invalid_authentication_artifact_or_dataset_never_calls_any_port() {
    let mutations: [fn(&mut Fixture); 10] = [
        |f| f.qualification.publication_digest = digest("tampered publication"),
        |f| f.qualification.decision.authentication_digest = digest("tampered authentication"),
        |f| f.candidate_evidence.signature[0] ^= 1,
        |f| f.decision_evidence.signature[0] ^= 1,
        |f| {
            f.bytes[0] ^= 1;
            f.run.snapshot.model_artifact_digest = Digest32::of_bytes(&f.bytes);
        },
        |f| f.run.snapshot.learning_artifact_generation += 1,
        |f| f.run.snapshot.model_artifact_digest = digest("another artifact"),
        |f| f.dataset.inclusion_policy_digest = digest("changed cut"),
        |f| f.qualification.snapshot_ids.push(id("unchecked-snapshot")),
        |f| f.intuition.state_digest = digest("wrong run"),
    ];
    for mutate in mutations {
        let mut fixture = Fixture::new();
        let mut ports = Ports::new(&fixture);
        mutate(&mut fixture);
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("ledger");
        let ledger = ledger_at(&path, &fixture);
        let (mut ledger, before, before_witness) =
            capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
        assert!(
            run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50)
                .is_err()
        );
        assert!(ports.calls.is_empty());
        assert!(ledger.records().unwrap().is_empty());
        let (_, after, after_witness) =
            capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
        assert_eq!(after, before);
        assert_eq!(after_witness, before_witness);
    }
}

#[test]
fn old_signed_evidence_cannot_enter_a_recomputed_new_authority_epoch() {
    let mut fixture = Fixture::new();
    // Keep all attestations unchanged but make the caller's new snapshot and
    // typed intuition internally consistent, so only the trust fence can reject.
    fixture.run.snapshot.authority_epoch += 1;
    fixture.intuition.state_digest = fixture.run.snapshot.digest().unwrap();
    let mut ports = Ports::new(&fixture);
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("ledger");
    let ledger = ledger_at(&path, &fixture);
    let (mut ledger, before, before_witness) =
        capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
    assert!(matches!(
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50,),
        Err(EvaluatedShadowError::Binding("authority epoch"))
    ));
    assert!(ports.calls.is_empty());
    assert!(ledger.records().unwrap().is_empty());
    let (_, after, after_witness) =
        capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
    assert_eq!(after, before);
    assert_eq!(after_witness, before_witness);
}

#[test]
fn tampered_product_receipt_or_expired_candidate_evidence_refuses_all_ports() {
    for case in 0..3 {
        let mut fixture = Fixture::new();
        if case == 0 {
            fixture.qualification.decision.decision.evidence_digest = Digest32::ZERO;
        } else if case == 1 {
            fixture.qualification.publication_digest = Digest32::ZERO;
        }
        let mut ports = Ports::new(&fixture);
        let temp = tempfile::tempdir().unwrap();
        let mut ledger = ledger_at(&temp.path().join("ledger"), &fixture);
        let result = run_evaluated_shadow_v1(
            fixture.request(),
            &mut ledger,
            &mut ports,
            if case == 2 { 95 } else { 50 },
        );
        if case != 2 {
            assert!(matches!(
                result,
                Err(EvaluatedShadowError::Qualification(_))
            ));
        } else {
            assert!(matches!(result, Err(EvaluatedShadowError::Evidence(_))));
        }
        assert!(ports.calls.is_empty());
        assert!(ledger.records().unwrap().is_empty());
    }
}

#[test]
fn host_failure_or_substituted_intuition_never_reaches_the_durable_stage() {
    for corrupt_intuition in [false, true] {
        let fixture = Fixture::new();
        let mut ports = Ports::new(&fixture);
        ports.fail_context = !corrupt_intuition;
        if corrupt_intuition {
            ports.intuition.receipt_digest = digest("fake intuition");
        }
        let temp = tempfile::tempdir().unwrap();
        let mut ledger = ledger_at(&temp.path().join("ledger"), &fixture);
        let receipt =
            run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50)
                .unwrap();
        assert!(matches!(
            receipt.pipeline.disposition,
            PipelineDispositionV1::Failed(_)
        ));
        assert_eq!(receipt.learning, None);
        assert!(ledger.records().unwrap().is_empty());
        assert!(!ports.calls.contains(&LaneFStageV1::DispatchProposed));
    }
}

#[test]
fn ledger_conflict_capacity_and_io_uncertainty_cannot_report_learning_recorded() {
    let fixture = Fixture::new();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("ledger");
    let mut ledger = ledger_at(&path, &fixture);
    let mut ports = Ports::new(&fixture);
    let mut wrong_head = fixture.request();
    wrong_head.expected_ledger_head = digest("unrelated predecessor");
    assert!(matches!(
        run_evaluated_shadow_v1(wrong_head, &mut ledger, &mut ports, /*now*/ 50),
        Err(EvaluatedShadowError::Ledger(
            ProductionLedgerError::Durable(DurableLedgerError::Conflict)
        ))
    ));
    assert!(ledger.records().unwrap().is_empty());
    let receipt =
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50).unwrap();
    let (mut ledger, before, before_witness) =
        capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
    let mut second = fixture.request();
    second.run.run_id = id("second-run");
    second.intuition.decision_id = id("second-run");
    second.episode_id = id("second-episode");
    second.expected_ledger_head = receipt.learning.unwrap().chain_digest;
    second.decision_evidence =
        fixture.decision_evidence_for(&second.run, &second.intuition, &second.episode_id);
    ports.intuition = decide_calibrated_v2(second.intuition.clone()).unwrap();
    assert!(matches!(
        run_evaluated_shadow_v1(second, &mut ledger, &mut ports, /*now*/ 50),
        Err(EvaluatedShadowError::Ledger(
            ProductionLedgerError::Durable(DurableLedgerError::Capacity)
        ))
    ));
    let (_, after, after_witness) =
        capture_and_reopen(ledger, &path, &fixture, /*max_records*/ 1);
    assert_eq!(after, before);
    assert_eq!(after_witness, before_witness);

    let path = temp.path().join("faulted-ledger");
    let mut ledger = ledger_at(&path, &fixture);
    OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(/*size*/ 0)
        .unwrap();
    let mut ports = Ports::new(&fixture);
    assert!(matches!(
        run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50),
        Err(EvaluatedShadowError::Ledger(
            ProductionLedgerError::Durable(DurableLedgerError::Corrupt)
        ))
    ));
    assert!(matches!(
        ledger.records(),
        Err(ProductionLedgerError::Durable(DurableLedgerError::Poisoned))
    ));
}

#[test]
fn abstention_and_slow_path_are_real_decisions_without_dispatch_or_outcome() {
    for slow in [false, true] {
        let mut fixture = Fixture::new();
        if slow {
            fixture.intuition.risk_class = RiskClass::High;
        } else {
            fixture.intuition.candidates[0].legal = false;
            fixture.intuition.completeness.candidate_set_digest =
                codex_hepta_intuition::canonical_candidate_set_digest_v1(
                    &fixture.intuition.candidates,
                )
                .unwrap();
        }
        fixture.resign_decision();
        let mut ports = Ports::new(&fixture);
        let temp = tempfile::tempdir().unwrap();
        let mut ledger = ledger_at(&temp.path().join("ledger"), &fixture);
        let receipt =
            run_evaluated_shadow_v1(fixture.request(), &mut ledger, &mut ports, /*now*/ 50)
                .unwrap();
        assert!(receipt.learning.is_some());
        assert_eq!(ports.calls.len(), 5);
        let expected = if slow {
            PipelineDispositionV1::SlowPath
        } else {
            PipelineDispositionV1::Abstained
        };
        assert_eq!(receipt.pipeline.disposition, expected);
        let records = ledger.records().unwrap();
        assert_eq!(records.len(), 1);
        let LedgerEvent::AuthenticatedDecisionV2(decision) = &records[0].event else {
            panic!("authenticated Decision, never Outcome")
        };
        assert_eq!(
            decision.selected_candidate_id,
            id(if slow { SLOW_PATH } else { ABSTAIN })
        );
        assert_eq!(decision.selected_propensity, ProbabilityQ32::ONE);
    }
}

#[path = "evaluated_shadow_segment_tests.rs"]
mod segmented;
