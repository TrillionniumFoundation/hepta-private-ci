use pretty_assertions::assert_eq;

use super::*;
use crate::cell_test_support::checked;

fn identity() -> CellTaskCostIdentityV2 {
    CellTaskCostIdentityV2 {
        task_digest: [1; 32],
        source_digest: [2; 32],
    }
}

fn measured(value: u64) -> CellCostMetricsV2 {
    CellCostMetricsV2 {
        wall_micros: Some(value),
        cpu_micros: Some(value),
        energy_microjoules: Some(value),
        storage_read_bytes: Some(value),
        storage_write_bytes: Some(value),
        storage_byte_micros: Some(value),
        communication_bytes: Some(value),
    }
}

fn entry(id: u8, stage: CellCostStageV2, outcome: CellCostOutcomeV2) -> CellCostEntryV2 {
    CellCostEntryV2 {
        event_id: [id; 32],
        identity: identity(),
        stage,
        outcome,
        accounting: CellCostAccountingV2::Exclusive,
        metrics: measured(1),
    }
}

fn envelope(id: u8, members: Vec<[u8; 32]>, value: u64) -> CellCostEntryV2 {
    CellCostEntryV2 {
        accounting: CellCostAccountingV2::InclusiveEnvelope {
            exclusive_event_ids: members,
        },
        metrics: measured(value),
        ..entry(id, CellCostStageV2::Inference, CellCostOutcomeV2::Failed)
    }
}

#[test]
fn replay_after_serialized_reopen_is_free_but_conflicting_reuse_is_atomic() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    let original = entry(3, CellCostStageV2::Inference, CellCostOutcomeV2::Failed);
    assert_eq!(
        costs.record(original.clone()),
        Ok(CellCostRecordV2::Inserted)
    );
    let bytes = checked(serde_json::to_vec(&costs));
    let mut reopened: CellTaskCostV2 = checked(serde_json::from_slice(&bytes));
    assert_eq!(
        reopened.record(original.clone()),
        Ok(CellCostRecordV2::Replayed)
    );
    assert_eq!(reopened, costs);
    for changed in [
        CellCostEntryV2 {
            metrics: measured(2),
            ..original.clone()
        },
        CellCostEntryV2 {
            outcome: CellCostOutcomeV2::Succeeded,
            ..original.clone()
        },
        CellCostEntryV2 {
            identity: CellTaskCostIdentityV2 {
                source_digest: [9; 32],
                ..identity()
            },
            ..original
        },
    ] {
        assert_eq!(
            reopened.record(changed),
            Err(CellTaskCostErrorV2::EventConflict)
        );
        assert_eq!(reopened, costs);
    }
}

#[test]
fn task_source_and_zero_identity_refusals_preserve_state() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    let before = costs.clone();
    for changed in [
        CellTaskCostIdentityV2 {
            task_digest: [3; 32],
            ..identity()
        },
        CellTaskCostIdentityV2 {
            source_digest: [3; 32],
            ..identity()
        },
    ] {
        let mut wrong = entry(3, CellCostStageV2::Recovery, CellCostOutcomeV2::Cancelled);
        wrong.identity = changed;
        assert_eq!(
            costs.record(wrong),
            Err(CellTaskCostErrorV2::SourceMismatch)
        );
        assert_eq!(costs, before);
    }
    assert_eq!(
        costs.record(entry(
            0,
            CellCostStageV2::Encoder,
            CellCostOutcomeV2::Rejected
        )),
        Err(CellTaskCostErrorV2::InvalidIdentity)
    );
    assert_eq!(
        CellTaskCostV2::new(CellTaskCostIdentityV2 {
            task_digest: [0; 32],
            ..identity()
        }),
        Err(CellTaskCostErrorV2::InvalidIdentity)
    );
    assert_eq!(costs, before);
}

