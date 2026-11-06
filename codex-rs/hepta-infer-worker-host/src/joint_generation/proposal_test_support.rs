//! Synthetic legal tensors exercise real code paths; they are not trained assets.

use crate::codec::Packet;
use crate::codec::Result;
use crate::codec::Tensor;
use crate::protocol::Command;
use crate::protocol::Response;
use crate::protocol::Sampler;

pub(super) struct Fixture {
    pub(super) weights: Vec<u8>,
    pub(super) public: Vec<u8>,
}

impl Fixture {
    pub(super) fn new() -> Result<Self> {
        Self::from_weights(weights())
    }
    pub(super) fn from_weights(weights: Packet) -> Result<Self> {
        let mut public = Packet::default();
        public
            .meta
            .insert("kind".into(), "joint-generator-public-v3".into());
        for (name, shape) in [
            ("image", vec![1, 3, 16, 16]),
            ("image_mask", vec![1, 3, 16, 16]),
            ("audio", vec![1, 1024]),
            ("audio_mask", vec![1, 1024]),
            ("video", vec![1, 4, 3, 16, 16]),
            ("video_mask", vec![1, 4, 3, 16, 16]),
            ("tokens", vec![1, 1]),
        ] {
            add(&mut public, name, shape, /*value*/ 0.0);
        }
        Ok(Self {
            weights: weights.encode()?,
            public: public.encode()?,
        })
    }
    pub(super) fn run(&self, state: &[u8], prefix: &[u8], command: Command) -> Result<Response> {
        crate::proposal::propose(&request(
            &self.weights,
            &self.public,
            state,
            prefix,
            command,
        ))
    }
}

pub(super) fn request(
    weights: &[u8],
    public: &[u8],
    state: &[u8],
    prefix: &[u8],
    command: Command,
) -> Vec<u8> {
    let mut bytes = b"HJREQV01".to_vec();
    bytes.extend([5; 32]);
    for blob in [weights, public, state, prefix] {
        bytes.extend((blob.len() as u32).to_le_bytes());
        bytes.extend(blob);
    }
    match command {
        Command::Init(law) => {
            bytes.push(0);
            bytes.extend(law.seed.to_le_bytes());
            bytes.push(match law.sampler {
                Sampler::Mean => 0,
                Sampler::SplitmixNormal => 1,
            });
        }
        Command::Advance(action) => bytes.extend([1, action]),
        Command::Auto(remaining) => {
            bytes.push(2);
            bytes.extend(remaining.to_le_bytes());
        }
        Command::Commit { modality, units } => {
            bytes.extend([3, modality]);
            bytes.extend(units.to_le_bytes());
        }
    }
    bytes
}

pub(super) fn raw_frame(modality: u8, start: u32, units: u32, payload: &[u8]) -> Vec<u8> {
    let mut frame = b"HGC1".to_vec();
    frame.push(modality);
    for value in [start, units, payload.len() as u32] {
        frame.extend(value.to_le_bytes());
    }
    frame.extend(payload);
    frame
}

fn add(packet: &mut Packet, name: &str, shape: Vec<usize>, value: f64) {
    let size = shape.iter().product();
    packet.tensors.insert(
        name.into(),
        Tensor {
            shape,
            data: vec![value; size],
        },
    );
}

pub(super) fn weights() -> Packet {
    let mut packet = Packet::default();
    for (key, value) in [
        ("kind", "joint-generator-weights-v3"),
        ("width", "32"),
        ("depth", "1"),
        ("mode", "dual"),
        ("boundary", "direct"),
        ("numeric_profile", "fp64-linux-libm-v1"),
        ("allow_initial_stop", "false"),
        ("suppress_redundant_verify", "false"),
    ] {
        packet.meta.insert(key.into(), value.into());
    }
    for (name, output, input) in [
        ("image_encoder.0", 32, 1536),
        ("audio_encoder.0", 32, 2048),
        ("video_encoder.0", 32, 128),
        ("encoder_fusion.0", 32, 128),
        ("initial_slots", 128, 32),
        ("feedback_projection", 32, 3),
        ("transition_input", 32, 96),
        ("emissions.text", 80, 64),
    ] {
        add(
            &mut packet,
            &format!("{name}.weight"),
            vec![output, input],
            /*value*/ 0.0,
        );
        add(
            &mut packet,
            &format!("{name}.bias"),
            vec![output],
            /*value*/ 0.0,
        );
    }
    add(
        &mut packet,
        "token_encoder.weight",
        vec![128, 32],
        /*value*/ 0.0,
    );
    add(
        &mut packet,
        "action_embedding.weight",
        vec![5, 32],
        /*value*/ 0.0,
    );
    for modality in ["image", "audio", "video", "text"] {
        add(
            &mut packet,
            &format!("adapters.{modality}.0.weight"),
            vec![32, 96],
            /*value*/ 0.0,
        );
        add(
            &mut packet,
            &format!("adapters.{modality}.0.bias"),
            vec![32],
            /*value*/ 0.0,
        );
    }
    for (modality, hidden, output) in [("image", 64, 768), ("audio", 64, 1024), ("video", 96, 3072)]
    {
        for (layer, output, input) in [(0, hidden, 64), (2, output, hidden)] {
            add(
                &mut packet,
                &format!("emissions.{modality}.{layer}.weight"),
                vec![output, input],
                /*value*/ 0.0,
            );
            add(
                &mut packet,
                &format!("emissions.{modality}.{layer}.bias"),
                vec![output],
                /*value*/ 0.0,
            );
        }
    }
    for name in ["actor", "critic", "delivery_critic"] {
        let output = if name == "actor" { 7 } else { 1 };
        add(
            &mut packet,
            &format!("{name}.0.weight"),
            vec![32, 69],
            /*value*/ 0.0,
        );
        add(
            &mut packet,
            &format!("{name}.0.bias"),
            vec![32],
            /*value*/ 0.0,
        );
        add(
            &mut packet,
            &format!("{name}.2.weight"),
            vec![output, 32],
            /*value*/ 0.0,
        );
        add(
            &mut packet,
            &format!("{name}.2.bias"),
            vec![output],
            /*value*/ 0.0,
        );
    }
    // The real actor selects STOP once its normal initial-stop mask permits it.
    packet.vector("actor.2.bias", vec![0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 4.0]);
    for name in [
        "drift_bias",
        "raw_diffusion",
        "raw_recovery",
        "raw_regeneration",
        "raw_adaptation",
        "raw_adaptation_decay",
        "raw_content_rate",
        "raw_boundary",
    ] {
        add(
            &mut packet,
            &format!("core.layers.0.{name}"),
            vec![32],
            /*value*/ 0.0,
        );
    }
    for name in ["drift_input", "content_state", "output", "content_input"] {
        add(
            &mut packet,
            &format!("core.layers.0.{name}.weight"),
            vec![32, 32],
            /*value*/ 0.0,
        );
    }
    for (name, shape, value) in [
        ("content_input.bias", vec![32], 0.0),
        ("channel_gates.weight", vec![64, 64], 0.0),
        ("channel_gates.bias", vec![64], 0.0),
        ("norm.weight", vec![32], 1.0),
        ("norm.bias", vec![32], 0.0),
    ] {
        add(&mut packet, &format!("core.layers.0.{name}"), shape, value);
    }
    packet
}
