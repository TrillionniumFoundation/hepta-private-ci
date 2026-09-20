use super::*;

#[test]
fn agent_budget_round_trip_uses_the_canonical_resource_model() {
    let budget = ResourceBudget::local_default();
    let resources = FleetResourceVectorV1::from_agent_budget(&budget);
    assert_eq!(resources.try_into_agent_budget().expect("round trip"), budget);
}

#[test]
fn vector_arithmetic_fails_closed_on_underflow_and_overflow() {
    let maximum = FleetResourceVectorV1 {
        concurrent_turns: u64::MAX,
        ..FleetResourceVectorV1::default()
    };
    let one = FleetResourceVectorV1 {
        concurrent_turns: 1,
        ..FleetResourceVectorV1::default()
    };
    assert_eq!(maximum.checked_add(one), None);
    assert_eq!(FleetResourceVectorV1::default().checked_sub(one), None);
}
