use super::*;
use crate::ime_router::ImeRouter;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
#[cfg(feature = "native-ime-sdk")]
use makepad_widgets::makepad_draw::text::selection::Cursor;
#[cfg(feature = "native-ime-sdk")]
use makepad_widgets::makepad_draw::text::selection::Selection;
#[cfg(not(feature = "native-ime-sdk"))]
use makepad_widgets::makepad_platform::event::CharOffset;
#[cfg(not(feature = "native-ime-sdk"))]
use makepad_widgets::makepad_platform::event::FullTextState;
use makepad_widgets::text_input::TextInputAction;
use std::ops::Range;

// Keep the five historical regression IDs in both profiles. Packet encoding is
// profile-specific; owner text, state, checkpoint and focus assertions are shared.
enum ImePhase<'a> {
    Preview(Range<usize>),
    Commit(&'a str),
    Cancel,
    RepeatCommit,
}

fn committed_change(text: &str) -> Option<String> {
    // Native commits emit Changed alongside the typed outcome even when the
    // visible preview already equals the commit. Legacy full-state sync may not.
    cfg!(feature = "native-ime-sdk").then(|| text.to_owned())
}

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
    #[cfg(feature = "native-ime-sdk")]
    last_delivery: Option<Event>,
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
        let input = root.text_input(&cx, ids!(message_input));
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
            #[cfg(feature = "native-ime-sdk")]
            last_delivery: None,
        };
        surface.draw();
        assert!(surface.input.area().is_valid(&surface.cx));
        surface.cx.set_key_focus(surface.input.area());
        surface
            .cx
            .widget_action(surface.input.widget_uid(), TextInputAction::KeyFocus);
        surface.cx.handle_actions();
        assert_eq!(surface.cx.key_focus(), surface.input.area());
        #[cfg(feature = "native-ime-sdk")]
        surface.select_native(text.len()..text.len());
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

    fn ime(&mut self, text: &str, phase: ImePhase<'_>) -> Option<String> {
        #[cfg(not(feature = "native-ime-sdk"))]
        let event = {
            let composition = match phase {
                ImePhase::Preview(range) => Some(range),
                ImePhase::Commit(_native_input) => None,
                ImePhase::Cancel | ImePhase::RepeatCommit => None,
            };
            let cursor = CharOffset(text.chars().count());
            Event::TextInput(TextInputEvent {
                full_state_sync: Some(FullTextState {
                    text: text.to_owned(),
                    selection: cursor..cursor,
                    composition: composition
                        .map(|range| CharOffset(range.start)..CharOffset(range.end)),
                }),
                ..Default::default()
            })
        };
        #[cfg(feature = "native-ime-sdk")]
        let event = match phase {
            ImePhase::Preview(range) => Event::TextInput(TextInputEvent {
                input: text.chars().skip(range.start).take(range.len()).collect(),
                replace_last: true,
                ..Default::default()
            }),
            ImePhase::Commit(input) => Event::TextInput(TextInputEvent {
                input: input.to_owned(),
                ..Default::default()
            }),
            ImePhase::Cancel => Event::TextInput(TextInputEvent {
                replace_last: true,
                ..Default::default()
            }),
            // Deliver the exact retained SDK action batch again. Sending another
            // raw TextInput would be another edit, not a replay of this outcome.
            ImePhase::RepeatCommit => self
                .last_delivery
                .take()
                .expect("a real SDK commit action batch was delivered"),
        };
        let actions = self.cx.capture_actions(|cx| {
            self.router
                .dispatch(cx, &self.root, &event, &mut self.workspace);
        });
        let changed = self.input.changed(&actions);
        let delivery = Event::Actions(actions);
        self.router
            .dispatch(&mut self.cx, &self.root, &delivery, &mut self.workspace);
        #[cfg(feature = "native-ime-sdk")]
        {
            self.last_delivery = Some(delivery);
        }
        changed
    }

    #[cfg(feature = "native-ime-sdk")]
    fn select_native(&mut self, range: Range<usize>) {
        self.input.set_selection(
            &mut self.cx,
            Selection {
                anchor: Cursor {
                    index: range.start,
                    prefer_next_row: false,
                },
                cursor: Cursor {
                    index: range.end,
                    prefer_next_row: false,
                },
            },
        );
    }
}

#[test]
fn same_text_full_state_commit_publishes_the_owner_before_redraw() {
    let mut surface = Surface::new("base ");
    let committed = surface.workspace.draft().clone();
    let expected = "base 中文🚀";
    assert_eq!(
        surface.ime(expected, ImePhase::Preview(5..8)),
        Some(expected.to_owned())
    );
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), expected);

    // Both profiles publish the real final commit before redraw, including
    // the legacy path where unchanged full-state text emits no Changed action.
    assert_eq!(
        surface.ime(expected, ImePhase::Commit("中文🚀")),
        committed_change(expected)
    );
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
        surface.ime(expected, ImePhase::Preview(start..start + 2));
        assert_eq!(surface.workspace.draft(), &committed);
        assert!(surface.input.is_composing());
        assert_eq!(
            surface.ime(expected, ImePhase::Commit("你🚀")),
            committed_change(expected)
        );
        assert_eq!(surface.workspace.draft().text, expected);
        let accepted = surface.workspace.draft().clone();
        assert_eq!(surface.ime(expected, ImePhase::RepeatCommit), None);
        assert_eq!(surface.workspace.draft(), &accepted);
        surface.draw();
        assert_eq!(surface.input.text(), expected);
    }
}

#[test]
fn full_state_cancel_keeps_the_previously_committed_draft() {
    let mut surface = Surface::new("retained draft");
    let committed = surface.workspace.draft().clone();
    surface.ime("retained draft你好", ImePhase::Preview(14..16));
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.ime("retained draft", ImePhase::Cancel);
    assert!(!surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), committed.text);
}

#[test]
fn rejected_full_state_commit_restores_the_original_sdk_checkpoint() {
    let mut surface = Surface::new("保留😀");
    let committed = surface.workspace.draft().clone();
    // Native desktop replacement uses the current SDK selection. Capture the
    // exact rollback checkpoint after that real selection is established.
    #[cfg(feature = "native-ime-sdk")]
    surface.select_native(0..surface.input.text().len());
    let checkpoint = format!("{:?}", surface.input.save_state());
    let oversized = "界".repeat(hepta_control_core::chat::MAX_DRAFT_BYTES);
    surface.ime(&oversized, ImePhase::Preview(0..oversized.chars().count()));
    assert!(surface.input.is_composing());
    assert_eq!(surface.workspace.draft(), &committed);
    assert_eq!(
        surface.ime(&oversized, ImePhase::Commit(&oversized)),
        committed_change(&oversized)
    );
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
    surface.ime("owner draft旧", ImePhase::Preview(11..12));
    assert!(surface.input.is_composing());
    surface.cx.set_key_focus(Area::Empty);
    surface
        .cx
        .widget_action(surface.input.widget_uid(), TextInputAction::KeyFocusLost);
    surface.cx.handle_actions();
    assert_eq!(surface.cx.key_focus(), Area::Empty);
    surface.ime("owner draft旧", ImePhase::Commit("旧"));
    assert_eq!(surface.workspace.draft(), &committed);
    surface.draw();
    assert_eq!(surface.input.text(), committed.text);
}
