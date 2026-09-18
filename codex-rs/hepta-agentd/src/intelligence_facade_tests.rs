use codex_hepta_intelligence::CapabilityBindingV2;
use codex_hepta_intelligence::CapabilityNecessityV2;
use codex_hepta_intelligence::CapabilityRequirementV2;
use codex_hepta_intelligence::CapabilitySnapshotRequestV2;
use codex_hepta_intelligence::CapabilitySnapshotV2;
use codex_hepta_intelligence::CompositionBudgetV3;
use codex_hepta_intelligence::CompositionControlV3;
use codex_hepta_intelligence::CompositionPortInputV3;
use codex_hepta_intelligence::CompositionPortReceiptV3;
use codex_hepta_intelligence::CompositionPortsV3;
use codex_hepta_intelligence::CompositionRunRequestV3;
use codex_hepta_intelligence::CompositionStageV3;
use codex_hepta_intelligence::LegalActionCandidateSetV1;
use codex_hepta_intelligence::LegalActionCandidateV1;
use codex_hepta_intelligence::PortDecisionV1;
use codex_hepta_intelligence::PortFailureV1;
use codex_hepta_intelligence::prepare_intelligence_run_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::*;
use crate::RunPhase;
use crate::RuntimeComposition;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Control;
impl CompositionControlV3 for Control {
    fn now_micros(&self) -> u64 {
        1_000_000
    }

    fn is_cancelled(&self) -> bool {
        false
    }
}

fn snapshot() -> CapabilitySnapshotV2 {
    let pairs = [
        ("objective.validation", "objective.compiler"),
        ("legal.actions", "intelligence.control"),
        ("utility.evaluation", "utility.ndu"),
        ("intuition.decision", "intuition.policy"),
        ("context.compilation", "context.compiler"),
        ("evaluation.admission", "learning.eval"),
        ("learning.record", "learning.ledger"),
        ("dispatch.proposal", "runtime.agentd"),
    ];
    let requirements = pairs
        .iter()
        .map(|(capability, owner)| CapabilityRequirementV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            necessity: CapabilityNecessityV2::Required,
        })
        .collect::<Vec<_>>();
    let bindings = pairs
        .iter()
        .map(|(capability, owner)| CapabilityBindingV2 {
            capability_id: id(capability),
            owner_id: id(owner),
            contract_digest: digest(&format!("contract:{capability}")),
            implementation_digest: digest(&format!("implementation:{owner}")),
            generation: Generation::new(1).expect("generation"),
        })
        .collect::<Vec<_>>();
    CapabilitySnapshotV2::admit(CapabilitySnapshotRequestV2 {
        objective_digest: digest("objective"),
        authority_epoch: 9,
        body_generation: Generation::new(1).expect("generation"),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        requirements,
        bindings,
    })
    .expect("snapshot")
}

struct Ports {
    snapshot: Digest32,
    objective: Digest32,
}

impl Ports {
    fn call(
        &mut self,
        input: &CompositionPortInputV3,
        producer: &str,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        let output = match input.stage {
            CompositionStageV3::ObjectiveValidated => self.objective,
            CompositionStageV3::ContextCompiled => digest("context"),
            _ => digest(&format!("{producer}:{:?}", input.stage)),
        };
        Ok(CompositionPortReceiptV3 {
            stage: input.stage,
            producer: id(producer),
            snapshot_digest: self.snapshot,
            predecessor_digest: input.predecessor_digest,
            output_digest: output,
            evidence_digest: if input.stage == CompositionStageV3::ContextCompiled {
                digest("context-receipt")
            } else {
                output
            },
            decision: PortDecisionV1::Continue,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl CompositionPortsV3 for Ports {
    fn validate_objective(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "objective.compiler")
    }

    fn evaluate_utility(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "utility.ndu")
    }

    fn collect_neural_signal(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "neuron.runtime")
    }

    fn build_prompt_portfolio(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "prompt.optimizer")
    }

