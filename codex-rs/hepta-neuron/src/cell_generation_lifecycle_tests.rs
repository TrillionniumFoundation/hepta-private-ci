use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

use super::super::support::*;
use super::*;
use crate::FileAnchorWitnessStore;
use crate::WitnessStoreError;
use crate::cell_task_cost::CellCostStageV2;
use crate::cell_test_support::checked;

#[test]
fn checkpoint_keeps_outbox_receipts_cost_and_archive_across_reopen() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let request = request(&owner, "committed");
    checked(owner.admit(request.clone(), /*now_micros*/ 10));
    let receipt = checked(owner.commit(proposal(&request), /*now_micros*/ 20));
    let original = owner.state.clone();
    let archive = fixture.bytes();
    let cut = checked(owner.checkpoint_to(fixture.file("successor")));
    assert_eq!(fixture.bytes(), archive);
    assert_eq!(
        cut.archived_digest,
        Digest32::of_bytes(&archive).into_array()
    );
    assert_eq!(cut.archived_bytes, archive.len() as u64);
    assert_eq!(
        checked(owner.journal_metrics(/*now_micros*/ 20)).segment_records,
        0
    );
    assert_eq!(owner.state, original);
    drop(owner);

    let mut reopened = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 128,
    ));
    assert_eq!(reopened.state, original);
    assert_eq!(
        checked(reopened.journal_metrics(/*now_micros*/ 20)).replay_records,
        0
    );
    assert_eq!(
        checked(reopened.admit(request, /*now_micros*/ 20)),
        Some(receipt)
    );
    let chunk = checked(
        checked(reopened.pending_output())
            .cloned()
            .ok_or("retained output"),
    );
    checked(reopened.acknowledge(chunk, [31; 32], cost()));
    let after_ack = reopened.state.clone();
    drop(reopened);
    let reopened = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 128,
    ));
    assert_eq!(reopened.state, after_ack);
    assert_eq!(
        checked(reopened.journal_metrics(/*now_micros*/ 20)).replay_records,
        1
    );
}

struct Readback {
    proposal: Option<CellGenerationProposalV2>,
    reads: usize,
}

impl CellGenerationControlPortV2 for Readback {
    fn execute_generation(
        &mut self,
        _: &CellBackendManifestV2,
        _: &CellGenerationRequestV2,
    ) -> Result<CellGenerationProposalV2, CellGenerationErrorV2> {
        panic!("reconciliation must never resubmit generation")
    }

    fn read_generation(
        &mut self,
        _: &CellGenerationRequestV2,
    ) -> Result<Option<CellGenerationProposalV2>, CellGenerationErrorV2> {
        self.reads += 1;
        Ok(self.proposal.clone())
    }

    fn cancel_generation(
        &mut self,
        _: &CellGenerationRequestV2,
    ) -> Result<(), CellGenerationErrorV2> {
        panic!("reconciliation must not contact cancellation")
    }
}

#[test]
fn checkpoint_reclaims_frames_but_unknown_stays_reserved_until_readback() {
    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 6);
    let request = request(&owner, "unknown");
    checked(owner.admit(request.clone(), /*now_micros*/ 10));
    checked(owner.observe_dispatch_time(checked(request.digest()), /*observed_at_micros*/ 12));
    checked(owner.cancel(checked(request.digest())));
    checked(owner.drain());
    assert_eq!(
        owner.record_cost(charge("overhead", CellCostStageV2::Persistence)),
        Err(CellGenerationErrorV2::Capacity)
    );
    let retained = owner.state.clone();
    checked(owner.checkpoint_to(fixture.file("successor")));
    assert_eq!(owner.state, retained);
    drop(owner);
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 6,
    ));
    assert_eq!(owner.state, retained);
    let metrics = checked(owner.journal_metrics(/*now_micros*/ 25));
    assert_eq!(
        (
            metrics.segment_records,
            metrics.reserved_records,
            metrics.pending_age_micros,
            metrics.queue_age_micros,
            metrics.cancelled,
            metrics.draining
        ),
        (0, 2, Some(15), None, true, true)
    );
    checked(owner.record_cost(charge("overhead", CellCostStageV2::Persistence)));
    let mut readback = Readback {
        proposal: None,
        reads: 0,
    };
    assert_eq!(checked(owner.reconcile_pending(&mut readback, || 25)), None);
    assert_eq!(checked(owner.pending_request()), Some(&request));
    assert_eq!(checked(owner.is_drained()), false);
    readback.proposal = Some(proposal(&request));
    let receipt =
        checked(checked(owner.reconcile_pending(&mut readback, || 30)).ok_or("known proposal"));
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    assert_eq!(readback.reads, 2);
    assert_eq!(checked(owner.pending_output()), None);
    assert_eq!(checked(owner.snapshot()).prefix, retained.snapshot.prefix);
    assert_eq!(checked(owner.is_drained()), true);
    assert_eq!(checked(owner.task_cost()).entries().len(), 2);
}

