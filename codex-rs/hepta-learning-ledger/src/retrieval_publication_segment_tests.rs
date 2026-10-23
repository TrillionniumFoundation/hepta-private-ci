use super::*;

use pretty_assertions::assert_eq;

use crate::RetrievalPublicationStateV2;
use crate::retrieval_publication::tests::intent;
use crate::retrieval_publication::tests::legacy;
use crate::retrieval_publication_confirmation_v2;

#[test]
fn publication_linkage_and_unknown_survive_rotation_and_anchored_replay() {
    let fixture = Fixture::new();
    let first = intent(1);
    let unknown = intent(2);
    let old = legacy(1, true);
    let mut ledger = fixture.create();
    append(&mut ledger, LedgerEvent::RetrievalAssignment(old.clone()));
    let receipt = append(
        &mut ledger,
        LedgerEvent::RetrievalAssignmentIntentV2(first.clone()),
    );
    let anchor = must(ledger.anchor());
    must(ledger.rotate(fixture.new_file("1"), anchor));
    let confirmation = retrieval_publication_confirmation_v2(&first, receipt.event_digest).unwrap();
    let confirmed = append(
        &mut ledger,
        LedgerEvent::RetrievalPublicationConfirmedV2(confirmation.clone()),
    );
    append(
        &mut ledger,
        LedgerEvent::RetrievalAssignmentIntentV2(unknown.clone()),
    );
    let checkpoint = must(ledger.checkpoint());
    let snapshot = must(ledger.snapshot());
    drop(ledger);
    let mut recovered = must(fixture.recover(2, checkpoint));
    assert_eq!(must(recovered.snapshot()), snapshot);
    let retry = must(recovered.append(
        anchor.chain_digest,
        LedgerEvent::RetrievalPublicationConfirmedV2(confirmation),
    ));
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.event_digest, confirmed.event_digest);
    let core = LearningLedger::from_snapshot(must(recovered.snapshot())).unwrap();
    assert_eq!(
        core.retrieval_publication(&first.record_id)
            .unwrap()
            .unwrap()
            .state,
        RetrievalPublicationStateV2::HostTransportWriteCompleted
    );
    assert_eq!(
        core.retrieval_publication(&unknown.record_id)
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
}
