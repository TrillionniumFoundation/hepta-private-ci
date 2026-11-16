use super::ProviderEffectAck;
use super::ProviderEffectAckSource;
use super::ProviderEffectAckStatus;
use super::ProviderEffectAppendDisposition;
use super::ProviderEffectBindingError;
use super::ProviderEffectIntent;
use super::ProviderEffectJournal;
use super::ProviderEffectKey;
use super::ProviderEffectState;
use super::ProviderEffectStatusObservation;
use crate::Sha256Digest;
use pretty_assertions::assert_eq;
use std::io::Write;
use std::path::Path;

fn pending_journal() -> (
    ProviderEffectJournal,
    ProviderEffectIntent,
    ProviderEffectAck,
) {
    let intent = ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("provider", "run", "step").expect("effect key"),
        Sha256Digest::for_bytes(b"exact payload"),
    );
    let accepted = ProviderEffectAck::new(
        intent.key.clone(),
        intent.payload_sha256.clone(),
        Sha256Digest::for_bytes(b"original provider operation"),
        ProviderEffectAckStatus::Accepted,
    );
    let mut journal = ProviderEffectJournal::default();
    journal.record_intent(intent.clone()).expect("intent");
    (journal, intent, accepted)
}

fn persist_and_reopen(path: &Path, journal: &ProviderEffectJournal) -> ProviderEffectJournal {
    let encoded = serde_json::to_vec(journal).expect("encode journal");
    let mut file = std::fs::File::create(path).expect("create journal");
    file.write_all(&encoded).expect("write journal");
    file.sync_all().expect("sync journal");
    drop(file);
    let stored = std::fs::read(path).expect("read closed journal");
    let reopened: ProviderEffectJournal =
        serde_json::from_slice(&stored).expect("validate persisted journal");
    assert_eq!(reopened.validate(), Ok(()));
    assert_eq!(&reopened, journal);
    reopened
}

#[test]
fn same_status_clears_reopened_quarantine_and_preserves_provenance() {
    let (mut journal, intent, accepted) = pending_journal();
    let key = intent.key;
    journal.record_ack(accepted.clone()).expect("dispatch ACK");
    journal
        .mark_indeterminate(&key, "provider_lookup_unknown")
        .expect("quarantine");
    let directory = tempfile::tempdir().expect("journal directory");
    let path = directory.path().join("journal.json");
    journal = persist_and_reopen(&path, &journal);
    assert_eq!(
        journal.state(&key),
        Some(ProviderEffectState::Indeterminate)
    );

    let observed = ProviderEffectStatusObservation::from_ack(&accepted);
    assert_eq!(
        journal.record_status_observation(observed.clone()),
        Ok(ProviderEffectAppendDisposition::Inserted)
    );
    assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
    assert_eq!(
        journal.acknowledgements(&key),
        &[accepted.clone(), accepted.clone()]
    );
    assert_eq!(
        journal.acknowledgement_sources(&key),
        &[
            ProviderEffectAckSource::DispatchResponse,
            ProviderEffectAckSource::StatusLookup,
        ]
    );
    assert_eq!(
        journal.status_observations(&key),
        std::slice::from_ref(&observed)
    );

    journal = persist_and_reopen(&path, &journal);
    let before = serde_json::to_vec(&journal).expect("encode reconciled journal");
    assert_eq!(
        journal.record_status_observation(observed),
        Ok(ProviderEffectAppendDisposition::AlreadyPresent)
    );
    assert_eq!(
        serde_json::to_vec(&journal).expect("encode duplicate status"),
        before
    );
    // The earlier identical dispatch ACK cannot bypass the later status fence.
    assert_eq!(
        journal.record_ack(accepted),
        Err(ProviderEffectBindingError::AckConflict)
    );
    assert_eq!(
        serde_json::to_vec(&journal).expect("encode rejected dispatch"),
        before
    );
    assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
}

#[test]
fn repeated_quarantine_records_each_reconciliation_without_rebinding_operation() {
    let (mut journal, intent, accepted) = pending_journal();
    let key = intent.key;
    let observed = ProviderEffectStatusObservation::from_ack(&accepted);
    journal
        .record_status_observation(observed.clone())
        .expect("initial status ACK");
    let directory = tempfile::tempdir().expect("journal directory");
    let path = directory.path().join("journal.json");

    for expected_observations in [2, 3] {
        let disposition = if expected_observations == 2 {
            ProviderEffectAppendDisposition::Inserted
        } else {
            ProviderEffectAppendDisposition::AlreadyPresent
        };
        // Repeating the same reason still re-engages quarantine. An old status
        // entry must not stand in for the later reconciliation observation.
        assert_eq!(
            journal.mark_indeterminate(&key, "provider_lookup_unknown"),
            Ok(disposition)
        );
        journal = persist_and_reopen(&path, &journal);
        assert_eq!(
            journal.state(&key),
            Some(ProviderEffectState::Indeterminate)
        );
        let before = serde_json::to_vec(&journal).expect("encode quarantine");

        let mut substituted = observed.clone();
        substituted.provider_operation_id_sha256 =
            Sha256Digest::for_bytes(b"different provider operation");
        assert_eq!(
            journal.record_status_observation(substituted),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            journal.record_ack(accepted.clone()),
            Err(ProviderEffectBindingError::AckConflict)
        );
        assert_eq!(
            serde_json::to_vec(&journal).expect("encode rejected observations"),
            before
        );
        assert_eq!(
            journal.record_status_observation(observed.clone()),
            Ok(ProviderEffectAppendDisposition::Inserted)
        );
        journal = persist_and_reopen(&path, &journal);
        assert_eq!(journal.state(&key), Some(ProviderEffectState::Accepted));
        assert_eq!(journal.acknowledgements(&key).len(), expected_observations);
        assert_eq!(
            journal.acknowledgement_sources(&key),
            vec![ProviderEffectAckSource::StatusLookup; expected_observations].as_slice()
        );
        assert_eq!(
            journal.status_observations(&key),
            vec![observed.clone(); expected_observations].as_slice()
        );
        assert_eq!(journal.uncertainties(&key).len(), 1);

        let before = serde_json::to_vec(&journal).expect("encode reconciled journal");
        assert_eq!(
            journal.record_status_observation(observed.clone()),
            Ok(ProviderEffectAppendDisposition::AlreadyPresent)
        );
        assert_eq!(
            serde_json::to_vec(&journal).expect("encode duplicate status"),
            before
        );
    }
}
