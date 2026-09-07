use super::*;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(id) => id,
        Err(error) => panic!("fixture ID: {error}"),
    }
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(generation) => generation,
        Err(error) => panic!("fixture generation: {error}"),
    }
}

fn graph() -> OrganGraphsV1 {
    let evidence = Digest32::of_bytes(b"fixture-only evidence");
    let generation = generation(1);
    OrganGraphsV1 {
        generation,
        organs: (0..3)
            .map(|i| OrganNodeV1 {
                id: id(&format!("organ:{i}")),
                owner: id("owner"),
                role: OrganRole::LocalSafety,
                inputs: if i < 2 { vec![id("state.v1")] } else { vec![] },
                outputs: vec![id("state.v1")],
                effect_scope: BTreeSet::new(),
                terminal: if i == 2 {
                    FallbackTerminal::SafeState(evidence)
                } else {
                    FallbackTerminal::None
                },
            })
            .collect(),
        initialization: vec![OrganEdge { from: 0, to: 1 }],
        runtime: vec![
            RuntimeLinkV1 {
                output: OutputPort { organ: 0, port: 0 },
                input: InputPort { organ: 1, port: 0 },
                timing: DataflowTiming::Buffered,
            },
            RuntimeLinkV1 {
                output: OutputPort { organ: 1, port: 0 },
                input: InputPort { organ: 0, port: 0 },
                timing: DataflowTiming::Buffered,
            },
        ],
        feedback: vec![FeedbackProfileV1 {
            members: BTreeSet::from([0, 1]),
            reference_generation: generation,
            period_ns: 10_000_000,
            delay_ns: 0,
            jitter_ns: 1_000,
            queue_capacity: 1,
            max_gain_q24: 4 << 24,
            saturation_q24: 2 << 24,
            gains_and_saturation: evidence,
            operating_region: evidence,
            stability_analysis: evidence,
            perturbation_tests: evidence,
            exit_organ: 2,
        }],
        fallback: vec![OrganEdge { from: 0, to: 2 }, OrganEdge { from: 1, to: 2 }],
        failure_domains: (0..3)
            .map(|organ| FailureDomainV1 {
                organ,
                process: id(&format!("process:{organ}")),
                host: id("host"),
            })
            .collect(),
    }
}

#[test]
fn qualified_feedback_does_not_create_a_startup_or_failure_domain_cycle() {
    assert_eq!(
        graph().validate(),
        Ok(ValidatedOrganGraphsV1 {
            initialization_order: vec![0, 1, 2],
            fallback_order: vec![0, 1, 2],
            feedback_components: vec![BTreeSet::from([0, 1])],
            host_failure_sets: BTreeMap::from([(id("host"), BTreeSet::from([0, 1, 2]))]),
        })
    );
}

#[test]
fn graph_kinds_enforce_independent_invariants() {
    let mut candidate = graph();
    candidate.initialization.push(OrganEdge { from: 1, to: 0 });
    assert_eq!(
        candidate.validate(),
        Err(OrganGraphError::InitializationCycle)
    );
    let mut candidate = graph();
    candidate.fallback.push(OrganEdge { from: 2, to: 0 });
    assert_eq!(candidate.validate(), Err(OrganGraphError::FallbackCycle));
    let mut candidate = graph();
    candidate.feedback.clear();
    assert_eq!(candidate.validate(), Err(OrganGraphError::FeedbackProfile));
    let mut candidate = graph();
    candidate.failure_domains[1] = candidate.failure_domains[0].clone();
    assert_eq!(candidate.validate(), Err(OrganGraphError::FailureDomain));
}

#[test]
fn ports_scope_and_central_dependencies_fail_closed() {
    let mut candidate = graph();
    candidate.runtime[0].input.port = 4;
    assert_eq!(candidate.validate(), Err(OrganGraphError::PortMismatch));
    let mut candidate = graph();
    candidate.organs[2].effect_scope.insert(id("new.authority"));
    assert_eq!(candidate.validate(), Err(OrganGraphError::UnsafeFallback));
    let mut candidate = graph();
    candidate.organs[0].role = OrganRole::Cognitive;
    candidate.runtime[0].timing = DataflowTiming::Synchronous;
    assert_eq!(
        candidate.validate(),
        Err(OrganGraphError::CentralSafetyDependency)
    );
    let mut candidate = graph();
    candidate.feedback[0].reference_generation = generation(2);
    assert_eq!(candidate.validate(), Err(OrganGraphError::FeedbackProfile));
}

#[test]
fn disconnected_exit_and_stray_feedback_profiles_are_rejected() {
    let mut candidate = graph();
    candidate.fallback[1].to = 0;
    candidate.fallback[0].to = 1;
    assert_eq!(candidate.validate(), Err(OrganGraphError::FallbackCycle));
    let mut candidate = graph();
    candidate.feedback.push(candidate.feedback[0].clone());
    assert_eq!(candidate.validate(), Err(OrganGraphError::FeedbackProfile));
    let mut candidate = graph();
    candidate.runtime.pop();
    assert_eq!(candidate.validate(), Err(OrganGraphError::PortMismatch));
}
