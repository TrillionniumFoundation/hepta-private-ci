//! A complete, content-derived projection of the native Joint v4 weight packet.
//!
//! This describes decoded parameters and the selected kernel contract. It does
//! not attest training, calibration quality, publication, or a model process's
//! execution. The native loader calls this before accepting v4 parameters.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;

pub const JOINT_V4_TEXT_PROFILE: &str = "utf8-byte256-scalar128-v1";
pub const JOINT_V4_MEDIA_PROFILE: &str = "ppm-wav16000-y4m4-v1";
pub const JOINT_V4_OBSERVATION_PROFILE: &str = "owner-prefix-budget-v1";
pub const JOINT_V4_OBSERVATION_FEATURES: usize = 68;
pub const JOINT_V4_NUMERIC_PROFILE: &str = "fp64-linux-libm-v1";
pub const JOINT_V4_TEXT_SCALAR_LIMIT: u32 = 128;
pub const JOINT_V4_INPUT_BYTE_LIMIT: usize = 4096;
pub const JOINT_V4_LAYER_NORM_EPSILON: f64 = 1e-5;
pub const JOINT_V4_RESIDUAL_GAIN: f64 = 0.25;
pub const JOINT_V4_CORE_DT: f64 = 0.5;
pub const JOINT_V4_STATE_SCHEMA: &[u8] = b"hepta.joint.observed-complete-proposal-state.v2";
pub const JOINT_V4_OUTPUT_SCHEMA: &[u8] = b"hepta.joint.HGC2-multimodal-prefix.v2";

const META: [&str; 13] = [
    "kind",
    "width",
    "depth",
    "mode",
    "boundary",
    "core_state_profile",
    "allow_initial_stop",
    "suppress_redundant_verify",
    "inference_profile",
    "observation_profile",
    "text_profile",
    "media_profile",
    "numeric_profile",
];
const NDU: [&str; 7] = [
    "ndu.risk",
    "ndu.discount_per_second",
    "ndu.latency_weight",
    "ndu.horizon",
    "ndu.max_forecasts",
    "ndu.action_micros",
    "ndu.critic_output",
];

/// A borrowed decoded tensor. Shape, values, name, and uniqueness are validated.
pub struct JointV4TensorViewV1<'a> {
    pub name: &'a str,
    pub shape: &'a [usize],
    pub values: &'a [f64],
}

/// Exclusive ownership of a tensor in this profile's component partition.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum JointV4TensorComponentV1 {
    Base,
    Encoder,
    Heads,
    Normalizer,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JointV4TensorBindingV1 {
    pub name: String,
    pub shape: Vec<usize>,
    pub component: JointV4TensorComponentV1,
    pub tensor_digest: Digest32,
}