    fn decide_intuition(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "intuition.policy")
    }

    fn compile_context(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "context.compiler")
    }

    fn admit_evaluation(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "learning.eval")
    }

    fn record_decision(
        &mut self,
        input: &CompositionPortInputV3,
    ) -> Result<CompositionPortReceiptV3, PortFailureV1> {
        self.call(input, "learning.ledger")
    }
}

fn envelope() -> codex_hepta_intelligence::IntelligenceHostEnvelopeV1 {
    let snapshot = snapshot();
    let candidate_set = LegalActionCandidateSetV1::new(
        id("candidate-set"),
        snapshot.digest(),
        id("intelligence.control"),
        digest("grammar"),
        vec![LegalActionCandidateV1 {
            candidate_id: id("action"),
            support_digest: digest("support"),
            support_ppm: 1_000_000,
        }],
        500_000,
    )
    .expect("candidate set");
    let request = CompositionRunRequestV3 {
        run_id: id("run:agentd-v3"),
        request_digest: digest("request"),
        body_digest: digest("body"),
        artifact_set_digest: digest("artifacts"),
        started_at_micros: 1_000_000,
        deadline_micros: 2_000_000,
        budget: CompositionBudgetV3 {
            total_micros: 1_000,
            evidence_floor_micros: 50,
            recovery_floor_micros: 50,
            objective_micros: 100,
            legal_set_micros: 100,
            utility_micros: 100,
            neural_micros: 100,
            prompt_micros: 100,
            intuition_micros: 100,
            context_micros: 100,
            evaluation_micros: 100,
            ledger_micros: 100,
        },
        snapshot: snapshot.clone(),
        candidate_set,
    };
    let mut ports = Ports {
        snapshot: snapshot.digest(),
        objective: snapshot.objective_digest(),
    };
    prepare_intelligence_run_v3(request, &mut ports, &Control)
        .expect("prepared")
        .envelope
        .expect("envelope")
}

#[test]
fn agentd_admits_exact_v3_envelope_then_marks_actual_dispatch() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent-v3".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("agentd-config").to_string(),
        ports_digest: digest("ports").to_string(),
    })
    .expect("runtime");
    let envelope = envelope();
    let mut caller = AgentdIntelligenceCaller::new(&mut coordinator);

    let attached = caller.admit(1_000_000, &envelope).expect("admit");
    assert_eq!(attached.phase, RunPhase::ContextAttached);
    assert_eq!(
        attached.context_digest,
        Some(envelope.context_digest.to_string())
    );

    let dispatched = caller
        .mark_dispatched(&envelope, attached.revision)
        .expect("dispatch");
    assert_eq!(dispatched.phase, RunPhase::Dispatched);
}

#[test]
fn stale_or_changed_envelope_cannot_rebind_an_existing_run() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent-v3".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("agentd-config").to_string(),
        ports_digest: digest("ports").to_string(),
    })
    .expect("runtime");
    let envelope = envelope();
    let mut caller = AgentdIntelligenceCaller::new(&mut coordinator);
    caller.admit(1_000_000, &envelope).expect("first");

    let mut tampered = envelope.clone();
    tampered.body_digest = digest("other-body");
    assert!(matches!(
        caller.admit(1_000_000, &tampered),
        Err(IntelligenceFacadeCallerError::Envelope(_))
    ));
}

#[test]
fn microsecond_deadline_is_never_widened_by_agentd_adapter() {
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent-v3-deadline".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("agentd-config-deadline").to_string(),
        ports_digest: digest("ports-deadline").to_string(),
    })
    .expect("runtime");
    let envelope = envelope();
    let now_micros = envelope.deadline_micros - 1;
    let mut caller = AgentdIntelligenceCaller::new(&mut coordinator);
    assert_eq!(
        caller.admit(now_micros, &envelope),
        Err(IntelligenceFacadeCallerError::Runtime(
            AgentRunError::InvalidDeadline
        ))
    );
}
