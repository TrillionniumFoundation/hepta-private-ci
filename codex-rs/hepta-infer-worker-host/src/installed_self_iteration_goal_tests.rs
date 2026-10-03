use super::*;
use codex_hepta_agentd::AgentdNeuronScopeIdentityV3;
use pretty_assertions::assert_eq;

#[test]
fn actual_successor_goal_with_same_subject_reserves_a_distinct_round_identity() {
    let pin = |name: &str| Digest32::of_bytes(name.as_bytes());
    let first = AgentdNeuronGoalScopeV3 {
        ordinal: 1,
        identity: AgentdNeuronScopeIdentityV3 {
            model_generation: 1,
            subject_scope_digest: pin("same-actual-subject"),
            objective_digest: pin("first-objective"),
            runtime_configuration_digest: pin("actual-model"),
            body_bundle_digest: pin("actual-body"),
        },
    };
    assert_eq!(
        from_scope(&first).unwrap(),
        StableId::new(format!("goal.{}", first.identity.subject_scope_digest)).unwrap()
    );
    let mut next = first.clone();
    next.ordinal = 2;
    next.identity.objective_digest = pin("next-objective");
    assert_ne!(from_scope(&next).unwrap(), from_scope(&first).unwrap());
    assert_eq!(
        from_scope(&next).unwrap(),
        from_scope(&next.clone()).unwrap()
    );
    let mut later = next.clone();
    later.ordinal = 3;
    assert_ne!(from_scope(&later).unwrap(), from_scope(&next).unwrap());
    let mut altered = next.clone();
    altered.identity.body_bundle_digest = pin("another-actual-body");
    assert_ne!(from_scope(&altered).unwrap(), from_scope(&next).unwrap());
    next.ordinal = 0;
    assert!(from_scope(&next).is_err());
}