#[test]
fn unwitnessed_successor_cannot_replace_original_owner_after_failed_switch() {
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
    let request = request(&owner, "pending");
    checked(owner.admit(request, /*now_micros*/ 10));
    let original = owner.state.clone();
    let archive = fixture.bytes();
    fail.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.checkpoint_to(fixture.file("successor")),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    checked(owner.recover());
    assert_eq!(owner.state, original);
    drop(owner);
    assert_eq!(
        CellGenerationJournalV2::open(
            fixture.file("successor"),
            fixture.witness(),
            config(),
            /*max_records*/ 128,
        )
        .err(),
        Some(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    let original_owner = fixture.open();
    assert_eq!(original_owner.state, original);
    assert_eq!(fixture.bytes(), archive);
}

struct LoseAcknowledgement {
    inner: FileAnchorWitnessStore,
    lose: Arc<AtomicBool>,
}

impl AnchorWitnessStore for LoseAcknowledgement {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        if self.lose.swap(false, Ordering::SeqCst) {
            return Err(WitnessStoreError::Indeterminate);
        }
        Ok(())
    }
}

#[test]
fn witnessed_switch_with_lost_ack_reopens_only_the_successor() {
    let fixture = Fixture::new();
    let lose = Arc::new(AtomicBool::new(false));
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("journal"),
        LoseAcknowledgement {
            inner: fixture.witness(),
            lose: Arc::clone(&lose),
        },
        config(),
        /*max_records*/ 128,
    ));
    let request = request(&owner, "pending");
    checked(owner.admit(request, /*now_micros*/ 10));
    let original = owner.state.clone();
    let archive = fixture.bytes();
    lose.store(true, Ordering::SeqCst);
    assert_eq!(
        owner.checkpoint_to(fixture.file("successor")),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(
        owner.recover(),
        Err(CellGenerationErrorV2::AcknowledgedHistoryMissing)
    );
    assert_eq!(fixture.bytes(), archive);
    drop(owner);
    let successor = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 128,
    ));
    assert_eq!(successor.state, original);
    drop(successor);
    let successor_file = fixture.file("successor");
    checked(successor_file.set_len(40));
    let truncated = checked(fs::read(fixture.0.join("successor")));
    assert_eq!(
        CellGenerationJournalV2::open(
            successor_file,
            fixture.witness(),
            config(),
            /*max_records*/ 128,
        )
        .err(),
        Some(CellGenerationErrorV2::Corrupt)
    );
    assert_eq!(checked(fs::read(fixture.0.join("successor"))), truncated);
}

#[test]
fn checkpoint_never_evicts_operation_identity_to_bypass_receipt_capacity() {
    let fixture = Fixture::new();
    let mut owner = fixture.open_with(config(), /*max_records*/ 1_024);
    let mut first = None;
    for index in 0..256 {
        let mut request = request(&owner, &format!("operation-{index}"));
        request.admitted_at_micros = 10 + index * 2;
        request.deadline_micros = request.admitted_at_micros + 100;
        checked(owner.admit(request.clone(), request.admitted_at_micros));
        let mut proposal = proposal(&request);
        proposal.output_delta.clear();
        let receipt = checked(owner.commit(proposal, request.admitted_at_micros + 1));
        if index == 0 {
            first = Some((request, receipt));
        }
    }
    let before = owner.state.clone();
    checked(owner.checkpoint_to(fixture.file("successor")));
    drop(owner);
    let mut owner = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 1_024,
    ));
    assert_eq!(owner.state, before);
    let (first_request, first_receipt) = checked(first.ok_or("first operation"));
    assert_eq!(
        checked(owner.admit(first_request, 1_000)),
        Some(first_receipt)
    );
    let mut fresh = request(&owner, "overflow");
    fresh.admitted_at_micros = 1_000;
    fresh.deadline_micros = 1_100;
    assert_eq!(
        owner.admit(fresh, 1_000),
        Err(CellGenerationErrorV2::Capacity)
    );
}