#[test]
fn failed_cancelled_rejected_and_unknown_work_remains_charged() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    for (id, stage, outcome) in [
        (3, CellCostStageV2::Encoder, CellCostOutcomeV2::Failed),
        (4, CellCostStageV2::Routing, CellCostOutcomeV2::Cancelled),
        (5, CellCostStageV2::Inference, CellCostOutcomeV2::Rejected),
        (6, CellCostStageV2::Recovery, CellCostOutcomeV2::Unknown),
    ] {
        checked(costs.record(entry(id, stage, outcome)));
    }
    let summary = checked(costs.summary());
    let known = CellCostTotalV2 {
        known_sum: 4,
        unknown_entries: 0,
    };
    assert_eq!(
        summary,
        CellTaskCostSummaryV2 {
            wall_work_micros: known,
            cpu_micros: known,
            energy_microjoules: known,
            storage_read_bytes: known,
            storage_write_bytes: known,
            storage_byte_micros: known,
            communication_bytes: known,
            missing_stages: vec![
                CellCostStageV2::Training,
                CellCostStageV2::Planning,
                CellCostStageV2::Critic,
                CellCostStageV2::Codec,
                CellCostStageV2::Queue,
                CellCostStageV2::Persistence,
                CellCostStageV2::Communication,
                CellCostStageV2::Evaluation,
                CellCostStageV2::ModelAcquisition,
                CellCostStageV2::Migration
            ],
            exclusive_entries: 4,
            inclusive_envelopes: 0,
            unsuccessful_entries: 3,
            unknown_outcome_entries: 1,
        }
    );
    assert_eq!(summary.complete_metrics(), None);
}

#[test]
fn missing_stage_and_unknown_measurement_are_not_measured_zero() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    assert_eq!(checked(costs.summary()).complete_metrics(), None);
    for (index, stage) in STAGES.into_iter().enumerate() {
        let mut zero = entry(index as u8 + 1, stage, CellCostOutcomeV2::Succeeded);
        zero.metrics = measured(0);
        checked(costs.record(zero));
    }
    assert_eq!(
        checked(costs.summary()).complete_metrics(),
        Some(measured(0))
    );
    let mut unknown = entry(99, CellCostStageV2::Inference, CellCostOutcomeV2::Unknown);
    unknown.metrics = CellCostMetricsV2::default();
    checked(costs.record(unknown));
    let summary = checked(costs.summary());
    assert_eq!(summary.complete_metrics(), None);
    assert_eq!(
        summary.cpu_micros,
        CellCostTotalV2 {
            known_sum: 0,
            unknown_entries: 1
        }
    );
    assert_eq!(
        summary.energy_microjoules,
        CellCostTotalV2 {
            known_sum: 0,
            unknown_entries: 1
        }
    );
    let encoded = checked(serde_json::to_value(&costs));
    assert_eq!(
        encoded["entries"][12]["metrics"]["cpu_micros"],
        serde_json::Value::Null
    );
}

#[test]
fn overlapping_envelopes_never_double_charge_parallel_exclusive_work() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    for id in [3, 4] {
        let mut work = entry(id, CellCostStageV2::Inference, CellCostOutcomeV2::Succeeded);
        work.metrics.wall_micros = Some(20);
        checked(costs.record(work));
    }
    let mut outer = envelope(5, vec![[3; 32], [4; 32]], 2);
    outer.metrics.wall_micros = Some(30);
    checked(costs.record(outer.clone()));
    outer.event_id = [6; 32];
    checked(costs.record(outer));
    let summary = checked(costs.summary());
    assert_eq!(
        summary.cpu_micros,
        CellCostTotalV2 {
            known_sum: 2,
            unknown_entries: 0
        }
    );
    assert_eq!(
        summary.wall_work_micros,
        CellCostTotalV2 {
            known_sum: 40,
            unknown_entries: 0
        }
    );
    assert_eq!(summary.inclusive_envelopes, 2);
    assert_eq!(costs.entries().len(), 4);
}

