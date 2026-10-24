//! Linux AT-SPI projection of the original active Makepad widget tree.
//! The adapter owns no draft, transcript, runtime or authentication state.
mod edit;
mod text;
mod tree;

use crate::presentation::PresentationAction;
use crate::presentation::PresentationCommand;
use crate::presentation::RoomKey;
use crate::presentation::apply_action;
use crate::robrix::rooms::SelectRoomAction;
use accesskit::Action;
use accesskit::ActionData;
use accesskit::ActionHandler;
use accesskit::ActionRequest;
use accesskit::ActivationHandler;
use accesskit::DeactivationHandler;
use accesskit::NodeId;
use accesskit::TextEditOperation;
use accesskit::TreeUpdate;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::makepad_draw::text::selection::Cursor;
use makepad_widgets::makepad_draw::text::selection::Selection;
use makepad_widgets::text_input::UndoGroup;
use makepad_widgets::*;
use std::collections::BTreeMap;
use std::sync::mpsc::Receiver;
use std::sync::mpsc::SyncSender;
use std::sync::mpsc::{self};

enum Request {
    Activate,
    Action(ActionRequest),
    Deactivate,
}

#[derive(Clone)]
struct Handler(SyncSender<Request>);

impl Handler {
    fn queue(&self, request: Request) {
        if self.0.try_send(request).is_ok() {
            SignalToUI::set_ui_signal();
        }
    }
}

impl ActivationHandler for Handler {
    fn request_initial_tree(&mut self) -> Option<TreeUpdate> {
        self.queue(Request::Activate);
        None
    }
}

impl ActionHandler for Handler {
    fn do_action(&mut self, request: ActionRequest) {
        if matches!(&request.data, Some(ActionData::Value(value)) if value.len() > hepta_control_core::chat::MAX_DRAFT_BYTES)
        {
            return;
        }
        if matches!(&request.data, Some(ActionData::EditText(edit))
            if edit.expected.len() > hepta_control_core::chat::MAX_DRAFT_BYTES
            || matches!(&edit.operation, TextEditOperation::Replace(value)
                if value.len() > hepta_control_core::chat::MAX_DRAFT_BYTES))
        {
            return;
        }
        self.queue(Request::Action(request));
    }
}

impl DeactivationHandler for Handler {
    fn deactivate_accessibility(&mut self) {
        self.queue(Request::Deactivate);
    }
}

enum Kind {
    Button,
    Room(RoomKey),
    Input {
        name: LiveId,
        runs: Vec<text::Run>,
        value: String,
    },
}

struct Target {
    widget: WidgetRef,
    room: RoomKey,
    kind: Kind,
}

fn visit_visible_branch(widget: &WidgetRef, visit: &mut dyn FnMut(LiveId, WidgetRef)) -> bool {
    if let Some(window) = widget.borrow::<Window>() {
        // Window::visit_cancel additionally requires keyboard focus, which is
        // appropriate for Escape routing but would remove an unfocused visible
        // window from AT-SPI. Its original child hook keeps visibility checks.
        window.cancel_children_impl(visit)
    } else {
        widget.visit_cancel(visit)
    }
}

pub(crate) struct NativeAccessibility {
    adapter: accesskit_unix::Adapter,
    requests: Receiver<Request>,
    active: bool,
    room: Option<RoomKey>,
    next_id: u64,
    ids: BTreeMap<(WidgetUid, usize), NodeId>,
    targets: BTreeMap<NodeId, Target>,
    dpi: f64,
}

impl NativeAccessibility {
    pub(crate) fn new() -> Self {
        let (send, requests) = mpsc::sync_channel(32);
        let handler = Handler(send);
        Self {
            adapter: accesskit_unix::Adapter::new(handler.clone(), handler.clone(), handler),
            requests,
            active: false,
            room: None,
            next_id: 2,
            ids: BTreeMap::new(),
            targets: BTreeMap::new(),
            dpi: 1.0,
        }
    }

    pub(crate) fn invalidate(&mut self) {
        self.ids.clear();
        self.targets.clear();
    }

    pub(crate) fn before_event(
        &mut self,
        cx: &mut Cx,
        ui: &WidgetRef,
        event: &Event,
        workspace: &mut ChatWorkspace,
    ) {
        if matches!(event, Event::Draw(_)) {
            return;
        }
        if matches!(event, Event::LiveEdit | Event::ScriptReapply) {
            self.invalidate();
        }
        let window = ui.window(cx, ids!(main_window)).window_id();
        match event {
            Event::WindowGotFocus(id) if Some(*id) == window => {
                self.adapter.update_window_focus_state(true)
            }
            Event::WindowLostFocus(id) if Some(*id) == window => {
                self.adapter.update_window_focus_state(false)
            }
            Event::WindowGeomChange(change) if Some(change.window_id) == window => {
                if change.new_geom.dpi_factor.is_finite() && change.new_geom.dpi_factor > 0.0 {
                    self.dpi = change.new_geom.dpi_factor;
                }
            }
            _ => {}
        }
        // Never interleave a semantic action ahead of a raw key/preedit event
        // that the original ImeRouter has not yet processed.
        if !matches!(event, Event::Signal | Event::Timer(_)) {
            return;
        }
        for _ in 0..32 {
            let Ok(request) = self.requests.try_recv() else {
                break;
            };
            match request {
                Request::Activate => {
                    self.active = true;
                    ui.redraw(cx);
                }
                Request::Deactivate => {
                    self.active = false;
                    self.invalidate();
                }
                Request::Action(request) => self.action(cx, ui, workspace, request),
            }
        }
    }

