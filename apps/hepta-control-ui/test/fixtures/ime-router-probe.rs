extern crate hepta_control_core;
extern crate makepad_widgets;
#[path = "../../rust/robrix-ui/src/ime_pointer_gate.rs"]
mod ime_pointer_gate;
#[path = "../../rust/robrix-ui/src/ime_router.rs"]
mod ime_router;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::makepad_draw::cx_draw::CxDraw;
use makepad_widgets::*;
use std::cell::Cell;
use std::sync::atomic::{AtomicU32, Ordering};
static STAGE: AtomicU32 = AtomicU32::new(0);
#[unsafe(no_mangle)]
pub extern "C" fn stage() -> u32 {
    STAGE.load(Ordering::SeqCst)
}
fn setup() -> (Cx, WidgetRef, ChatWorkspace, ime_router::ImeRouter) {
    std::panic::set_hook(Box::new(|info| {
        STAGE.store(
            info.location().map_or(9000, |l| 10000 + l.line()),
            Ordering::SeqCst,
        );
    }));
    let mut cx = Cx::new(Box::new(|_, _| {}));
    let root = cx.with_vm(|vm| {
        makepad_widgets::script_mod(vm);
        let value = vm.eval(
            script! {use mod.prelude.widgets.* TextInput {width: 180 height: 40 empty_text: ""}},
        );
        WidgetRef::script_from_value(vm, value)
    });
    let pass = DrawPass::new(&mut cx);
    pass.set_size(&mut cx, dvec2(300.0, 100.0));
    let mut list = DrawList2d::new(&mut cx);
    let event = DrawEvent::default();
    {
        let mut draw = CxDraw::new(&mut cx, &event);
        let mut cx2d = Cx2d::new(&mut draw);
        cx2d.begin_pass(&pass, None);
        list.begin_always(&mut cx2d);
        cx2d.begin_root_turtle(dvec2(300.0, 100.0), Layout::flow_overlay());
        root.draw_all(&mut cx2d, &mut Scope::empty());
        cx2d.end_pass_sized_turtle();
        list.end(&mut cx2d);
        cx2d.end_pass(&pass);
    }
    assert!(root.area().is_valid(&cx));
    cx.set_key_focus(root.area());
    cx.action(0u32);
    cx.handle_actions();
    assert_eq!(cx.key_focus(), root.area());
    root.handle_event(
        &mut cx,
        &Event::TextInput(TextInputEvent {
            input: "中".into(),
            replace_last: true,
            composition: Some(0..1),
            ..Default::default()
        }),
        &mut Scope::empty(),
    );
    assert!(root.as_text_input().is_composing());
    let mut workspace = ChatWorkspace::default();
    let mut router = ime_router::ImeRouter::default();
    router.synchronize(&mut cx, &root, &mut workspace);
    assert!(workspace.composing);
    (cx, root, workspace, router)
}
fn key(code: KeyCode) -> Event {
    Event::KeyDown(KeyEvent {
        key_code: code,
        ..Default::default()
    })
}
#[unsafe(no_mangle)]
pub extern "C" fn check_keys() -> u32 {
    STAGE.store(1, Ordering::SeqCst);
    for code in [
        KeyCode::ArrowLeft,
        KeyCode::ArrowRight,
        KeyCode::ArrowUp,
        KeyCode::ArrowDown,
        KeyCode::Home,
        KeyCode::End,
        KeyCode::PageUp,
        KeyCode::PageDown,
        KeyCode::Backspace,
        KeyCode::Delete,
        KeyCode::Tab,
        KeyCode::ReturnKey,
        KeyCode::Escape,
    ] {
        let (mut cx, root, mut workspace, mut router) = setup();
        router.dispatch(&mut cx, &root, &key(code), &mut workspace);
        assert!(root.as_text_input().is_composing());
        assert!(workspace.composing);
        assert_eq!(root.text(), "中");
    }
    STAGE.store(2, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    router.dispatch(
        &mut cx,
        &root,
        &Event::TextInput(TextInputEvent {
            input: "中文".into(),
            replace_last: false,
            composition: None,
            ..Default::default()
        }),
        &mut workspace,
    );
    assert!(!workspace.composing);
    assert_eq!(root.text(), "中文");
    router.dispatch(&mut cx, &root, &key(KeyCode::ArrowLeft), &mut workspace);
    assert_eq!(root.as_text_input().selection().cursor.index, 3);
    14
}
#[unsafe(no_mangle)]
pub extern "C" fn check_negative_control() -> u32 {
    STAGE.store(3, Ordering::SeqCst);
    let (mut cx, root, _, _) = setup();
    root.handle_event(&mut cx, &key(KeyCode::ArrowLeft), &mut Scope::empty());
    assert!(!root.as_text_input().is_composing());
    1
}
#[unsafe(no_mangle)]
pub extern "C" fn check_mouse() -> u32 {
    STAGE.store(4, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    let down = Event::MouseDown(MouseDownEvent {
        abs: dvec2(260.0, 90.0),
        button: MouseButton::PRIMARY,
        window_id: WindowId(0, 0),
        modifiers: Default::default(),
        handled: Cell::new(Area::Empty),
        time: 1.0,
    });
    router.dispatch(&mut cx, &root, &down, &mut workspace);
    let up = Event::MouseUp(MouseUpEvent {
        abs: dvec2(260.0, 90.0),
        button: MouseButton::PRIMARY,
        window_id: WindowId(0, 0),
        modifiers: Default::default(),
        time: 1.1,
    });
    router.dispatch(&mut cx, &root, &up, &mut workspace);
    assert!(root.as_text_input().is_composing());
    assert!(workspace.composing);
    STAGE.store(5, Ordering::SeqCst);
    root.handle_event(&mut cx, &up, &mut Scope::empty());
    assert!(!root.as_text_input().is_composing());
    2
}
#[unsafe(no_mangle)]
pub extern "C" fn check_scope_and_resize() -> u32 {
    STAGE.store(6, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    cx.global::<ime_router::CompositionLayout>().variant = Some(live_id!(Desktop));
    assert_eq!(
        ime_router::adaptive_variant(&mut cx, &dvec2(640.0, 800.0)),
        live_id!(Desktop)
    );
    workspace.disconnect_owner();
    router.synchronize(&mut cx, &root, &mut workspace);
    assert!(!workspace.composing);
    assert_eq!(root.text(), "");
    assert_eq!(
        ime_router::adaptive_variant(&mut cx, &dvec2(640.0, 800.0)),
        live_id!(Mobile)
    );
    2
}

#[unsafe(no_mangle)]
pub extern "C" fn check_detached_and_focus_lost() -> u32 {
    STAGE.store(7, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    router.synchronize(&mut cx, &WidgetRef::empty(), &mut workspace);
    assert!(!workspace.composing);
    assert!(!root.as_text_input().is_composing());
    assert_eq!(root.text(), "中");
    STAGE.store(8, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    cx.set_key_focus(Area::Empty);
    cx.action(0u32);
    cx.handle_actions();
    assert!(root.as_text_input().is_composing());
    router.synchronize(&mut cx, &root, &mut workspace);
    assert!(!workspace.composing);
    assert!(!root.as_text_input().is_composing());
    assert_eq!(root.text(), "中");
    2
}
#[unsafe(no_mangle)]
pub extern "C" fn check_edit_shortcuts_and_clipboard() -> u32 {
    STAGE.store(9, Ordering::SeqCst);
    for code in [KeyCode::KeyA, KeyCode::KeyZ] {
        let (mut cx, root, mut workspace, mut router) = setup();
        let event = Event::KeyDown(KeyEvent {
            key_code: code,
            modifiers: KeyModifiers {
                control: true,
                ..Default::default()
            },
            ..Default::default()
        });
        let actions = cx.capture_actions(|cx| router.dispatch(cx, &root, &event, &mut workspace));
        assert!(root.as_text_input().is_composing());
        assert_eq!(root.text(), "中");
        assert!(root.as_text_input().key_down_unhandled(&actions).is_none());
    }
    STAGE.store(10, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    let event = Event::KeyDown(KeyEvent {
        key_code: KeyCode::KeyC,
        modifiers: KeyModifiers {
            control: true,
            ..Default::default()
        },
        ..Default::default()
    });
    let actions = cx.capture_actions(|cx| router.dispatch(cx, &root, &event, &mut workspace));
    assert_eq!(
        root.as_text_input()
            .key_down_unhandled(&actions)
            .unwrap()
            .key_code,
        KeyCode::KeyC
    );
    let response = std::rc::Rc::new(std::cell::RefCell::new(None));
    router.dispatch(
        &mut cx,
        &root,
        &Event::TextCopy(TextClipboardEvent {
            response: response.clone(),
        }),
        &mut workspace,
    );
    assert!(response.borrow().is_some());
    assert!(root.as_text_input().is_composing());
    *response.borrow_mut() = None;
    router.dispatch(
        &mut cx,
        &root,
        &Event::TextCut(TextClipboardEvent {
            response: response.clone(),
        }),
        &mut workspace,
    );
    assert!(response.borrow().is_none());
    assert!(root.as_text_input().is_composing());
    5
}

fn mixed_touch(area: Area, cx: &Cx) -> Event {
    use makepad_widgets::makepad_platform::event::finger::{
        TouchPoint, TouchState, TouchUpdateEvent,
    };
    let rect = area.rect(cx);
    let point = |uid, abs| TouchPoint {
        state: TouchState::Start,
        abs,
        time: 1.0,
        uid,
        rotation_angle: 0.0,
        force: 1.0,
        radius: dvec2(0.0, 0.0),
        handled: Cell::new(Area::Empty),
        sweep_lock: Cell::new(Area::Empty),
    };
    Event::TouchUpdate(TouchUpdateEvent {
        time: 1.0,
        window_id: WindowId(0, 0),
        modifiers: Default::default(),
        touches: vec![
            point(1, rect.pos + rect.size + dvec2(20.0, 20.0)),
            point(2, rect.pos + rect.size * 0.5),
        ],
    })
}

// Tests actual SDK hit-claim propagation, not in-field preedit editing semantics
// or platform contact-finalization/GPU behavior.
#[unsafe(no_mangle)]
pub extern "C" fn check_mixed_touch_claims() -> u32 {
    STAGE.store(11, Ordering::SeqCst);
    let (mut cx, root, mut workspace, mut router) = setup();
    let area = root.area();
    let event = mixed_touch(area, &cx);
    router.dispatch(&mut cx, &root, &event, &mut workspace);
    if let Event::TouchUpdate(touch) = &event {
        assert_eq!(touch.touches[0].handled.get(), Area::Empty);
        assert_eq!(touch.touches[1].handled.get(), area);
    }
    assert_eq!(cx.fingers.touch_capture_area(2), Some(area));
    STAGE.store(12, Ordering::SeqCst);
    let (mut cx, root, _, _) = setup();
    let original = mixed_touch(root.area(), &cx);
    if let Event::TouchUpdate(touch) = &original {
        let clone = Event::TouchUpdate(touch.clone());
        root.handle_event(&mut cx, &clone, &mut Scope::empty());
        assert_eq!(touch.touches[1].handled.get(), Area::Empty);
        assert_eq!(cx.fingers.touch_capture_area(2), Some(root.area()));
    }
    2
}
