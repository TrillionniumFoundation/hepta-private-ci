use std::fmt::Debug;

use codex_hepta_types::Digest32;

use super::NduProjectionJournalError;
use super::NduProjectionJournalV1;
use super::NduProjectionKindV1;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
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
            .select_projection(digest("second-selection"), objective, subject, projection,)
            .expect_err("revoked projection must not be reselected"),
        NduProjectionJournalError::RevokedProjection
    );
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

#[test]
fn revocation_is_scoped_by_objective_and_subject() {
    let objective_a = digest("objective-a");
    let objective_b = digest("objective-b");
    let subject_a = digest("subject-a");
    let subject_b = digest("subject-b");
    let projection = digest("shared-projection");

    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-a"),
        objective_a,
        subject_a,
        projection,
    ));
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-b"),
        objective_b,
        subject_b,
        projection,
    ));
    must(journal.select_projection(
        digest("selection-a"),
        objective_a,
        subject_a,
        projection,
    ));
    must(journal.select_projection(
        digest("selection-b"),
        objective_b,
        subject_b,
        projection,
    ));
    must(journal.revoke_projection(
        digest("revocation-a"),
        objective_a,
        subject_a,
        projection,
    ));

    assert_eq!(
        journal.selected_projection_digest(objective_a, subject_a),
        None
    );
    assert_eq!(
        journal.selected_projection_digest(objective_b, subject_b),
        Some(projection)
    );
    must(journal.select_projection(
        digest("selection-b-2"),
        objective_b,
        subject_b,
        projection,
    ));
}
