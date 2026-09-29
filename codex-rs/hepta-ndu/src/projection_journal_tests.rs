use std::fmt::Debug;

use codex_hepta_types::Digest32;

use super::MAX_RECORDS;
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
    must(journal.select_projection_if_current(
        digest("selection-identity"),
        objective,
        subject,
        None,
        projection,
    ));

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
fn stale_selection_cannot_replace_newer_selection() {
    let objective = digest("objective");
    let subject = digest("subject");
    let projection_a = digest("projection-a");
    let projection_b = digest("projection-b");
    let mut journal = NduProjectionJournalV1::new();
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-a-identity"),
        objective,
        subject,
        projection_a,
    ));
    must(journal.append_projection(
        NduProjectionKindV1::Preference,
        digest("projection-b-identity"),
        objective,
        subject,
        projection_b,
    ));
    must(journal.select_projection_if_current(
        digest("selection-a"),
        objective,
        subject,
        None,
        projection_a,
    ));

    assert_eq!(
        journal
            .select_projection_if_current(
                digest("stale-selection-b"),
                objective,
                subject,
                None,
                projection_b,
            )
            .expect_err("late selection must not overwrite a newer selected predecessor"),
        NduProjectionJournalError::SelectionPredecessorMismatch
    );

    let selected_b = must(journal.select_projection_if_current(
        digest("selection-b"),
        objective,
        subject,
        Some(projection_a),
        projection_b,
    ));
    let replay = must(journal.select_projection_if_current(
        digest("selection-b"),
        objective,
        subject,
        None,
        projection_b,
    ));
    assert_eq!(
        replay, selected_b,
        "exact operation replay stays idempotent"
    );
    assert_eq!(
        journal.selected_projection_digest(objective, subject),
        Some(projection_b)
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
    must(journal.select_projection_if_current(
        digest("selection-identity"),
        objective,
        subject,
        None,
        projection,
    ));
    must(journal.revoke_projection(
        digest("revocation-identity"),
        objective,
        subject,
        projection,
    ));
    assert_eq!(journal.selected_projection_digest(objective, subject), None);
    assert_eq!(
        journal
            .select_projection_if_current(
                digest("second-selection"),
                objective,
                subject,
                None,
                projection,
            )
            .expect_err("revoked projection must not be reselected"),
        NduProjectionJournalError::RevokedProjection
    );
}

#[test]
fn revocation_is_scoped_to_objective_and_subject() {
    let projection = digest("shared-projection");
    let objective_a = digest("objective-a");
    let subject_a = digest("subject-a");
    let objective_b = digest("objective-b");
    let subject_b = digest("subject-b");
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
    must(journal.revoke_projection(digest("revoke-a"), objective_a, subject_a, projection));
    must(journal.select_projection_if_current(
        digest("select-b"),
        objective_b,
        subject_b,
        None,
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
}

#[test]
fn revocation_requires_a_recorded_projection() {
    let mut journal = NduProjectionJournalV1::new();
    assert_eq!(
        journal
            .revoke_projection(
                digest("revocation"),
                digest("objective"),
                digest("subject"),
                digest("projection"),
            )
            .expect_err("unknown projection cannot be revoked"),
        NduProjectionJournalError::ProjectionNotRecorded
    );
}

#[test]
fn capacity_reserves_a_revocation_for_every_live_projection() {
    let objective = digest("capacity-objective");
    let subject = digest("capacity-subject");
    let mut journal = NduProjectionJournalV1::new();

    for index in 0..(MAX_RECORDS / 2) {
        must(journal.append_projection(
            NduProjectionKindV1::Preference,
            digest(&format!("capacity-identity-{index}")),
            objective,
            subject,
            digest(&format!("capacity-projection-{index}")),
        ));
    }

    assert_eq!(
        journal
            .append_projection(
                NduProjectionKindV1::Preference,
                digest("capacity-overflow-identity"),
                objective,
                subject,
                digest("capacity-overflow-projection"),
            )
            .expect_err("ordinary history must not consume the reserved revocation frontier"),
        NduProjectionJournalError::RevocationCapacityExhausted
    );

    must(journal.revoke_projection(
        digest("capacity-revocation"),
        objective,
        subject,
        digest("capacity-projection-0"),
    ));
    let reopened = must(NduProjectionJournalV1::reopen(&journal.export_bytes()));
    assert_eq!(reopened.entries(), journal.entries());
}

#[test]
fn reopen_rejects_well_hashed_selection_without_projection() {
    let mut forged = NduProjectionJournalV1::new();
    must(forged.append(
        NduProjectionKindV1::SelectedProjection,
        digest("selection"),
        digest("objective"),
        digest("subject"),
        digest("projection"),
    ));

    assert_eq!(
        NduProjectionJournalV1::reopen(&forged.export_bytes())
            .expect_err("semantic replay must reject selection without projection"),
        NduProjectionJournalError::ProjectionNotRecorded
    );
}

#[test]
fn reopen_rejects_well_hashed_revocation_without_projection() {
    let mut forged = NduProjectionJournalV1::new();
    must(forged.append(
        NduProjectionKindV1::Revocation,
        digest("revocation"),
        digest("objective"),
        digest("subject"),
        digest("projection"),
    ));

    assert_eq!(
        NduProjectionJournalV1::reopen(&forged.export_bytes())
            .expect_err("semantic replay must reject revocation without projection"),
        NduProjectionJournalError::ProjectionNotRecorded
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
