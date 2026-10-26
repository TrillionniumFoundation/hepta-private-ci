use crate::ime_router::ImeRouter;
use crate::robrix::rooms::RoomsListEntry;
use hepta_control_core::chat::ChatWorkspace;
use hepta_control_core::chat::WorkspaceTab;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
use makepad_widgets::*;
use std::cell::RefCell;
use std::rc::Rc;

#[derive(Default)]
struct Scene {
    root: WidgetRef,
    workspace: ChatWorkspace,
    router: ImeRouter,
    #[cfg(feature = "native-presentation")]
    intents: Vec<crate::native_presentation::chat_controls::ChatIntent>,
}

impl Scene {
    fn dispatch(&mut self, cx: &mut Cx, event: &Event) {
        #[cfg(feature = "native-presentation")]
        if let Event::Actions(actions) = event {
            use crate::native_presentation::chat_controls::ChatIntent;
            for action in actions {
                let intent = action.as_widget_action().cast::<ChatIntent>();
                if !matches!(intent, ChatIntent::None) {
                    self.intents.push(intent);
                }
            }
        }
        self.router
            .dispatch(cx, &self.root, event, &mut self.workspace);
    }
}

// Draw the actual original HomeScreen/PortalList/editors/buttons. Native raw
// events pass through ImeRouter and the SDK, then their original action reducers.
// No accessibility action, focus assignment or owner/effect fixture is used.
struct Surface {
    cx: Cx,
    scene: Rc<RefCell<Scene>>,
    pass: DrawPass,
    draw_list: DrawList2d,
}

impl Surface {
    fn new() -> Self {
        let scene = Rc::new(RefCell::new(Scene::default()));
        let callback = scene.clone();
        let mut cx = Cx::new(Box::new(move |cx, event| {
            callback.borrow_mut().dispatch(cx, event);
        }));
        cx.init_cx_os();
        scene.borrow_mut().root = cx.with_vm(|vm| {
            makepad_widgets::script_mod(vm);
            crate::robrix::styles::script_mod(vm);
            crate::robrix::dock::script_mod(vm);
            crate::robrix::composer::script_mod(vm);
            crate::robrix::rooms::script_mod(vm);
            crate::robrix::room::script_mod(vm);
            crate::robrix::home::script_mod(vm);
            let value = vm.eval(makepad_widgets::makepad_script::script! {
                use mod.prelude.widgets.*
                use mod.widgets.*
                HomeScreen {width: Fill height: Fill}
            });
            WidgetRef::script_from_value(vm, value)
        });
        let pass = DrawPass::new(&mut cx);
        pass.set_size(&mut cx, dvec2(1280.0, 800.0));
        let draw_list = DrawList2d::new(&mut cx);
        let mut surface = Self {
            cx,
            scene,
            pass,
            draw_list,
        };
        surface.cx.redraw_all();
        surface.draw();
        surface
    }

    fn draw(&mut self) {
        // Match the SDK's call_draw_event: consume the real queued redraws.
        // An empty event leaves Dock contents cached even after root.redraw,
        // retaining stale rendered RoomKeys and visible proposal snapshots.
        let event = std::mem::take(&mut self.cx.new_draw_event);
        let mut draw = CxDraw::new(&mut self.cx, &event);
        let mut cx2d = Cx2d::new(&mut draw);
        cx2d.begin_pass(&self.pass, None);
        self.draw_list.begin_always(&mut cx2d);
        cx2d.begin_root_turtle(dvec2(1280.0, 800.0), Layout::flow_down());
        let mut scene = self.scene.borrow_mut();
        let root = scene.root.clone();
        root.draw_all(&mut cx2d, &mut Scope::with_data(&mut scene.workspace));
        cx2d.end_pass_sized_turtle();
        self.draw_list.end(&mut cx2d);
        cx2d.end_pass(&self.pass);
    }

    fn event(&mut self, event: Event) {
        self.scene.borrow_mut().dispatch(&mut self.cx, &event);
        // The SDK's platform event pump is private. Its public action pump
        // performs the same real pending-focus transition and delivers KeyFocus.
        // The inert action is only a pump barrier, never a button or focus action.
        self.cx.action(());
        self.cx.handle_actions();
    }

