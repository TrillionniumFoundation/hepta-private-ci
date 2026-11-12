//! Actual task and signature owners produce the facts before all owner Arcs
//! close. This tests data/signature verification, not a Root historical grant.

use std::fs::File;

use crate::cell_q24_task_ledger::history::OriginalTaskLedgerHistoryContextV1;
use crate::cell_q24_task_ledger::history::OriginalTaskLedgerHistoryDataV1;

use super::*;

struct Closed {
    root: tempfile::TempDir,
    identity: crate::AgentdIdentity,
    definition: codex_hepta_neuron::CellDefinitionV1,
    source: crate::CircuitTaskSourceInputV1,
    config: crate::OriginalCellQ24TaskLedgerConfigV1,
    trust: ActivatedLearningTrustV1,
    publication: CircuitTaskSourcePublicationV1,
    cell: codex_hepta_neuron::CellDecisionReceiptV1,
    envelopes: [Vec<u8>; 2],
    expected: [LedgerRecord; 2],
}

impl Closed {
    async fn original(run: &str) -> anyhow::Result<Self> {
        let mut f = Fixture::new(run, /*lifetime*/ 600, /*automatic*/ true).await?;
        let outcome = f.outcome();
        let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
        let Status::Complete { decision, outcome } = f
            .producer
            .submit_original_terminal_outcome(outcome, &signed)?
        else {
            anyhow::bail!("original task did not produce both witnessed facts");
        };
        let envelopes = test_faults::retained_signature_envelopes(&f.producer)?;
        let cell = f.session.cell.committed(&f.publication)?;
        let identity = f.session.runtime.identity.clone();
        let definition = f.session.retirement.definition().clone();
        let source = f.session.retirement.source().clone();
        f.session.stop().await?;
        // Keep only data and the temporary directory. In particular no State,
        // Source, Cell, producer, LedgerWriter or signing key survives here.
        let Fixture {
            root,
            session,
            ledger,
            producer,
            config,
            publication,
            trust,
            ..
        } = f;
        drop(session);
        drop(producer);
        drop(ledger);
        Ok(Self {
            root,
            identity,
            definition,
            source,
            config,
            trust,
            publication,
            cell,
            envelopes,
            expected: [decision, outcome],
        })
    }

    fn read(&self) -> anyhow::Result<LedgerReadOnlyObservationV1> {
        let reader = ReadOnlyLedgerViewV1::observe_closed(
            File::open(self.root.path().join("ledger"))?,
            File::open(self.root.path().join("ledger.witness"))?,
            cell::d("original-task-ledger-fixture"),
            /*max_records*/ 64,
        )?;
        Ok(reader.observe()?)
    }

    fn context(&self) -> OriginalTaskLedgerHistoryContextV1<'_> {
        OriginalTaskLedgerHistoryContextV1 {
            identity: &self.identity,
            definition: &self.definition,
            source: &self.source,
            config: &self.config,
            ledger_binding: cell::d("original-task-ledger-fixture"),
            verifier: self.trust.verifier(),
        }
    }
}

#[tokio::test]
async fn task_ledger_history_verifies_actual_terminal_after_original_owners_close()
-> anyhow::Result<()> {
    let f = Closed::original("history-original-terminal").await?;
    let before = fs::read(f.root.path().join("ledger"))?;
    let observed = f.read()?;
    let context = f.context();
    let verified = context.verify_original_terminal(
        &observed,
        &f.publication,
        &f.cell,
        &f.envelopes[0],
        &f.envelopes[1],
        fixture::now(),
    )?;
    assert_eq!(
        verified,
        OriginalTaskLedgerHistoryDataV1 {
            signature_binding: context.signature_binding()?,
            decision: f.expected[0].clone(),
            outcome: f.expected[1].clone(),
        }
    );
    assert_eq!(fs::read(f.root.path().join("ledger"))?, before);
    Ok(())
}

#[tokio::test]
async fn task_ledger_history_rejects_wrong_context_signatures_and_incomplete_cut()
-> anyhow::Result<()> {
    let mut f = Closed::original("history-physical-binding").await?;
    let mut observed = f.read()?;
    let original = f.config.clone();
    f.config.generator.verifying_key[0] ^= 1;
    assert!(
        f.context()
            .verify_original_terminal(
                &observed,
                &f.publication,
                &f.cell,
                &f.envelopes[0],
                &f.envelopes[1],
                fixture::now(),
            )
            .is_err()
    );
    f.config = original;
    let mut changed = f.envelopes[1].clone();
    let last = changed
        .last_mut()
        .ok_or_else(|| anyhow::anyhow!("original signature envelope is empty"))?;
    *last ^= 1;
    for (decision, outcome) in [
        (&f.envelopes[0], &changed),
        (&f.envelopes[1], &f.envelopes[0]),
    ] {
        assert!(
            f.context()
                .verify_original_terminal(
                    &observed,
                    &f.publication,
                    &f.cell,
                    decision,
                    outcome,
                    fixture::now(),
                )
                .is_err()
        );
    }
    observed.cut.frontier.anchor.sequence = 1;
    assert!(
        f.context()
            .verify_original_terminal(
                &observed,
                &f.publication,
                &f.cell,
                &f.envelopes[0],
                &f.envelopes[1],
                fixture::now(),
            )
            .is_err()
    );
    Ok(())
}
