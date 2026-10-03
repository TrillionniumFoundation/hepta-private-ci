//! Same original Round journal, genuine incompatible scope facts, no model fiction.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
fn serving_terminal(round: &AgentdSelfIterationRoundV1) -> AgentdSelfIterationPreparationStatusV1 {
    let d = Digest32::of_bytes(b"actual protected original owner fixture");
    let facts = SelfIterationServingScopeIncompatibleFactsV1 {
        round_identity_digest: round.identity_digest(),
        round_payload_digest: Digest32::of_bytes(&round.canonical_bytes().expect("whole round")),
        canonical_policy_digest: round.canonical_policy_digest(),
        execution_envelope_digest: round.execution_envelope_digest(),
        enrolled_inputs_digest: d,
        serving_observation_digest: d,
        training_material_digest: d,
        training_registration_digest: d,
        registry_binding_digest: d,
        registry_head_digest: d,
        registry_acknowledgement_digest: d,
        serving_scope_digest: d,
        serving_objective_digest: Digest32::of_bytes(b"actual user objective"),
        training_scope_digest: d,
        training_objective_digest: d,
        expected_training_scope_digest: d,
        expected_training_objective_digest: Digest32::of_bytes(
            b"original admitted training contract",
        ),
        configuration_digest: d,
        body_bundle_digest: d,
        neuron_generation: 1,
        goal_ordinal: Some(3),
        admitted_at_ms: round.admitted_at_ms(),
        deadline_ms: round.deadline_ms(),
        observed_at_ms: 1001,
    };
    let payload = self_iteration_serving_scope_signing_payload_v1(&facts).expect("whole facts");
    AgentdSelfIterationPreparationStatusV1 {
        facts_hex: String::new(),
        serving_scope_facts_hex: Some(payload.iter().map(|b| format!("{b:02x}")).collect()),
        source_path: "/run/original-root-e/serving-terminal.bin".into(),
        source_digest: d,
        evaluator_evidence_digest: d,
    }
}
#[test]
fn incompatible_actual_scope_cold_terminal_consumes_quota_and_cannot_retire_started_effects() {
    let (canonical, envelope) = inputs(4);
    let mut rounds = RoundJournal::default();
    let round = rounds
        .reserve(
            StableId::new("actual.goal.1").expect("id"),
            &canonical,
            &envelope,
            1000,
        )
        .expect("sole reserve");
    let terminal = serving_terminal(&round);
    let mut mixed = terminal.clone();
    mixed.facts_hex = "aa".into();
    assert!(rounds.complete_preparation(&round, mixed).is_err());
    let mut started = rounds.clone();
    started
        .begin(&round, &request(&round), 1001)
        .expect("real request intent");
    assert!(
        started
            .complete_preparation(&round, terminal.clone())
            .is_err()
    );
    rounds.retain_terminal_clock(2000);
    rounds
        .complete_preparation(&round, terminal.clone())
        .expect("timely signed facts late arrival");
    rounds
        .complete_preparation(&round, terminal.clone())
        .expect("same receipt idempotent");
    let mut changed = terminal.clone();
    changed.evaluator_evidence_digest = Digest32::of_bytes(b"other E receipt");
    assert!(rounds.complete_preparation(&round, changed).is_err());
    let directory = directory();
    let path = directory.path().join("original-round.json");
    let mut journal = journal::IterationJournal::open(path.clone()).expect("same owner");
    journal.persist_rounds(rounds).expect("original persist");
    drop(journal);
    let bytes = std::fs::read(&path).expect("original bytes");
    let journal = journal::IterationJournal::open(path.clone()).expect("cold owner");
    let mut rounds = journal.rounds.expect("original reservation");
    let current = rounds
        .current_status()
        .expect("readonly")
        .expect("same round");
    assert!(current.can_admit_next_round());
    assert_eq!(current.status.preparation, Some(terminal));
    assert!(current.status.model_stages.is_empty() && current.status.frozen_digest.is_none());
    assert_eq!(std::fs::read(&path).expect("readonly bytes"), bytes);
    assert_eq!(
        AgentdSelfIterationRoundStatusV1::from_json(&current.status.to_json().expect("sole codec"))
            .expect("full decode"),
        current.status
    );
    assert!(
        rounds
            .reserve(
                StableId::new("goal.clock.rollback").expect("id"),
                &canonical,
                &envelope,
                1999
            )
            .is_err()
    );
    let next = rounds
        .reserve(
            StableId::new("actual.goal.2").expect("id"),
            &canonical,
            &envelope,
            2001,
        )
        .expect("new bounded round");
    assert_eq!(next.ordinal(), 2);
    assert_eq!(next.deadline_ms(), round.deadline_ms());
    assert_eq!(
        rounds
            .current_status()
            .expect("read")
            .expect("new round")
            .status
            .admitted_policy_candidates,
        4
    );
}