/// The eleven required Cell components and the two explicitly absent overlays.
/// Intrinsic modality MLPs belong to `base`; they are not organ/Cell overlays.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct JointV4ComponentDigestsV1 {
    pub base: Digest32,
    pub organ_adapter: Option<Digest32>,
    pub cell_adapter: Option<Digest32>,
    pub heads: Digest32,
    pub composition: Digest32,
    pub encoder: Digest32,
    pub tokenizer: Digest32,
    pub normalizer: Digest32,
    /// Actual output interpretation and declared planner forecasts, not a claim
    /// that either critic or its duration forecasts were empirically calibrated.
    pub calibration: Digest32,
    pub numeric_profile: Digest32,
    pub output_schema: Digest32,
    pub state_schema: Digest32,
    pub state_semantics: Digest32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct JointV4NduProfileV1 {
    pub risk: f64,
    pub discount: f64,
    pub latency_weight: f64,
    pub horizon: usize,
    pub forecast_cap: usize,
    pub durations_micros: [u64; 7],
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum JointV4InferenceV1 {
    ActorGreedy,
    FiniteNdu(JointV4NduProfileV1),
}

/// Constructed only by the complete projection below. This value binds all
/// decoded parameter bytes; it is not a signed loading/publication receipt.
#[derive(Clone, Debug, PartialEq)]
pub struct JointV4WeightProjectionV1 {
    components: JointV4ComponentDigestsV1,
    inventory: Vec<JointV4TensorBindingV1>,
    decoded_weights_digest: Digest32,
    inference: JointV4InferenceV1,
}

impl JointV4WeightProjectionV1 {
    pub fn components(&self) -> &JointV4ComponentDigestsV1 {
        &self.components
    }
    pub fn inventory(&self) -> &[JointV4TensorBindingV1] {
        &self.inventory
    }
    /// Domain-separated decoded content identity, not the HEPTAPK3 file SHA.
    pub fn decoded_weights_digest(&self) -> Digest32 {
        self.decoded_weights_digest
    }
    pub fn inference(&self) -> JointV4InferenceV1 {
        self.inference
    }
}

/// Project the exact decoded metadata/tensors used by the native loader.
/// No component may be omitted, assigned twice, or supplied as an opaque digest.
/// Unknown fields, tensors, nonfinite values and mismatched shapes are refused.
/// The 64 MiB admission bound covers the HEPTAPK3 payload, as in the native
/// codec. Its separate 64-byte ASCII hexadecimal checksum is not part of this
/// decoded input; canonical file/checksum validation remains with the codec.
pub fn project_joint_v4_weights_v1<'a>(
    metadata: &BTreeMap<String, String>,
    tensors: impl IntoIterator<Item = JointV4TensorViewV1<'a>>,
) -> Result<JointV4WeightProjectionV1, String> {
    let text = |key: &str| {
        metadata
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing Joint v4 metadata {key}"))
    };
    for key in META {
        text(key)?;
    }
    if metadata.iter().any(|(key, value)| {
        (!META.contains(&key.as_str()) && !NDU.contains(&key.as_str()))
            || key.len() > 8192
            || value.len() > 8192
    }) {
        return Err("unknown or oversized Joint v4 metadata".into());
    }
    for (key, expected) in [
        ("kind", "joint-generator-weights-v4"),
        ("text_profile", JOINT_V4_TEXT_PROFILE),
        ("media_profile", JOINT_V4_MEDIA_PROFILE),
        ("observation_profile", JOINT_V4_OBSERVATION_PROFILE),
        ("numeric_profile", JOINT_V4_NUMERIC_PROFILE),
    ] {
        if text(key)? != expected {
            return Err(format!("unsupported Joint v4 {key}"));
        }
    }
    let width = text("width")?
        .parse::<usize>()
        .map_err(|_| "invalid Joint v4 width")?;
    let depth = text("depth")?
        .parse::<usize>()
        .map_err(|_| "invalid Joint v4 depth")?;
    let mode = text("mode")?;
    let boundary = text("boundary")?;
    if !(1..=256).contains(&width)
        || !(1..=8).contains(&depth)
        || !["dual", "single", "no_adaptation", "ordinary"].contains(&mode)
        || !["fixed", "direct"].contains(&boundary)
        || !["persistent-v1", "reset-each-action-v1"].contains(&text("core_state_profile")?)
        || !["true", "false"].contains(&text("allow_initial_stop")?)
        || !["true", "false"].contains(&text("suppress_redundant_verify")?)
    {
        return Err("unsupported Joint v4 kernel configuration".into());
    }
    let ndu = if NDU.iter().any(|key| metadata.contains_key(*key))
        || text("inference_profile")? == "ndu-finite-deterministic-v1"
    {
        Some(read_ndu(metadata)?)
    } else {
        None
    };
    let inference = match text("inference_profile")? {
        "ndu-finite-deterministic-v1" => {
            JointV4InferenceV1::FiniteNdu(ndu.ok_or("missing NDU profile")?)
        }
        // Existing actor comparisons may retain a complete, inactive NDU block.
        // It is validated and hashed, but it is never used as an active planner.
        "actor-greedy-observed-v1" => JointV4InferenceV1::ActorGreedy,
        _ => return Err("unknown Joint v4 inference profile".into()),
    };
    let expected = expected_tensors(width, depth, mode, boundary);
    let mut actual = BTreeMap::new();
    for tensor in tensors {
        if actual.insert(tensor.name, tensor).is_some() || actual.len() > 512 {
            return Err("duplicate or oversized Joint v4 tensor inventory".into());
        }
    }
    if actual.len() != expected.len() {
        return Err("unknown or missing Joint v4 tensor".into());
    }
    let mut metadata_bytes = Vec::new();
    let mut packet_payload_bytes = 8 + 4 + 4;
    for (key, value) in metadata {
        field(&mut metadata_bytes, key.as_bytes());
        field(&mut metadata_bytes, value.as_bytes());
        packet_payload_bytes += 4 + key.len() + 4 + value.len();
    }
    let mut groups: [Vec<u8>; 4] = std::array::from_fn(|_| Vec::new());
    let mut inventory = Vec::new();
    let mut composition = metadata_bytes.clone();
    let mut all = metadata_bytes.clone();
    for (name, (shape, component)) in expected {
        let tensor = actual
            .remove(name.as_str())
            .ok_or_else(|| format!("missing Joint v4 tensor {name}"))?;
        let count = shape.iter().product::<usize>();
        if tensor.shape != shape.as_slice()
            || tensor.values.len() != count
            || tensor.values.iter().any(|value| !value.is_finite())
        {
            return Err(format!("invalid Joint v4 tensor {name}"));
        }
        packet_payload_bytes += 4 + name.len() + 4 + 4 * shape.len() + 4 + 8 * count;
        if packet_payload_bytes > 64 * 1024 * 1024 {
            return Err("Joint v4 packet bound".into());
        }
        let mut structural = Vec::new();
        field(&mut structural, name.as_bytes());
        structural.extend((shape.len() as u64).to_le_bytes());
        for dimension in &shape {
            structural.extend((*dimension as u64).to_le_bytes());
        }
        let mut bytes = structural.clone();
        for value in tensor.values {
            bytes.extend(value.to_le_bytes());
        }
        let tensor_digest = digest(b"tensor-f64-le", &bytes);
        let index = match component {
            JointV4TensorComponentV1::Base => 0,
            JointV4TensorComponentV1::Encoder => 1,
            JointV4TensorComponentV1::Heads => 2,
            JointV4TensorComponentV1::Normalizer => 3,
        };
        composition.extend(&structural);
        composition.push(index as u8);
        all.extend(&structural);
        all.extend(tensor_digest.as_array());
        groups[index].extend(structural);
        groups[index].extend(tensor_digest.as_array());
        inventory.push(JointV4TensorBindingV1 {
            name,
            shape,
            component,
            tensor_digest,
        });
    }
    if !actual.is_empty() || groups.iter().any(Vec::is_empty) {
        return Err("incomplete Joint v4 component partition".into());
    }
    field(
        &mut composition,
        b"dense-fp64;no-overlay;shared-core-then-modality-residual;v1",
    );
    composition.extend(JOINT_V4_RESIDUAL_GAIN.to_le_bytes());
    let mut normalizer = b"input-no-rescale;media-range-minus1-to1;mask-range0to1;population-layer-norm-affine;epsilon-f64-le\0".to_vec();
    normalizer.extend(JOINT_V4_LAYER_NORM_EPSILON.to_le_bytes());
    normalizer.extend(&groups[3]);
    let mut calibration = b"no-calibration-transform;raw-critics;ndu-sigmoid-quality;declared-duration-forecasts;quality-not-attested\0".to_vec();
    field(&mut calibration, text("inference_profile")?.as_bytes());
    for key in NDU {
        if let Some(value) = metadata.get(key) {
            field(&mut calibration, key.as_bytes());
            field(&mut calibration, value.as_bytes());
        }
    }
    let mut state_semantics = b"context/shared/modality-slots;content-voltage-adaptation-event;feedback;verification-revision;byte-state;v1\0".to_vec();
    for key in [
        "width",
        "depth",
        "mode",
        "boundary",
        "core_state_profile",
        "allow_initial_stop",
        "suppress_redundant_verify",
    ] {
        field(&mut state_semantics, key.as_bytes());
        field(&mut state_semantics, text(key)?.as_bytes());
    }
    state_semantics.extend(JOINT_V4_CORE_DT.to_le_bytes());
    let mut tokenizer = JOINT_V4_TEXT_PROFILE.as_bytes().to_vec();
    field(
        &mut tokenizer,
        b"ordered-utf8-input;valid-next-unicode-scalar;no-learned-tokenizer",
    );
    tokenizer.extend((JOINT_V4_INPUT_BYTE_LIMIT as u64).to_le_bytes());
    tokenizer.extend(JOINT_V4_TEXT_SCALAR_LIMIT.to_le_bytes());
    let components = JointV4ComponentDigestsV1 {
        base: digest(b"base", &groups[0]),
        organ_adapter: None,
        cell_adapter: None,
        heads: digest(b"heads", &groups[2]),
        composition: digest(b"composition", &composition),
        encoder: digest(b"encoder", &groups[1]),
        tokenizer: digest(b"tokenizer", &tokenizer),
        normalizer: digest(b"normalizer", &normalizer),
        calibration: digest(b"calibration", &calibration),
        numeric_profile: digest(b"numeric-profile", JOINT_V4_NUMERIC_PROFILE.as_bytes()),
        output_schema: Digest32::of_bytes(JOINT_V4_OUTPUT_SCHEMA),
        state_schema: Digest32::of_bytes(JOINT_V4_STATE_SCHEMA),
        state_semantics: digest(b"state-semantics", &state_semantics),
    };
    Ok(JointV4WeightProjectionV1 {
        components,
        inventory,
        decoded_weights_digest: digest(b"decoded-weights", &all),
        inference,
    })
}

