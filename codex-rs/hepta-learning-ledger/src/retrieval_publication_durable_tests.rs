use super::*;

use pretty_assertions::assert_eq;

use crate::RetrievalPublicationStateV2;
use crate::retrieval_publication::tests::intent;
use crate::retrieval_publication::tests::legacy;
use crate::retrieval_publication_confirmation_v2;

#[test]
fn mixed_legacy_intent_and_confirmed_recover_without_upgrading_old_rows() {
    let fixture = Fixture::new();
    let planned = intent(1);
    let old = legacy(1, true);
    let mut ledger = fixture.create();
    let receipt = must(ledger.append(
        Digest32::ZERO,
        LedgerEvent::RetrievalAssignment(old.clone()),
    ));
    let intent_receipt = must(ledger.append(
        receipt.chain_digest,
        LedgerEvent::RetrievalAssignmentIntentV2(planned.clone()),
    ));
    let snapshot = must(ledger.snapshot());
    drop(ledger);
    let mut recovered = must(fixture.recover(anchored(&snapshot)));
    let core = LearningLedger::from_snapshot(must(recovered.snapshot())).unwrap();
    assert_eq!(
        core.retrieval_publication(&planned.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::Unknown
    );
    assert_eq!(
        core.retrieval_publication(&old.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::LegacyOwnerAsserted
    );
    let confirmation =
        retrieval_publication_confirmation_v2(&planned, intent_receipt.event_digest).unwrap();
    let confirmed = must(recovered.append(
        intent_receipt.chain_digest,
        LedgerEvent::RetrievalPublicationConfirmedV2(confirmation.clone()),
    ));
    let snapshot = must(recovered.snapshot());
    drop(recovered);
    let mut recovered = must(fixture.recover(anchored(&snapshot)));
    let retry = must(recovered.append(
        intent_receipt.chain_digest,
        LedgerEvent::RetrievalPublicationConfirmedV2(confirmation),
    ));
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.chain_digest, confirmed.chain_digest);
    let core = LearningLedger::from_snapshot(must(recovered.snapshot())).unwrap();
    let projection = core
        .retrieval_publication(&planned.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(
        projection.state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert!(projection.ledger_lineage_active);
    assert_eq!(
        core.retrieval_publication(&old.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::LegacyOwnerAsserted
    );
}

#[test]
fn interrupted_confirmation_tail_recovers_to_unknown_without_inferred_exposure() {
    let fixture = Fixture::new();
    let planned = intent(2);
    let mut ledger = fixture.create();
    let receipt = must(ledger.append(
        Digest32::ZERO,
        LedgerEvent::RetrievalAssignmentIntentV2(planned.clone()),
    ));
    let snapshot = must(ledger.snapshot());
    let mut complete = LearningLedger::from_snapshot(snapshot.clone()).unwrap();
    let confirmation =
        retrieval_publication_confirmation_v2(&planned, receipt.event_digest).unwrap();
    complete
        .append(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation))
        .unwrap();
    let frame = crate::durable_codec::encode_frame(complete.records().last().unwrap()).unwrap();
    drop(ledger);
    let mut file = fixture.file();
    must(file.seek(SeekFrom::End(0)));
    must(file.write_all(&frame[..frame.len() / 2]));
    must(file.sync_all());
    drop(file);
    let recovered = must(fixture.recover(anchored(&snapshot)));
    assert_eq!(must(recovered.snapshot()), snapshot);
    let core = LearningLedger::from_snapshot(must(recovered.snapshot())).unwrap();
    let projection = core
        .retrieval_publication(&planned.record_id)
        .unwrap()
        .unwrap();
    assert_eq!(projection.state, RetrievalPublicationStateV2::Unknown);
    assert!(!projection.ledger_lineage_active);
    assert_eq!(projection.confirmation_event_digest, None);
}
