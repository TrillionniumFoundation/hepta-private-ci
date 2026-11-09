//! Synthetic parameter mutations exercise the real native loader. No trained
//! checkpoint, dataset, calibration evidence, or artifact authority is supplied.

use codex_hepta_infer_core::JointV4TensorComponentV1;

use super::support;
use crate::codec::Packet;
use crate::codec::Result;
use crate::model::Model;

#[test]
fn native_load_projects_every_tensor_and_localizes_changed_parameters() -> Result<()> {
    let original = support::observed_weights();
    let model = Model::new(Packet::decode(&original.encode()?)?)?;
    let before = model.joint_v4_projection()?;
    let projected_names: Vec<_> = before
        .inventory()
        .iter()
        .map(|tensor| &tensor.name)
        .collect();
    assert_eq!(projected_names, original.tensors.keys().collect::<Vec<_>>());
    for (name, group) in [
        ("image_encoder.0.weight", JointV4TensorComponentV1::Encoder),
        ("adapters.image.0.weight", JointV4TensorComponentV1::Base),
        ("emissions.image.0.weight", JointV4TensorComponentV1::Heads),
        (
            "core.layers.0.norm.weight",
            JointV4TensorComponentV1::Normalizer,
        ),
    ] {
        let mut weights = original.clone();
        weights
            .tensors
            .get_mut(name)
            .ok_or("missing fixture tensor")?
            .data[0] += 0.5;
        let changed = Model::new(Packet::decode(&weights.encode()?)?)?;
        let after = changed.joint_v4_projection()?;
        assert_ne!(
            before.decoded_weights_digest(),
            after.decoded_weights_digest()
        );
        let mut expected = before.components().clone();
        let (prior, replacement) = match group {
            JointV4TensorComponentV1::Base => (&mut expected.base, after.components().base),
            JointV4TensorComponentV1::Encoder => {
                (&mut expected.encoder, after.components().encoder)
            }
            JointV4TensorComponentV1::Heads => (&mut expected.heads, after.components().heads),
            JointV4TensorComponentV1::Normalizer => {
                (&mut expected.normalizer, after.components().normalizer)
            }
        };
        assert_ne!(*prior, replacement);
        *prior = replacement;
        assert_eq!(&expected, after.components());
    }
    Ok(())
}

#[test]
fn native_v4_loader_rejects_incomplete_or_ambiguous_component_data() -> Result<()> {
    let original = support::observed_weights();
    let mut missing = original.clone();
    missing.tensors.remove("text_condition.bias");
    assert!(Model::new(missing).is_err());
    let mut extra = original.clone();
    let tensor = extra
        .tensors
        .get("text_condition.bias")
        .ok_or("fixture bias")?
        .clone();
    extra
        .tensors
        .insert("undeclared.overlay.bias".into(), tensor);
    assert!(Model::new(extra).is_err());
    let mut nonfinite = original.clone();
    nonfinite
        .tensors
        .get_mut("critic.2.bias")
        .ok_or("fixture critic")?
        .data[0] = f64::NAN;
    assert!(Model::new(nonfinite).is_err());
    let mut wrong_shape = original.clone();
    wrong_shape
        .tensors
        .get_mut("critic.2.bias")
        .ok_or("fixture critic")?
        .shape = vec![1, 1];
    assert!(Model::new(wrong_shape).is_err());
    let mut missing_policy = original.clone();
    missing_policy.meta.remove("ndu.critic_output");
    assert!(Model::new(missing_policy).is_err());
    let mut unknown_policy = original;
    unknown_policy
        .meta
        .insert("undocumented_normalizer".into(), "enabled".into());
    assert!(Model::new(unknown_policy).is_err());
    Ok(())
}

#[test]
fn reset_policy_changes_semantics_without_relabeling_parameter_bytes() -> Result<()> {
    let weights = support::observed_weights();
    let before = Model::new(weights.clone())?;
    let mut reset_weights = weights;
    reset_weights
        .meta
        .insert("core_state_profile".into(), "reset-each-action-v1".into());
    let after = Model::new(reset_weights)?;
    let mut expected = before.joint_v4_projection()?.components().clone();
    let actual = after.joint_v4_projection()?.components();
    assert_ne!(expected.state_semantics, actual.state_semantics);
    assert_ne!(expected.composition, actual.composition);
    expected.state_semantics = actual.state_semantics;
    expected.composition = actual.composition;
    assert_eq!(&expected, actual);
    Ok(())
}
