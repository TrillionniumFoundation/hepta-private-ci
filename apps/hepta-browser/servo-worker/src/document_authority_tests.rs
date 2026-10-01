use super::DocumentAuthority;
use super::LoadPhase;

const URL_A: &str = "https://example.com/a";
const URL_B: &str = "https://example.com/b";

#[test]
fn every_observation_advances_and_only_the_current_snapshot_can_authorize() {
    let mut authority = DocumentAuthority::default();
    let first = authority
        .observe(URL_A, "https://example.com", |generation, epoch| {
            format!("{generation}:{epoch}")
        })
        .unwrap();
    let second = authority
        .observe(URL_A, "https://example.com", |generation, epoch| {
            format!("{generation}:{epoch}")
        })
        .unwrap();
    assert_eq!((first.page_generation, second.page_generation), (1, 2));
    assert!(
        authority
            .validate_observation(1, &first.document_digest, URL_A)
            .is_err()
    );
    assert!(
        authority
            .validate_observation(2, "changed-digest", URL_A)
            .is_err()
    );
    assert!(
        authority
            .validate_observation(2, &second.document_digest, URL_B)
            .is_err()
    );
    assert_eq!(
        authority.validate_observation(2, &second.document_digest, URL_A),
        Ok(())
    );
    authority.consume_observation();
    assert!(
        authority
            .validate_observation(2, &second.document_digest, URL_A)
            .is_err()
    );
}

#[test]
fn spontaneous_navigation_and_same_url_reloads_invalidate_authority() {
    let mut authority = DocumentAuthority::default();
    let observation = authority
        .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
        .unwrap();
    authority.navigation_requested(URL_A).unwrap();
    assert!(
        authority
            .validate_observation(observation.page_generation, "digest", URL_A)
            .is_err()
    );
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    let observation = authority
        .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
        .unwrap();
    authority.load_changed(LoadPhase::Started, URL_A);
    assert!(
        authority
            .validate_observation(observation.page_generation, "digest", URL_A)
            .is_err()
    );
}

#[test]
fn old_complete_and_unrelated_navigation_do_not_complete_an_operation() {
    let mut authority = DocumentAuthority::default();
    let first = authority.begin_navigation(URL_A, "about:blank").unwrap();
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(!authority.navigation_complete(&first, URL_A, LoadPhase::Complete));
    authority.navigation_requested(URL_A).unwrap();
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_B);
    assert!(!authority.navigation_complete(&first, URL_B, LoadPhase::Complete));
    let second = authority.begin_navigation(URL_B, URL_A).unwrap();
    authority.navigation_requested(URL_B).unwrap();
    authority.load_changed(LoadPhase::Started, URL_B);
    authority.url_changed(URL_B);
    authority.load_changed(LoadPhase::Complete, URL_B);
    assert!(!authority.navigation_complete(&first, URL_A, LoadPhase::Complete));
    assert!(authority.navigation_complete(&second, URL_B, LoadPhase::Complete));
}

#[test]
fn redirect_and_repeat_same_url_navigation_supersede_pending_completion() {
    let mut authority = DocumentAuthority::default();
    let attempt = authority.begin_navigation(URL_A, "about:blank").unwrap();
    authority.navigation_requested(URL_A).unwrap();
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.navigation_requested(URL_A).unwrap();
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(!authority.navigation_complete(&attempt, URL_A, LoadPhase::Complete));
    let attempt = authority.begin_navigation(URL_A, "about:blank").unwrap();
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.url_changed(URL_B);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(!authority.navigation_complete(&attempt, URL_A, LoadPhase::Complete));
}

#[test]
fn consumed_or_observed_documents_cannot_reenter_bootstrap() {
    let mut authority = DocumentAuthority::default();
    assert!(authority.bootstrap_allowed("about:blank"));
    assert!(!authority.bootstrap_allowed(URL_A));
    authority.consume_observation();
    assert!(!authority.bootstrap_allowed("about:blank"));
    let mut authority = DocumentAuthority::default();
    authority
        .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
        .unwrap();
    assert!(!authority.bootstrap_allowed("about:blank"));
}

