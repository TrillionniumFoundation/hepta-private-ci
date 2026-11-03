use super::*;
use super::super::lifecycle as codec;
use pretty_assertions::assert_eq;

fn cancellation_for(start: &RunStartAppendReceipt, run_id: &StableId) -> RunCancellationRecordV1 {
    RunCancellationRecordV1 {
        run_id: run_id.clone(),
        run_start_record_digest: start.record_digest,
        revision: 3,
        cancel_reason: "operator_cancel".to_owned(),
    }
}

fn closed_for(cancellation: &RunCancellationRecordV1, phase: RunClosedPhaseV1) -> RunClosedRecordV1 {
    RunClosedRecordV1 {
        run_id: cancellation.run_id.clone(),
        run_start_record_digest: cancellation.run_start_record_digest,
        closed_revision: cancellation.revision + 1,
        phase,
        cancel_reason: Some(cancellation.cancel_reason.clone()),
    }
}

fn prepared_for(start: &RunStartAppendReceipt, run_id: &StableId) -> RunPreparedRecordV1 {
    let payload = b"original sealed seven-owner handoff".to_vec();
    RunPreparedRecordV1 {
        run_id: run_id.clone(),
        run_start_record_digest: start.record_digest,
        payload_digest: Digest32::of_bytes(&payload),
        payload,
    }
}

#[test]
fn cancellation_and_terminal_survive_reopen_without_erasing_prepared_audit() -> Result<(), RunStartStoreError> {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("lifecycle-cold", b"objective");
    let run_id = &original.snapshot.run_id;
    let start = journal.append(Digest32::ZERO, original.clone())?;
    let prepared = prepared_for(&start, run_id);
    journal.append_prepared(journal.head_digest(), prepared.clone())?;
    let original_prepared = journal.prepared(run_id)?;
    let cancellation = cancellation_for(&start, run_id);
    let cancelled = journal.append_cancellation(journal.head_digest(), cancellation.clone())?;
    let before = locked_bytes(&journal.file.0);
    drop(journal);

    let mut cold = fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
        sequence: cancelled.sequence, chain_digest: cancelled.chain_digest,
    }))?;
    assert_eq!(cold.cancellation(run_id)?, Some(&cancellation));
    assert_eq!(cold.closed(run_id)?, None);
    assert_eq!(cold.prepared(run_id)?, original_prepared);
    assert_eq!(cold.append_prepared(cold.head_digest(), prepared.clone()), Err(RunStartStoreError::Conflict));
    assert_eq!(locked_bytes(&cold.file.0), before);
    let closed = closed_for(&cancellation, RunClosedPhaseV1::Succeeded);
    let terminal = cold.append_closed(cold.head_digest(), closed.clone())?;
    let terminal_bytes = locked_bytes(&cold.file.0);
    drop(cold);

    let mut reopened = fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
        sequence: terminal.sequence, chain_digest: terminal.chain_digest,
    }))?;
    assert_eq!(reopened.cancellation(run_id)?, Some(&cancellation));
    assert_eq!(reopened.closed(run_id)?, Some(&closed));
    assert_eq!(reopened.prepared(run_id)?, original_prepared);
    assert_eq!(reopened.records()?, vec![&original]);
    assert_eq!(reopened.authentication_records()?, vec![(&original.authentication, run_id)]);
    assert_eq!(reopened.append_cancellation(Digest32::ZERO, cancellation)?, RunStartAppendReceipt {
        disposition: RunStartAppendDisposition::IdempotentReplay, ..cancelled
    });
    assert_eq!(reopened.append_closed(Digest32::ZERO, closed)?, RunStartAppendReceipt {
        disposition: RunStartAppendDisposition::IdempotentReplay, ..terminal
    });
    assert_eq!(reopened.append(Digest32::ZERO, original)?.record_digest, start.record_digest);
    assert_eq!(reopened.append_prepared(Digest32::ZERO, prepared), Err(RunStartStoreError::Conflict));
    assert_eq!(locked_bytes(&reopened.file.0), terminal_bytes);
    Ok(())
}

#[test]
fn direct_terminal_blocks_new_preparation_and_late_cancellation() -> Result<(), RunStartStoreError> {
    for phase in [RunClosedPhaseV1::Cancelled, RunClosedPhaseV1::Succeeded, RunClosedPhaseV1::Failed] {
        let fixture = Fixture::new();
        let mut journal = fixture.create();
        let original = record("closed-without-preparation", b"objective");
        let run_id = &original.snapshot.run_id;
        let start = journal.append(Digest32::ZERO, original.clone())?;
        let cancellation = cancellation_for(&start, run_id);
        let mut closed = closed_for(&cancellation, phase);
        if phase != RunClosedPhaseV1::Cancelled {
            closed.cancel_reason = None;
        }
        journal.append_closed(journal.head_digest(), closed.clone())?;
        let before = locked_bytes(&journal.file.0);
        drop(journal);
        let mut cold = fixture.recover(RunStartRecovery::Unacknowledged)?;
        assert_eq!(cold.closed(run_id)?, Some(&closed));
        assert_eq!(cold.cancellation(run_id)?, None);
        assert_eq!(cold.prepared(run_id)?, None);
        assert_eq!(cold.append_prepared(cold.head_digest(), prepared_for(&start, run_id)), Err(RunStartStoreError::Conflict));
        assert_eq!(cold.append_cancellation(cold.head_digest(), cancellation), Err(RunStartStoreError::Conflict));
        closed.closed_revision += 1;
        assert_eq!(cold.append_closed(cold.head_digest(), closed), Err(RunStartStoreError::Conflict));
        assert_eq!(locked_bytes(&cold.file.0), before);
    }
    Ok(())
}

