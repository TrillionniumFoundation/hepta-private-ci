//! Actual pinned SDK full-state input through the original RoomScreen owner.
//! Firefox 155 keyboard.insertText emits a marked preview and an identical
//! unmarked commit. The SDK intentionally emits Changed only for text changes.
use super::*;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
use makepad_widgets::text_input::TextInputAction;

const FIREFOX_DRAFT: &str = "Theme round trip draft 中文🚀";

struct Fixture {
    cx: Cx,
    room: RoomScreenRef,
    input: TextInputRef,
    workspace: ChatWorkspace,
    _pass: DrawPass,
    _draw_list: DrawList2d,
}

impl Fixture {
    fn new(text: &str) -> Self {
        let mut cx = Cx::new(Box::new(|_, _| {}));
        let room = cx.with_vm(|vm| {
            makepad_widgets::script_mod(vm);
            let prototype = RoomScreen::register_widget(vm);
            let value = vm.eval(makepad_widgets::makepad_script::script! {
                use mod.prelude.widgets.*
                #(prototype) {
                    message_input := TextInput { is_multiline: true }
                }
            });
            WidgetRef::script_from_value(vm, value).as_room_screen()
        });
        let input = room
            .borrow()
            .expect("original RoomScreen")
            .view
            .text_input(&mut cx, ids!(message_input));
        input.set_text(&mut cx, text);
        let mut workspace = ChatWorkspace::default();
        assert!(workspace.edit(text.to_owned()));
        room.borrow_mut().unwrap().active_key = Some(RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        });

        // Retain an actual SDK draw area and focus. Input reaches TextInput via
        // RoomScreen::handle_event, including its later original Actions pass.
        cx.init_cx_os();
        let size = dvec2(640.0, 160.0);
        let pass = DrawPass::new(&mut cx);
        pass.set_size(&mut cx, size);
        let mut draw_list = DrawList2d::new(&mut cx);
        {
            let event = DrawEvent::default();
            let mut draw = CxDraw::new(&mut cx, &event);
            let mut cx2d = Cx2d::new(&mut draw);
            cx2d.begin_pass(&pass, None);
            draw_list.begin_always(&mut cx2d);
            cx2d.begin_root_turtle(size, Layout::flow_down());
            input
                .borrow_mut()
                .unwrap()
                .draw_all(&mut cx2d, &mut Scope::empty());
            cx2d.end_pass_sized_turtle();
            draw_list.end(&mut cx2d);
            cx2d.end_pass(&pass);
        }
        assert!(input.area().is_valid(&cx));
        cx.set_key_focus(input.area());
        cx.widget_action(input.widget_uid(), TextInputAction::KeyFocus);
        cx.handle_actions();
        assert_eq!(cx.key_focus(), input.area());
        Self {
            cx,
            room,
            input,
            workspace,
            _pass: pass,
            _draw_list: draw_list,
        }
    }

    fn full_state(&mut self, text: &str, composing: bool) -> bool {
        let end = CharOffset(text.chars().count());
        let event = Event::TextInput(TextInputEvent {
            full_state_sync: Some(FullTextState {
                text: text.to_owned(),
                selection: end..end,
                composition: composing.then_some(CharOffset(0)..end),
            }),
            ..Default::default()
        });
        let actions = self.cx.capture_actions(|cx| {
            self.room.borrow_mut().unwrap().handle_event(
                cx,
                &event,
                &mut Scope::with_data(&mut self.workspace),
            );
        });
        let changed = self.input.changed(&actions).is_some();
        self.room.borrow_mut().unwrap().handle_event(
            &mut self.cx,
            &Event::Actions(actions),
            &mut Scope::with_data(&mut self.workspace),
        );
        changed
    }
}

#[test]
fn full_state_commit_reaches_original_room_owner_without_a_changed_action() {
    let mut fixture = Fixture::new("");
    assert!(fixture.full_state(FIREFOX_DRAFT, true));
    assert!(fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft().text, "");

    // Exact two packets observed from the original bridge in Firefox 155.
    assert!(!fixture.full_state(FIREFOX_DRAFT, false));
    assert!(!fixture.input.is_composing());
    assert_eq!(fixture.input.text(), FIREFOX_DRAFT);
    assert_eq!(fixture.workspace.draft().text, FIREFOX_DRAFT);
    assert_eq!(fixture.workspace.draft().title, FIREFOX_DRAFT);

    let editor = format!("{:?}", fixture.input.save_state());
    let draft = fixture.workspace.draft().clone();
    assert!(!fixture.full_state(FIREFOX_DRAFT, false));
    assert_eq!(fixture.workspace.draft(), &draft);
    assert_eq!(format!("{:?}", fixture.input.save_state()), editor);
}

#[test]
fn full_state_unchanged_commit_rejection_restores_exact_editor_checkpoint() {
    let mut fixture = Fixture::new("retained 中文");
    let editor = format!("{:?}", fixture.input.save_state());
    let original_text = fixture.workspace.draft().text.clone();
    let oversized = "界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES);
    assert!(fixture.full_state(&oversized, true));
    assert!(fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft().text, original_text);

    assert!(!fixture.full_state(&oversized, false));
    assert!(!fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft().text, original_text);
    assert_eq!(fixture.workspace.draft().status, ComposeStatus::InputLimit);
    assert_eq!(format!("{:?}", fixture.input.save_state()), editor);
}

#[test]
fn full_state_cancel_keeps_original_committed_draft() {
    let mut fixture = Fixture::new("retained draft");
    let draft = fixture.workspace.draft().clone();
    assert!(fixture.full_state(FIREFOX_DRAFT, true));
    assert!(fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft(), &draft);
    assert!(fixture.full_state(&draft.text, false));
    assert!(!fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft(), &draft);
    assert_eq!(fixture.input.text(), draft.text);
}

#[test]
fn full_state_completion_cannot_edit_a_new_room() {
    let mut fixture = Fixture::new("previous room");
    assert!(fixture.full_state(FIREFOX_DRAFT, true));
    assert!(fixture.workspace.new_draft());
    let draft = fixture.workspace.draft().clone();
    assert!(!fixture.full_state(FIREFOX_DRAFT, false));
    assert!(!fixture.input.is_composing());
    assert_eq!(fixture.workspace.draft(), &draft);
    assert_eq!(fixture.workspace.draft().text, "");
}
