use super::*;
use crate::chat_owner::CHAT_OWNER_PROTOCOL;
use crate::chat_owner::ChatCapability;
use crate::chat_owner::OwnerScope;
use crate::chat_owner::OwnerSession;

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
fn every_parked_partition_survives_but_only_original_authentication_can_reveal_it() {
    let mut original = ChatWorkspace::default();
    original.edit("anonymous draft".into());
    for principal in ["A", "B", "C", "D"] {
        original.install_owner(session(principal), 1).unwrap();
        original.edit(format!("{principal} private first"));
        original.new_draft();
        original.edit(format!("{principal} private second 中文"));
    }
    let expected = original.archive_local_drafts().unwrap();
    let serialized = serde_json::to_string(&expected).unwrap();
    let mut restored =
        ChatWorkspace::from_local_draft_archive(serde_json::from_str(&serialized).unwrap())
            .unwrap();
    assert_eq!(restored.archive_local_drafts().unwrap(), expected);
    assert_eq!(restored.draft().text, "anonymous draft");
    assert_eq!(restored.drafts().count(), 1);
    assert!(restored.timeline().is_none());
    assert!(!restored.request_send());
    for principal in ["B", "A", "D", "C"] {
        restored.install_owner(session(principal), 2).unwrap();
        assert_eq!(
            restored.draft().text,
            format!("{principal} private second 中文")
        );
        assert_eq!(restored.drafts().count(), 2);
        assert!(restored.timeline().is_none());
        assert!(restored.delivery_for(restored.active_id(), 2).is_none());
    }
    restored.disconnect_owner();
    assert_eq!(restored.draft().text, "anonymous draft");
}

#[test]
fn corrupt_partitions_and_preedit_are_rejected_without_partial_restoration() {
    let mut workspace = ChatWorkspace::default();
    workspace.edit("keep".into());
    let good = workspace.archive_local_drafts().unwrap();
    let mut duplicate = good.clone();
    duplicate.partitions.push(duplicate.partitions[0].clone());
    assert!(ChatWorkspace::from_local_draft_archive(duplicate).is_err());
    let mut invalid = good.clone();
    invalid.partitions[0].rooms[0] = "bad\0text".into();
    assert!(ChatWorkspace::from_local_draft_archive(invalid).is_err());
    let mut missing_anonymous = good.clone();
    missing_anonymous.partitions[0].principal = Some("A".into());
    assert!(ChatWorkspace::from_local_draft_archive(missing_anonymous).is_err());
    workspace.composing = true;
    assert!(workspace.archive_local_drafts().is_err());
    assert_eq!(workspace.draft().text, "keep");
    let json = serde_json::to_string(&good)
        .unwrap()
        .replace("\"version\":1", "\"version\":1,\"owner\":true");
    assert!(serde_json::from_str::<LocalDraftArchive>(&json).is_err());
}
