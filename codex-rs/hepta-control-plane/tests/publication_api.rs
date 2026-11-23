use codex_hepta_control_plane::ControlRuntimePublicationErrorV1;
use codex_hepta_control_plane::ControlRuntimePublicationHeadV1;
use codex_hepta_control_plane::ControlRuntimePublicationKindV1;
use codex_hepta_control_plane::ControlRuntimePublicationRequestV1;
use codex_hepta_control_plane::ControlRuntimePublicationV1;
use codex_hepta_control_plane::PlannerJournalHeadV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn positional_publication(
    request: ControlRuntimePublicationRequestV1,
) -> Result<ControlRuntimePublicationV1, ControlRuntimePublicationErrorV1> {
    ControlRuntimePublicationV1::new(
        request.owner_id,
        request.expected,
        request.policy_epoch,
        request.kind,
        request.subject_digest,
        request.payload,
        request.journal_head,
        request.occurred_at_micros,
    )
}

#[test]
fn named_and_positional_v1_constructors_bind_the_same_record()
-> Result<(), Box<dyn std::error::Error>> {
    let payload = b"publication".to_vec();
    let mut request = ControlRuntimePublicationRequestV1 {
        owner_id: StableId::new("control.runtime")?,
        expected: ControlRuntimePublicationHeadV1 {
            sequence: 4,
            publication_digest: Digest32::of_bytes(b"predecessor"),
        },
        policy_epoch: 2,
        kind: ControlRuntimePublicationKindV1::DecisionCommitted,
        subject_digest: Digest32::of_bytes(&payload),
        payload,
        journal_head: PlannerJournalHeadV1 {
            sequence: 3,
            entry_digest: Digest32::of_bytes(b"journal"),
        },
        occurred_at_micros: 11,
    };
    let record = positional_publication(request.clone())?;
    assert_eq!(
        record,
        ControlRuntimePublicationV1::from_request(request.clone())?
    );
    assert_eq!(record.sequence, 5);
    assert_eq!(
        record.predecessor_publication_digest,
        request.expected.publication_digest
    );
    record.verify_against(request.expected)?;

    request.subject_digest = Digest32::of_bytes(b"different payload");
    assert_eq!(
        positional_publication(request.clone()),
        Err(ControlRuntimePublicationErrorV1::PayloadDigestMismatch)
    );
    assert_eq!(
        ControlRuntimePublicationV1::from_request(request),
        Err(ControlRuntimePublicationErrorV1::PayloadDigestMismatch)
    );
    Ok(())
}
