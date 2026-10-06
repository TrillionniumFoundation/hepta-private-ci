//! Pre-dispatch IME routing. Platform processing and capture cleanup stay outside
//! this adapter; only application widget dispatch can be withheld.
use crate::ime_pointer_gate::Capture;
use crate::ime_pointer_gate::PointerGate;
use crate::ime_pointer_gate::PointerId;
use crate::ime_pointer_gate::Position;
use crate::ime_pointer_gate::Preedit;
use crate::ime_pointer_gate::Route;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::makepad_platform::event::finger::TouchState;
use makepad_widgets::*;

#[derive(Default)]
pub(crate) struct CompositionLayout {
    pub(crate) active: bool,
    pub(crate) variant: Option<LiveId>,
}

struct Owner {
    epoch: u64,
    widget: WidgetUid,
    input: TextInputRef,
}

#[derive(Default)]
pub(crate) struct ImeRouter {
    owner: Option<Owner>,
    pointers: PointerGate,
    keyboard_focus: crate::keyboard_focus::KeyboardFocus,
}

impl ImeRouter {
    pub(crate) fn synchronize(
        &mut self,
        cx: &mut Cx,
        root: &WidgetRef,
        workspace: &mut ChatWorkspace,
    ) {
        let epoch = workspace.presentation_epoch();
        if self
            .owner
            .as_ref()
            .is_some_and(|owner| owner.epoch != epoch)
            && let Some(owner) = self.owner.take()
        {
            owner.input.restore_state(cx, TextInputState::default());
            cx.set_key_focus(Area::Empty);
        }
        let focus = cx.key_focus();
        let mut observed = None;
        if focus.is_valid(cx) {
            let mut stack = vec![root.clone()];
            for _ in 0..4096 {
                let Some(widget) = stack.pop() else { break };
                let input = widget.as_text_input();
                if input.area() == focus && input.is_composing() {
                    observed = Some(Owner {
                        epoch,
                        widget: widget.widget_uid(),
                        input,
                    });
                    break;
                }
                widget.children(&mut |_, child| stack.push(child));
            }
        }
        if let Some(previous) = self.owner.take()
            && observed
                .as_ref()
                .is_none_or(|owner| owner.widget != previous.widget)
            && previous.input.is_composing()
        {
            // Detachment/focus loss is cancellation, not an IME commit. Preserve
            // local draft text, but do not keep a dead editor locking navigation.
            let selection = previous.input.selection();
            previous.input.set_selection(cx, selection);
            if focus == previous.input.area() {
                cx.set_key_focus(Area::Empty);
            }
        }
        self.owner = observed;
        let composing = self.owner.is_some();
        cx.global::<CompositionLayout>().active = composing;
        if workspace.composing != composing {
            workspace.composing = composing;
            root.redraw(cx);
        }
    }

