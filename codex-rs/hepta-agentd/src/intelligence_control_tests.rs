use codex_hepta_intelligence::CapabilityBindingV2;
use codex_hepta_intelligence::CapabilityNecessityV2;
use codex_hepta_intelligence::CapabilityRequirementV2;
use codex_hepta_intelligence::CapabilitySnapshotRequestV2;
use codex_hepta_intelligence::CapabilitySnapshotV2;
use codex_hepta_intelligence::CompositionBudgetV3;
use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::CompositionPortDecisionV3;
use codex_hepta_intelligence::CompositionPortFailureV3;
use codex_hepta_intelligence::CompositionPortInputV3;
use codex_hepta_intelligence::CompositionPortReceiptV3;
use codex_hepta_intelligence::CompositionPortsV3;
use codex_hepta_intelligence::CompositionRunRequestV3;
use codex_hepta_intelligence::CompositionStageV3;
use codex_hepta_intelligence::LegalActionCandidateSetRequestV1;
use codex_hepta_intelligence::LegalActionCandidateV1;
use codex_hepta_intelligence::build_legal_candidates;
use codex_hepta_intelligence::prepare_intelligence_run_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::RunPhase;
use crate::RuntimeComposition;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    Generation::new(value).unwrap_or_else(|error| panic!("valid generation: {error}"))
}

struct Control;

impl CompositionControlV3 for Control {
    fn now_unix_micros(&self) -> u64 {
        1_000_000
    }

    fn is_cancelled(&self, _: &StableId) -> bool {
        false
    }
}

struct Ports {
    intuition: CompositionPortDecisionV3,
}

impl Ports {
    fn receipt(
        input: &CompositionPortInputV3,
        producer: &str,
        output: Digest32,
        decision: CompositionPortDecisionV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Ok(CompositionPortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: input.snapshot_digest,
            predecessor_digest: input.predecessor_digest,
            output_digest: output,
            evidence_digest: digest(&format!("receipt:{producer}")),
            decision,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl CompositionPortsV3 for Ports {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "objective.compiler",
            digest("objective"),
            CompositionPortDecisionV3::Continue,
        )
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "utility.ndu",
            digest("utility"),
            CompositionPortDecisionV3::Continue,
        )
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "learning.eval",
            digest("evaluation"),
            CompositionPortDecisionV3::Continue,
        )
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "neuron.runtime",
            digest("neural"),
            CompositionPortDecisionV3::Continue,
        )
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "prompt.optimizer",
            digest("prompt"),
            CompositionPortDecisionV3::Continue,
        )
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "intuition.policy",
            digest("intuition"),
            self.intuition,
        )
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, CompositionPortFailureV3> {
        Self::receipt(
            input,
            "context.compiler",
            digest("context"),
            CompositionPortDecisionV3::Continue,
        )
    }
}

fn snapshot() -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("utility.evaluation", "utility.ndu"),
        ("evaluation.admission", "learning.eval"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
    ];
    let mut requirements = Vec::new();
    let mut bindings = Vec::new();
    for (capability, owner) in pairs {
        let contract = digest(&format!("contract:{capability}"));
        requirements.push(CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: contract,
            necessity: CapabilityNecessityV2::Required,
        });
        bindings.push(CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: contract,
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: generation(1),
        });
    }
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 7,
        body_generation: generation(3),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("snapshot")
}

fn composition_request(
    decision: CompositionPortDecisionV3,
) -> (CompositionRunRequestV3, Ports) {
    let snapshot = snapshot();
    let legal = build_legal_candidates(LegalActionCandidateSetRequestV1 {
        candidate_set_id: id("candidate-set"),
        state_digest: snapshot.digest(),
        grammar_digest: digest("grammar"),
        candidates: vec![LegalActionCandidateV1 {
            candidate_id: id("action"),
            action_digest: digest("action"),
            support_digest: digest("support"),
            support_ppm: 1_000_000,
        }],
        support_floor_ppm: 900_000,
    })
    .expect("candidate set");
    (
        CompositionRunRequestV3 {
            run_id: id("run:agentd-intelligence"),
            request_digest: digest("request"),
            body_digest: digest("body"),
            artifact_set_digest: digest("artifact-set"),
            snapshot,
            legal_candidates: legal,
            budget: CompositionBudgetV3 {
                total_micros: 800,
                objective_micros: 100,
                legal_set_micros: 100,
                utility_micros: 100,
                evaluation_micros: 100,
                neural_micros: 100,
                prompt_micros: 100,
                intuition_micros: 100,
                context_micros: 100,
            },
            deadline_unix_micros: 2_000_000,
        },
        Ports {
            intuition: decision,
        },
    )
}

fn composition(
    decision: CompositionPortDecisionV3,
) -> codex_hepta_intelligence::CompositionPipelineReceiptV3 {
    let (request, mut ports) = composition_request(decision);
    prepare_intelligence_run_v3(request, &mut ports, &Control).expect("composition")
}

fn coordinator() -> AgentRunCoordinator {
    AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent-1".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("agentd-config").to_string(),
        ports_digest: digest("agentd-ports").to_string(),
    })
    .expect("coordinator")
}

#[test]
fn agentd_directly_invokes_v3_before_host_admission() {
    let (request, mut ports) = composition_request(CompositionPortDecisionV3::Continue);
    let mut coordinator = coordinator();
    let receipt = compose_and_admit_intelligence_run_v1(
        &mut coordinator,
        1_000,
        request,
        &mut ports,
        &Control,
    )
    .expect("direct composition admission");

    assert_eq!(
        receipt.composition.disposition,
        codex_hepta_intelligence::CompositionDispositionV3::HostEnvelopePrepared
    );
    let admission = receipt.admission.expect("host admission");
    assert_eq!(admission.run.phase, RunPhase::ContextAttached);
    assert!(
        coordinator
            .run("run:agentd-intelligence")
            .is_some_and(|run| run.phase == RunPhase::ContextAttached)
    );
}

#[test]
fn prepared_intelligence_envelope_is_admitted_and_stops_before_dispatch() {
    let composition = composition(CompositionPortDecisionV3::Continue);
    let mut coordinator = coordinator();
    let receipt =
        admit_intelligence_run_v1(&mut coordinator, 1_000, &composition).expect("admission");

    assert_eq!(receipt.run.phase, RunPhase::ContextAttached);
    assert!(!receipt.run.terminal_observed);
    assert_eq!(
        coordinator
            .run("run:agentd-intelligence")
            .expect("run")
            .phase,
        RunPhase::ContextAttached
    );
    assert!(!receipt.envelope_digest.is_zero());
    assert!(!receipt.composition_trace_digest.is_zero());

    let replay = admit_intelligence_run_v1(&mut coordinator, 1_000, &composition).expect("replay");
    assert_eq!(replay.run.phase, RunPhase::ContextAttached);
    assert!(replay.run.idempotent);
}

#[test]
fn abstention_never_creates_an_agentd_run() {
    let composition = composition(CompositionPortDecisionV3::Abstain);
    let mut coordinator = coordinator();
    assert!(matches!(
        admit_intelligence_run_v1(&mut coordinator, 1_000, &composition),
        Err(IntelligenceControlCallerErrorV1::NotPrepared)
    ));
    assert!(coordinator.run("run:agentd-intelligence").is_none());
}
