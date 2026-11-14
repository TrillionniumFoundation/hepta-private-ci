//! Actual task and signature owners produce the facts before all owner Arcs
//! close. This tests data/signature verification, not a Root historical grant.

use std::fs::File;

use pretty_assertions::assert_eq;

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

#[tokio::test]
async fn historical_wire_budget_counts_actual_signed_ledger_and_source_components()
-> anyhow::Result<()> {
    use crate::root_historical_task_read_protocol::HistoricalTaskReadResponseV1;
    use crate::root_historical_task_read_protocol::PURPOSE;
    use crate::root_historical_task_read_protocol::WIRE_BOUND;
    use base64::Engine;
    use base64::engine::general_purpose::STANDARD;

    let original = Closed::original("history-image-budget").await?;
    let observed = original.read()?;
    let bytes = encode_readonly_ledger_data_v1(observed.cut.binding, &original.expected)?;
    assert_eq!(bytes, fs::read(original.root.path().join("ledger"))?);
    assert_eq!(
        decode_readonly_ledger_data_v1(&bytes, observed.cut, /*max_records*/ 2)?,
        observed.snapshot
    );
    // Both components come from actual execution/file fixtures. They are
    // independent fixtures: this measures serialization budget only, never a
    // joined Root authorization, retained execution or full learning positive.
    let (publication, mut ledger, _, _) = crate::circuit_task::publication_data_fixture().await?;
    ledger.cut.ledger_binding = observed.cut.binding.to_string();
    ledger.cut.ledger_chain = observed.cut.frontier.anchor.chain_digest.to_string();
    ledger.cut.ledger_length = observed.cut.ledger_length;
    ledger.cut.ledger_image = observed.cut.ledger_digest.to_string();
    ledger.cut.witness_length = observed.cut.witness_length;
    ledger.cut.witness_image = observed.cut.witness_digest.to_string();
    ledger.cut.decision_chain = original.expected[0].chain_digest.to_string();
    ledger.cut.outcome_chain = original.expected[1].chain_digest.to_string();
    ledger.ledger_image_bytes = STANDARD.encode(&bytes);
    let ledger_size = serde_json::to_vec(&ledger)?.len();
    let source_size = serde_json::to_vec(&publication)?.len();
    let response = HistoricalTaskReadResponseV1 {
        schema: 1,
        purpose: PURPOSE.into(),
        request_id: 1,
        profile: Digest32::of_bytes(b"data-only-budget-profile").to_string(),
        data_cut: Digest32::of_bytes(b"data-only-budget-cut").to_string(),
        ledger,
        publication,
    };
    let reply_size = serde_json::to_vec(&response)?.len();
    eprintln!(
        "HISTORICAL_WIRE_COMPONENT_BUDGET ledger_image={} ledger_dto={ledger_size} source_dto={source_size} reply={reply_size} limit={WIRE_BOUND}",
        bytes.len()
    );
    assert!(ledger_size <= 12 * 1024);
    assert!(reply_size <= WIRE_BOUND);
    Ok(())
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
