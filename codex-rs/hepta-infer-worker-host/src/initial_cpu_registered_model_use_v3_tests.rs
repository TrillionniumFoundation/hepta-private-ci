use super::*;

#[test]
fn same_current_head_and_three_manifests_cannot_substitute_another_publication_or_predecessor()
-> HostResult<()> {
    let original = body()?.binding;
    require_current_binding(Some(&original), &original)?;
    assert!(require_current_binding(None, &original).is_err());
    for field in [
        "publication_operation_id",
        "predecessor_id",
        "registry_binding",
        "withdrawal_head",
        "material_digest",
    ] {
        let mut value = serde_json::to_value(&original)?;
        value[field] = if field.ends_with("_id") {
            Value::String("foreign.original.owner.operation".into())
        } else {
            Value::String(Digest32::of_bytes(b"foreign authenticated owner material").to_string())
        };
        let changed: RegisteredOperationalModelBindingV3 = serde_json::from_value(value)?;
        assert_eq!(changed.registry_head, original.registry_head);
        assert_eq!(changed.manifest_digests, original.manifest_digests);
        assert!(require_current_binding(Some(&changed), &original).is_err());
    }
    Ok(())
}

fn body() -> HostResult<Body> {
    let pin = Digest32::of_bytes(b"public signature fixture only").to_string();
    let mut binding = serde_json::Map::new();
    for field in [
        "material_digest",
        "runtime_digest",
        "native_digest",
        "body_digest",
        "execution_profile_digest",
        "input_profile_digest",
        "objective_digest",
        "scope_digest",
        "predecessor_manifest_digest",
        "registry_binding",
        "registry_head",
        "current_witness",
        "current_trust",
        "withdrawal_scope",
        "withdrawal_head",
    ] {
        binding.insert(field.into(), Value::String(pin.clone()));
    }
    for (field, value) in [
        ("purpose", "registered-successor-cpu-abstention-only.v3"),
        ("subject", "enrolled.subject"),
        ("model_artifact_id", "actual.model.2"),
        ("predecessor_id", "actual.model.1"),
        ("publication_operation_id", "actual.publication"),
    ] {
        binding.insert(field.into(), Value::String(value.into()));
    }
    binding.insert("model_generation".into(), serde_json::json!(2));
    binding.insert("authority_epoch".into(), serde_json::json!(2));
    for field in ["manifest_digests", "payload_digests"] {
        binding.insert(field.into(), serde_json::json!([pin, pin, pin]));
    }
    Ok(Body {
        schema: "hepta.cpu-neuron.registered-abstention-model-use.v3".into(),
        configuration_digest: pin.clone(),
        binding: serde_json::from_value(Value::Object(binding))?,
        evaluator_authentication_digest: pin.clone(),
        selector_id: "separate.selector".into(),
        selector_controller_id: "separate.controller".into(),
        selector_credential_digest: pin.clone(),
        selector_key_digest: pin.clone(),
        selector_program_digest: pin,
        selector_uid: 985,
        selector_gid: 985,
        authority_epoch: 2,
        issued_at: 10,
        expires_at: 20,
    })
}

#[test]
fn registered_operational_signature_rejects_material_current_role_and_evidence_substitution()
-> HostResult<()> {
    let original = body()?;
    let key = SigningKey::from_bytes(&[93; 32]);
    let signed = key.sign(&original.signing_bytes()?);
    key.verifying_key()
        .verify_strict(&original.signing_bytes()?, &signed)?;
    let json = serde_json::to_value(&original)?;
    for (field, value) in json.as_object().ok_or("full body")? {
        if field == "binding" {
            continue;
        }
        let mut changed = json.clone();
        changed[field] = match value {
            Value::String(s) => Value::String(format!("{s}.foreign")),
            Value::Number(n) => serde_json::json!(n.as_u64().ok_or("unsigned field")? + 1),
            _ => return Err("unexpected original signed field".into()),
        };
        let changed: Body = serde_json::from_value(changed)?;
        assert!(
            key.verifying_key()
                .verify_strict(&changed.signing_bytes()?, &signed)
                .is_err(),
            "{field}"
        );
    }
    for (field, value) in json["binding"]
        .as_object()
        .ok_or("full registered binding")?
    {
        let mut changed = json.clone();
        changed["binding"][field] = match value {
            Value::String(s) => Value::String(format!("{s}.foreign")),
            Value::Number(n) => serde_json::json!(n.as_u64().ok_or("unsigned field")? + 1),
            Value::Array(_) => serde_json::json!(["foreign", "foreign", "foreign"]),
            _ => return Err("unexpected registered binding field".into()),
        };
        let changed: Body = serde_json::from_value(changed)?;
        assert!(
            key.verifying_key()
                .verify_strict(&changed.signing_bytes()?, &signed)
                .is_err(),
            "binding.{field}"
        );
    }
    for domain in [
        b"hepta.learning-artifacts.selection.v1\0".as_slice(),
        b"hepta.cpu-neuron.installed-abstention-model-use.v2\0".as_slice(),
    ] {
        let mut wrong = domain.to_vec();
        wrong.extend_from_slice(&serde_json::to_vec(&original)?);
        assert!(key.verifying_key().verify_strict(&wrong, &signed).is_err());
    }
    Ok(())
}

#[test]
fn registered_selection_cannot_add_goal_authority_or_omit_current_or_overflow_preimage()
-> HostResult<()> {
    let mut value = serde_json::to_value(body()?)?;
    value["goal_authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<Body>(value).is_err());
    let mut value = serde_json::to_value(body()?)?;
    value["binding"]
        .as_object_mut()
        .ok_or("binding")?
        .remove("current_witness");
    assert!(serde_json::from_value::<Body>(value).is_err());
    let mut oversized = body()?;
    oversized.selector_controller_id = "x".repeat(32 * 1024);
    assert!(oversized.signing_bytes().is_err());
    Ok(())
}