#[test]
fn lifecycle_facts_require_exact_original_run_record_digest() -> Result<(), RunStartStoreError> {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("lifecycle-binding", b"objective");
    let start = journal.append(Digest32::ZERO, original.clone())?;
    let conflict = conflict_record("conflict-is-not-run", b"original conflict");
    let conflict_start = journal.append_conflict(journal.head_digest(), conflict.clone())?;
    let valid = cancellation_for(&start, &original.snapshot.run_id);
    let mut missing = valid.clone();
    missing.run_id = id("missing-run");
    let mut wrong_digest = valid;
    wrong_digest.run_start_record_digest = original.snapshot.objective_digest;
    let conflict_only = cancellation_for(&conflict_start, &conflict.run_id);
    let before = locked_bytes(&journal.file.0);
    for invalid in [missing, wrong_digest, conflict_only] {
        let closed = closed_for(&invalid, RunClosedPhaseV1::Cancelled);
        assert_eq!(journal.append_cancellation(journal.head_digest(), invalid), Err(RunStartStoreError::Conflict));
        assert_eq!(journal.append_closed(journal.head_digest(), closed), Err(RunStartStoreError::Conflict));
    }
    assert_eq!(locked_bytes(&journal.file.0), before);
    Ok(())
}

#[test]
fn immutable_slots_reject_changed_decisions_and_inconsistent_terminal_facts() -> Result<(), RunStartStoreError> {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("immutable-control", b"objective");
    let start = journal.append(Digest32::ZERO, original.clone())?;
    let cancellation = cancellation_for(&start, &original.snapshot.run_id);
    journal.append_cancellation(journal.head_digest(), cancellation.clone())?;
    let before = locked_bytes(&journal.file.0);
    let mut newer = cancellation.clone();
    newer.revision += 1;
    let mut different_reason = cancellation.clone();
    different_reason.cancel_reason = "other request".to_owned();
    for changed in [newer, different_reason] {
        assert_eq!(journal.append_cancellation(journal.head_digest(), changed), Err(RunStartStoreError::Conflict));
    }
    let valid = closed_for(&cancellation, RunClosedPhaseV1::Cancelled);
    let mut older = valid.clone();
    older.closed_revision = cancellation.revision - 1;
    let mut no_reason = valid.clone();
    no_reason.cancel_reason = None;
    let mut changed_reason = valid.clone();
    changed_reason.cancel_reason = Some("other request".to_owned());
    for changed in [older, no_reason, changed_reason] {
        assert_eq!(journal.append_closed(journal.head_digest(), changed), Err(RunStartStoreError::Conflict));
    }
    assert_eq!(locked_bytes(&journal.file.0), before);
    let mut same_revision = valid;
    same_revision.closed_revision = cancellation.revision;
    journal.append_closed(journal.head_digest(), same_revision.clone())?;
    let terminal_bytes = locked_bytes(&journal.file.0);
    same_revision.phase = RunClosedPhaseV1::Failed;
    assert_eq!(journal.append_closed(journal.head_digest(), same_revision), Err(RunStartStoreError::Conflict));
    assert_eq!(locked_bytes(&journal.file.0), terminal_bytes);
    Ok(())
}

#[test]
fn lifecycle_uses_original_shared_frame_capacity_and_exact_replay() -> Result<(), RunStartStoreError> {
    let fixture = Fixture::new();
    let mut journal = DurableRunStartJournal::create(fixture.file(), binding(), /*max_records*/ 2)?;
    let original = record("capacity-control", b"objective");
    let start = journal.append(Digest32::ZERO, original.clone())?;
    let cancellation = cancellation_for(&start, &original.snapshot.run_id);
    let accepted = journal.append_cancellation(journal.head_digest(), cancellation.clone())?;
    let before = locked_bytes(&journal.file.0);
    assert_eq!(journal.append_closed(journal.head_digest(), closed_for(&cancellation, RunClosedPhaseV1::Failed)), Err(RunStartStoreError::Capacity));
    assert_eq!(journal.append(journal.head_digest(), record("extra-run", b"other")), Err(RunStartStoreError::Capacity));
    assert_eq!(journal.append_cancellation(Digest32::ZERO, cancellation)?, RunStartAppendReceipt {
        disposition: RunStartAppendDisposition::IdempotentReplay, ..accepted
    });
    assert_eq!(locked_bytes(&journal.file.0), before);
    Ok(())
}

