use super::codec::Reader;
use super::*;
use serde_json::Value;

fn hash(value: &Value, field: &str) -> Result<Digest32, TrainingHandoffErrorV7> {
    let result: Digest32 = value[field]
        .as_str()
        .ok_or(TrainingHandoffErrorV7::Binding)?
        .parse()
        .map_err(|_| TrainingHandoffErrorV7::Binding)?;
    if result.is_zero() {
        return Err(TrainingHandoffErrorV7::Binding);
    }
    Ok(result)
}

fn count(value: &Value, field: &str) -> Result<u64, TrainingHandoffErrorV7> {
    value[field]
        .as_u64()
        .filter(|n| *n < (1_u64 << 63))
        .ok_or(TrainingHandoffErrorV7::State)
}

pub(crate) fn tensor_digest(shape: &[usize], values: &[f64]) -> Digest32 {
    let shape = shape
        .iter()
        .map(usize::to_string)
        .collect::<Vec<_>>()
        .join(",");
    let mut bytes = format!("[\"<f8\",[{shape}]]").into_bytes();
    for value in values {
        bytes.extend_from_slice(&value.to_bits().to_le_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn state_digest(metadata: &[u8], vector: &[f64]) -> Digest32 {
    let mut bytes = metadata.to_vec();
    bytes.extend_from_slice(tensor_digest(&[vector.len()], vector).as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn validate(
    serving: &TrainedCellBundleV5,
    protocol: Digest32,
    checkpoints: &[CellTrainingCheckpointV7],
    controller_version: ControllerVersion,
) -> Result<(), TrainingHandoffErrorV7> {
    let theta = serving_theta(serving)?;
    for ((head, checkpoint), theta) in serving.heads().iter().zip(checkpoints).zip(theta) {
        let metadata: Value = serde_json::from_slice(&checkpoint.state_metadata_json)
            .map_err(|_| TrainingHandoffErrorV7::State)?;
        let required = [
            "schema",
            "head",
            "protocol",
            "bindings",
            "contexts",
            "active_context",
            "step_count",
            "sampler_draw_count",
            "external_batch_count",
            "rng",
            "parameter_names",
        ];
        let fields = metadata.as_object().ok_or(TrainingHandoffErrorV7::State)?;
        let mode = metadata["head"]["mode"]
            .as_str()
            .ok_or(TrainingHandoffErrorV7::State)?;
        let names = match mode {
            "linear" => serde_json::json!(["W", "b"]),
            "gated" => serde_json::json!(["W", "a", "b", "g"]),
            _ => return Err(TrainingHandoffErrorV7::State),
        };
        let p = theta.len();
        if fields.len() != required.len()
            || required.iter().any(|key| !fields.contains_key(*key))
            || metadata["schema"] != "hepta.cell-field-training-state.v1"
            || metadata["head"]["width"] != 8
            || metadata["head"]["classes"] != 4
            || metadata["parameter_names"] != names
            || p != if mode == "linear" { 36 } else { 52 }
            || checkpoint.cell_id != *head.cell_id()
            || checkpoint.state_vector.len() != 3 * p
            || checkpoint.state_vector[..p]
                .iter()
                .zip(theta)
                .any(|(a, b)| a.to_bits() != b.to_bits())
            || checkpoint.state_vector[2 * p..].iter().any(|v| *v < 0.0)
            || hash(&metadata["bindings"], "feature_identity")? != head.feature_identity_digest()
            || metadata["bindings"]["head_mode"] != mode
            || metadata["rng"]["bit_generator"] != "PCG64"
            || metadata["protocol"]["optimizer"] != "adam"
            || metadata["protocol"]["normalization"] != "l2_times_sqrt_width"
            || state_digest(&checkpoint.state_metadata_json, &checkpoint.state_vector)
                != head.training_state_digest()
        {
            return Err(TrainingHandoffErrorV7::State);
        }
        let task = metadata["bindings"]["task"]
            .as_str()
            .ok_or(TrainingHandoffErrorV7::Binding)?;
        let seed = count(&metadata["bindings"], "seed")?;
        if checkpoint.cell_id.as_str() != format!("{task}-{mode}-seed{seed}") {
            return Err(TrainingHandoffErrorV7::Binding);
        }
        let active = metadata["active_context"]
            .as_str()
            .ok_or(TrainingHandoffErrorV7::State)?;
        let contexts = metadata["contexts"]
            .as_object()
            .ok_or(TrainingHandoffErrorV7::State)?;
        if contexts.is_empty() || contexts.len() > 32 || !contexts.contains_key(active) {
            return Err(TrainingHandoffErrorV7::State);
        }
        for name in contexts.keys() {
            if name.is_empty() || name.len() > 128 {
                return Err(TrainingHandoffErrorV7::State);
            }
            hash(&metadata["contexts"], name)?;
        }
        let clock = count(&metadata, "step_count")?;
        count(&metadata, "sampler_draw_count")?;
        if count(&metadata, "external_batch_count")? > clock {
            return Err(TrainingHandoffErrorV7::State);
        }
        controller(
            checkpoint,
            protocol,
            hash(&metadata["bindings"], "protocol_sha256")?,
            head.training_state_digest(),
            clock,
            controller_version,
        )?;
    }
    Ok(())
}

fn controller(
    checkpoint: &CellTrainingCheckpointV7,
    protocol: Digest32,
    optimizer_origin_protocol: Digest32,
    state_digest: Digest32,
    optimizer_clock: u64,
    controller_version: ControllerVersion,
) -> Result<(), TrainingHandoffErrorV7> {
    let value: Value = serde_json::from_slice(&checkpoint.controller_metadata_json)
        .map_err(|_| TrainingHandoffErrorV7::Controller)?;
    let step = count(&value, "absolute_step")?;
    let origin = count(&value, "plan_origin_step")?;
    let cursor = count(&value, "action_cursor")?;
    let horizon = checkpoint.planned_actions.len();
    let p = checkpoint.state_vector.len() / 3;
    let flat: Vec<f64> = checkpoint
        .planned_actions
        .iter()
        .flatten()
        .copied()
        .collect();
    let source = value["source_controller_json"]
        .as_str()
        .ok_or(TrainingHandoffErrorV7::Controller)?;
    let original: Value =
        serde_json::from_str(source).map_err(|_| TrainingHandoffErrorV7::Controller)?;
    let registered = count(&value, "registered_steps")?;
    if value["schema"] != controller_version.wrapper_schema()
        || value["resume_boundary"] != "committed-state-with-frozen-plan"
        || hash(&value, "protocol_sha256")? != protocol
        || hash(&value, "optimizer_origin_protocol_sha256")? != optimizer_origin_protocol
        || hash(&value, "state_sha256")? != state_digest
        || count(&value, "warmup_step_count")?.checked_add(step) != Some(optimizer_clock)
        || value["plan_horizon"] != horizon
        || cursor != checkpoint.action_cursor as u64
        || origin.checked_add(cursor) != Some(step)
        || registered == 0
        || registered > 4096
        || step > registered
        || (step == registered && cursor != horizon as u64)
        || (cursor == 0 && hash(&value, "plan_origin_state_sha256")? != state_digest)
        || (step == 0 && hash(&value, "original_warmup_state_sha256")? != state_digest)
        || hash(&value, "resolved_plan_sha256")? != tensor_digest(&[horizon, p], &flat)
        || source.len() > MAX_CHECKPOINT_METADATA / 2
        || !original.is_object()
        || hash(&value, "source_controller_sha256")? != Digest32::of_bytes(source.as_bytes())
        || hash(&original, "full_state_sha256")? != state_digest
        || hash(&original, "protocol_sha256")? != protocol
        || hash(&original["contract"], "protocol_sha256")? != protocol
        || hash(&original["contract"], "optimizer_origin_protocol_sha256")?
            != optimizer_origin_protocol
        || hash(&original["contract"], "controller_source_sha256")?
            != hash(&value, "controller_source_sha256")?
        || original["schema"] != controller_version.source_schema()
        || original["authority"] != "DENY_ALL"
        || original["production_authority"] != false
        || original["absolute_step"] != step
        || original["plan_origin_step"] != origin
        || original["action_cursor"] != cursor
        || original["plan_horizon"] != horizon
        || hash(&original, "resolved_plan_sha256")? != hash(&value, "resolved_plan_sha256")?
    {
        return Err(TrainingHandoffErrorV7::Controller);
    }
    for field in [
        "plan_origin_state_sha256",
        "original_warmup_state_sha256",
        "intended_plan_sha256",
        "panel_anchors_sha256",
        "panel_identity_sha256",
        "controller_config_sha256",
        "receipt_chain_sha256",
    ] {
        hash(&value, field)?;
    }
    for field in [
        "warmup_step_count",
        "registered_steps",
        "plan_origin_state_sha256",
        "original_warmup_state_sha256",
        "intended_plan_sha256",
    ] {
        if value[field] != original[field] {
            return Err(TrainingHandoffErrorV7::Controller);
        }
    }
    if controller_version == ControllerVersion::V8 {
        crate::training_handoff_controller_v8::validate(
            &value,
            &original,
            &checkpoint.planned_actions,
            p,
            step,
            origin,
            cursor,
            registered,
        )?;
    }
    Ok(())
}

// V5's public codec fixes exact W,b,a,g order. Read those already validated
// wire bits to compare every theta bit, including signed zero, with the full
// research-state order W,a,b,g. This does not duplicate forward computation.
fn serving_theta(serving: &TrainedCellBundleV5) -> Result<Vec<Vec<f64>>, TrainingHandoffErrorV7> {
    let bytes = serving.encode();
    let mut reader = Reader {
        bytes: &bytes,
        offset: 8,
    };
    let name = u16::from_be_bytes(reader.fixed()?) as usize;
    reader.take(name + 8 + 32 + 384 * 8 * 8)?;
    let count = u16::from_be_bytes(reader.fixed()?) as usize;
    let mut result = Vec::with_capacity(count);
    for _ in 0..count {
        let name = u16::from_be_bytes(reader.fixed()?) as usize;
        reader.take(name + 64)?;
        let tag = reader.take(1)?[0];
        let n = if tag == 0 { 36 } else { 52 };
        let mut values = Vec::with_capacity(n);
        for _ in 0..n {
            values.push(f64::from_bits(u64::from_be_bytes(reader.fixed()?)));
        }
        if tag == 1 {
            let mut sorted = values[..32].to_vec();
            sorted.extend_from_slice(&values[36..44]);
            sorted.extend_from_slice(&values[32..36]);
            sorted.extend_from_slice(&values[44..]);
            values = sorted;
        }
        result.push(values);
    }
    Ok(result)
}
