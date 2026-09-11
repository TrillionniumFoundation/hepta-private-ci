use super::*;
use crate::LaneFStageV1;
use crate::PipelineDispositionV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;

#[path = "evaluated_shadow_test_support.rs"]
mod support;
use support::Fixture;
use support::digest;
use support::id;

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
fn ledger_at(path: &std::path::Path) -> DurableLedger {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .unwrap();
    DurableLedger::create(
        file,
        digest("host-authorized-ledger"),
        /*max_records*/ 1,
    )
    .unwrap()
}

#[test]
fn durable_stage_records_a_decision_and_retries_after_reopen_without_new_bytes() {
    let fixture = Fixture::new();
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("ledger");
    let mut ledger = ledger_at(&path);
    let mut ports = Ports::new(&fixture);
    let receipt = run_evaluated_shadow_v1(
        fixture.request(),
        &fixture.verifier,
        &mut ledger,
        &mut ports,
        /*now*/ 50,
    )
    .unwrap();
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
    let LedgerEvent::Decision(decision) = &expected_records[0].event else {
        panic!("only a Decision")
    };
    assert_eq!(decision.record_id, fixture.run.run_id);
    assert_eq!(decision.selected_candidate_id, id("action"));
    assert_eq!(decision.selected_propensity, ProbabilityQ32::ONE);
    let original_bytes = fs::read(&path).unwrap();
    drop(ledger);
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .unwrap();
    let mut reopened = DurableLedger::recover(
        file,
        digest("host-authorized-ledger"),
        /*max_records*/ 1,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: 1,
            chain_digest: append.chain_digest,
        }),
    )
    .unwrap();
    assert_eq!(reopened.records().unwrap(), expected_records);
    let replay = run_evaluated_shadow_v1(
        fixture.request(),
        &fixture.verifier,
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
    assert_eq!(fs::read(&path).unwrap(), original_bytes);
    let mut drift = fixture.request();
    drift.intuition.sequence += 1;
    ports.intuition = decide_calibrated_v2(drift.intuition.clone()).unwrap();
    assert!(matches!(
        run_evaluated_shadow_v1(
            drift,
            &fixture.verifier,
            &mut reopened,
            &mut ports,
            /*now*/ 50
        ),
        Err(EvaluatedShadowError::Ledger(DurableLedgerError::Semantic(
            _
        )))
    ));
    assert_eq!(fs::read(&path).unwrap(), original_bytes);
}

#[test]
fn invalid_authentication_artifact_or_dataset_never_calls_any_port() {
    let mutations: [fn(&mut Fixture); 9] = [
        |f| f.evidence.generator_plan.signature[0] ^= 1,
        |f| f.evidence.evaluator_bundle.signature[0] ^= 1,
        |f| f.candidate_evidence.signature[0] ^= 1,
        |f| {
            f.bytes[0] ^= 1;
            f.run.snapshot.model_artifact_digest = Digest32::of_bytes(&f.bytes);
        },
        |f| f.run.snapshot.learning_artifact_generation += 1,
        |f| f.run.snapshot.model_artifact_digest = digest("another artifact"),
        |f| f.dataset.inclusion_policy_digest = digest("changed cut"),
        |f| {
            f.bundle.snapshot_ids.push(id("unchecked-snapshot"));
            f.resign_evaluator();
        },
        |f| f.intuition.state_digest = digest("wrong run"),
    ];
    for mutate in mutations {
        let mut fixture = Fixture::new();
        let mut ports = Ports::new(&fixture);
        mutate(&mut fixture);
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("ledger");
        let mut ledger = ledger_at(&path);
        let before = fs::read(&path).unwrap();
        assert!(
            run_evaluated_shadow_v1(
                fixture.request(),
                &fixture.verifier,
                &mut ledger,
                &mut ports,
                /*now*/ 50
            )
            .is_err()
        );
        assert!(ports.calls.is_empty());
        assert!(ledger.records().unwrap().is_empty());
        assert_eq!(fs::read(path).unwrap(), before);
    }
}