    fn tab(&mut self, modifiers: KeyModifiers) {
        self.event(Event::KeyDown(KeyEvent {
            key_code: KeyCode::Tab,
            modifiers,
            ..Default::default()
        }));
    }

    fn press(&mut self, key_code: KeyCode) {
        self.event(Event::KeyDown(KeyEvent {
            key_code,
            ..Default::default()
        }));
        self.event(Event::KeyUp(KeyEvent {
            key_code,
            ..Default::default()
        }));
        self.draw();
    }

    fn widget(&self, path: &[LiveId]) -> WidgetRef {
        self.scene.borrow().root.widget(&self.cx, path)
    }

    fn seek(&mut self, target: &WidgetRef) {
        for _ in 0..48 {
            if target.key_focus(&self.cx) {
                return;
            }
            self.tab(KeyModifiers::default());
        }
        panic!(
            "native Tab did not reach original widget {:?}",
            target.widget_uid()
        );
    }

    fn row(&mut self, index: usize) -> WidgetRef {
        let sidebar = self.widget(ids!(rooms_sidebar));
        let row = sidebar
            .portal_list(&self.cx, ids!(list))
            .item(&mut self.cx, index, id!(Room));
        assert!(row.area().is_valid(&self.cx));
        assert!(
            row.borrow::<RoomsListEntry>()
                .unwrap()
                .rendered_room()
                .is_some()
        );
        row
    }
}

#[test]
fn native_tab_enters_original_home_cycles_both_directions_and_skips_disabled_send() {
    let mut surface = Surface::new();
    assert_eq!(surface.cx.key_focus(), Area::Empty);
    let expected = [
        surface.widget(ids!(rail_chat)),
        surface.widget(ids!(rail_console)),
        surface.widget(ids!(room_filter)),
        surface.widget(ids!(new_draft)),
        surface.row(0),
        surface.widget(ids!(theme_switch)),
        surface.widget(ids!(message_input)),
    ];
    for target in expected.iter().chain(expected.first()) {
        surface.tab(KeyModifiers::default());
        assert!(target.area().is_valid(&surface.cx));
        assert_eq!(surface.cx.key_focus(), target.area());
    }
    for target in expected[1..].iter().rev().chain(expected.first()) {
        surface.tab(KeyModifiers {
            shift: true,
            ..Default::default()
        });
        assert_eq!(surface.cx.key_focus(), target.area());
    }
    assert!(
        !surface
            .widget(ids!(send_message_button))
            .as_button()
            .borrow()
            .unwrap()
            .enabled()
    );
    assert_eq!(surface.scene.borrow().workspace.drafts().count(), 1);
    assert_eq!(surface.scene.borrow().workspace.draft().text, "");
}

#[test]
fn reverse_entry_hidden_disabled_and_undrawn_widgets_use_real_focus_eligibility() {
    let mut surface = Surface::new();
    let editor = surface.widget(ids!(message_input));
    surface.tab(KeyModifiers {
        shift: true,
        ..Default::default()
    });
    assert!(editor.key_focus(&surface.cx));
    let chat = surface.widget(ids!(rail_chat));
    chat.as_button().set_enabled(&mut surface.cx, false);
    let console = surface.widget(ids!(rail_console));
    console.as_button().set_visible(&mut surface.cx, false);
    surface.tab(KeyModifiers::default());
    assert!(surface.widget(ids!(room_filter)).key_focus(&surface.cx));
    let undrawn = surface.cx.with_vm(|vm| {
        let value = vm.eval(makepad_widgets::makepad_script::script! {
            use mod.prelude.widgets.*
            Button {text: "not drawn"}
        });
        WidgetRef::script_from_value(vm, value)
    });
    assert!(!undrawn.area().is_valid(&surface.cx));
    let before = surface.cx.key_focus();
    assert!(super::handle_tab(
        &mut surface.cx,
        &undrawn,
        &Event::KeyDown(KeyEvent {
            key_code: KeyCode::Tab,
            ..Default::default()
        })
    ));
    surface.cx.action(());
    surface.cx.handle_actions();
    assert_eq!(surface.cx.key_focus(), before);
}