#[test]
fn exhausted_navigation_identity_never_reuses_previous_evidence() {
    let mut authority = DocumentAuthority::default();
    authority.navigation_epoch = super::MAX_SAFE_INTEGER;
    assert!(authority.begin_navigation(URL_A, "about:blank").is_err());
    assert!(!authority.bootstrap_allowed("about:blank"));
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_err()
    );
}

#[test]
fn same_url_reload_is_indeterminate_without_request_specific_completion() {
    let mut authority = DocumentAuthority::default();
    let attempt = authority.begin_navigation(URL_A, URL_A).unwrap();
    authority.navigation_requested(URL_A).unwrap();
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::InProgress, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(!authority.navigation_complete(&attempt, URL_A, LoadPhase::Complete));
}

#[test]
fn pending_navigation_cannot_authorize_the_previous_complete_document() {
    let mut authority = DocumentAuthority::default();
    authority.begin_navigation(URL_A, "about:blank").unwrap();
    authority.load_changed(LoadPhase::Complete, "about:blank");
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Started, "about:blank");
    authority.url_changed(URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_ok()
    );
}

#[test]
fn unsolicited_navigation_cannot_reauthorize_the_previous_complete_document() {
    let mut authority = DocumentAuthority::default();
    authority
        .observe(URL_A, "https://example.com", |_, _| "first".to_string())
        .unwrap();
    authority.navigation_requested(URL_B).unwrap();
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "second".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "second".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.url_changed(URL_B);
    authority.load_changed(LoadPhase::Complete, URL_B);
    assert!(
        authority
            .observe(URL_B, "https://example.com", |_, _| "second".to_string())
            .is_ok()
    );
}

#[test]
fn superseded_operation_stays_fenced_until_the_new_target_completes() {
    let mut authority = DocumentAuthority::default();
    let attempt = authority.begin_navigation(URL_A, "about:blank").unwrap();
    authority.navigation_requested(URL_B).unwrap();
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "digest".to_string())
            .is_err()
    );
    authority.url_changed(URL_B);
    authority.load_changed(LoadPhase::Complete, URL_B);
    assert!(
        authority
            .observe(URL_B, "https://example.com", |_, _| "digest".to_string())
            .is_ok()
    );
    assert!(!authority.navigation_complete(&attempt, URL_A, LoadPhase::Complete));
}

#[test]
fn startup_blank_load_is_bootstrappable_but_pending_web_navigation_is_not() {
    let mut authority = DocumentAuthority::default();
    authority.navigation_requested("about:blank").unwrap();
    authority.load_changed(LoadPhase::Started, "about:blank");
    assert!(authority.bootstrap_allowed("about:blank"));
    authority.load_changed(LoadPhase::Complete, "about:blank");
    assert!(authority.bootstrap_allowed("about:blank"));
    authority.navigation_requested(URL_A).unwrap();
    assert!(!authority.bootstrap_allowed("about:blank"));
    authority.load_changed(LoadPhase::Complete, "about:blank");
    assert!(!authority.bootstrap_allowed("about:blank"));
}

#[test]
fn stale_history_callbacks_cannot_replace_an_accepted_navigation_target() {
    let mut authority = DocumentAuthority::default();
    authority
        .observe(URL_A, "https://example.com", |_, _| "first".to_string())
        .unwrap();
    authority.navigation_requested(URL_B).unwrap();
    authority.url_changed(URL_A);
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "second".to_string())
            .is_err()
    );
    authority.url_changed(URL_B);
    authority.load_changed(LoadPhase::Complete, URL_B);
    assert!(
        authority
            .observe(URL_B, "https://example.com", |_, _| "second".to_string())
            .is_ok()
    );
}

#[test]
fn unexpected_load_progress_fences_in_flight_dom_completion_and_new_observations() {
    let mut authority = DocumentAuthority::default();
    authority
        .observe(URL_A, "https://example.com", |_, _| "first".to_string())
        .unwrap();
    authority.consume_observation();
    let dispatch_epoch = authority.navigation_epoch;
    authority.load_changed(LoadPhase::InProgress, URL_A);
    assert!(authority.navigation_epoch > dispatch_epoch);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "second".to_string())
            .is_err()
    );
    authority.load_changed(LoadPhase::Started, URL_A);
    authority.load_changed(LoadPhase::Complete, URL_A);
    assert!(
        authority
            .observe(URL_A, "https://example.com", |_, _| "second".to_string())
            .is_ok()
    );
}
