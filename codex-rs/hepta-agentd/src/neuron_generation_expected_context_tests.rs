//! Real journal, witness, CURRENT and signed publication mechanisms. Proposals
//! are synthetic inputs; no test supplies or claims a successful Cell verifier.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::*;
use codex_hepta_types::AuthorityPosture;
use pretty_assertions::assert_eq;

use super::Fixture;
use super::RECORDS;
use super::config;
use super::cost;
use super::request;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;

fn proposal(
    expected: &CellGenerationExpectedContextV1,
) -> anyhow::Result<CellGenerationProposalV2> {
    let config = expected.configuration();
    Ok(CellGenerationProposalV2 {
        request_digest: expected.request().digest()?,
        bundle_digest: config.manifest.bundle_digest,
        runtime_digest: config.manifest.runtime_digest,
        device_digest: config.manifest.device_digest,
        successor_state: vec![2],
        output_delta: vec![42],
        disposition: CellGenerationDispositionV2::Advanced,
        cost: cost(config, "context-step", CellCostStageV2::Inference)?,
    })
}

#[test]
fn expected_context_reads_only_guarded_durable_admission_and_rejects_substitution()
-> anyhow::Result<()> {
    let fixture = Fixture::new(config()?)?;
    let mut journal = fixture.old_journal()?;
    assert_eq!(
        journal.pending_expected_context(),
        Err(CellGenerationErrorV2::Conflict)
    );
    let original = request(&journal, &fixture.old_config, "context-step")?;
    journal.admit(original.clone(), /*now_micros*/ 10)?;
    let expected = journal.pending_expected_context()?;
    let binding = CellGenerationOwnerBindingV1::new(&fixture.old_config, RECORDS)?;
    assert_eq!(
        (
            expected.configuration(),
            expected.request(),
            expected.owner_binding(),
            expected.checkpoint()
        ),
        (
            &fixture.old_config,
            &original,
            &binding,
            journal.continuity_checkpoint()?
        )
    );
    let bytes = (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?);
    let substitutions: [fn(&mut CellGenerationRequestV2); 9] = [
        |r| r.input.push(99),
        |r| r.task_digest[0] ^= 1,
        |r| r.source_frontier[0] ^= 1,
        |r| r.deadline_micros += 1,
        |r| r.predecessor.generation += 1,
        |r| r.predecessor.writer_epoch += 1,
        |r| r.predecessor.scope.cell_id.push_str("-other"),
        |r| r.predecessor.state.push(99),
        |r| r.operation_id.push_str("-other"),
    ];
    for substitute in substitutions {
        let mut substituted = original.clone();
        substitute(&mut substituted);
        let mut supplied = proposal(&expected)?;
        supplied.request_digest = substituted.digest()?;
        assert_eq!(
            journal.commit_with_expected_context(&expected, supplied, /*now_micros*/ 11),
            Err(CellGenerationErrorV2::Conflict)
        );
    }
    assert_eq!(journal.pending_request()?, Some(&original));
    assert_eq!(
        (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?),
        bytes
    );

    let target = fixture.target_create()?;
    let mut unguarded = CellGenerationJournalV2::open(
        target.file,
        target.witness,
        target.config,
        target.max_records,
    )?;
    let fresh = request(&unguarded, &fixture.target_config, "unguarded")?;
    unguarded.admit(fresh, /*now_micros*/ 10)?;
    assert_eq!(
        unguarded.pending_expected_context(),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    Ok(())
}

#[test]
fn expected_context_requires_exact_checkpoint_and_preserves_replay_and_conflict()
-> anyhow::Result<()> {
    let fixture = Fixture::new(config()?)?;
    let mut journal = fixture.old_journal()?;
    let original = request(&journal, &fixture.old_config, "context-step")?;
    journal.admit(original.clone(), /*now_micros*/ 10)?;
    let stale = journal.pending_expected_context()?;
    let supplied = proposal(&stale)?;
    journal.observe_dispatch_time(original.digest()?, /*observed_at_micros*/ 11)?;
    let before = (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?);
    assert_eq!(
        journal.require_expected_context(&stale),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        journal.commit_with_expected_context(&stale, supplied.clone(), /*now_micros*/ 12),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?),
        before
    );
    let current = journal.pending_expected_context()?;
    assert_ne!(current.checkpoint(), stale.checkpoint());
    let receipt =
        journal.commit_with_expected_context(&current, supplied.clone(), /*now_micros*/ 12)?;
    assert_eq!(receipt.authority(), AuthorityPosture::DENY_ALL);
    let committed = (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?);
    assert_eq!(
        journal.require_expected_context(&current),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        journal.commit_with_expected_context(
            &current,
            supplied.clone(),
            /*now_micros*/ 101
        )?,
        receipt
    );
    let mut conflicting = supplied.clone();
    conflicting.output_delta.push(99);
    assert_eq!(
        journal.commit_with_expected_context(&current, conflicting, /*now_micros*/ 13),
        Err(CellGenerationErrorV2::Conflict)
    );
    assert_eq!(
        (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?),
        committed
    );
    drop(journal);
    let mut reopened = fixture.old_journal()?;
    assert_eq!(reopened.lookup(&original)?, Some(receipt.clone()));
    assert_eq!(
        reopened.commit_with_expected_context(&current, supplied, /*now_micros*/ 102)?,
        receipt
    );
    assert_eq!(
        (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?),
        committed
    );
    Ok(())
}