#[test]
fn envelope_rejects_unaccounted_overhead_missing_nested_and_duplicate_members() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    checked(costs.record(entry(
        3,
        CellCostStageV2::Encoder,
        CellCostOutcomeV2::Succeeded,
    )));
    checked(costs.record(envelope(4, vec![[3; 32]], 1)));
    let before = costs.clone();
    for invalid in [
        envelope(5, vec![[3; 32]], 2),
        envelope(5, vec![[3; 32]], 0),
        envelope(5, vec![[99; 32]], 1),
        envelope(5, vec![[4; 32]], 1),
        envelope(5, vec![[3; 32], [3; 32]], 2),
        envelope(5, vec![], 1),
    ] {
        assert_eq!(
            costs.record(invalid),
            Err(CellTaskCostErrorV2::InvalidEnvelope)
        );
        assert_eq!(costs, before);
    }
}

#[test]
fn inclusive_observation_cannot_fill_unknown_exclusive_energy() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    let mut work = entry(3, CellCostStageV2::Inference, CellCostOutcomeV2::Cancelled);
    work.metrics.energy_microjoules = None;
    checked(costs.record(work));
    checked(costs.record(envelope(4, vec![[3; 32]], 1)));
    assert_eq!(
        checked(costs.summary()).energy_microjoules,
        CellCostTotalV2 {
            known_sum: 0,
            unknown_entries: 1
        }
    );
}

#[test]
fn overflow_refuses_new_charge_without_clamping_or_partial_append() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    let mut work = entry(3, CellCostStageV2::Training, CellCostOutcomeV2::Failed);
    work.metrics.cpu_micros = Some(u64::MAX);
    checked(costs.record(work));
    let before = costs.clone();
    assert_eq!(
        costs.record(entry(
            4,
            CellCostStageV2::Training,
            CellCostOutcomeV2::Rejected
        )),
        Err(CellTaskCostErrorV2::ArithmeticOverflow)
    );
    assert_eq!(costs, before);
    assert_eq!(
        checked(costs.summary()).cpu_micros,
        CellCostTotalV2 {
            known_sum: u64::MAX,
            unknown_entries: 0
        }
    );
}

#[test]
fn deserialize_does_not_bypass_identity_or_duplicate_validation() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    let original = entry(
        3,
        CellCostStageV2::Persistence,
        CellCostOutcomeV2::Succeeded,
    );
    checked(costs.record(original.clone()));
    let mut encoded = checked(serde_json::to_value(&costs));
    let duplicate = encoded["entries"][0].clone();
    checked(encoded["entries"].as_array_mut().ok_or("entries")).push(duplicate);
    let mut poisoned: CellTaskCostV2 = checked(serde_json::from_value(encoded));
    assert_eq!(
        poisoned.validate(),
        Err(CellTaskCostErrorV2::DuplicateEvent)
    );
    assert_eq!(poisoned.summary(), Err(CellTaskCostErrorV2::DuplicateEvent));
    assert_eq!(
        poisoned.record(original),
        Err(CellTaskCostErrorV2::DuplicateEvent)
    );
}

#[test]
fn capacity_keeps_replay_available_without_permitting_new_work() {
    let mut costs = checked(CellTaskCostV2::new(identity()));
    for id in 1..=MAX_ENTRIES {
        let mut work = entry(1, CellCostStageV2::Queue, CellCostOutcomeV2::Cancelled);
        work.event_id[..8].copy_from_slice(&(id as u64).to_be_bytes());
        costs.entries.push(work);
    }
    checked(costs.validate());
    let replay = costs.entries()[0].clone();
    let before = costs.clone();
    assert_eq!(costs.record(replay), Ok(CellCostRecordV2::Replayed));
    assert_eq!(
        costs.record(entry(
            99,
            CellCostStageV2::Queue,
            CellCostOutcomeV2::Rejected
        )),
        Err(CellTaskCostErrorV2::CapacityExceeded)
    );
    assert_eq!(costs, before);
}
