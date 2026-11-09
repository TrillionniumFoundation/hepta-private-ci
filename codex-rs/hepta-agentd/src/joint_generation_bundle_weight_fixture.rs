//! Synthetic structural inputs copied from the existing native Joint fixture.
//! These are neither trained parameters nor authenticated owner observations.

use codex_hepta_infer_core::JointTensorPacketV1 as Packet;
use codex_hepta_infer_core::JointTensorV1 as Tensor;

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

fn weights() -> Packet {
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

pub(super) fn observed_weights() -> Packet {
    let mut packet = weights();
    for (key, value) in [
        ("kind", "joint-generator-weights-v4"),
        ("observation_profile", "owner-prefix-budget-v1"),
        ("text_profile", "utf8-byte256-scalar128-v1"),
        ("media_profile", "ppm-wav16000-y4m4-v1"),
        ("core_state_profile", "persistent-v1"),
        ("inference_profile", "ndu-finite-deterministic-v1"),
        ("ndu.risk", "0.25"),
        ("ndu.discount_per_second", "1"),
        ("ndu.latency_weight", "0.01"),
        ("ndu.horizon", "2"),
        ("ndu.max_forecasts", "32"),
        ("ndu.action_micros", "1000,1000,1000,1000,1000,1000,1000"),
        ("ndu.critic_output", "sigmoid-quality-v1"),
    ] {
        packet.meta.insert(key.into(), value.into());
    }
    for (name, shape) in [
        ("token_encoder.weight", vec![256, 32]),
        ("emissions.text.weight", vec![256, 64]),
        ("emissions.text.bias", vec![256]),
        ("text_recurrent.weight", vec![32, 32]),
        ("text_recurrent.bias", vec![32]),
        ("text_condition.weight", vec![32, 64]),
        ("text_condition.bias", vec![32]),
        (
            "actor.0.weight",
            vec![
                32,
                69 + codex_hepta_infer_core::JOINT_V4_OBSERVATION_FEATURES,
            ],
        ),
        (
            "critic.0.weight",
            vec![
                32,
                69 + codex_hepta_infer_core::JOINT_V4_OBSERVATION_FEATURES,
            ],
        ),
        (
            "delivery_critic.0.weight",
            vec![
                32,
                69 + codex_hepta_infer_core::JOINT_V4_OBSERVATION_FEATURES,
            ],
        ),
    ] {
        add(&mut packet, name, shape, /*value*/ 0.0);
    }
    packet
}