fn digest(component: &[u8], content: &[u8]) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.joint-v4.component-projection.v1\0",
        component,
        content,
    ])
}

fn field(out: &mut Vec<u8>, value: &[u8]) {
    out.extend((value.len() as u64).to_le_bytes());
    out.extend(value);
}

fn read_ndu(metadata: &BTreeMap<String, String>) -> Result<JointV4NduProfileV1, String> {
    let text = |key: &str| {
        metadata
            .get(key)
            .map(String::as_str)
            .ok_or_else(|| format!("missing {key}"))
    };
    let number = |key: &str| {
        text(key)?
            .parse::<f64>()
            .map_err(|_| format!("invalid {key}"))
    };
    let integer = |key: &str| {
        text(key)?
            .parse::<usize>()
            .map_err(|_| format!("invalid {key}"))
    };
    let profile = JointV4NduProfileV1 {
        risk: number("ndu.risk")?,
        discount: number("ndu.discount_per_second")?,
        latency_weight: number("ndu.latency_weight")?,
        horizon: integer("ndu.horizon")?,
        forecast_cap: integer("ndu.max_forecasts")?,
        durations_micros: text("ndu.action_micros")?
            .split(',')
            .map(|value| {
                value
                    .parse::<u64>()
                    .map_err(|_| "invalid NDU duration".to_string())
            })
            .collect::<Result<Vec<_>, _>>()?
            .try_into()
            .map_err(|_| "NDU duration width")?,
    };
    if !(profile.risk.is_finite()
        && profile.risk >= 0.0
        && profile.discount.is_finite()
        && profile.discount > 0.0
        && profile.discount <= 1.0
        && profile.latency_weight.is_finite()
        && profile.latency_weight >= 0.0)
        || !(1..=4).contains(&profile.horizon)
        || !(7..=512).contains(&profile.forecast_cap)
        || profile
            .durations_micros
            .iter()
            .any(|value| *value == 0 || *value > 3_600_000_000)
        || text("ndu.critic_output")? != "sigmoid-quality-v1"
    {
        return Err("invalid finite NDU profile".into());
    }
    Ok(profile)
}

