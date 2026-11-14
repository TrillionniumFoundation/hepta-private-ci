use super::*;
use makepad_widgets::text::selection::Cursor;

fn field(cx: &mut Cx) -> WidgetRef {
    cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = vm.eval(makepad_widgets::makepad_script::script! {
            use mod.prelude.widgets.*
            TextInput {}
        });
        WidgetRef::script_from_value(vm, value)
    })
}

fn selection(anchor: usize, cursor: usize) -> Selection {
    Selection {
        anchor: Cursor { index: anchor, prefer_next_row: false },
        cursor: Cursor { index: cursor, prefer_next_row: true },
    }
}

#[test]
fn cached_renderers_and_room_return_preserve_unicode_selection() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let desktop = field(&mut cx);
    let compact = field(&mut cx);
    let mut workspace = ChatWorkspace::default();
    workspace.edit("a中文🚀z".into());
    activate(&mut cx, desktop.widget_uid(), desktop.as_text_input(), &workspace);
    let expected = selection(7, 1);
    desktop.as_text_input().set_selection(&mut cx, expected);
    activate(&mut cx, compact.widget_uid(), compact.as_text_input(), &workspace);
    assert_eq!(compact.as_text_input().text(), "a中文🚀z");
    assert_eq!((compact.as_text_input().selection().anchor, compact.as_text_input().selection().cursor), (expected.anchor, expected.cursor));
    workspace.new_draft();
    workspace.edit("second".into());
    activate(&mut cx, compact.widget_uid(), compact.as_text_input(), &workspace);
    compact.as_text_input().set_selection(&mut cx, selection(2, 4));
    workspace.select(0);
    activate(&mut cx, compact.widget_uid(), compact.as_text_input(), &workspace);
    assert_eq!((compact.as_text_input().selection().anchor, compact.as_text_input().selection().cursor), (expected.anchor, expected.cursor));
    activate(&mut cx, desktop.widget_uid(), desktop.as_text_input(), &workspace);
    assert_eq!((desktop.as_text_input().selection().anchor, desktop.as_text_input().selection().cursor), (expected.anchor, expected.cursor));
}

#[test]
fn changed_text_does_not_restore_a_previous_revision_selection() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let input = field(&mut cx);
    let mut workspace = ChatWorkspace::default();
    workspace.edit("private old text".into());
    activate(&mut cx, input.widget_uid(), input.as_text_input(), &workspace);
    input.as_text_input().set_selection(&mut cx, selection(0, 7));
    workspace.new_draft();
    activate(&mut cx, input.widget_uid(), input.as_text_input(), &workspace);
    workspace.select(0);
    workspace.edit("new".into());
    activate(&mut cx, input.widget_uid(), input.as_text_input(), &workspace);
    assert_eq!(input.as_text_input().text(), "new");
    assert!(input.as_text_input().selected_text().is_empty());
}

#[test]
fn revocation_clears_cached_field_and_editor_memory_before_events() {
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let root = field(&mut cx);
    let mut workspace = ChatWorkspace::default();
    clear_changed_epoch(&mut cx, &root, &mut workspace);
    workspace.edit("private".into());
    activate(&mut cx, root.widget_uid(), root.as_text_input(), &workspace);
    workspace.disconnect_owner();
    clear_changed_epoch(&mut cx, &root, &mut workspace);
    assert_eq!(root.as_text_input().text(), "");
    assert!(cx.global::<EditorInputs>().active.is_none());
    assert!(!workspace.composing);
}
