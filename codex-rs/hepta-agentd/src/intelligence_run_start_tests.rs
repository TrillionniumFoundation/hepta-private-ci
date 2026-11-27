use super::*;
use pretty_assertions::assert_eq;

#[test]
fn preparation_budget_is_capped_by_the_original_deadline() {
    assert_eq!(
        remaining_preparation_budget(100, 105, 70_000_000).unwrap(),
        5_000
    );
    assert_eq!(
        remaining_preparation_budget(100, 1_000, 2_000).unwrap(),
        2_000
    );
    for original_deadline in [99, 100] {
        assert!(matches!(
            remaining_preparation_budget(100, original_deadline, 70_000_000),
            Err(AgentdIntelligenceProductError::Run(
                crate::AgentRunError::InvalidDeadline
            ))
        ));
    }
}
