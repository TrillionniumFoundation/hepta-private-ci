use super::*;

fn body() -> Body {
    let digest = Digest32::of_bytes(b"signature fixture only").to_string();
    Body {
        schema: "hepta.cpu-neuron.installed-abstention-model-use.v2".into(),
        configuration_digest: digest.clone(),
        model_binding: serde_json::json!({"model_generation":1,"purpose":OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1}),
        evaluator_authentication_digest: digest.clone(),
        installed_identity_digest: digest.clone(),
        installed_body_digest: digest.clone(),
        runtime_body_digest: digest.clone(),
        registry_head: digest.clone(),
        current_witness: digest.clone(),
        current_trust: digest.clone(),
        withdrawal_scope: digest.clone(),
        withdrawal_head: Digest32::ZERO.to_string(),
        authority_epoch: 1,
        payload_digests: std::array::from_fn(|_| digest.clone()),
        selector_id: "separate.s".into(),
        selector_credential_digest: digest.clone(),
        selector_key_digest: digest.clone(),
        selector_program_digest: digest,
        issued_at: 1,
        expires_at: 2,
    }
}

#[test]
fn new_model_use_signature_binds_current_body_roles_full_model_and_source_windows() -> HostResult<()>
{
    let original = body();
    let key = SigningKey::from_bytes(&[89; 32]);
    let signature = key.sign(&original.signing_bytes()?);
    key.verifying_key()
        .verify_strict(&original.signing_bytes()?, &signature)?;
    let original_value = serde_json::to_value(&original)?;
    for (field, value) in original_value.as_object().ok_or("body")? {
        let mut changed = original_value.clone();
        changed[field] = match value {
            Value::String(s) => Value::String(format!("{s}.changed")),
            Value::Number(n) => serde_json::json!(n.as_u64().ok_or("unsigned field")? + 1),
            Value::Array(_) => serde_json::json!(["changed", "changed", "changed"]),
            Value::Object(_) => {
                serde_json::json!({"model_generation":2,"purpose":OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1})
            }
            _ => return Err("unexpected signed body field".into()),
        };
        let changed: Body = serde_json::from_value(changed)?;
        assert!(
            key.verifying_key()
                .verify_strict(&changed.signing_bytes()?, &signature)
                .is_err(),
            "{field}"
        );
    }
    let mut old_domain = b"hepta.learning-artifacts.selection.v1\0".to_vec();
    old_domain.extend_from_slice(&serde_json::to_vec(&original)?);
    assert!(
        key.verifying_key()
            .verify_strict(&old_domain, &signature)
            .is_err()
    );
    Ok(())
}

#[test]
fn stable_use_body_rejects_goal_or_promotion_fields_and_oversized_preimages() -> HostResult<()> {
    let mut value = serde_json::to_value(body())?;
    value["objective_digest"] = serde_json::json!("cannot widen existing signatures");
    assert!(serde_json::from_value::<Body>(value).is_err());
    let mut oversized = body();
    oversized.model_binding = serde_json::json!({"unknown": "x".repeat(32*1024)});
    assert!(oversized.signing_bytes().is_err());
    Ok(())
}
