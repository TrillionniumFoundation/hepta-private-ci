use super::*;
use codex_hepta_intelligence::CapabilityBindingV2;
use codex_hepta_intelligence::CapabilityNecessityV2;
use codex_hepta_intelligence::CapabilityRequirementV2;
use codex_hepta_intelligence::CapabilitySnapshotRequestV2;
use codex_hepta_intelligence::CapabilitySnapshotV2;
use codex_hepta_intelligence::IntelligenceBudgetV3;
use codex_hepta_intelligence::IntelligenceDispositionV3;
use codex_hepta_intelligence::IntelligenceFailureClassV3;
use codex_hepta_intelligence::IntelligencePortDecisionV3;
use codex_hepta_intelligence::IntelligencePortFailureV3;
use codex_hepta_intelligence::IntelligenceStageOutcomeV3;
use codex_hepta_intelligence::IntelligenceStageV3;
use codex_hepta_types::Generation;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn request() -> IntelligenceRunRequestV3 {
    let required = [
        ("objective.validation", "objective.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("host.handoff", "runtime.agentd"),
        ("learning.record", "learning.ledger"),
    ];
    let contract = digest("contract");
    let snapshot = CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 1,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocation"),
        requirements: required
            .iter()
            .map(|(capability, owner)| CapabilityRequirementV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                necessity: CapabilityNecessityV2::Required,
            })
            .collect(),
        bindings: required
            .iter()
            .map(|(capability, owner)| CapabilityBindingV2 {
                capability_id: id(capability),
                owner_id: id(owner),
                contract_digest: contract,
                implementation_digest: digest(owner),
                generation: Generation::new(1).expect("generation"),
            })
            .collect(),
    })
    .expect("snapshot");
    IntelligenceRunRequestV3 {
        run_id: id("run:agentd-v3"),
        request_digest: digest("request"),
        snapshot,
        budget: IntelligenceBudgetV3 {
            total_micros: 10_000,
            objective_micros: 1_000,
            evaluation_micros: 1_000,
            legal_set_micros: 1_000,
            utility_micros: 1_000,
            neural_micros: 1_000,
            prompt_micros: 1_000,
            intuition_micros: 1_000,
            context_micros: 1_000,
            handoff_micros: 1_000,
            ledger_micros: 1_000,
        },
    }
}

#[derive(Default)]
struct Upstream;

impl Upstream {
    fn receipt(
        input: &IntelligencePortInputV3,
        producer: &str,
    ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
        Ok(IntelligencePortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: digest(&format!("{producer}:{:?}", input.stage)),
            decision: IntelligencePortDecisionV3::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

macro_rules! port {
    ($name:ident, $owner:literal) => {
        fn $name(
            &mut self,
            input: &IntelligencePortInputV3,
        ) -> Result<IntelligencePortReceiptV3, IntelligencePortFailureV3> {
            Self::receipt(input, $owner)
        }
    };
}

impl AgentdUpstreamIntelligencePortsV3 for Upstream {
    port!(validate_objective, "objective.compiler");
    port!(admit_evaluation, "learning.eval");
    port!(build_legal_set, "intelligence.control");
    port!(evaluate_utility, "utility.ndu");
    port!(collect_neural_signal, "neuron.runtime");
    port!(build_prompt_portfolio, "prompt.optimizer");
    port!(decide_intuition, "intuition.policy");
    port!(compile_context, "context.compiler");
    port!(record_learning, "learning.ledger");
}

#[test]
fn agentd_is_the_named_host_handoff_producer() {
    let receipt = run_agentd_intelligence_v3(request(), &mut Upstream).expect("agentd composition");
    assert_eq!(
        receipt.disposition,
        IntelligenceDispositionV3::HostHandedOff
    );
    let handoff = receipt
        .stages
        .iter()
        .find(|trace| trace.stage == IntelligenceStageV3::HostHandoff)
        .expect("handoff");
    assert_eq!(handoff.producer.as_str(), "runtime.agentd");
    assert_eq!(handoff.outcome, IntelligenceStageOutcomeV3::Completed);
    assert!(receipt.host_envelope.is_some());
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn missing_optional_adapters_do_not_call_upstream_or_fabricate_success() {
    let receipt = run_agentd_intelligence_v3(request(), &mut Upstream).expect("agentd composition");
    assert!(receipt.stages.iter().any(|trace| {
        trace.stage == IntelligenceStageV3::NeuralSignalCollected
            && trace.outcome
                == IntelligenceStageOutcomeV3::FallbackUsed(IntelligenceFailureClassV3::Unavailable)
    }));
    assert!(receipt.stages.iter().any(|trace| {
        trace.stage == IntelligenceStageV3::PromptPortfolioBuilt
            && trace.outcome
                == IntelligenceStageOutcomeV3::FallbackUsed(IntelligenceFailureClassV3::Unavailable)
    }));
}
