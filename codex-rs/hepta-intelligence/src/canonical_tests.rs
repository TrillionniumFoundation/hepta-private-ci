use std::collections::BTreeMap;

use super::*;
use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallResourceReceiptV1;
use codex_hepta_cognitive_types::hnmf_learning::SelectedEventRefV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).expect("valid generation")
}

fn owners() -> Vec<OwnerBindingV1> {
    [
        "objective.compiler",
        "utility.ndu",
        "neuron.runtime",
        "prompt.optimizer",
        "intuition.policy",
        "context.compiler",
        "learning.eval",
    ]
    .into_iter()
    .enumerate()
    .map(|(index, owner)| OwnerBindingV1 {
        owner_id: id(owner),
        generation: generation((index + 1) as u64),
        implementation_digest: digest(&format!("{owner}:impl")),
        key_digest: digest(&format!("{owner}:key")),
        key_epoch: (index + 1) as u64,
    })
    .collect()
}

fn snapshot() -> CanonicalIntelligenceSnapshotV1 {
    CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: digest("objective"),
        authority_epoch: 11,
        body_generation: generation(4),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation"),
        owner_bindings: owners(),
    })
    .expect("snapshot")
}

fn request() -> CanonicalIntelligenceRunRequestV1 {
    CanonicalIntelligenceRunRequestV1 {
        run_id: id("run:canonical"),
        snapshot: snapshot(),
        legal_candidates: LegalActionCandidateSetRequestV1 {
            candidate_set_id: id("candidate-set:canonical"),
            state_digest: digest("objective"),
            generator_id: id("intelligence.control"),
            grammar_digest: digest("legal-grammar"),
            candidates: vec![LegalActionCandidateV1 {
                candidate_id: id("action:one"),
                support_digest: digest("action:one:support"),
            }],
            support_floor_ppm: 1,
        },
        budget: CanonicalBudgetV1 {
            total_micros: 7_000,
            objective_micros: 1_000,
            utility_micros: 1_000,
            neural_micros: 1_000,
            prompt_micros: 1_000,
            intuition_micros: 1_000,
            context_micros: 1_000,
            evaluation_micros: 1_000,
        },
    }
}

fn contract_id(value: &str) -> ContractIdV1 {
    ContractIdV1::new(value).expect("contract id")
}

fn contract_digest(value: &str) -> ContractDigestV1 {
    ContractDigestV1::from_digest(digest(value)).expect("contract digest")
}

fn canonical_recall_packet() -> RecallPacketV1 {
    RecallPacketV1 {
        cue_digest: contract_digest("recall-cue"),
        event_snapshot_digest: contract_digest("recall-event-snapshot"),
        engram_snapshot_digest: contract_digest("recall-engram-snapshot"),
        selected_events: vec![SelectedEventRefV1 {
            event_id: contract_id("event:recalled"),
            revision: 1,
            event_digest: contract_digest("event:recalled:digest"),
        }],
        active_nodes: Vec::new(),
        activation_paths: Vec::new(),
        contradictions: Vec::new(),
        coverage_ppm: 1_000_000,
        confidence_ppm: 900_000,
        ood_ppm: 0,
        abstain: None,
        resource_receipt: RecallResourceReceiptV1 {
            candidate_event_count: 1,
            node_count: 0,
            synapse_count: 0,
            active_node_count: 0,
            settling_steps: 0,
        },
    }
}

#[derive(Clone)]
struct Oracle {
    states: BTreeMap<StableId, CurrentOwnerStateV1>,
    drift_after_first: Option<StableId>,
    calls: BTreeMap<StableId, usize>,
}

impl Oracle {
    fn new(snapshot: &CanonicalIntelligenceSnapshotV1) -> Self {
        let states = owners()
            .into_iter()
            .map(|owner| {
                let current = CurrentOwnerStateV1 {
                    owner_id: owner.owner_id.clone(),
                    generation: owner.generation,
                    implementation_digest: owner.implementation_digest,
                    key_digest: owner.key_digest,
                    key_epoch: owner.key_epoch,
                    authority_epoch: snapshot.authority_epoch(),
                    revocation_frontier_digest: snapshot.revocation_frontier_digest(),
                };
                (owner.owner_id, current)
            })
            .collect();
        Self {
            states,
            drift_after_first: None,
            calls: BTreeMap::new(),
        }
    }
}

impl CanonicalFreshnessOracleV1 for Oracle {
    fn current(
        &mut self,
        owner_id: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        let calls = self.calls.entry(owner_id.clone()).or_default();
        *calls += 1;
        let mut current =
            self.states.get(owner_id).cloned().ok_or_else(|| {
                CanonicalIntelligenceError::FreshnessUnavailable(owner_id.clone())
            })?;
        if self.drift_after_first.as_ref() == Some(owner_id) && *calls > 1 {
            current.generation = generation(current.generation.get() + 1);
        }
        Ok(current)
    }
}