#[test]
fn expected_context_cold_pending_replay_and_cancellation_keep_original_identity()
-> anyhow::Result<()> {
    let fixture = Fixture::new(config()?)?;
    let mut journal = fixture.old_journal()?;
    let original = request(&journal, &fixture.old_config, "context-step")?;
    journal.admit(original.clone(), /*now_micros*/ 10)?;
    let expected = journal.pending_expected_context()?;
    drop(journal);
    let mut journal = CellGenerationJournalV2::open_guarded(
        fixture.file("old-journal")?,
        fixture.witness("old-witness", &fixture.old_config)?,
        fixture.old_config.clone(),
        RECORDS,
        fixture.reopen_current()?,
    )?;
    assert_eq!(journal.pending_expected_context()?, expected);
    journal.require_expected_context(&expected)?;
    journal.cancel(original.digest()?)?;
    let supplied = proposal(&expected)?;
    assert_eq!(
        journal.commit_with_expected_context(&expected, supplied.clone(), /*now_micros*/ 11),
        Err(CellGenerationErrorV2::Conflict)
    );
    let cancelled = journal.pending_expected_context()?;
    let receipt =
        journal.commit_with_expected_context(&cancelled, supplied, /*now_micros*/ 11)?;
    assert_eq!(receipt.disposition, CellGenerationDispositionV2::Cancelled);
    let mut after = original.predecessor;
    after.revision += 1;
    assert_eq!(journal.snapshot()?, &after);
    assert_eq!(journal.pending_output()?, None);
    Ok(())
}