#[test]
fn lifecycle_reasons_and_decoders_are_bounded_by_original_control_contract() -> Result<(), RunStartStoreError> {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("bounded-control", b"objective");
    let start = journal.append(Digest32::ZERO, original.clone())?;
    let valid = cancellation_for(&start, &original.snapshot.run_id);
    let before = locked_bytes(&journal.file.0);
    for reason in [String::new(), " \n".to_owned(), "cancel\0reason".to_owned(), "x".repeat(513), "é".repeat(257)] {
        let mut invalid = valid.clone();
        invalid.cancel_reason = reason;
        assert!(matches!(journal.append_cancellation(journal.head_digest(), invalid.clone()), Err(RunStartStoreError::InvalidSnapshot(_))));
        assert!(matches!(journal.append_closed(journal.head_digest(), closed_for(&invalid, RunClosedPhaseV1::Cancelled)), Err(RunStartStoreError::InvalidSnapshot(_))));
        assert_eq!(codec::decode_cancellation(&codec::encode_cancellation(&invalid)), Err(RunStartStoreError::Corrupt));
    }
    let mut zero_revision = valid.clone();
    zero_revision.revision = 0;
    assert!(matches!(journal.append_cancellation(journal.head_digest(), zero_revision), Err(RunStartStoreError::InvalidSnapshot(_))));
    let mut zero_digest = valid.clone();
    zero_digest.run_start_record_digest = Digest32::ZERO;
    assert!(matches!(journal.append_cancellation(journal.head_digest(), zero_digest), Err(RunStartStoreError::InvalidSnapshot(_))));
    assert_eq!(locked_bytes(&journal.file.0), before);
    let mut bounded = valid;
    bounded.cancel_reason = "é".repeat(256);
    let encoded = codec::encode_cancellation(&bounded);
    assert_eq!(codec::decode_cancellation(&encoded)?, bounded);
    let mut trailing = encoded.clone();
    trailing.push(0);
    let mut oversized = encoded.clone();
    let reason_offset = codec::CANCELLATION_DOMAIN.len() + 4 + bounded.run_id.as_str().len() + 32 + 8;
    oversized[reason_offset..reason_offset + 4].copy_from_slice(&u32::MAX.to_be_bytes());
    for malformed in [&encoded[..encoded.len() - 1], trailing.as_slice(), oversized.as_slice()] {
        assert_eq!(codec::decode_cancellation(malformed), Err(RunStartStoreError::Corrupt));
    }
    journal.append_cancellation(journal.head_digest(), bounded.clone())?;
    let closed = closed_for(&bounded, RunClosedPhaseV1::Failed);
    let encoded = codec::encode_closed(&closed);
    assert_eq!(codec::decode_closed(&encoded)?, closed);
    let phase_offset = codec::CLOSED_DOMAIN.len() + 4 + closed.run_id.as_str().len() + 32 + 8;
    for offset in [phase_offset, phase_offset + 1] {
        let mut invalid = encoded.clone();
        invalid[offset] = u8::MAX;
        assert_eq!(codec::decode_closed(&invalid), Err(RunStartStoreError::Corrupt));
    }
    Ok(())
}

fn append_unvalidated_frame(journal: &mut DurableRunStartJournal, record: StoredRunStartRecord) -> Result<(), RunStartStoreError> {
    let sequence = journal.records.len() as u64 + 1;
    let predecessor = journal.head_digest();
    let record_digest = Digest32::of_bytes(&encode_outcome_record(&record));
    let stored = StoredRunStart {
        sequence,
        predecessor_chain_digest: predecessor,
        record_digest,
        chain_digest: digest_chain(predecessor, sequence, record_digest),
        record,
    };
    journal.file.0.seek(SeekFrom::End(0))?;
    journal.file.0.write_all(&encode_frame(&stored)?)?;
    journal.file.0.sync_all()?;
    Ok(())
}

#[test]
fn cold_replay_rejects_well_hashed_frames_that_cross_a_lifecycle_blocker() -> Result<(), RunStartStoreError> {
    for case in 0..4 {
        let fixture = Fixture::new();
        let mut journal = fixture.create();
        let original = record("illegal-lifecycle-frame", b"objective");
        let run_id = &original.snapshot.run_id;
        let start = journal.append(Digest32::ZERO, original.clone())?;
        let cancellation = cancellation_for(&start, run_id);
        let closed = closed_for(&cancellation, RunClosedPhaseV1::Cancelled);
        journal.append_closed(journal.head_digest(), closed.clone())?;
        let invalid = match case {
            0 => StoredRunStartRecord::Prepared(Box::new(prepared_for(&start, run_id))),
            1 => StoredRunStartRecord::Cancellation(Box::new(cancellation)),
            2 => StoredRunStartRecord::Closed(Box::new(RunClosedRecordV1 {
                run_start_record_digest: digest("not the original start"), ..closed
            })),
            _ => StoredRunStartRecord::Closed(Box::new(closed)),
        };
        append_unvalidated_frame(&mut journal, invalid)?;
        let bytes = locked_bytes(&journal.file.0);
        drop(journal);
        assert!(matches!(fixture.recover(RunStartRecovery::Unacknowledged), Err(RunStartStoreError::Corrupt)));
        assert_eq!(fs::read(fixture.path())?, bytes);
    }
    Ok(())
}
