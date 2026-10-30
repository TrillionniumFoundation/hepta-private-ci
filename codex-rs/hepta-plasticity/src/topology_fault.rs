//! Qualification-only topology fault matrix.
//!
//! This module does not apply a topology. It enumerates the lifecycle fault
//! points that a real supervisor/runtime integration must inject and records
//! the safe disposition expected from each point. Keeping the matrix in the
//! proposal crate prevents split/merge/rewire/retire from being treated as
//! special cases during qualification.

use crate::TopologyOperationV2;

const TOPOLOGY_OPERATIONS: [TopologyOperationV2; 4] = [
    TopologyOperationV2::Split,
    TopologyOperationV2::Merge,
    TopologyOperationV2::Rewire,
    TopologyOperationV2::Retire,
];

const FAULT_POINTS: [TopologyFaultPointV1; 10] = [
    TopologyFaultPointV1::Candidate,
    TopologyFaultPointV1::IndependentEvaluation,
    TopologyFaultPointV1::Selector,
    TopologyFaultPointV1::SignedSuccessorSnapshot,
    TopologyFaultPointV1::StateMigration,
    TopologyFaultPointV1::OldWriterFence,
    TopologyFaultPointV1::RouteCutover,
    TopologyFaultPointV1::Canary,
    TopologyFaultPointV1::RollbackRehearsal,
    TopologyFaultPointV1::ProductionAdmission,
];

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopologyFaultPointV1 {
    Candidate,
    IndependentEvaluation,
    Selector,
    SignedSuccessorSnapshot,
    StateMigration,
    OldWriterFence,
    RouteCutover,
    Canary,
    RollbackRehearsal,
    ProductionAdmission,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopologyFaultDispositionV1 {
    RejectedBeforeAdmission,
    ReconcileThenRollback,
    Quarantine,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TopologyFaultScenarioV1 {
    pub operation: TopologyOperationV2,
    pub point: TopologyFaultPointV1,
    pub disposition: TopologyFaultDispositionV1,
}

/// Return the complete qualification matrix for the four structural mutations
/// that require explicit failure injection.
#[must_use]
pub fn topology_fault_scenarios_v1() -> Vec<TopologyFaultScenarioV1> {
    TOPOLOGY_OPERATIONS
        .into_iter()
        .flat_map(|operation| {
            FAULT_POINTS
                .into_iter()
                .map(move |point| TopologyFaultScenarioV1 {
                    operation,
                    point,
                    disposition: disposition_for(point),
                })
        })
        .collect()
}

#[must_use]
pub const fn topology_fault_points_v1() -> &'static [TopologyFaultPointV1; 10] {
    &FAULT_POINTS
}

const fn disposition_for(point: TopologyFaultPointV1) -> TopologyFaultDispositionV1 {
    match point {
        TopologyFaultPointV1::Candidate
        | TopologyFaultPointV1::IndependentEvaluation
        | TopologyFaultPointV1::Selector
        | TopologyFaultPointV1::SignedSuccessorSnapshot => {
            TopologyFaultDispositionV1::RejectedBeforeAdmission
        }
        TopologyFaultPointV1::StateMigration
        | TopologyFaultPointV1::OldWriterFence
        | TopologyFaultPointV1::RouteCutover
        | TopologyFaultPointV1::Canary
        | TopologyFaultPointV1::ProductionAdmission => {
            TopologyFaultDispositionV1::ReconcileThenRollback
        }
        TopologyFaultPointV1::RollbackRehearsal => TopologyFaultDispositionV1::Quarantine,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_structural_operation_has_every_fault_point() {
        let scenarios = topology_fault_scenarios_v1();
        assert_eq!(scenarios.len(), 40);
        for operation in TOPOLOGY_OPERATIONS {
            assert_eq!(
                scenarios
                    .iter()
                    .filter(|scenario| scenario.operation == operation)
                    .count(),
                FAULT_POINTS.len()
            );
        }
    }

    #[test]
    fn no_injected_fault_is_admitted_as_success() {
        assert!(topology_fault_scenarios_v1().iter().all(|scenario| {
            matches!(
                scenario.disposition,
                TopologyFaultDispositionV1::RejectedBeforeAdmission
                    | TopologyFaultDispositionV1::ReconcileThenRollback
                    | TopologyFaultDispositionV1::Quarantine
            )
        }));
    }
}
