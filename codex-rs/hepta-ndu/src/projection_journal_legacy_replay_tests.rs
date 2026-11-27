use std::fmt::Debug;

use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

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
fn original_hndupj01_capacity_images_remain_readable() {
    let objective = digest("legacy-capacity-objective");
    let subject = digest("legacy-capacity-subject");
    for count in [MAX_RECORDS / 2 + 1, MAX_RECORDS] {
        let mut legacy = NduProjectionJournalV1::new();
        for index in 0..count {
            // The original HNDUPJ01 writer allowed up to MAX_RECORDS live
            // projections. This test-only primitive reproduces those bytes.
            must(legacy.append(
                NduProjectionKindV1::Preference,
                digest(&format!("legacy-capacity-identity-{index}")),
                objective,
                subject,
                digest(&format!("legacy-capacity-projection-{index}")),
            ));
        }
        let bytes = legacy.export_bytes();
        let reopened = must(NduProjectionJournalV1::reopen(&bytes));
        assert_eq!(reopened.entries(), legacy.entries());
        assert_eq!(reopened.export_bytes(), bytes);
        assert_eq!(reopened.entries().len(), count);
    }
}

#[test]
fn original_hndupj01_revocation_history_remains_non_resurrecting() {
    let objective = digest("legacy-revocation-objective");
    let subject = digest("legacy-revocation-subject");
    let projection_a = digest("legacy-projection-a");
    let projection_b = digest("legacy-projection-b");
    let mut legacy = NduProjectionJournalV1::new();
    for (kind, identity, projection) in [
        (NduProjectionKindV1::Preference, "append-a", projection_a),
        (
            NduProjectionKindV1::SelectedProjection,
            "select-a",
            projection_a,
        ),
        (NduProjectionKindV1::Utility, "append-b", projection_b),
        (
            NduProjectionKindV1::SelectedProjection,
            "replace-b",
            projection_b,
        ),
        (NduProjectionKindV1::Revocation, "revoke-a", projection_a),
        (
            NduProjectionKindV1::Revocation,
            "repeat-revoke-a",
            projection_a,
        ),
        (
            NduProjectionKindV1::Preference,
            "repeat-append-a",
            projection_a,
        ),
    ] {
        // These operations were legal in the original format; every selected
        // or revoked projection is already recorded, and no revoked one is selected.
        must(legacy.append(kind, digest(identity), objective, subject, projection));
    }
    let bytes = legacy.export_bytes();
    let mut reopened = must(NduProjectionJournalV1::reopen(&bytes));
    assert_eq!(reopened.entries(), legacy.entries());
    assert_eq!(reopened.export_bytes(), bytes);
    assert_eq!(
        reopened.selected_projection_digest(objective, subject),
        Some(projection_b)
    );
    assert_eq!(
        reopened
            .select_projection(digest("resurrect-a"), objective, subject, projection_a,)
            .expect_err("retained revocations still reject resurrection"),
        NduProjectionJournalError::RevokedProjection
    );
    assert_eq!(reopened.export_bytes(), bytes);
}