#[test]
fn reconciliation_rejects_an_old_receipt_for_another_pending_request() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let first = request(&owner, "first");
    checked(owner.admit(first.clone(), /*now_micros*/ 10));
    let mut first_proposal = proposal(&first);
    first_proposal.output_delta.clear();
    checked(owner.commit(first_proposal.clone(), /*now_micros*/ 20));
    let mut second = request(&owner, "second");
    second.admitted_at_micros = 21;
    checked(owner.admit(second.clone(), /*now_micros*/ 21));
    let mut readback = Readback {
        proposal: Some(first_proposal),
        reads: 0,
    };
    assert_eq!(
        owner.reconcile_pending(&mut readback, || 25),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(checked(owner.pending_request()), Some(&second));
}

#[test]
fn checkpoint_payload_authenticates_the_config_and_limits_not_just_outer_header() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    checked(owner.drain());
    checked(owner.checkpoint_to(fixture.file("successor")));
    drop(owner);
    let checkpoint = checked(fs::read(fixture.0.join("successor")));
    for case in 0..5 {
        let mut target = config();
        let mut max_records = 128;
        match case {
            0 => target.source_frontier = [90; 32],
            1 => target.task_digest = [91; 32],
            2 => target.initial.generation = 2,
            3 => target.initial.writer_epoch = 2,
            4 => max_records = 127,
            _ => unreachable!(),
        }
        let mut transplanted = checkpoint.clone();
        let header = checked(owner_header(&target, max_records));
        transplanted[8..HEADER_BYTES].copy_from_slice(&header[8..]);
        checked(fs::write(fixture.0.join("successor"), &transplanted));
        assert_eq!(
            CellGenerationJournalV2::open(
                fixture.file("successor"),
                fixture.witness(),
                target,
                max_records,
            )
            .err(),
            Some(CellGenerationErrorV2::Corrupt)
        );
        assert_eq!(checked(fs::read(fixture.0.join("successor"))), transplanted);
    }
    checked(fs::write(fixture.0.join("successor"), checkpoint));
    let owner = checked(CellGenerationJournalV2::open(
        fixture.file("successor"),
        fixture.witness(),
        config(),
        /*max_records*/ 128,
    ));
    assert_eq!(checked(owner.is_drained()), true);
}

#[test]
fn reconciliation_samples_after_readback_and_never_adopts_late_output() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let request = request(&owner, "late-readback");
    checked(owner.admit(request.clone(), /*now_micros*/ 10));
    let before = checked(owner.snapshot()).clone();
    let mut readback = Readback {
        proposal: Some(proposal(&request)),
        reads: 0,
    };
    let mut samples = [20, 101].into_iter();
    let receipt = checked(
        checked(owner.reconcile_pending(&mut readback, || {
            checked(samples.next().ok_or("clock sample"))
        }))
        .ok_or("settled readback"),
    );
    assert_eq!(
        receipt.disposition,
        CellGenerationDispositionV2::DeadlineExceeded
    );
    assert_eq!(checked(owner.snapshot()).prefix, before.prefix);
    assert_eq!(checked(owner.snapshot()).state, before.state);
    assert_eq!(checked(owner.task_cost()).entries(), receipt.cost.entries());
    assert_eq!(checked(owner.pending_request()), None);
}

#[test]
fn reconciliation_clock_rollback_keeps_pending_work_and_cost_unadopted() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let request = request(&owner, "clock-rollback");
    checked(owner.admit(request.clone(), /*now_micros*/ 10));
    let before = owner.state.clone();
    let mut readback = Readback {
        proposal: Some(proposal(&request)),
        reads: 0,
    };
    let mut samples = [20, 19].into_iter();
    assert_eq!(
        owner.reconcile_pending(&mut readback, || checked(
            samples.next().ok_or("clock sample")
        )),
        Err(CellGenerationErrorV2::Deadline)
    );
    assert_eq!(owner.state, before);
}