    pub(crate) fn dispatch(
        &mut self,
        cx: &mut Cx,
        root: &WidgetRef,
        event: &Event,
        workspace: &mut ChatWorkspace,
    ) {
        // Owner cleanup can itself queue focus changes. Do not replace them.
        let had_ime_owner = self.owner.is_some();
        self.synchronize(cx, root, workspace);
        let ime_quiet = !had_ime_owner && self.owner.is_none() && !workspace.composing;
        let keyboard_plan = self
            .keyboard_focus
            .before_dispatch(cx, root, event, workspace, ime_quiet);
        let area = self.owner.as_ref().map(|owner| owner.input.area());
        let preedit = if area.is_some() {
            Preedit::Active
        } else {
            Preedit::Inactive
        };
        let position = |cx: &Cx, point| {
            if area.is_some_and(|area| area.is_valid(cx) && area.clipped_rect(cx).contains(point)) {
                Position::FocusedField
            } else {
                Position::OutsideFocusedField
            }
        };
        let mut forward = !keyboard_plan.consume_tab;
        match event {
            Event::MouseDown(mouse) => {
                forward = self.pointers.start(
                    PointerId::Mouse(mouse.button.bits()),
                    preedit,
                    position(cx, mouse.abs),
                ) == Route::Forward;
            }
            Event::MouseMove(_) => {
                if let Some((button, _)) = cx.fingers.first_mouse_button {
                    forward =
                        self.pointers.motion(PointerId::Mouse(button.bits())) == Route::Forward;
                }
            }
            Event::MouseUp(mouse) => {
                let captured = area.is_some_and(|area| {
                    cx.fingers
                        .first_mouse_button
                        .is_some_and(|(button, _)| button == mouse.button)
                        && cx.fingers.is_area_captured(area)
                });
                let capture = if captured {
                    Capture::FocusedField
                } else {
                    Capture::OtherOrNone
                };
                forward = self.pointers.finish(
                    PointerId::Mouse(mouse.button.bits()),
                    preedit,
                    position(cx, mouse.abs),
                    capture,
                ) == Route::Forward;
            }
            Event::TouchUpdate(touch) => {
                let mut filtered = touch.clone();
                filtered.touches.clear();
                let mut indices = Vec::new();
                for (index, point) in touch.touches.iter().enumerate() {
                    let id = PointerId::Touch(point.uid);
                    let location = position(cx, point.abs);
                    let route = match point.state {
                        TouchState::Start => self.pointers.start(id, preedit, location),
                        TouchState::Move | TouchState::Stable => self.pointers.motion(id),
                        TouchState::Stop | TouchState::Cancel => {
                            let capture = if area.is_some_and(|area| {
                                cx.fingers.touch_capture_area(point.uid) == Some(area)
                            }) {
                                Capture::FocusedField
                            } else {
                                Capture::OtherOrNone
                            };
                            self.pointers.finish(id, preedit, location, capture)
                        }
                    };
                    if route == Route::Forward {
                        indices.push(index);
                        filtered.touches.push(point.clone());
                    }
                }
                if !filtered.touches.is_empty() {
                    let filtered_event = Event::TouchUpdate(filtered);
                    root.handle_event(cx, &filtered_event, &mut Scope::with_data(&mut *workspace));
                    if let Event::TouchUpdate(filtered) = filtered_event {
                        // Cells are copied by Clone. Return real hit/sweep claims
                        // to the original packet used by platform finalization.
                        for (index, point) in indices.into_iter().zip(filtered.touches) {
                            touch.touches[index].handled.set(point.handled.get());
                            touch.touches[index].sweep_lock.set(point.sweep_lock.get());
                        }
                    }
                }
                forward = false;
            }
            Event::KeyDown(key) if preedit == Preedit::Active => {
                // The OS/IME receives the original event before AppMain. Do not
                // reinterpret candidate-selection/cancel/navigation keys as UI
                // submit or focus changes; real TextInput commit still flows.
                let edits_or_navigates = matches!(
                    key.key_code,
                    KeyCode::Tab
                        | KeyCode::ReturnKey
                        | KeyCode::NumpadEnter
                        | KeyCode::Escape
                        | KeyCode::ArrowLeft
                        | KeyCode::ArrowRight
                        | KeyCode::ArrowUp
                        | KeyCode::ArrowDown
                        | KeyCode::Home
                        | KeyCode::End
                        | KeyCode::PageUp
                        | KeyCode::PageDown
                        | KeyCode::Backspace
                        | KeyCode::Delete
                ) || (key.modifiers.is_primary()
                    && matches!(key.key_code, KeyCode::KeyA | KeyCode::KeyZ));
                forward = !edits_or_navigates;
            }
            Event::TextCut(_) if preedit == Preedit::Active => forward = false,
            Event::ImeAction(_) if preedit == Preedit::Active => forward = false,
            _ => {}
        }
        if forward {
            root.handle_event(cx, event, &mut Scope::with_data(&mut *workspace));
        }
        if self.pointers.is_overflowed() {
            let warning = "Input gesture capacity exceeded. Keyboard navigation remains available after composition; reopen the application to restore pointer input.";
            if workspace
                .presentation_note
                .as_deref()
                .is_none_or(|note| !note.contains(warning))
            {
                let existing = workspace.presentation_note.take().unwrap_or_default();
                workspace.presentation_note = Some(format!("{warning}\n{existing}"));
                root.redraw(cx);
            }
        }
        self.synchronize(cx, root, workspace);
        self.keyboard_focus.after_dispatch(
            cx,
            root,
            event,
            workspace,
            ime_quiet && self.owner.is_none() && !workspace.composing,
            keyboard_plan,
        );
    }
}

pub(crate) fn adaptive_variant(cx: &mut Cx, size: &Vec2d) -> LiveId {
    let requested = if size.x >= 760.0 {
        live_id!(Desktop)
    } else {
        live_id!(Mobile)
    };
    let state = cx.global::<CompositionLayout>();
    if state.active {
        state.variant.unwrap_or(requested)
    } else {
        state.variant = Some(requested);
        requested
    }
}
