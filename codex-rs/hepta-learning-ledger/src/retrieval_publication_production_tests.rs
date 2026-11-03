use super::*;

use pretty_assertions::assert_eq;

use crate::RetrievalPublicationStateV2;
use crate::retrieval_publication::tests::intent;
use crate::retrieval_publication::tests::legacy;
use crate::retrieval_publication_confirmation_v2;

#[test]
fn product_publication_uses_one_writer_and_witnesses_both_exact_stages() {
    let fixture = Fixture::new();
    let planned = intent(1);
    let old = legacy(1, true);
    let mut writer = fixture.writer();
    writer
        .append_retrieval_assignment_current(old.clone())
        .unwrap();
    let receipt = writer
        .append_retrieval_assignment_intent_current(planned.clone())
        .unwrap();
    assert_eq!(
        writer.witness_frontier().unwrap().anchor.chain_digest,
        receipt.chain_digest
    );
    assert_eq!(
        writer
            .retrieval_publication(&planned.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::Unknown
    );
    let confirmation =
        retrieval_publication_confirmation_v2(&planned, receipt.event_digest).unwrap();
    let confirmed = writer
        .append_retrieval_publication_confirmed_current(confirmation.clone())
        .unwrap();
    assert_eq!(
        writer.witness_frontier().unwrap().anchor.chain_digest,
        confirmed.chain_digest
    );
    let frontier = writer.witness_frontier().unwrap();
    assert_eq!(
        writer
            .append_retrieval_assignment_intent_current(planned.clone())
            .unwrap()
            .disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(
        writer
            .append_retrieval_publication_confirmed_current(confirmation.clone())
            .unwrap()
            .disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(writer.witness_frontier().unwrap(), frontier);
    let records = writer.snapshot().unwrap();
    drop(writer);
    let ledger = DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        64,
        LedgerRecovery::Acknowledged(frontier.anchor),
    )
    .unwrap();
    let witness = LedgerWitnessStore::recover(fixture.file("witness"), binding()).unwrap();
    let directory = fixture.directory();
    let mut recovered =
        LedgerWriter::from_durable(ledger, witness, activated_trust(), &directory, &directory)
            .unwrap();
    assert_eq!(recovered.snapshot().unwrap(), records);
    let projection = recovered
        .retrieval_publication(&planned.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(
        projection.state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert!(projection.ledger_lineage_active);
    assert_eq!(
        recovered
            .retrieval_publication(&old.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::LegacyOwnerAsserted
    );
    recovered
        .append_retrieval_publication_confirmed_current(confirmation)
        .unwrap();
    assert_eq!(recovered.witness_frontier().unwrap(), frontier);
}

#[test]
fn lost_witness_ack_requires_exact_stage_retry_and_never_infers_missing_confirmation() {
    let fixture = Fixture::new();
    let planned = intent(2);
    let mut writer = fixture.writer();
    // Simulate the existing durable ledger commit -> independent witness failure
    // boundary without a mock journal or changing product writer semantics.
    let receipt = writer
        .backend
        .append(
            Digest32::ZERO,
            LedgerEvent::RetrievalAssignmentIntentV2(planned.clone()),
        )
        .unwrap();
    assert_eq!(writer.witness_frontier().unwrap().anchor.sequence, 0);
    let projection = writer
        .retrieval_publication(&planned.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(projection.state, RetrievalPublicationStateV2::Unknown);
    assert!(!projection.ledger_lineage_active);
    assert!(matches!(
        writer.append_retrieval_assignment_intent_current(intent(3)),
        Err(ProductionLedgerError::WitnessLag)
    ));
    let retry = writer
        .append_retrieval_assignment_intent_current(planned.clone())
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(
        writer.witness_frontier().unwrap().anchor.chain_digest,
        receipt.chain_digest
    );
    let confirmation =
        retrieval_publication_confirmation_v2(&planned, receipt.event_digest).unwrap();
    let confirmed = writer
        .backend
        .append(
            receipt.chain_digest,
            LedgerEvent::RetrievalPublicationConfirmedV2(confirmation.clone()),
        )
        .unwrap();
    let projection = writer
        .retrieval_publication(&planned.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(
        projection.state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert!(!projection.ledger_lineage_active);
    assert!(matches!(
        writer.append_retrieval_assignment_intent_current(intent(3)),
        Err(ProductionLedgerError::WitnessLag)
    ));
    let retry = writer
        .append_retrieval_publication_confirmed_current(confirmation)
        .unwrap();
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(
        writer.witness_frontier().unwrap().anchor.chain_digest,
        confirmed.chain_digest
    );
    assert!(
        writer
            .retrieval_publication(&planned.record_id)
            .unwrap()
            .unwrap()
            .ledger_lineage_active
    );
}
