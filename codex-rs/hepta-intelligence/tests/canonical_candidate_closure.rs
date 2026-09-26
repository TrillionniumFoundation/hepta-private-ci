use codex_hepta_intelligence::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

const OWNERS: [&str; 7] = [
    "objective.compiler",
    "utility.ndu",
    "neuron.runtime",
    "prompt.optimizer",
    "intuition.policy",
    "context.compiler",
    "learning.eval",
];

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap()
}

fn request() -> CanonicalIntelligenceRunRequestV1 {
    CanonicalIntelligenceRunRequestV1 {
        run_id: id("run.closure"),
        snapshot: CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
            objective_digest: digest("objective"),
            authority_epoch: 9,
            body_generation: generation(41),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("frontier"),
            owner_bindings: OWNERS
                .into_iter()
                .map(|owner| OwnerBindingV1 {
                    owner_id: id(owner),
                    generation: generation(41),
                    implementation_digest: digest(owner),
                    key_digest: digest("key"),
                    key_epoch: 1,
                })
                .collect(),
        })
        .unwrap(),
        legal_candidates: LegalActionCandidateSetRequestV1 {
            candidate_set_id: id("set.closure"),
            state_digest: digest("objective"),
            generator_id: id("intelligence.control"),
            grammar_digest: digest("grammar"),
            candidates: ["candidate.b", "candidate.a"]
                .into_iter()
                .map(|value| LegalActionCandidateV1 {
                    candidate_id: id(value),
                    support_digest: digest(value),
                })
                .collect(),
            support_floor_ppm: 1,
        },
        budget: CanonicalBudgetV1 {
            total_micros: 1_000_000,
            objective_micros: 100_000,
            utility_micros: 100_000,
            neural_micros: 100_000,
            prompt_micros: 100_000,
            intuition_micros: 100_000,
            context_micros: 100_000,
            evaluation_micros: 100_000,
        },
    }
}

struct Oracle;
impl CanonicalFreshnessOracleV1 for Oracle {
    fn current(
        &mut self,
        owner: &StableId,
    ) -> Result<CurrentOwnerStateV1, CanonicalIntelligenceError> {
        Ok(CurrentOwnerStateV1 {
            owner_id: owner.clone(),
            generation: generation(41),
            implementation_digest: digest(owner.as_str()),
            key_digest: digest("key"),
            key_epoch: 1,
            authority_epoch: 9,
            revocation_frontier_digest: digest("frontier"),
        })
    }
}

struct Ports {
    calls: Vec<CanonicalStageV1>,
    decision: CanonicalPortDecisionV1,
}
impl Ports {
    fn selected(candidate: &str, probability: u64) -> Self {
        Self {
            calls: Vec::new(),
            decision: CanonicalPortDecisionV1::Selected {
                candidate_id: id(candidate),
                propensity: ProbabilityQ32::from_raw(probability).unwrap(),
            },
        }
    }
    fn receipt(&mut self, input: &CanonicalPortInputV1, owner: &str) -> CanonicalPortReceiptV1 {
        self.calls.push(input.stage);
        CanonicalPortReceiptV1 {
            stage: input.stage,
            producer: id(owner),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(owner),
            decision: if input.stage == CanonicalStageV1::IntuitionDecided {
                self.decision.clone()
            } else {
                CanonicalPortDecisionV1::Continue
            },
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}
macro_rules! stage {
    ($method:ident, $owner:literal) => {
        fn $method(
            &mut self,
            input: &CanonicalPortInputV1,
        ) -> Result<CanonicalPortReceiptV1, CanonicalPortFailureV1> {
            Ok(self.receipt(input, $owner))
        }
    };
}
impl CanonicalOwnerPortsV1 for Ports {
    stage!(validate_objective, "objective.compiler");
    stage!(evaluate_utility, "utility.ndu");
    stage!(collect_neural_signal, "neuron.runtime");
    stage!(build_prompt_portfolio, "prompt.optimizer");
    stage!(decide_intuition, "intuition.policy");
    stage!(compile_context, "context.compiler");
    stage!(evaluate_candidate, "learning.eval");
}

#[test]
fn malicious_selection_cannot_reach_context_or_evaluation() {
    for (candidate, probability) in [("candidate.outside", 1), ("candidate.a", 0)] {
        let mut ports = Ports::selected(candidate, probability);
        let error = prepare_intelligence_run(request(), &mut ports, &mut Oracle).unwrap_err();
        assert!(matches!(
            error,
            CanonicalIntelligenceError::InvalidCandidateSet(_)
        ));
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
}

#[test]
fn candidate_permutations_produce_identical_public_outcomes() {
    let left = request();
    let mut right = left.clone();
    right.legal_candidates.candidates.reverse();
    let first = prepare_intelligence_run(left, &mut Ports::selected("candidate.a", 1), &mut Oracle)
        .unwrap();
    let second =
        prepare_intelligence_run(right, &mut Ports::selected("candidate.a", 1), &mut Oracle)
            .unwrap();
    assert_eq!(first, second);
}

#[test]
fn boundary_rehashes_mutable_candidate_receipts() {
    let mut legal = build_legal_candidates(request().legal_candidates).unwrap();
    let intuition = CanonicalPortReceiptV1 {
        stage: CanonicalStageV1::IntuitionDecided,
        producer: id("intuition.policy"),
        snapshot_digest: digest("snapshot"),
        predecessor_digest: digest("predecessor"),
        output_digest: digest("intuition"),
        decision: Ports::selected("candidate.a", 1).decision,
        authority: AuthorityPosture::DENY_ALL,
    };
    assert!(decide_boundary(&id("run.closure"), &legal, &intuition).is_ok());
    legal.candidates[0].support_digest = digest("substituted-support");
    assert_eq!(
        decide_boundary(&id("run.closure"), &legal, &intuition),
        Err(CanonicalIntelligenceError::InvalidCandidateSet(
            "digest mismatch"
        ))
    );
}

#[test]
fn direct_boundary_rejects_out_of_set_and_zero_propensity() {
    let legal = build_legal_candidates(request().legal_candidates).unwrap();
    for (candidate, probability) in [("candidate.outside", 1), ("candidate.a", 0)] {
        let receipt = CanonicalPortReceiptV1 {
            stage: CanonicalStageV1::IntuitionDecided,
            producer: id("intuition.policy"),
            snapshot_digest: digest("snapshot"),
            predecessor_digest: digest("predecessor"),
            output_digest: digest("intuition"),
            decision: Ports::selected(candidate, probability).decision,
            authority: AuthorityPosture::DENY_ALL,
        };
        assert!(decide_boundary(&id("run.closure"), &legal, &receipt).is_err());
    }
}