    fn action(
        &mut self,
        cx: &mut Cx,
        ui: &WidgetRef,
        workspace: &mut ChatWorkspace,
        request: ActionRequest,
    ) {
        let Some(target) = self.targets.get(&request.target) else {
            return;
        };
        let current = RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        };
        if !self.active
            || target.room != current
            || workspace.composing
            || !target.widget.visible()
            || !target.widget.area().is_valid(cx)
        {
            return;
        }
        let mut active = false;
        let mut stack = vec![ui.clone()];
        for _ in 0..4096 {
            let Some(widget) = stack.pop() else { break };
            let mut children = Vec::new();
            if !visit_visible_branch(&widget, &mut |_, child| children.push(child)) {
                continue;
            }
            if widget.widget_uid() == target.widget.widget_uid() {
                active = true;
                break;
            }
            stack.extend(children);
        }
        if !active {
            return;
        }
        let input = target.widget.as_text_input();
        if input.is_composing() {
            return;
        }
        match request.action {
            Action::Focus => {
                if matches!(&target.kind, Kind::Input { .. }) {
                    input.take_key_focus(cx);
                } else if !matches!(&target.kind, Kind::Button)
                    || target
                        .widget
                        .as_button()
                        .borrow()
                        .is_some_and(|button| button.enabled())
                {
                    target.widget.set_key_focus(cx);
                }
            }
            Action::Click => match &target.kind {
                Kind::Button => {
                    if target
                        .widget
                        .as_button()
                        .borrow()
                        .is_some_and(|button| button.enabled())
                    {
                        cx.widget_action(
                            target.widget.widget_uid(),
                            ButtonAction::Clicked(KeyModifiers::default()),
                        );
                    }
                }
                Kind::Room(room) => cx.action(SelectRoomAction(Some(*room))),
                Kind::Input { .. } => {}
            },
            Action::SetValue => {
                if let Kind::Input { name, .. } = &target.kind
                    && let Some(ActionData::Value(value)) = request.data
                {
                    let limit = if *name == id!(room_filter) {
                        crate::presentation::MAX_FILTER_BYTES
                    } else {
                        hepta_control_core::chat::MAX_DRAFT_BYTES
                    };
                    if value.len() > limit || value.contains('\0') {
                        let command = if *name == id!(room_filter) {
                            PresentationCommand::SetFilter(value.into())
                        } else {
                            PresentationCommand::Edit(value.into())
                        };
                        apply_action(
                            workspace,
                            PresentationAction {
                                source: current,
                                command,
                            },
                        );
                    } else {
                        // The original SDK emits Changed; its original widget
                        // reducer applies the complete, validated transaction.
                        let _ =
                            input.replace_range(cx, 0..input.text().len(), &value, UndoGroup::New);
                    }
                }
            }
            Action::SetTextSelection => {
                if let Kind::Input { runs, value, .. } = &target.kind
                    && value == &input.text()
                    && let Some(ActionData::SetTextSelection(selection)) = request.data
                    && let Some((anchor, cursor)) = text::selection(runs, selection)
                {
                    input.set_selection(
                        cx,
                        Selection {
                            anchor: Cursor {
                                index: anchor,
                                prefer_next_row: false,
                            },
                            cursor: Cursor {
                                index: cursor,
                                prefer_next_row: false,
                            },
                        },
                    );
                }
            }
            Action::EditText => {
                if let Kind::Input { name, runs, value } = &target.kind
                    && let Some(ActionData::EditText(edit)) = request.data
                {
                    let current_text = input.text();
                    // A prior SDK Changed action must reach the sole reducer
                    // before another accessibility edit can use that draft.
                    if *name != id!(room_filter) && current_text != workspace.draft().text {
                        return;
                    }
                    let limit = if *name == id!(room_filter) {
                        crate::presentation::MAX_FILTER_BYTES
                    } else {
                        hepta_control_core::chat::MAX_DRAFT_BYTES
                    };
                    let Some(range) = edit::validate(runs, value, &current_text, &edit, limit)
                    else {
                        return;
                    };
                    match edit.operation {
                        TextEditOperation::Replace(replacement) => {
                            let _ = input.replace_range(cx, range, &replacement, UndoGroup::New);
                        }
                        TextEditOperation::Copy => cx.copy_to_clipboard(&current_text[range]),
                        TextEditOperation::Cut => {
                            let selected = &current_text[range.clone()];
                            if input.replace_range(cx, range, "", UndoGroup::New).is_ok() {
                                cx.copy_to_clipboard(selected);
                            }
                        }
                    }
                }
            }
            _ => return,
        }
        ui.redraw(cx);
    }
}
