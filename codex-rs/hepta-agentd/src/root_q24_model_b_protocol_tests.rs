use super::*;
use pretty_assertions::assert_eq;

#[test]
fn original_model_b_wire_rejects_extra_action_authority() -> anyhow::Result<()> {
    for bytes in [
        br#"{"kind":"bind","material":"peer"}"#.as_slice(),
        br#"{"kind":"read","qualified":true}"#.as_slice(),
        br#"{"kind":"bind","owner":"replacement"}"#.as_slice(),
    ] {
        assert!(serde_json::from_slice::<Action>(bytes).is_err());
    }
    for bytes in [
        br#"{"kind":"bind"}"#.as_slice(),
        br#"{"kind":"read"}"#.as_slice(),
    ] {
        let action: Action = serde_json::from_slice(bytes)?;
        assert_eq!(serde_json::to_vec(&action)?, bytes);
    }
    Ok(())
}

#[test]
fn original_model_b_wire_requires_the_actual_factory_predecessor() -> anyhow::Result<()> {
    let request = Request {
        schema: 2,
        operation: PURPOSE.into(),
        request_id: 3,
        binding: "factory".into(),
        original_b: "original-b".into(),
        training_head: "training".into(),
        expected: FactoryLease {
            epoch: 0,
            material: None,
            revocations: "original".into(),
        },
        action: Action::Read {},
    };
    let bytes = serde_json::to_vec(&request)?;
    let mut value: serde_json::Value = serde_json::from_slice(&bytes)?;
    value
        .as_object_mut()
        .ok_or_else(|| anyhow::anyhow!("request object"))?
        .remove("expected");
    assert!(serde_json::from_value::<Request>(value).is_err());
    let mut value: serde_json::Value = serde_json::from_slice(&bytes)?;
    value
        .as_object_mut()
        .ok_or_else(|| anyhow::anyhow!("request object"))?
        .insert("native_qualification".into(), serde_json::Value::Bool(true));
    assert!(serde_json::from_value::<Request>(value).is_err());
    let decoded: Request = serde_json::from_slice(&bytes)?;
    assert_eq!(serde_json::to_vec(&decoded)?, bytes);
    Ok(())
}