#[test]
fn expected_context_rejects_foreign_task_and_current_generation_replacement() -> anyhow::Result<()>
{
    let fixture = Fixture::new(config()?)?;
    let mut old = fixture.old_journal()?;
    let original = request(&old, &fixture.old_config, "context-step")?;
    old.admit(original, /*now_micros*/ 10)?;
    let expected = old.pending_expected_context()?;
    let mut supplied = proposal(&expected)?;
    supplied.disposition = CellGenerationDispositionV2::Stopped;
    supplied.output_delta.clear();
    let mut foreign_config = config()?;
    foreign_config.task_digest[0] ^= 1;
    let foreign_fixture = Fixture::new(foreign_config)?;
    let mut foreign = foreign_fixture.old_journal()?;
    let foreign_request = request(&foreign, &foreign_fixture.old_config, "context-step")?;
    foreign.admit(foreign_request, /*now_micros*/ 10)?;
    let foreign_bytes = foreign_fixture.bytes("old-journal")?;
    assert_eq!(
        foreign.commit_with_expected_context(&expected, supplied.clone(), /*now_micros*/ 11),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(foreign_fixture.bytes("old-journal")?, foreign_bytes);
    old.commit_with_expected_context(&expected, supplied.clone(), /*now_micros*/ 11)?;
    old.drain()?;
    let mut selected = fixture.selection()?;
    let binding = CellGenerationOwnerBindingV1::new(&fixture.target_config, RECORDS)?;
    let prepared =
        fixture
            .current
            .prepare(&old, "replace-context-task".into(), binding, &selected)?;
    let target = fixture.target_create()?;
    let new = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        fixture.current.clone(),
    )?;
    let signed = fixture.sign(prepared.final_use_binding())?;
    {
        let mut artifacts = fixture
            .artifacts
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact lock"))?;
        fixture.current.publish(
            &prepared,
            &old,
            &new,
            &mut selected,
            NeuronGenerationUpdatePublicationV1 {
                artifacts: &mut artifacts,
                authority: &fixture.authority,
                signed: &signed,
                clock: fixture.clock.as_ref(),
            },
        )?;
    }
    let after = (
        fixture.bytes("old-journal")?,
        fixture.bytes("old-witness")?,
        fixture.bytes("current.json")?,
        fixture.bytes("final-use/authority.claims")?,
    );
    assert_eq!(
        old.require_expected_context(&expected),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(
        old.commit_with_expected_context(&expected, supplied, /*now_micros*/ 12),
        Err(CellGenerationErrorV2::InvalidBinding)
    );
    assert_eq!(new.snapshot()?, &fixture.target_config.initial);
    assert_eq!(
        (
            fixture.bytes("old-journal")?,
            fixture.bytes("old-witness")?,
            fixture.bytes("current.json")?,
            fixture.bytes("final-use/authority.claims")?
        ),
        after
    );
    Ok(())
}

struct LostWitnessAck {
    inner: FileAnchorWitnessStore,
    lose_next: Arc<AtomicBool>,
}

impl AnchorWitnessStore for LostWitnessAck {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        if self.lose_next.swap(/*val*/ false, Ordering::SeqCst) {
            Err(WitnessStoreError::Unavailable)
        } else {
            Ok(())
        }
    }
}

#[test]
fn expected_context_lost_witness_ack_recovers_exact_commit_without_another_append()
-> anyhow::Result<()> {
    let fixture = Fixture::new(config()?)?;
    let lose_next = Arc::new(AtomicBool::new(/*v*/ false));
    let mut journal = CellGenerationJournalV2::open_guarded(
        fixture.file("old-journal")?,
        LostWitnessAck {
            inner: fixture.witness("old-witness", &fixture.old_config)?,
            lose_next: lose_next.clone(),
        },
        fixture.old_config.clone(),
        RECORDS,
        fixture.current.clone(),
    )?;
    let original = CellGenerationRequestV2 {
        operation_id: "context-unknown".into(),
        task_digest: fixture.old_config.task_digest,
        source_frontier: fixture.old_config.source_frontier,
        predecessor: journal.snapshot()?.clone(),
        input: vec![7],
        admitted_at_micros: 10,
        deadline_micros: 100,
    };
    journal.admit(original.clone(), /*now_micros*/ 10)?;
    let expected = journal.pending_expected_context()?;
    let supplied = proposal(&expected)?;
    lose_next.store(/*val*/ true, Ordering::SeqCst);
    assert_eq!(
        journal.commit_with_expected_context(&expected, supplied.clone(), /*now_micros*/ 11),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    assert_eq!(
        journal.pending_expected_context(),
        Err(CellGenerationErrorV2::CommitUncertain)
    );
    let durable = (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?);
    drop(journal);
    let mut reopened = fixture.old_journal()?;
    let receipt = reopened
        .lookup(&original)?
        .ok_or_else(|| anyhow::anyhow!("missing original commit"))?;
    assert_eq!(
        reopened.commit_with_expected_context(&expected, supplied, /*now_micros*/ 12)?,
        receipt
    );
    assert_eq!(reopened.admit(original, /*now_micros*/ 12)?, Some(receipt));
    assert_eq!(
        (fixture.bytes("old-journal")?, fixture.bytes("old-witness")?),
        durable
    );
    assert_eq!(fixture.authority.capacity()?.used_nonces, 0);
    Ok(())
}
