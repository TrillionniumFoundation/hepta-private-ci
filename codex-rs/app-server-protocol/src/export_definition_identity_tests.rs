use super::insert_definition;
use pretty_assertions::assert_eq;
use serde_json::Map;
use serde_json::json;

#[test]
fn original_response_can_be_reused_as_nested_receipt_in_either_order() -> anyhow::Result<()> {
    let nested = json!({"type":"object","properties":{"id":{"type":"string"}},"required":["id"]});
    let mut root = nested.clone();
    root["title"] = json!("ThreadStartResponse");
    root["$schema"] = json!("http://json-schema.org/draft-07/schema#");
    for pair in [[&root, &nested], [&nested, &root]] {
        let mut definitions = Map::new();
        for schema in pair {
            insert_definition(
                &mut definitions,
                "ThreadStartResponse".into(),
                schema.clone(),
                "v2",
            )?;
        }
        assert_eq!(definitions["ThreadStartResponse"], root);
    }
    Ok(())
}

#[test]
fn different_validation_title_and_dialect_still_fail_closed() -> anyhow::Result<()> {
    let original = json!({"type":"object","title":"Receipt","required":["id"]});
    for changed in [
        json!({"type":"object","title":"Receipt","required":["anotherId"]}),
        json!({"type":"object","title":"AnotherReceipt","required":["id"]}),
        json!({"type":"object","title":"Receipt","required":["id"],"$schema":"https://json-schema.org/draft/2020-12/schema"}),
    ] {
        let mut definitions = Map::new();
        insert_definition(&mut definitions, "Receipt".into(), original.clone(), "v2")?;
        assert!(insert_definition(&mut definitions, "Receipt".into(), changed, "v2").is_err());
        assert_eq!(definitions["Receipt"], original);
    }
    Ok(())
}
