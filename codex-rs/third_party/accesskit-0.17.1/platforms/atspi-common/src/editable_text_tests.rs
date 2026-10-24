use super::*;
use crate::context::ActionHandlerWrapper;
use accesskit::ActionHandler;
use accesskit::Node as RawNode;
use accesskit::TextPosition;
use accesskit::Tree as RawTree;
use accesskit::TreeUpdate;
use std::sync::Mutex;

struct Record(Arc<Mutex<Vec<ActionRequest>>>);
impl ActionHandler for Record {
    fn do_action(&mut self, request: ActionRequest) {
        self.0.lock().unwrap().push(request);
    }
}

fn snapshot(editable: bool) -> TreeUpdate {
    let mut root = RawNode::new(Role::Window);
    root.set_children(vec![NodeId(2)]);
    let mut input = RawNode::new(Role::MultilineTextInput);
    input.set_children(vec![NodeId(3)]);
    input.set_value("中e\u{301}🙂");
    if editable {
        input.add_action(Action::EditText);
    }
    let mut run = RawNode::new(Role::TextRun);
    run.set_value("中e\u{301}🙂");
    run.set_character_lengths(vec![3, 3, 4]);
    TreeUpdate {
        nodes: vec![(NodeId(1), root), (NodeId(2), input), (NodeId(3), run)],
        tree: Some(RawTree::new(NodeId(1))),
        focus: NodeId(2),
    }
}

fn setup() -> (Arc<Context>, PlatformNode, Arc<Mutex<Vec<ActionRequest>>>) {
    let requests = Arc::new(Mutex::new(Vec::new()));
    let context = Context::new(
        &AppContext::new(),
        accesskit_consumer::Tree::new(snapshot(true), true),
        Arc::new(ActionHandlerWrapper::new(Record(requests.clone()))),
        WindowBounds::default(),
    );
    let node = PlatformNode::new(&context, 0, NodeId(2));
    (context, node, requests)
}

#[test]
fn entire_value_is_one_revision_bound_request() {
    let (_context, node, requests) = setup();
    assert!(node.interfaces().unwrap().contains(Interface::EditableText));
    assert!(node.set_text_contents("中文").unwrap());
    let requests = requests.lock().unwrap();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].action, Action::EditText);
    let Some(ActionData::EditText(edit)) = &requests[0].data else {
        panic!("missing atomic edit")
    };
    assert_eq!(edit.expected.as_ref(), "中e\u{301}🙂");
    assert_eq!(
        edit.range.anchor,
        TextPosition {
            node: NodeId(3),
            character_index: 0
        }
    );
    assert_eq!(
        edit.range.focus,
        TextPosition {
            node: NodeId(3),
            character_index: 3
        }
    );
    assert_eq!(edit.operation, TextEditOperation::Replace("中文".into()));
}

#[test]
fn unicode_scalar_offsets_never_round_inside_grapheme() {
    let (_context, node, requests) = setup();
    assert!(matches!(
        node.delete_text(2, 3),
        Err(Error::IndexOutOfRange)
    ));
    assert!(matches!(
        node.insert_text(-1, "a", 1),
        Err(Error::IndexOutOfRange)
    ));
    assert!(matches!(
        node.delete_text(3, 1),
        Err(Error::IndexOutOfRange)
    ));
    assert!(requests.lock().unwrap().is_empty());
    assert!(node.delete_text(1, 3).unwrap());
    let requests = requests.lock().unwrap();
    let Some(ActionData::EditText(edit)) = &requests[0].data else {
        panic!()
    };
    assert_eq!(edit.range.anchor.character_index, 1);
    assert_eq!(edit.range.focus.character_index, 2);
}

#[test]
fn insert_length_is_bytes_and_invalid_utf8_prefix_is_refused() {
    let (_context, node, requests) = setup();
    assert!(!node.insert_text(1, "你好", 1).unwrap());
    assert!(!node.insert_text(1, "你好", -1).unwrap());
    assert!(!node.insert_text(1, "你好", 7).unwrap());
    assert!(requests.lock().unwrap().is_empty());
    assert!(node.insert_text(1, "你好", 3).unwrap());
    let requests = requests.lock().unwrap();
    let Some(ActionData::EditText(edit)) = &requests[0].data else {
        panic!()
    };
    assert_eq!(edit.operation, TextEditOperation::Replace("你".into()));
    assert_eq!(edit.range.anchor, edit.range.focus);
}

#[test]
fn limit_nul_and_unavailable_action_never_queue_mutation() {
    let (context, node, requests) = setup();
    assert!(!node.set_text_contents(&"界".repeat(6000)).unwrap());
    assert!(!node.set_text_contents("a\0b").unwrap());
    assert!(!node.insert_text(0, &"x".repeat(16384), 16384).unwrap());
    context.tree.write().unwrap().update(snapshot(false));
    assert!(!node.interfaces().unwrap().contains(Interface::EditableText));
    assert!(matches!(
        node.set_text_contents("new"),
        Err(Error::UnsupportedInterface)
    ));
    assert!(requests.lock().unwrap().is_empty());
}

#[test]
fn clipboard_and_defunct_node_preserve_original_range_identity() {
    let (context, node, requests) = setup();
    assert!(node.copy_text(0, 1).unwrap());
    assert!(node.cut_text(1, 3).unwrap());
    let captured = requests.lock().unwrap();
    assert_eq!(captured.len(), 2);
    let Some(ActionData::EditText(copy)) = &captured[0].data else {
        panic!()
    };
    let Some(ActionData::EditText(cut)) = &captured[1].data else {
        panic!()
    };
    assert_eq!(copy.operation, TextEditOperation::Copy);
    assert_eq!(cut.operation, TextEditOperation::Cut);
    assert_eq!(copy.expected, cut.expected);
    drop(captured);
    context.tree.write().unwrap().update(TreeUpdate {
        nodes: vec![(NodeId(1), RawNode::new(Role::Window))],
        tree: None,
        focus: NodeId(1),
    });
    assert!(matches!(node.delete_text(0, 1), Err(Error::Defunct)));
    assert_eq!(requests.lock().unwrap().len(), 2);
}