fn expected_tensors(
    width: usize,
    depth: usize,
    mode: &str,
    boundary: &str,
) -> BTreeMap<String, (Vec<usize>, JointV4TensorComponentV1)> {
    use JointV4TensorComponentV1::Base;
    use JointV4TensorComponentV1::Encoder;
    use JointV4TensorComponentV1::Heads;
    use JointV4TensorComponentV1::Normalizer;
    let mut expected = BTreeMap::new();
    let mut add = |name: String, shape: Vec<usize>, component| {
        expected.insert(name, (shape, component));
    };
    for (name, output, input, component) in [
        ("image_encoder.0", width, 1536, Encoder),
        ("audio_encoder.0", width, 2048, Encoder),
        ("video_encoder.0", width, 4 * width, Encoder),
        ("encoder_fusion.0", width, 4 * width, Encoder),
        ("initial_slots", 4 * width, width, Base),
        ("feedback_projection", width, 3, Base),
        ("transition_input", width, 3 * width, Base),
        ("emissions.text", 256, 2 * width, Heads),
        ("text_recurrent", width, width, Encoder),
        ("text_condition", width, 2 * width, Heads),
    ] {
        add(format!("{name}.weight"), vec![output, input], component);
        add(format!("{name}.bias"), vec![output], component);
    }
    add("token_encoder.weight".into(), vec![256, width], Encoder);
    add("action_embedding.weight".into(), vec![5, width], Base);
    for modality in ["image", "audio", "video", "text"] {
        add(
            format!("adapters.{modality}.0.weight"),
            vec![width, 3 * width],
            Base,
        );
        add(format!("adapters.{modality}.0.bias"), vec![width], Base);
    }
    for (modality, hidden, output) in [("image", 64, 768), ("audio", 64, 1024), ("video", 96, 3072)]
    {
        add(
            format!("emissions.{modality}.0.weight"),
            vec![hidden, 2 * width],
            Heads,
        );
        add(format!("emissions.{modality}.0.bias"), vec![hidden], Heads);
        add(
            format!("emissions.{modality}.2.weight"),
            vec![output, hidden],
            Heads,
        );
        add(format!("emissions.{modality}.2.bias"), vec![output], Heads);
    }
    for name in ["actor", "critic", "delivery_critic"] {
        add(
            format!("{name}.0.weight"),
            vec![width, 2 * width + 5 + JOINT_V4_OBSERVATION_FEATURES],
            Heads,
        );
        add(format!("{name}.0.bias"), vec![width], Heads);
        let output = if name == "actor" { 7 } else { 1 };
        add(format!("{name}.2.weight"), vec![output, width], Heads);
        add(format!("{name}.2.bias"), vec![output], Heads);
    }
    for layer in 0..depth {
        let prefix = format!("core.layers.{layer}");
        for name in [
            "drift_bias",
            "raw_diffusion",
            "raw_recovery",
            "raw_regeneration",
            "raw_adaptation",
            "raw_adaptation_decay",
            "raw_content_rate",
        ] {
            add(format!("{prefix}.{name}"), vec![width], Base);
        }
        let boundary_name = if boundary == "direct" {
            "raw_boundary"
        } else {
            "fixed_boundary"
        };
        add(format!("{prefix}.{boundary_name}"), vec![width], Base);
        for name in ["drift_input", "content_state", "output", "content_input"] {
            add(format!("{prefix}.{name}.weight"), vec![width, width], Base);
        }
        add(format!("{prefix}.content_input.bias"), vec![width], Base);
        let gates = if mode == "single" { width } else { 2 * width };
        add(
            format!("{prefix}.channel_gates.weight"),
            vec![gates, 2 * width],
            Base,
        );
        add(format!("{prefix}.channel_gates.bias"), vec![gates], Base);
        add(format!("{prefix}.norm.weight"), vec![width], Normalizer);
        add(format!("{prefix}.norm.bias"), vec![width], Normalizer);
    }
    expected
}
