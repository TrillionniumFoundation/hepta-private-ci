use super::*;
use accesskit::Node as RawNode;
use accesskit::Tree as RawTree;
use accesskit::TreeUpdate;

fn projected_state(node: RawNode) -> StateSet {
    let mut root = RawNode::new(Role::Window);
    root.set_children(vec![NodeId(2)]);
    let tree = accesskit_consumer::Tree::new(
        TreeUpdate {
            nodes: vec![(NodeId(1), root), (NodeId(2), node)],
            tree: Some(RawTree::new(NodeId(1))),
            focus: NodeId(1),
        },
        /*is_host_focused*/ true,
    );
    let node = tree.state().node_by_id(NodeId(2)).unwrap();
    NodeWrapper(&node).state(true)
}

#[test]
fn disabled_buttons_are_never_advertised_as_enabled_or_sensitive() {
    for disabled in [false, true] {
        let mut button = RawNode::new(Role::Button);
        button.set_label("Send");
        if disabled {
            button.set_disabled();
        }
        let state = projected_state(button);
        assert_eq!(
            (
                state.contains(State::Enabled),
                state.contains(State::Sensitive),
                state.contains(State::ReadOnly),
            ),
            (!disabled, !disabled, false),
        );
    }
}

#[test]
fn disabled_and_read_only_text_inputs_do_not_advertise_editability() {
    for role in [Role::TextInput, Role::MultilineTextInput] {
        for disabled in [false, true] {
            let mut input = RawNode::new(role);
            if disabled {
                input.set_disabled();
            } else {
                input.set_read_only();
            }
            let state = projected_state(input);
            assert_eq!(
                (
                    state.contains(State::Enabled),
                    state.contains(State::Sensitive),
                    state.contains(State::Editable),
                    state.contains(State::ReadOnly),
                ),
                (false, false, false, true),
            );
        }
    }
}
