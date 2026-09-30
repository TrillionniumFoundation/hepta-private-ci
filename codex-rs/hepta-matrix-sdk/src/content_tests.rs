use super::*;
use pretty_assertions::assert_eq;

#[test]
fn canonical_encoder_preserves_the_exact_root_and_edit_semantics() {
    let target = MatrixEventId::parse("$root:example.test").expect("target");
    let root = outbound_message_content("hello", /*replaces_event_id*/ None);
    let edit = outbound_message_content("hello", Some(&target));
    assert_eq!(
        serde_json::to_string(&CanonicalJson(&root)).expect("root encoding"),
        r#"{"body":"hello","msgtype":"m.text"}"#
    );
    assert_eq!(
        serde_json::to_string(&CanonicalJson(&edit)).expect("edit encoding"),
        r#"{"body":"hello","m.new_content":{"body":"hello","msgtype":"m.text"},"m.relates_to":{"event_id":"$root:example.test","rel_type":"m.replace"},"msgtype":"m.text"}"#
    );
    assert_ne!(content_digest(&root), content_digest(&edit));
}

#[test]
fn replacement_target_and_nested_content_are_in_the_signed_digest() {
    let first = MatrixEventId::parse("$first:example.test").expect("first target");
    let second = MatrixEventId::parse("$second:example.test").expect("second target");
    let first_content = outbound_message_content("same body", Some(&first));
    let second_content = outbound_message_content("same body", Some(&second));
    assert_ne!(
        content_digest(&first_content),
        content_digest(&second_content)
    );
    let mut altered = first_content.clone();
    altered["m.new_content"]["body"] = Value::String("different".to_string());
    assert_ne!(content_digest(&first_content), content_digest(&altered));
    altered = first_content.clone();
    altered["m.relates_to"]["rel_type"] = Value::String("m.reference".to_string());
    assert_ne!(content_digest(&first_content), content_digest(&altered));
}

#[test]
fn object_insertion_order_is_not_semantic_but_unicode_and_escaping_are() {
    let left = serde_json::json!({"z": {"b": "雪", "a": "line\nquote\""}, "a": "x"});
    let right: Value =
        serde_json::from_str(r#"{"a":"x","z":{"a":"line\nquote\"","b":"雪"}}"#).expect("same JSON");
    assert_eq!(content_digest(&left), content_digest(&right));
    let composed = outbound_message_content("é", /*replaces_event_id*/ None);
    let decomposed = outbound_message_content("e\u{301}", /*replaces_event_id*/ None);
    assert_ne!(content_digest(&composed), content_digest(&decomposed));
}
