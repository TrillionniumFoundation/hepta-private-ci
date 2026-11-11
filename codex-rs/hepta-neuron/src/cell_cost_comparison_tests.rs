use pretty_assertions::assert_eq;

use super::*;
use crate::CellCostAccountingV2;
use crate::CellCostEntryV2;
use crate::CellCostOutcomeV2;
use crate::CellCostStageV2;
use crate::CellTaskCostIdentityV2;
use crate::cell_test_support::checked;

fn ledger(value: u64) -> CellTaskCostV2 {
    let identity = CellTaskCostIdentityV2 {
        task_digest: [1; 32],
        source_digest: [2; 32],
    };
    ledger_with_identity(value, identity)
}

fn ledger_with_identity(value: u64, identity: CellTaskCostIdentityV2) -> CellTaskCostV2 {
    let mut costs = checked(CellTaskCostV2::new(identity));
    for (index, stage) in [
        CellCostStageV2::Encoder,
        CellCostStageV2::Routing,
        CellCostStageV2::Inference,
        CellCostStageV2::Training,
        CellCostStageV2::Planning,
        CellCostStageV2::Critic,
        CellCostStageV2::Codec,
        CellCostStageV2::Queue,
        CellCostStageV2::Persistence,
        CellCostStageV2::Recovery,
        CellCostStageV2::Communication,
        CellCostStageV2::Evaluation,
        CellCostStageV2::ModelAcquisition,
        CellCostStageV2::Migration,
    ]
    .into_iter()
    .enumerate()
    {
        checked(costs.record(CellCostEntryV2 {
            event_id: [index as u8 + 1; 32],
            identity,
            stage,
            outcome: CellCostOutcomeV2::Succeeded,
            accounting: CellCostAccountingV2::Exclusive,
            metrics: CellCostMetricsV2 {
                wall_micros: Some(value),
                cpu_micros: Some(value),
                energy_microjoules: Some(value),
                storage_read_bytes: Some(value),
                storage_write_bytes: Some(value),
                storage_byte_micros: Some(value),
                communication_bytes: Some(value),
            },
        }));
    }
    costs
}

fn basis() -> CellCostComparisonBasisV2 {
    CellCostComparisonBasisV2 {
        inputs: [3; 32],
        resource_budget: [4; 32],
        executor: [5; 32],
        metering_contract: [6; 32],
        evaluation: [7; 32],
    }
}

fn compare(
    before: &CellTaskCostV2,
    after: &CellTaskCostV2,
) -> Result<CellCostDifferenceV2, CellCostComparisonErrorV2> {
    let basis = basis();
    compare_cell_task_costs_v2(
        CellCostComparisonRunV2 {
            basis: &basis,
            costs: before,
            elapsed_micros: Some(100),
        },
        CellCostComparisonRunV2 {
            basis: &basis,
            costs: after,
            elapsed_micros: Some(80),
        },
    )
}

#[test]
fn complete_cycles_charge_failed_candidates_and_keep_latency_separate() {
    let baseline = ledger(3);
    let mut candidate = ledger(1);
    let mut failed = candidate.entries()[3].clone();
    failed.event_id = [99; 32];
    failed.outcome = CellCostOutcomeV2::Failed;
    checked(candidate.record(failed.clone()));
    checked(candidate.record(failed));
    assert_eq!(
        compare(&baseline, &candidate),
        Ok(CellCostDifferenceV2 {
            baseline_identity: baseline.identity(),
            candidate_identity: candidate.identity(),
            elapsed_micros: -20,
            wall_work_micros: -27,
            cpu_micros: -27,
            energy_microjoules: -27,
            storage_read_bytes: -27,
            storage_write_bytes: -27,
            storage_byte_micros: -27,
            communication_bytes: -27,
        })
    );
}

#[test]
fn different_implementations_share_conditions_and_retain_both_source_identities() {
    let baseline = ledger(3);
    let candidate = ledger_with_identity(
        /*value*/ 1,
        CellTaskCostIdentityV2 {
            source_digest: [9; 32],
            ..baseline.identity()
        },
    );
    assert_eq!(
        compare(&baseline, &candidate),
        Ok(CellCostDifferenceV2 {
            baseline_identity: baseline.identity(),
            candidate_identity: candidate.identity(),
            elapsed_micros: -20,
            wall_work_micros: -28,
            cpu_micros: -28,
            energy_microjoules: -28,
            storage_read_bytes: -28,
            storage_write_bytes: -28,
            storage_byte_micros: -28,
            communication_bytes: -28,
        })
    );
}

