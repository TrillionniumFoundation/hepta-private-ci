use std::fmt::Debug;

use codex_hepta_types::Digest32;

use super::NduProjectionJournalError;
use super::NduProjectionJournalV1;
use super::NduProjectionKindV1;
use super::digest_entry;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn forged_single_transition(kind: NduProjectionKindV1) -> Vec<u8> {
    let sequence = 1_u64;
    let identity = digest("forged-identity");
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection-never-recorded");
    let predecessor = Digest32::ZERO;
    let entry_digest = digest_entry(
        sequence,
        kind,
        identity,
        objective,
        subject,
        projection,
        predecessor,
    );

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"HNDUPJ01");
    bytes.extend_from_slice(&1_u32.to_be_bytes());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.push(kind.tag());
    bytes.extend_from_slice(identity.as_array());
    bytes.extend_from_slice(objective.as_array());
    bytes.extend_from_slice(subject.as_array());
    bytes.extend_from_slice(projection.as_array());
    bytes.extend_from_slice(predecessor.as_array());
    bytes.extend_from_slice(entry_digest.as_array());
    bytes
}

#[test]
fn projection_journal_round_trips_and_restores_selection() {
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-identity"),
        objective,
        subject,
        projection,
    ));
    must(journal.select_projection(digest("selection-identity"), objective, subject, projection));

    let bytes = journal.export_bytes();
    let reopened = must(NduProjectionJournalV1::reopen(&bytes));
    assert_eq!(reopened.entries(), journal.entries());
    assert_eq!(
        reopened.selected_projection_digest(objective, subject),
        Some(projection)
    );
}

#[test]
fn identity_replay_is_idempotent_and_drift_conflicts() {
    let objective = digest("objective");
    let subject = digest("subject");
    let identity = digest("identity");
    let projection = digest("projection");
    let mut journal = NduProjectionJournalV1::new();
    let first = must(journal.append_projection(
        NduProjectionKindV1::Utility,
        identity,
        objective,
        subject,
        projection,
    ));
    let replay = must(journal.append_projection(
        NduProjectionKindV1::Utility,
        identity,
        objective,
        subject,
        projection,
    ));
    assert_eq!(first, replay);
    assert_eq!(journal.entries().len(), 1);

    assert_eq!(
        journal
            .append_projection(
                NduProjectionKindV1::Utility,
                identity,
                objective,
                subject,
                digest("different-projection"),
            )
            .expect_err("semantic drift must conflict"),
        NduProjectionJournalError::IdentityConflict
    );
}

#[test]
fn same_scoped_payload_cannot_be_registered_as_both_preference_and_utility() {
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("shared-projection-payload");
    let mut journal = NduProjectionJournalV1::new();

    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("preference-id"),
        objective,
        subject,
        projection,
    ));
    assert_eq!(
        journal
            .append_projection(
                NduProjectionKindV1::Utility,
                digest("utility-id"),
                objective,
                subject,
                projection,
            )
            .expect_err("selection by digest cannot disambiguate projection kind"),
        NduProjectionJournalError::ProjectionKindConflict
    );
}

#[test]
fn revocation_prevents_projection_resurrection() {
    let objective = digest("objective");
    let subject = digest("subject");
    let projection = digest("projection");
    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-identity"),
        objective,
        subject,
        projection,
    ));
    must(journal.select_projection(digest("selection-identity"), objective, subject, projection));
    must(journal.revoke_projection(
        digest("revocation-identity"),
        objective,
        subject,
        projection,
    ));
    assert_eq!(journal.selected_projection_digest(objective, subject), None);
    assert_eq!(
        journal
            .select_projection(digest("second-selection"), objective, subject, projection)
            .expect_err("revoked projection must not be reselected"),
        NduProjectionJournalError::RevokedProjection
    );
}

#[test]
fn revocation_is_scoped_to_objective_and_subject() {
    let objective_a = digest("objective-a");
    let objective_b = digest("objective-b");
    let subject_a = digest("subject-a");
    let subject_b = digest("subject-b");
    let shared_projection = digest("shared-projection-bytes");
    let mut journal = NduProjectionJournalV1::new();

    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-a"),
        objective_a,
        subject_a,
        shared_projection,
    ));
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-b"),
        objective_b,
        subject_b,
        shared_projection,
    ));
    must(journal.select_projection(
        digest("selection-a"),
        objective_a,
        subject_a,
        shared_projection,
    ));
    must(journal.select_projection(
        digest("selection-b"),
        objective_b,
        subject_b,
        shared_projection,
    ));
    must(journal.revoke_projection(
        digest("revocation-a"),
        objective_a,
        subject_a,
        shared_projection,
    ));

    assert_eq!(
        journal.selected_projection_digest(objective_a, subject_a),
        None
    );
    assert_eq!(
        journal.selected_projection_digest(objective_b, subject_b),
        Some(shared_projection)
    );
    must(journal.select_projection(
        digest("selection-b-again"),
        objective_b,
        subject_b,
        shared_projection,
    ));
}

#[test]
fn live_selection_and_revocation_require_a_recorded_projection() {
    let objective = digest("objective");
    let subject = digest("subject");
    let missing = digest("missing-projection");
    let mut journal = NduProjectionJournalV1::new();

    assert_eq!(
        journal
            .select_projection(digest("selection"), objective, subject, missing)
            .expect_err("selection without projection must reject"),
        NduProjectionJournalError::ProjectionNotRecorded
    );
    assert_eq!(
        journal
            .revoke_projection(digest("revocation"), objective, subject, missing)
            .expect_err("revocation without projection must reject"),
        NduProjectionJournalError::ProjectionNotRecorded
    );
}

#[test]
fn hash_valid_but_semantically_impossible_recovery_rejects() {
    for kind in [
        NduProjectionKindV1::SelectedProjection,
        NduProjectionKindV1::Revocation,
    ] {
        let bytes = forged_single_transition(kind);
        assert_eq!(
            NduProjectionJournalV1::reopen(&bytes)
                .expect_err("semantic transition without a recorded projection must reject"),
            NduProjectionJournalError::ProjectionNotRecorded
        );
    }
}

#[test]
fn truncation_and_tampering_fail_closed() {
    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("identity"),
        digest("objective"),
        digest("subject"),
        digest("projection"),
    ));
    let bytes = journal.export_bytes();
    assert_eq!(
        NduProjectionJournalV1::reopen(&bytes[..bytes.len() - 1])
            .expect_err("truncation must reject"),
        NduProjectionJournalError::Truncated
    );

    let mut tampered = bytes;
    let last = tampered.len() - 1;
    tampered[last] ^= 1;
    assert_eq!(
        NduProjectionJournalV1::reopen(&tampered).expect_err("tamper must reject"),
        NduProjectionJournalError::CorruptEntryDigest
    );
}
