use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::support::*;
use crate::CellCostMetricsV2;
use crate::CellCostStageV2;
use crate::CellGenerationDispositionV2;
use crate::CellGenerationErrorV2;
use crate::CellGenerationJournalV2;
use crate::CellGenerationProposalV2;
use crate::CellGenerationRequestV2;
use crate::cell_test_support::checked;

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

fn metered_proposal(
    request: &CellGenerationRequestV2,
    disposition: CellGenerationDispositionV2,
) -> CellGenerationProposalV2 {
    let mut proposed = proposal(request);
    let mut entry = proposed.cost.entries()[0].clone();
    entry.metrics = measured(3);
    proposed.cost = cost();
    checked(proposed.cost.record(entry));
    proposed.disposition = disposition;
    proposed
}

#[test]
fn pending_cancel_reopen_stop_and_ack_gate_complete_task_cost() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
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
        let mut entry = charge(&format!("prior-{index}"), stage);
        entry.metrics = measured(1);
        checked(owner.record_cost(entry));
    }
    let before = checked(owner.observe_generation());
    assert_eq!(
        checked(before.cost().summary()).complete_metrics(),
        Some(measured(14))
    );
    assert_eq!(before.complete_metrics(), None);
    assert_eq!(
        before.initial_snapshot_digest(),
        checked(config().initial.digest())
    );
    assert_eq!(before.source_digest(), config().manifest.source_digest);
    assert_eq!(before.source_frontier(), config().source_frontier);
    assert_eq!(before.task_digest(), config().task_digest);
    assert_eq!(
        before.manifest_digest(),
        checked(config().manifest.digest())
    );
    let bytes = fixture.bytes();
    assert_eq!(owner.observe_generation(), Ok(before.clone()));
    assert_eq!(fixture.bytes(), bytes);

    let req = request(&owner, "uncertain");
    checked(owner.admit(req.clone(), /*now_micros*/ 11));
    checked(owner.observe_dispatch_time(checked(req.digest()), /*observed_at_micros*/ 12));
    let pending = checked(owner.observe_generation());
    assert_eq!(
        pending.pending_request_digest(),
        Some(checked(req.digest()))
    );
    assert_eq!(pending.cost(), before.cost());
    assert_eq!(pending.snapshot(), before.snapshot());
    assert!(!pending.is_terminal());
    assert_eq!(pending.complete_metrics(), None);
    checked(owner.cancel(checked(req.digest())));
    let cancelled = checked(owner.observe_generation());
    assert_eq!(
        cancelled.pending_request_digest(),
        pending.pending_request_digest()
    );
    assert_ne!(cancelled.digest(), pending.digest());
    assert_ne!(cancelled.owner_checkpoint(), pending.owner_checkpoint());
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.observe_generation(), Ok(cancelled));
    checked(owner.commit(
        metered_proposal(&req, CellGenerationDispositionV2::Advanced),
        /*now_micros*/ 20,
    ));
    let settled = checked(owner.observe_generation());
    assert_eq!(settled.pending_request_digest(), None);
    assert_eq!(settled.first_advance_input_digest(), None);
    assert_eq!(settled.snapshot().prefix, before.snapshot().prefix);
    assert_eq!(
        checked(settled.cost().summary()).complete_metrics(),
        Some(measured(17))
    );
    assert_eq!(settled.complete_metrics(), None);

    let stop = request(&owner, "stop");
    checked(owner.admit(stop.clone(), /*now_micros*/ 30));
    checked(owner.commit(
        metered_proposal(&stop, CellGenerationDispositionV2::Stopped),
        /*now_micros*/ 31,
    ));
    let stopped = checked(owner.observe_generation());
    assert!(stopped.snapshot().stopped);
    assert!(!stopped.is_terminal());
    assert_eq!(stopped.complete_metrics(), None);
    let chunk = checked(stopped.pending_output().cloned().ok_or("stopped outbox"));
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.observe_generation(), Ok(stopped.clone()));
    let mut delivery_cost = cost();
    let mut entry = charge("delivery", CellCostStageV2::Communication);
    entry.metrics = measured(2);
    checked(delivery_cost.record(entry));
    checked(owner.acknowledge(chunk.clone(), [1; 32], delivery_cost.clone()));
    let terminal = checked(owner.observe_generation());
    assert!(terminal.is_terminal());
    assert_eq!(terminal.complete_metrics(), Some(measured(22)));
    assert_eq!(terminal.snapshot(), stopped.snapshot());
    assert_ne!(terminal.digest(), stopped.digest());
    checked(owner.acknowledge(chunk, [1; 32], delivery_cost));
    assert_eq!(owner.observe_generation(), Ok(terminal.clone()));
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.observe_generation(), Ok(terminal.clone()));

    let mut recovery = charge("late-recovery", CellCostStageV2::Recovery);
    recovery.metrics = CellCostMetricsV2::default();
    checked(owner.record_cost(recovery));
    let incomplete = checked(owner.observe_generation());
    assert!(incomplete.is_terminal());
    assert_eq!(incomplete.complete_metrics(), None);
    assert_eq!(terminal.complete_metrics(), Some(measured(22)));
    assert_eq!(incomplete.snapshot(), terminal.snapshot());
    assert_ne!(incomplete.digest(), terminal.digest());
    assert_eq!(
        checked(incomplete.cost().summary()).cpu_micros.known_sum,
        22
    );
    assert_eq!(
        checked(incomplete.cost().summary())
            .cpu_micros
            .unknown_entries,
        1
    );
}

