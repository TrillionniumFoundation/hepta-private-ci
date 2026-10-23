use super::*;
use crate::presentation::{
    ActionResult, PresentationAction, PresentationCommand, RoomKey, apply_action,
};

#[test]
fn adoption_does_not_replace_an_existing_draft_or_construct_a_second_source() {
    let mut slot = ChatSourceSlot::default();
    assert!(slot.adopt_once(|| ChatSource::Standalone(Box::default())));
    let source = RoomKey {
        epoch: slot.workspace().presentation_epoch(),
        local_id: slot.workspace().active_id(),
    };
    assert_eq!(
        apply_action(
            slot.workspace_mut(),
            PresentationAction {
                source,
                command: PresentationCommand::Edit("唯一草稿".into())
            }
        ),
        ActionResult::Applied
    );
    assert!(!slot.adopt_once(|| panic!("second workspace must not even be constructed")));
    assert_eq!(slot.workspace().draft().text, "唯一草稿");
    assert_eq!(
        apply_action(
            slot.workspace_mut(),
            PresentationAction {
                source,
                command: PresentationCommand::RequestSend
            }
        ),
        ActionResult::SendUnavailable
    );
    assert_eq!(slot.workspace().draft().text, "唯一草稿");
}

#[cfg(feature = "native-presentation")]
#[test]
fn embedded_adoption_borrows_the_original_draft_and_exits_once() {
    use crate::native_presentation::tests::Client;
    use std::cell::Cell;
    use std::rc::Rc;

    let exits = Rc::new(Cell::new(0));
    let mut original = ChatWorkspace::default();
    let source = RoomKey {
        epoch: original.presentation_epoch(),
        local_id: original.active_id(),
    };
    assert_eq!(
        apply_action(
            &mut original,
            PresentationAction {
                source,
                command: PresentationCommand::Edit("已存在的草稿 📝".into()),
            }
        ),
        ActionResult::Applied
    );
    let draft_allocation = original.draft().text.as_ptr();
    let client = Client {
        workspace: original,
        exits: Rc::clone(&exits),
    };
    let mut slot = ChatSourceSlot::default();
    assert!(slot.adopt_once(|| ChatSource::Embedded(OwnedComposition::new(Box::new(client)))));
    assert_eq!(slot.workspace().draft().text.as_ptr(), draft_allocation);
    assert_eq!(slot.workspace_mut().draft().text.as_ptr(), draft_allocation);
    assert!(!slot.adopt_once(|| panic!("the original source must not be replaced")));
    assert_eq!(
        apply_action(
            slot.workspace_mut(),
            PresentationAction {
                source,
                command: PresentationCommand::RequestSend,
            }
        ),
        ActionResult::SendUnavailable
    );
    assert_eq!(slot.workspace().draft().text.as_ptr(), draft_allocation);
    slot.composition_mut().unwrap().exit();
    drop(slot);
    assert_eq!(exits.get(), 1);
}