#[test]
fn native_space_and_return_reuse_original_room_and_page_actions_and_retain_drafts() {
    let mut surface = Surface::new();
    let first_id = surface.scene.borrow().workspace.active_id();
    let editor = surface.widget(ids!(message_input));
    surface.seek(&editor);
    surface.event(Event::TextInput(TextInputEvent {
        input: "first room".into(),
        ..Default::default()
    }));
    surface.draw();
    assert_eq!(surface.scene.borrow().workspace.draft().text, "first room");
    let new_draft = surface.widget(ids!(new_draft));
    surface.seek(&new_draft);
    surface.press(KeyCode::Space);
    assert_eq!(surface.scene.borrow().workspace.drafts().count(), 2);
    assert_eq!(surface.scene.borrow().workspace.draft().text, "");
    assert_eq!(editor.text(), "");
    surface.seek(&editor);
    surface.event(Event::TextInput(TextInputEvent {
        input: "second room".into(),
        ..Default::default()
    }));
    surface.draw();
    assert_eq!(surface.scene.borrow().workspace.draft().text, "second room");
    let first_row = (0..2)
        .map(|index| surface.row(index))
        .find(|row| {
            row.borrow::<RoomsListEntry>()
                .unwrap()
                .rendered_room()
                .unwrap()
                .local_id
                == first_id
        })
        .unwrap();
    surface.seek(&first_row);
    surface.press(KeyCode::ReturnKey);
    assert_eq!(surface.scene.borrow().workspace.active_id(), first_id);
    assert_eq!(surface.scene.borrow().workspace.draft().text, "first room");
    assert_eq!(
        surface
            .scene
            .borrow()
            .workspace
            .drafts()
            .map(|(_, draft)| draft.text.clone())
            .collect::<Vec<_>>(),
        ["first room", "second room"]
    );
    let console = surface.widget(ids!(rail_console));
    surface.seek(&console);
    surface.press(KeyCode::ReturnKey);
    assert_eq!(surface.scene.borrow().workspace.tab, WorkspaceTab::Console);
    let chat = surface.widget(ids!(rail_chat));
    for _ in 0..8 {
        surface.tab(KeyModifiers::default());
        assert!(
            !editor.key_focus(&surface.cx),
            "inactive cached editor entered Tab cycle"
        );
    }
    surface.seek(&chat);
    surface.press(KeyCode::Space);
    assert_eq!(
        surface.scene.borrow().workspace.tab,
        WorkspaceTab::Conversations
    );
    assert_eq!(surface.scene.borrow().workspace.draft().text, "first room");
}

#[test]
fn original_ime_preedit_and_modified_tab_do_not_move_focus_or_change_the_draft() {
    let mut surface = Surface::new();
    let editor = surface.widget(ids!(message_input));
    surface.seek(&editor);
    for modifiers in [
        KeyModifiers {
            control: true,
            ..Default::default()
        },
        KeyModifiers {
            alt: true,
            ..Default::default()
        },
        KeyModifiers {
            logo: true,
            ..Default::default()
        },
    ] {
        surface.tab(modifiers);
        assert!(editor.key_focus(&surface.cx));
    }
    surface.event(Event::TextInput(TextInputEvent {
        input: "你好".into(),
        replace_last: true,
        ..Default::default()
    }));
    assert!(editor.as_text_input().is_composing());
    let state = format!("{:?}", editor.as_text_input().save_state());
    for modifiers in [
        KeyModifiers::default(),
        KeyModifiers {
            shift: true,
            ..Default::default()
        },
    ] {
        surface.tab(modifiers);
        assert!(editor.key_focus(&surface.cx));
        assert_eq!(format!("{:?}", editor.as_text_input().save_state()), state);
        assert_eq!(surface.scene.borrow().workspace.draft().text, "");
    }
    surface.event(Event::TextInput(TextInputEvent {
        replace_last: true,
        ..Default::default()
    }));
    assert!(!editor.as_text_input().is_composing());
    surface.tab(KeyModifiers::default());
    assert!(surface.widget(ids!(rail_chat)).key_focus(&surface.cx));
}

