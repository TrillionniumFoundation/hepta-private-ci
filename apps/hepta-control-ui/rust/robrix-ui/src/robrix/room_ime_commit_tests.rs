use super::*;
use crate::ime_router::ImeRouter;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
use makepad_widgets::makepad_platform::event::CharOffset;
use makepad_widgets::makepad_platform::event::FullTextState;
use makepad_widgets::text_input::TextInputAction;
use std::ops::Range;

// Exercise the production RoomScreen, router, SDK hit/focus checks, action
// delivery and redraw. No mock editor or manually published Changed action.
struct Surface {
    cx: Cx,
    root: WidgetRef,
    input: TextInputRef,
    workspace: ChatWorkspace,
    router: ImeRouter,
    pass: DrawPass,
    draw_list: DrawList2d,
}

impl Surface {
    fn new(text: &str) -> Self {
        let mut cx = Cx::new(Box::new(|_, _| {}));
        cx.init_cx_os();
        let root = cx.with_vm(|vm| {
            <crate::app::App as AppMain>::script_mod(vm);
            let value = vm.eval(makepad_widgets::makepad_script::script! {
                use mod.prelude.widgets.*
                use mod.widgets.*
                RoomScreen {}
            });
            WidgetRef::script_from_value(vm, value)
        });
        let input = root.text_input(&mut cx, ids!(message_input));
        assert!(!input.is_empty());
        let mut workspace = ChatWorkspace::default();
        assert!(workspace.edit(text.to_owned()));
        let pass = DrawPass::new(&mut cx);
        pass.set_size(&mut cx, dvec2(640.0, 800.0));
        let draw_list = DrawList2d::new(&mut cx);
        let mut surface = Self {
            cx,
            root,
            input,
            workspace,
            router: ImeRouter::default(),
            pass,
            draw_list,
        };
        surface.draw();
        assert!(surface.input.area().is_valid(&surface.cx));
        surface.cx.set_key_focus(surface.input.area());
        surface
            .cx
            .widget_action(surface.input.widget_uid(), TextInputAction::KeyFocus);
        surface.cx.handle_actions();
        assert_eq!(surface.cx.key_focus(), surface.input.area());
        surface
    }

    fn draw(&mut self) {
        let event = DrawEvent::default();
        let mut draw = CxDraw::new(&mut self.cx, &event);
        let mut cx = Cx2d::new(&mut draw);
        cx.begin_pass(&self.pass, None);
        self.draw_list.begin_always(&mut cx);
        cx.begin_root_turtle(dvec2(640.0, 800.0), Layout::flow_down());
        self.root
            .draw_all(&mut cx, &mut Scope::with_data(&mut self.workspace));
        cx.end_pass_sized_turtle();
        self.draw_list.end(&mut cx);
        cx.end_pass(&self.pass);
    }

    fn full_state(&mut self, text: &str, composition: Option<Range<usize>>) -> Option<String> {
        let cursor = CharOffset(text.chars().count());
        let event = Event::TextInput(TextInputEvent {
            full_state_sync: Some(FullTextState {
                text: text.to_owned(),
                selection: cursor..cursor,
                composition: composition
                    .map(|range| CharOffset(range.start)..CharOffset(range.end)),
            }),
            ..Default::default()
        });
        let actions = self.cx.capture_actions(|cx| {
            self.router
                .dispatch(cx, &self.root, &event, &mut self.workspace);
        });
        let changed = self.input.changed(&actions);
        self.router.dispatch(
            &mut self.cx,
            &self.root,
            &Event::Actions(actions),
            &mut self.workspace,
        );
        changed
    }
}

#[test]
fn same_text_full_state_commit_publishes_the_owner_before_redraw() {
    let mut surface = Surface::new("base ");
    let committed = surface.workspace.draft().clone();
    let expected = "base 中文🚀";
    assert_eq!(
        surface.full_state(expected, Some(5..8)),
        Some(expected.to_owned())
    );
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), expected);

    // The pinned SDK emits Changed only for text changes. Ending composition
    // with identical text must still reach the owner through the real event.
    assert_eq!(surface.full_state(expected, None), None);
    assert!(!surface.input.is_composing());
    assert_eq!(surface.workspace.draft().text, expected);
    surface.draw();
    assert_eq!(surface.input.text(), expected);
    assert_eq!(surface.workspace.draft().title, expected);
}

#[test]
fn repeated_commits_and_duplicate_final_packets_preserve_exact_text() {
    let mut surface = Surface::new("");
    for (expected, start) in [("你🚀", 0), ("你🚀你🚀", 2)] {
        let committed = surface.workspace.draft().clone();
        surface.full_state(expected, Some(start..start + 2));
        assert_eq!(surface.workspace.draft(), &committed);
        assert!(surface.input.is_composing());
        assert_eq!(surface.full_state(expected, None), None);
        assert_eq!(surface.workspace.draft().text, expected);
        let accepted = surface.workspace.draft().clone();
        assert_eq!(surface.full_state(expected, None), None);
        assert_eq!(surface.workspace.draft(), &accepted);
        surface.draw();
        assert_eq!(surface.input.text(), expected);
    }
}

#[test]
fn full_state_cancel_keeps_the_previously_committed_draft() {
    let mut surface = Surface::new("retained draft");
    let committed = surface.workspace.draft().clone();
    surface.full_state("retained draft你好", Some(14..16));
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.full_state("retained draft", None);
    assert!(!surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), committed.text);
}

#[test]
fn rejected_full_state_commit_restores_the_original_sdk_checkpoint() {
    let mut surface = Surface::new("保留😀");
    let committed = surface.workspace.draft().clone();
    let checkpoint = format!("{:?}", surface.input.save_state());
    let oversized = "界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES);
    surface.full_state(&oversized, Some(0..oversized.chars().count()));
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    assert_eq!(surface.full_state(&oversized, None), None);
    assert!(!surface.input.is_composing());
    assert_eq!(surface.workspace.draft().text, committed.text);
    assert_eq!(surface.workspace.draft().title, committed.title);
    assert_eq!(surface.workspace.draft().status, ComposeStatus::InputLimit);
    assert_eq!(format!("{:?}", surface.input.save_state()), checkpoint);
    surface.draw();
    assert_eq!(surface.input.text(), committed.text);
}

#[test]
fn a_late_full_state_commit_cannot_publish_after_focus_retirement() {
    let mut surface = Surface::new("owner draft");
    let committed = surface.workspace.draft().clone();
    surface.full_state("owner draft旧", Some(11..12));
    assert!(surface.input.is_composing());
    surface.cx.set_key_focus(Area::Empty);
    surface
        .cx
        .widget_action(surface.input.widget_uid(), TextInputAction::KeyFocusLost);
    surface.cx.handle_actions();
    assert_eq!(surface.cx.key_focus(), Area::Empty);
    surface.full_state("owner draft旧", None);
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), committed.text);
}
