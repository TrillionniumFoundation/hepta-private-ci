use super::Kind;
use super::NativeAccessibility;
use super::Target;
use super::text;
use super::visit_visible_branch;
use crate::presentation::RoomKey;
use crate::robrix::rooms::RoomsListEntry;
use accesskit::Action;
use accesskit::Node;
use accesskit::NodeId;
use accesskit::Rect as AccessibleRect;
use accesskit::Role;
use accesskit::TextSelection;
use accesskit::Tree;
use accesskit::TreeUpdate;
use hepta_control_core::chat::ChatWorkspace;
use makepad_widgets::*;
use std::collections::BTreeSet;

const ROOT: NodeId = NodeId(1);

fn layout_bounds(cx: &Cx, window_id: WindowId, rect: Rect) -> AccessibleRect {
    let rect = cx.windows[window_id].layout_rect_to_physical_pixels(rect);
    AccessibleRect {
        x0: rect.pos.x,
        y0: rect.pos.y,
        x1: rect.pos.x + rect.size.x,
        y1: rect.pos.y + rect.size.y,
    }
}

fn window_bounds(cx: &Cx, window_id: WindowId) -> AccessibleRect {
    let window = &cx.windows[window_id];
    let size = window.layout_vec2d_to_physical_pixels(window.get_inner_size());
    // The SDK's X11 screen position is already physical; only the layout size
    // is converted. Read the current window, including its initial DPI and any
    // override, without depending on a preceding WindowGeomChange event.
    let position = window.get_position();
    AccessibleRect {
        x0: position.x,
        y0: position.y,
        x1: position.x + size.x,
        y1: position.y + size.y,
    }
}

impl NativeAccessibility {
    fn id(&mut self, widget: WidgetUid, part: usize) -> NodeId {
        *self.ids.entry((widget, part)).or_insert_with(|| {
            let id = NodeId(self.next_id);
            self.next_id = self
                .next_id
                .checked_add(1)
                .expect("accessibility node identity exhausted");
            id
        })
    }