struct Ports {
    calls: Vec<CanonicalStageV1>,
    abstain: bool,
    wrong_owner: Option<CanonicalStageV1>,
    consumed_recall: Option<RecallPacketV1>,
}

impl Ports {
    fn new() -> Self {
        Self {
            calls: Vec::new(),
            abstain: false,
            wrong_owner: None,
            consumed_recall: None,
        }
    }

    fn receipt(
        &mut self,
        input: &CanonicalPortInputV1,
        owner: &str,
        decision: CanonicalPortDecisionV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.calls.push(input.stage);
        let producer = if self.wrong_owner == Some(input.stage) {
            id("wrong.owner")
        } else {
            id(owner)
        };
        Ok(CanonicalPortReceiptV1 {
            stage: input.stage,
            producer,
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(&format!("{owner}:{:?}", input.stage)),
            decision,
            authority: codex_hepta_types::AuthorityPosture::DENY_ALL,
        })
    }
}

impl CanonicalOwnerPortsV1 for Ports {
    fn validate_objective(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(
            input,
            "objective.compiler",
            CanonicalPortDecisionV1::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(input, "utility.ndu", CanonicalPortDecisionV1::Continue)
    }

    fn collect_neural_signal(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(input, "neuron.runtime", CanonicalPortDecisionV1::Continue)
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(input, "prompt.optimizer", CanonicalPortDecisionV1::Continue)
    }

    fn decide_intuition(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        let decision = if self.abstain {
            CanonicalPortDecisionV1::Abstained
        } else {
            CanonicalPortDecisionV1::Selected {
                candidate_id: id("action:one"),
                propensity: ProbabilityQ32::ONE,
            }
        };
        self.receipt(input, "intuition.policy", decision)
    }

    fn compile_context(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(input, "context.compiler", CanonicalPortDecisionV1::Continue)
    }

    fn compile_context_with_canonical_recall(
        &mut self,
        input: &CanonicalPortInputV1,
        recall: &CanonicalRecallIntelligenceInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.consumed_recall = Some(recall.packet.clone());
        let mut receipt = self.compile_context(input)?;
        receipt.output_digest =
            canonical_contract_digest_v1(&recall.packet).expect("recall digest");
        Ok(receipt)
    }

    fn evaluate_candidate(
        &mut self,
        input: &CanonicalPortInputV1,
    ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
        self.receipt(input, "learning.eval", CanonicalPortDecisionV1::Continue)
    }
}

#[test]
fn canonical_selected_path_has_first_class_ndu_and_all_seven_owners() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    let outcome =
        prepare_intelligence_run(request, &mut ports, &mut oracle).expect("canonical run");
    let CanonicalRunOutcomeV1::Ready(envelope) = outcome else {
        panic!("selected run must produce host envelope");
    };
    assert_eq!(
        ports.calls,
        vec![
            CanonicalStageV1::ObjectiveValidated,
            CanonicalStageV1::UtilityEvaluated,
            CanonicalStageV1::NeuralSignalCollected,
            CanonicalStageV1::PromptPortfolioBuilt,
            CanonicalStageV1::IntuitionDecided,
            CanonicalStageV1::ContextCompiled,
            CanonicalStageV1::EvaluationAdmitted,
        ]
    );
    assert!(!envelope.utility_receipt_digest.is_zero());
    assert!(!envelope.envelope_digest.is_zero());
    assert!(!envelope.authority.grants_any());
}

#[test]
fn canonical_recall_is_bound_before_the_product_intelligence_run() {
    let request = request();
    let recall = bind_canonical_recall_for_intelligence_v1(
        request.run_id.clone(),
        canonical_recall_packet(),
        Some(digest("legacy-recall-packet")),
    )
    .expect("canonical recall binding");
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    let outcome =
        prepare_intelligence_run_with_canonical_recall(request, recall, &mut ports, &mut oracle)
            .expect("canonical recall intelligence run");
    assert!(matches!(outcome, CanonicalRunOutcomeV1::Ready(_)));
}

#[test]
fn canonical_recall_cannot_be_replayed_for_another_run() {
    let request = request();
    let recall =
        bind_canonical_recall_for_intelligence_v1(id("run:other"), canonical_recall_packet(), None)
            .expect("canonical recall binding");
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    assert_eq!(
        prepare_intelligence_run_with_canonical_recall(request, recall, &mut ports, &mut oracle,)
            .expect_err("cross-run recall must reject"),
        CanonicalIntelligenceError::CanonicalRecallRunMismatch
    );
    assert!(ports.calls.is_empty());
}

