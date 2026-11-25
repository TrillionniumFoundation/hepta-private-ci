use super::*;
use crate::chat_owner::*;
use crate::chat_timeline::*;
fn session(principal: &str) -> OwnerSession {
    OwnerSession {
        protocol: CHAT_OWNER_PROTOCOL.into(),
        scope: OwnerScope {
            principal_id: principal.into(),
            session_id: format!("{principal}-session"),
            connection_generation: 1,
            permission_revision: 1,
            agent_id: "agent".into(),
            agent_generation: 1,
            thread_id: "thread".into(),
        },
        expires_at_ms: 1000,
        capabilities: vec![ChatCapability::SubmitSignedText],
    }
}
#[test]
fn principal_rotation_hides_all_history_and_drafts_without_discarding_them() {
    let mut w = ChatWorkspace::default();
    w.install_owner(session("A"), 1).unwrap();
    w.edit("A private draft".into());
    let old = w
        .begin_history(
            0,
            "thread",
            ViewFence {
                owner_session: "A-session".into(),
                generation: 1,
            },
        )
        .unwrap();
    w.receive_history(
        &old,
        History {
            thread_id: "thread".into(),
            title: "A private history".into(),
            revision: 1,
            event_sequence: 0,
            messages: vec![],
        },
    )
    .unwrap();
    w.new_draft();
    w.edit("A second draft".into());
    w.filter = "A private search".into();
    w.presentation_note = Some("A private note".into());
    let epoch = w.presentation_epoch();
    w.install_owner(session("B"), 2).unwrap();
    assert!(w.draft().text.is_empty());
    assert!(w.filter.is_empty());
    assert!(w.presentation_note.is_none());
    assert!(w.timeline().is_none());
    assert_eq!(w.drafts().count(), 1);
    assert!(w.presentation_epoch() > epoch);
    assert_eq!(
        w.receive_delta(&old, "late", 1, "A content"),
        Err(ProjectionError::Stale)
    );
    w.edit("B draft".into());
    w.install_owner(session("A"), 3).unwrap();
    assert_eq!(w.draft().text, "A second draft");
    w.select(0);
    assert_eq!(w.draft().text, "A private draft");
    assert!(w.timeline().is_none());
    let mut invalid = session("B");
    invalid.expires_at_ms = 0;
    assert!(w.install_owner(invalid, 4).is_err());
    assert!(w.draft().text.is_empty());
    assert!(w.timeline().is_none());
    w.install_owner(session("B"), 5).unwrap();
    assert_eq!(w.draft().text, "B draft");
}