    pub(crate) fn after_draw(&mut self, cx: &mut Cx, ui: &WidgetRef, workspace: &ChatWorkspace) {
        if !self.active {
            return;
        }
        let Some(window_id) = ui.window(cx, ids!(main_window)).window_id() else {
            return;
        };
        let room = RoomKey {
            epoch: workspace.presentation_epoch(),
            local_id: workspace.active_id(),
        };
        if self.room != Some(room) || self.ids.len() > 4096 {
            self.invalidate();
            self.room = Some(room);
        }
        let previous = std::mem::take(&mut self.targets);
        let mut nodes = Vec::new();
        let mut children = Vec::new();
        let mut focus = ROOT;
        let mut visited = BTreeSet::new();
        let mut stack = vec![(LiveId::empty(), ui.clone())];
        for _ in 0..4096 {
            let Some((name, widget)) = stack.pop() else {
                break;
            };
            if !visited.insert(widget.widget_uid()) {
                continue;
            }
            let mut descendants = Vec::new();
            // Unlike structural children(), this original SDK visitor omits
            // inactive cached Dock/PageFlip/AdaptiveView branches.
            if !visit_visible_branch(&widget, &mut |id, child| descendants.push((id, child))) {
                continue;
            }
            let area = widget.area();
            if !area.is_valid(cx) {
                stack.extend(descendants.into_iter().rev());
                continue;
            }
            let rect = area.clipped_rect_union(cx);
            if rect.size.x <= 0.0
                || rect.size.y <= 0.0
                || ![rect.pos.x, rect.pos.y, rect.size.x, rect.size.y]
                    .iter()
                    .all(|value| value.is_finite())
            {
                continue;
            }
            let uid = widget.widget_uid();
            let input = widget.as_text_input();
            let input_exists = input.borrow().is_some();
            let button_enabled = widget.as_button().borrow().map(|button| button.enabled());
            let row = widget
                .borrow::<RoomsListEntry>()
                .and_then(|row| row.rendered_room());
            let mut node;
            let id = self.id(uid, 0);
            if input_exists {
                let value = input.text();
                if previous.get(&id).is_none_or(|target| !matches!(&target.kind, Kind::Input { value: old, .. } if old == &value)) {
                    self.ids.retain(|(old_uid, part), _| *old_uid != uid || *part == 0);
                }
                node = Node::new(if input.is_multiline() {
                    Role::MultilineTextInput
                } else {
                    Role::TextInput
                });
                node.set_label(if name == id!(room_filter) {
                    "Find a conversation"
                } else {
                    "Message / 消息"
                });
                node.set_value(value.clone());
                node.add_action(Action::Focus);
                if !workspace.composing && !input.is_composing() {
                    node.add_action(Action::SetValue);
                }
                let (text_nodes, runs) = text::build(&value, |part| self.id(uid, part + 1));
                if !workspace.composing && !input.is_composing() && runs.len() == text_nodes.len() {
                    node.add_action(Action::SetTextSelection);
                    node.add_action(Action::EditText);
                    #[cfg(feature = "native-clipboard-sdk")]
                    node.add_action(Action::PasteText);
                }
                node.set_children(text_nodes.iter().map(|(id, _)| *id).collect::<Vec<_>>());
                let selection = input.selection();
                if let (Some(anchor), Some(focus)) = (
                    text::position(&runs, selection.anchor.index),
                    text::position(&runs, selection.cursor.index),
                ) {
                    node.set_text_selection(TextSelection { anchor, focus });
                }
                nodes.extend(text_nodes);
                self.targets.insert(
                    id,
                    Target {
                        widget: widget.clone(),
                        room,
                        kind: Kind::Input { name, runs, value },
                    },
                );
            } else if let Some(selected_room) = row {
                node = Node::new(Role::ListBoxOption);
                node.set_label(
                    workspace
                        .title_for(selected_room.local_id)
                        .unwrap_or("Conversation"),
                );
                node.set_selected(selected_room == room);
                node.add_action(Action::Focus);
                if !workspace.composing {
                    node.add_action(Action::Click);
                }
                self.targets.insert(
                    id,
                    Target {
                        widget: widget.clone(),
                        room,
                        kind: Kind::Room(selected_room),
                    },
                );
            } else if let Some(enabled) = button_enabled {
                node = Node::new(Role::Button);
                let label = widget.text();
                node.set_label(if label.is_empty() {
                    "Window control".to_owned()
                } else {
                    label
                });
                if enabled && !workspace.composing {
                    node.add_action(Action::Focus);
                    node.add_action(Action::Click);
                } else {
                    node.set_disabled();
                }
                self.targets.insert(
                    id,
                    Target {
                        widget: widget.clone(),
                        room,
                        kind: Kind::Button,
                    },
                );
            } else if widget.as_label().borrow().is_some() {
                let value = widget.text();
                if value.is_empty() {
                    continue;
                }
                node = Node::new(Role::Label);
                node.set_value(value);
            } else {
                stack.extend(descendants.into_iter().rev());
                continue;
            }
            if widget.key_focus(cx) {
                focus = id;
            }
            node.set_bounds(layout_bounds(cx, window_id, rect));
            nodes.push((id, node));
            children.push(id);
        }
        let bounds = window_bounds(cx, window_id);
        self.adapter.set_root_window_bounds(bounds, bounds);
        let mut root = Node::new(Role::Window);
        root.set_label("Hepta Conversations");
        root.set_children(children);
        nodes.push((ROOT, root));
        let mut tree = Tree::new(ROOT);
        tree.app_name = Some("Hepta Conversations".into());
        self.adapter.update_if_active(|| TreeUpdate {
            nodes,
            tree: Some(tree),
            focus,
        });
    }
}

#[cfg(test)]
#[path = "tree_tests.rs"]
mod tests;
