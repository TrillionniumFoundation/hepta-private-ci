use super::*;
#[test]
fn drafts_survive_switch_and_unavailable_repeated_submission() {
    let mut model = ChatWorkspace::default();
    assert!(model.edit("你好\nUnsent local text".into()));
    assert!(model.new_draft());
    assert!(model.edit("Second draft".into()));
    assert!(model.select(0));
    for _ in 0..5 {
        assert!(!model.request_send());
    }
    assert_eq!(model.draft().text, "你好\nUnsent local text");
    assert_eq!(model.drafts().count(), 2);
}
#[test]
fn composition_never_submits_switches_or_discards_input() {
    let mut model = ChatWorkspace::default();
    assert!(model.edit("中文".into()));
    model.composing = true;
    assert!(!model.request_send());
    assert!(!model.clear());
    assert!(!model.new_draft());
    assert!(!model.select(0));
    assert_eq!(model.draft().text, "中文");
    assert_eq!(model.draft().status, ComposeStatus::LocalDraft);
}
#[test]
fn bounded_unicode_drafts_reject_whole_update_without_truncation() {
    let mut model = ChatWorkspace::default();
    assert!(model.edit("kept".into()));
    assert!(!model.edit("界".repeat(MAX_DRAFT_BYTES)));
    assert_eq!(model.draft().text, "kept");
    assert_eq!(model.draft().status, ComposeStatus::InputLimit);
    assert!(!model.edit("bad\0input".into()));
    for _ in 1..MAX_LOCAL_DRAFTS {
        assert!(model.new_draft());
    }
    assert!(!model.new_draft());
    assert_eq!(model.drafts().count(), MAX_LOCAL_DRAFTS);
}