#[test]
fn envelopes_do_not_add_costs_but_unknown_envelopes_block_the_complete_cycle() {
    let baseline = ledger(3);
    let mut candidate = ledger(1);
    let expected = checked(compare(&baseline, &candidate));
    let mut envelope = candidate.entries()[0].clone();
    envelope.event_id = [99; 32];
    envelope.accounting = CellCostAccountingV2::InclusiveEnvelope {
        exclusive_event_ids: vec![candidate.entries()[0].event_id],
    };
    checked(candidate.record(envelope.clone()));
    assert_eq!(compare(&baseline, &candidate), Ok(expected));
    let complete_metrics = checked(candidate.summary()).complete_metrics();
    envelope.event_id = [100; 32];
    envelope.outcome = CellCostOutcomeV2::Unknown;
    checked(candidate.record(envelope));
    assert_eq!(
        checked(candidate.summary()).complete_metrics(),
        complete_metrics
    );
    assert_eq!(
        compare(&baseline, &candidate),
        Err(CellCostComparisonErrorV2::IncompleteCycle)
    );
}

#[test]
fn missing_new_stages_unknown_energy_or_unresolved_work_cannot_claim_savings() {
    let baseline = ledger(2);
    for omitted in [
        CellCostStageV2::ModelAcquisition,
        CellCostStageV2::Migration,
    ] {
        let mut missing = checked(CellTaskCostV2::new(baseline.identity()));
        for entry in ledger(1)
            .entries()
            .iter()
            .filter(|entry| entry.stage != omitted)
        {
            checked(missing.record(entry.clone()));
        }
        assert_eq!(
            compare(&baseline, &missing),
            Err(CellCostComparisonErrorV2::IncompleteCycle)
        );
    }
    for unknown_outcome in [false, true] {
        let mut missing = ledger(1);
        let mut entry = missing.entries()[0].clone();
        entry.event_id = [99; 32];
        if unknown_outcome {
            entry.outcome = CellCostOutcomeV2::Unknown;
        } else {
            entry.metrics.energy_microjoules = None;
        }
        checked(missing.record(entry));
        assert_eq!(
            compare(&baseline, &missing),
            Err(CellCostComparisonErrorV2::IncompleteCycle)
        );
    }
}

#[test]
fn different_conditions_or_task_remain_incomparable_across_sources() {
    let baseline = ledger(2);
    let candidate = ledger_with_identity(
        /*value*/ 1,
        CellTaskCostIdentityV2 {
            source_digest: [9; 32],
            ..baseline.identity()
        },
    );
    let basis = basis();
    for other in [
        CellCostComparisonBasisV2 {
            inputs: [8; 32],
            ..basis.clone()
        },
        CellCostComparisonBasisV2 {
            resource_budget: [8; 32],
            ..basis.clone()
        },
        CellCostComparisonBasisV2 {
            executor: [8; 32],
            ..basis.clone()
        },
        CellCostComparisonBasisV2 {
            metering_contract: [8; 32],
            ..basis.clone()
        },
        CellCostComparisonBasisV2 {
            evaluation: [8; 32],
            ..basis.clone()
        },
    ] {
        assert_eq!(
            compare_cell_task_costs_v2(
                CellCostComparisonRunV2 {
                    basis: &basis,
                    costs: &baseline,
                    elapsed_micros: Some(100)
                },
                CellCostComparisonRunV2 {
                    basis: &other,
                    costs: &candidate,
                    elapsed_micros: Some(80)
                },
            ),
            Err(CellCostComparisonErrorV2::IncompatibleBasis)
        );
    }
    let other_task = ledger_with_identity(
        /*value*/ 1,
        CellTaskCostIdentityV2 {
            task_digest: [9; 32],
            ..candidate.identity()
        },
    );
    assert_eq!(
        compare(&baseline, &other_task),
        Err(CellCostComparisonErrorV2::IncompatibleBasis)
    );
}

#[test]
fn matching_unspecified_conditions_are_not_an_explicit_comparison_basis() {
    let baseline = ledger(2);
    let candidate = ledger_with_identity(
        /*value*/ 1,
        CellTaskCostIdentityV2 {
            source_digest: [9; 32],
            ..baseline.identity()
        },
    );
    let basis = CellCostComparisonBasisV2 {
        metering_contract: [0; 32],
        ..basis()
    };
    assert_eq!(
        compare_cell_task_costs_v2(
            CellCostComparisonRunV2 {
                basis: &basis,
                costs: &baseline,
                elapsed_micros: Some(100)
            },
            CellCostComparisonRunV2 {
                basis: &basis,
                costs: &candidate,
                elapsed_micros: Some(80)
            },
        ),
        Err(CellCostComparisonErrorV2::IncompatibleBasis)
    );
}
