use super::*;
use std::cell::Cell;
use std::rc::Rc;

pub(crate) struct Client {
    pub(crate) workspace: ChatWorkspace,
    pub(crate) exits: Rc<Cell<usize>>,
}

impl NativeChatComposition for Client {
    fn workspace(&self) -> &ChatWorkspace {
        &self.workspace
    }
    fn workspace_mut(&mut self) -> &mut ChatWorkspace {
        &mut self.workspace
    }
    fn set_waker(&mut self, _: Arc<dyn Fn() + Send + Sync>) {}
    fn poll_console(&mut self) -> NativeConsoleObservation {
        NativeConsoleObservation {
            text: "test observation".into(),
            refresh_pending: false,
        }
    }
    fn request_refresh(&mut self) {}
    fn on_ui_exit(&mut self) {
        self.exits.set(self.exits.get() + 1);
    }
}

#[test]
fn explicit_shutdown_and_later_drop_close_only_once() {
    let exits = Rc::new(Cell::new(0));
    let mut owned = OwnedComposition::new(Box::new(Client {
        workspace: ChatWorkspace::default(),
        exits: Rc::clone(&exits),
    }));
    owned.exit();
    owned.exit();
    drop(owned);
    assert_eq!(exits.get(), 1);
}

#[test]
fn failed_adoption_or_abnormal_drop_also_closes_the_client() {
    let exits = Rc::new(Cell::new(0));
    let owned = OwnedComposition::new(Box::new(Client {
        workspace: ChatWorkspace::default(),
        exits: Rc::clone(&exits),
    }));
    drop(owned);
    assert_eq!(exits.get(), 1);
}

#[test]
fn console_bound_is_utf8_safe_explicit_and_does_not_clear_pending() {
    let observation = bounded_console(NativeConsoleObservation {
        text: "界".repeat(MAX_NATIVE_CONSOLE_BYTES),
        refresh_pending: true,
    });
    assert!(observation.text.len() <= MAX_NATIVE_CONSOLE_BYTES);
    assert!(observation.text.ends_with("Console view limit.]"));
    assert!(observation.refresh_pending);
    let exact = NativeConsoleObservation {
        text: "x".repeat(MAX_NATIVE_CONSOLE_BYTES),
        refresh_pending: false,
    };
    assert_eq!(bounded_console(exact.clone()), exact);
}

#[test]
fn default_notes_port_hides_actions_refuses_callbacks_and_retains_the_original_draft() {
    let mut client = Client {
        workspace: ChatWorkspace::default(),
        exits: Rc::new(Cell::new(0)),
    };
    client.workspace.edit("unsent original Notes draft".into());
    let room = RoomKey {
        epoch: client.workspace.presentation_epoch(),
        local_id: client.workspace.active_id(),
    };
    assert_eq!(client.notes_view(), None);
    assert!(client.request_write_note(room).is_err());
    assert!(client.request_notes_refresh(room).is_err());
    assert!(client.request_notes_cancel(room).is_err());
    assert!(
        client
            .request_notes_model_decision(
                room,
                "model-original",
                &"a".repeat(64),
                NativeNotesModelDecision::Confirm
            )
            .is_err()
    );
    assert!(
        client
            .request_notes_model_decision(
                room,
                "model-original",
                &"a".repeat(64),
                NativeNotesModelDecision::Decline
            )
            .is_err()
    );
    assert_eq!(client.workspace.draft().text, "unsent original Notes draft");
    assert_eq!(client.workspace.active_id(), room.local_id);
    assert_eq!(client.exits.get(), 0);
}