#[cfg(feature = "native-presentation")]
#[test]
fn native_model_confirm_rechecks_the_original_last_drawn_proposal_on_key_release() {
    use crate::native_presentation::NativeNotesModelDecision;
    use crate::native_presentation::NativeNotesModelProposalView;
    use crate::native_presentation::NativeNotesView;
    use crate::native_presentation::chat_controls::ChatIntent;
    use crate::native_presentation::chat_controls::Controls;
    use crate::presentation::RoomKey;
    use hepta_control_core::chat_timeline::History;
    use hepta_control_core::chat_timeline::ViewFence;
    let mut surface = Surface::new();
    let room = {
        let mut scene = surface.scene.borrow_mut();
        let workspace = &mut scene.workspace;
        let id = workspace.active_id();
        let ticket = workspace
            .begin_history(
                id,
                "original-thread",
                ViewFence {
                    owner_session: "fixture-owner".into(),
                    generation: 1,
                },
            )
            .unwrap();
        workspace
            .receive_history(
                &ticket,
                History {
                    thread_id: "original-thread".into(),
                    title: "Original".into(),
                    revision: 1,
                    event_sequence: 0,
                    messages: vec![],
                },
            )
            .unwrap();
        RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: id,
        }
    };
    *surface.cx.global::<Controls>() = Controls {
        room: Some(room),
        notes: Some(NativeNotesView {
            model_proposal: Some(NativeNotesModelProposalView {
                proposal_id: "model-first".into(),
                proposal_sha256: "a".repeat(64),
                thread_id: "original-thread".into(),
                details: "Reviewed first text".into(),
                can_confirm: true,
                can_decline: true,
            }),
            ..NativeNotesView::default()
        }),
        ..Controls::default()
    };
    // The real native renderer redraws after installing changed Controls.
    surface.scene.borrow().root.redraw(&mut surface.cx);
    surface.draw();
    let confirm = surface.widget(ids!(original_notes_model_confirm));
    surface.seek(&confirm);
    surface.event(Event::KeyDown(KeyEvent {
        key_code: KeyCode::ReturnKey,
        ..Default::default()
    }));
    let proposal = surface
        .cx
        .global::<Controls>()
        .notes
        .as_mut()
        .unwrap()
        .model_proposal
        .as_mut()
        .unwrap();
    proposal.proposal_id = "model-next".into();
    proposal.proposal_sha256 = "b".repeat(64);
    proposal.details = "Undrawn replacement text".into();
    surface.event(Event::KeyUp(KeyEvent {
        key_code: KeyCode::ReturnKey,
        ..Default::default()
    }));
    assert!(
        surface.scene.borrow().intents.is_empty(),
        "stale visible proposal authorized a keyboard decision"
    );
    // Only now present the replacement; the stale press above saw no redraw.
    surface.scene.borrow().root.redraw(&mut surface.cx);
    surface.draw();
    surface.seek(&confirm);
    surface.press(KeyCode::Space);
    let mut scene = surface.scene.borrow_mut();
    assert_eq!(scene.intents.len(), 1);
    let ChatIntent::NotesModelDecision(actual_room, id, digest, decision) =
        scene.intents.pop().unwrap()
    else {
        panic!("expected the original model decision intent");
    };
    assert_eq!(
        (actual_room, id, digest, decision),
        (
            room,
            "model-next".into(),
            "b".repeat(64),
            NativeNotesModelDecision::Confirm
        )
    );
    assert_eq!(scene.workspace.draft().text, "");
    drop(scene);
    surface.event(Event::KeyDown(KeyEvent {
        key_code: KeyCode::ReturnKey,
        ..Default::default()
    }));
    assert!(surface.scene.borrow_mut().workspace.new_draft());
    surface.event(Event::KeyUp(KeyEvent {
        key_code: KeyCode::ReturnKey,
        ..Default::default()
    }));
    assert!(
        surface.scene.borrow().intents.is_empty(),
        "old RoomKey authorized a keyboard decision after room change"
    );
}