#[test]
fn signed_ineligibility_insufficiency_and_expiry_refuse_all_ports() {
    for case in 0..3 {
        let mut fixture = Fixture::new();
        if case == 0 {
            fixture.bundle.metrics[0].candidate.lower = codex_hepta_types::FixedQ32::ZERO;
            fixture.bundle.metrics[0].candidate.upper = codex_hepta_types::FixedQ32::ZERO;
        } else if case == 1 {
            fixture.bundle.metrics[0].support_digest = Digest32::ZERO;
        }
        fixture.resign_evaluator();
        let mut ports = Ports::new(&fixture);
        let temp = tempfile::tempdir().unwrap();
        let mut ledger = ledger_at(&temp.path().join("ledger"));
        let result = run_evaluated_shadow_v1(
            fixture.request(),
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            if case == 2 { 95 } else { 50 },
        );
        if case != 2 {
            assert!(matches!(result, Err(EvaluatedShadowError::Ineligible(_))));
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
        let mut ledger = ledger_at(&temp.path().join("ledger"));
        let receipt = run_evaluated_shadow_v1(
            fixture.request(),
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            /*now*/ 50,
        )
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
    let mut ledger = ledger_at(&path);
    let mut ports = Ports::new(&fixture);
    let mut wrong_head = fixture.request();
    wrong_head.expected_ledger_head = digest("unrelated predecessor");
    assert!(matches!(
        run_evaluated_shadow_v1(
            wrong_head,
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            /*now*/ 50
        ),
        Err(EvaluatedShadowError::Ledger(DurableLedgerError::Conflict))
    ));
    assert!(ledger.records().unwrap().is_empty());
    let receipt = run_evaluated_shadow_v1(
        fixture.request(),
        &fixture.verifier,
        &mut ledger,
        &mut ports,
        /*now*/ 50,
    )
    .unwrap();
    let before = fs::read(&path).unwrap();
    let mut second = fixture.request();
    second.run.run_id = id("second-run");
    second.intuition.decision_id = id("second-run");
    second.episode_id = id("second-episode");
    second.expected_ledger_head = receipt.learning.unwrap().chain_digest;
    ports.intuition = decide_calibrated_v2(second.intuition.clone()).unwrap();
    assert!(matches!(
        run_evaluated_shadow_v1(
            second,
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            /*now*/ 50
        ),
        Err(EvaluatedShadowError::Ledger(DurableLedgerError::Capacity))
    ));
    assert_eq!(fs::read(path).unwrap(), before);

    let path = temp.path().join("faulted-ledger");
    let mut ledger = ledger_at(&path);
    OpenOptions::new()
        .write(true)
        .open(&path)
        .unwrap()
        .set_len(/*size*/ 0)
        .unwrap();
    let mut ports = Ports::new(&fixture);
    assert!(matches!(
        run_evaluated_shadow_v1(
            fixture.request(),
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            /*now*/ 50
        ),
        Err(EvaluatedShadowError::Ledger(DurableLedgerError::Corrupt))
    ));
    assert!(matches!(
        ledger.records(),
        Err(DurableLedgerError::Poisoned)
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
        let mut ports = Ports::new(&fixture);
        let temp = tempfile::tempdir().unwrap();
        let mut ledger = ledger_at(&temp.path().join("ledger"));
        let receipt = run_evaluated_shadow_v1(
            fixture.request(),
            &fixture.verifier,
            &mut ledger,
            &mut ports,
            /*now*/ 50,
        )
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
        let LedgerEvent::Decision(decision) = &records[0].event else {
            panic!("Decision, never Outcome")
        };
        assert_eq!(
            decision.selected_candidate_id,
            id(if slow { SLOW_PATH } else { ABSTAIN })
        );
        assert_eq!(decision.selected_propensity, ProbabilityQ32::ONE);
    }
}