#[test]
fn uncertain_owner_never_mints_an_observation_before_witness_recovery() {
    let fixture = Fixture::new();
    let fail = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        FailOnce {
            inner: fixture.witness(),
            fail: Arc::clone(&fail),
        },
        config(),
        /*max_records*/ 128,
    ));
    let before = checked(owner.observe_generation());
    fail.store(true, Ordering::SeqCst);
    let entry = charge("uncertain-write", CellCostStageV2::Persistence);
    assert_eq!(
        owner.record_cost(entry.clone()),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(
        owner.observe_generation(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    checked(owner.recover());
    let recovered = checked(owner.observe_generation());
    assert_eq!(recovered.snapshot(), before.snapshot());
    assert_eq!(recovered.cost().entries(), &[entry]);
    assert_ne!(recovered.owner_checkpoint(), before.owner_checkpoint());
    assert_ne!(recovered.digest(), before.digest());
    assert_eq!(recovered.complete_metrics(), None);
}

#[test]
fn first_adopted_input_is_rebuilt_without_promoting_failed_or_cancelled_initialization() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    assert_eq!(
        checked(owner.observe_generation()).first_advance_input_digest(),
        None
    );
    for (index, disposition) in [
        CellGenerationDispositionV2::Failed,
        CellGenerationDispositionV2::Cancelled,
        CellGenerationDispositionV2::DeadlineExceeded,
    ]
    .into_iter()
    .enumerate()
    {
        let mut req = request(&owner, &format!("unadopted-{index}"));
        req.input = b"wrong initialization".to_vec();
        checked(owner.admit(req.clone(), /*now_micros*/ 11));
        let mut proposed = proposal(&req);
        proposed.disposition = disposition;
        proposed.successor_state = req.predecessor.state.clone();
        proposed.output_delta.clear();
        checked(owner.commit(proposed, /*now_micros*/ 11));
        assert_eq!(
            checked(owner.observe_generation()).first_advance_input_digest(),
            None
        );
    }
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(
        checked(owner.observe_generation()).first_advance_input_digest(),
        None
    );
    let mut req = request(&owner, "actual-init");
    req.input = b"frozen initialization".to_vec();
    checked(owner.admit(req.clone(), /*now_micros*/ 12));
    let mut proposed = proposal(&req);
    proposed.output_delta.clear();
    checked(owner.commit(proposed, /*now_micros*/ 13));
    let adopted = checked(owner.observe_generation());
    assert_eq!(
        adopted.first_advance_input_digest(),
        Some(Digest32::of_bytes(&req.input).into_array())
    );
    drop(owner);
    let mut owner = fixture.open();
    assert_eq!(owner.observe_generation(), Ok(adopted.clone()));
    let mut later = request(&owner, "later-step");
    later.input = b"different successor input".to_vec();
    checked(owner.admit(later.clone(), /*now_micros*/ 14));
    let mut proposed = proposal(&later);
    proposed.output_delta.clear();
    checked(owner.commit(proposed, /*now_micros*/ 15));
    assert_eq!(
        checked(owner.observe_generation()).first_advance_input_digest(),
        adopted.first_advance_input_digest()
    );
}