#[test]
fn abstention_stops_before_context_and_evaluation() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    ports.abstain = true;
    let outcome =
        prepare_intelligence_run(request, &mut ports, &mut oracle).expect("canonical run");
    assert!(matches!(outcome, CanonicalRunOutcomeV1::Abstained(_)));
    assert_eq!(
        ports.calls,
        vec![
            CanonicalStageV1::ObjectiveValidated,
            CanonicalStageV1::UtilityEvaluated,
            CanonicalStageV1::NeuralSignalCollected,
            CanonicalStageV1::PromptPortfolioBuilt,
            CanonicalStageV1::IntuitionDecided,
        ]
    );
}

#[test]
fn owner_generation_change_between_call_and_publication_fails_closed() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    oracle.drift_after_first = Some(id("utility.ndu"));
    let mut ports = Ports::new();
    let error = prepare_intelligence_run(request, &mut ports, &mut oracle)
        .expect_err("post-call drift must reject");
    assert_eq!(
        error,
        CanonicalIntelligenceError::StaleOwner(id("utility.ndu"))
    );
    assert_eq!(
        ports.calls,
        vec![
            CanonicalStageV1::ObjectiveValidated,
            CanonicalStageV1::UtilityEvaluated,
        ]
    );
}

#[test]
fn key_rotation_and_wrong_owner_receipt_fail_closed() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    oracle
        .states
        .get_mut(&id("objective.compiler"))
        .expect("owner")
        .key_epoch += 1;
    let mut ports = Ports::new();
    assert_eq!(
        prepare_intelligence_run(request.clone(), &mut ports, &mut oracle).expect_err("key drift"),
        CanonicalIntelligenceError::KeyDrift(id("objective.compiler"))
    );
    assert!(ports.calls.is_empty());

    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    ports.wrong_owner = Some(CanonicalStageV1::UtilityEvaluated);
    assert_eq!(
        prepare_intelligence_run(request, &mut ports, &mut oracle).expect_err("wrong owner"),
        CanonicalIntelligenceError::ProducerMismatch
    );
}

#[test]
fn legal_candidate_set_rejects_replay_identity_with_duplicate_semantics() {
    let mut value = request().legal_candidates;
    value.candidates.push(value.candidates[0].clone());
    assert_eq!(
        build_legal_candidates(value).expect_err("duplicate must reject"),
        CanonicalIntelligenceError::DuplicateCandidate(id("action:one"))
    );
}

#[test]
fn canonical_recall_reaches_context_and_changes_product_handoff() {
    let first = canonical_recall_packet();
    let mut second = first.clone();
    second.selected_events[0].event_digest =
        ContractDigestV1::from_digest(digest("other event revision")).expect("digest");
    let execute = |packet: RecallPacketV1| {
        let request = request();
        let recall =
            bind_canonical_recall_for_intelligence_v1(request.run_id.clone(), packet.clone(), None)
                .expect("bind");
        let mut oracle = Oracle::new(&request.snapshot);
        let mut ports = Ports::new();
        let result = prepare_intelligence_run_with_canonical_recall(
            request,
            recall,
            &mut ports,
            &mut oracle,
        )
        .expect("run");
        assert_eq!(ports.consumed_recall, Some(packet));
        result
    };
    assert_ne!(execute(first), execute(second));
}

struct LegacyPorts(Ports);

macro_rules! delegate_legacy_port {
    ($name:ident) => {
        fn $name(
            &mut self,
            input: &CanonicalPortInputV1,
        ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
            self.0.$name(input)
        }
    };
}

impl CanonicalOwnerPortsV1 for LegacyPorts {
    delegate_legacy_port!(validate_objective);
    delegate_legacy_port!(evaluate_utility);
    delegate_legacy_port!(collect_neural_signal);
    delegate_legacy_port!(build_prompt_portfolio);
    delegate_legacy_port!(decide_intuition);
    delegate_legacy_port!(compile_context);
    delegate_legacy_port!(evaluate_candidate);
}

#[test]
fn legacy_owner_cannot_silently_ignore_canonical_recall() {
    let request = request();
    let recall = bind_canonical_recall_for_intelligence_v1(
        request.run_id.clone(),
        canonical_recall_packet(),
        None,
    )
    .expect("bind");
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = LegacyPorts(Ports::new());
    assert!(
        prepare_intelligence_run_with_canonical_recall(request, recall, &mut ports, &mut oracle)
            .is_err()
    );
    assert!(!ports.0.calls.contains(&CanonicalStageV1::ContextCompiled));
}
