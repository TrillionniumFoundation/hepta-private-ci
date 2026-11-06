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

#[test]
fn input_limit_disables_original_objective_until_a_valid_edit() {
    use crate::chat_owner::CHAT_OWNER_PROTOCOL;
    use crate::chat_owner::ChatCapability;
    use crate::chat_owner::OwnerScope;
    use crate::chat_owner::OwnerSession;
    use crate::objective_ui::ObjectiveUiBinding;
    use crate::objective_ui::ObjectiveUiCommand;
    use crate::objective_ui::ObjectiveUiError;
    use crate::objective_ui::ObjectiveUiObservation;
    use crate::objective_ui::ObjectiveUiPhase;
    use crate::objective_ui::ObjectiveUiPort;
    use crate::objective_ui::ObjectiveUiRequest;
    use sha2::Digest;
    use sha2::Sha256;
    use std::sync::Arc;
    use std::sync::Mutex;

    struct PreparedPort {
        binding: ObjectiveUiBinding,
        observation: Option<ObjectiveUiObservation>,
        requests: Arc<Mutex<Vec<ObjectiveUiCommand>>>,
    }
    impl ObjectiveUiPort for PreparedPort {
        fn binding(&self) -> &ObjectiveUiBinding {
            &self.binding
        }
        fn request(
            &mut self,
            command: ObjectiveUiCommand,
            presentation_epoch: u64,
            room: u64,
            draft: &str,
        ) -> Result<ObjectiveUiRequest, ObjectiveUiError> {
            if presentation_epoch != self.binding.presentation_epoch || room != self.binding.room {
                return Err(ObjectiveUiError::Binding);
            }
            if !self.binding.matches_draft(draft) {
                return Err(ObjectiveUiError::DraftChanged);
            }
            self.requests.lock().unwrap().push(command);
            Ok(ObjectiveUiRequest::Queued)
        }
        fn poll(&mut self) -> Option<ObjectiveUiObservation> {
            self.observation.take()
        }
        fn close(&mut self) {}
    }

    let session = OwnerSession {
        protocol: CHAT_OWNER_PROTOCOL.into(),
        scope: OwnerScope {
            principal_id: "principal".into(),
            session_id: "session".into(),
            connection_generation: 1,
            permission_revision: 1,
            agent_id: "agent".into(),
            agent_generation: 1,
            thread_id: "thread".into(),
        },
        expires_at_ms: 1000,
        capabilities: vec![ChatCapability::SubmitSignedText],
    };
    let mut model = ChatWorkspace::default();
    model.install_owner(session.clone(), 1).unwrap();
    assert!(model.edit("保留原始任务 中文".into()));
    let original = model.draft().clone();
    let binding = ObjectiveUiBinding {
        owner: session.scope,
        owner_expires_at_ms: session.expires_at_ms,
        window_id: "window".into(),
        window_generation: 1,
        presentation_epoch: model.presentation_epoch(),
        room: model.active_id(),
        draft_sha256: Sha256::digest(original.text.as_bytes()).into(),
    };
    let requests = Arc::new(Mutex::new(Vec::new()));
    model
        .install_objective_owner(
            Box::new(PreparedPort {
                observation: Some(ObjectiveUiObservation {
                    binding: binding.clone(),
                    sequence: 1,
                    phase: ObjectiveUiPhase::Prepared,
                    retained_publication: None,
                    can_cancel: true,
                    can_refresh: false,
                }),
                binding,
                requests: requests.clone(),
            }),
            1,
        )
        .unwrap();
    assert!(model.objective_can_submit());

    assert!(!model.edit("界".repeat(MAX_DRAFT_BYTES)));
    assert_eq!(
        model.draft(),
        &Draft {
            status: ComposeStatus::InputLimit,
            ..original.clone()
        }
    );
    assert!(!model.objective_can_submit());
    assert!(!model.request_send());
    assert!(requests.lock().unwrap().is_empty());

    // Editing remains available, but a changed task does not inherit the
    // independently prepared original request's sending permission.
    assert!(model.edit("修改后的任务".into()));
    assert_eq!(model.draft().status, ComposeStatus::LocalDraft);
    assert!(!model.objective_can_submit());
    assert!(model.edit(original.text.clone()));
    assert_eq!(model.draft(), &original);
    assert!(model.objective_can_submit());
    assert!(model.request_send());
    assert_eq!(*requests.lock().unwrap(), vec![ObjectiveUiCommand::Submit]);
    assert_eq!(model.draft(), &original);
}
