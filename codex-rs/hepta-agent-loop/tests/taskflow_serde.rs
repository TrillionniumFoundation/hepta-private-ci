#![cfg(feature = "taskflow-owner")]
#![allow(clippy::expect_used, reason = "isolated codec fixtures fail loudly")]

use codex_hepta_agent_loop::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;
use serde_json::json;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("original validated constructor")
}

fn frame() -> Frame {
    let payload = "original context";
    Frame {
        binding: TurnBinding {
            run_id: id("run:1"),
            turn_id: id("turn:1"),
            generation: Generation::new(7).expect("generation"),
            admission_digest: Digest32::of_bytes(b"original admission"),
            deadline_unix_ms: 1_000,
        },
        revision: 0,
        round: 0,
        consumed_tokens: 0,
        phase: Phase::Model(ModelRequest {
            request_id: id("model:1"),
            payload: payload.into(),
            context_digest: Digest32::of_bytes(payload.as_bytes()),
            input_tokens: 3,
            maximum_provider_input_tokens: 10,
            maximum_output_tokens: 4,
        }),
    }
}

#[test]
fn retained_frame_roundtrips_exact_validated_primitives() {
    let original = frame();
    let bytes = serde_json::to_vec(&original).expect("encode");
    let decoded: Frame = serde_json::from_slice(&bytes).expect("validated decode");
    assert_eq!(decoded, original);
    assert_eq!(serde_json::to_vec(&decoded).expect("same bytes"), bytes);
    let encoded = serde_json::to_value(original).expect("wire value");
    assert_eq!(encoded["binding"]["run_id"], "run:1");
    assert_eq!(encoded["binding"]["generation"], 7);
    assert_eq!(
        encoded["binding"]["admission_digest"],
        Digest32::of_bytes(b"original admission").to_string()
    );
}

#[test]
fn retained_identifiers_reuse_the_original_grammar_and_byte_bound() {
    let original = serde_json::to_value(frame()).expect("frame");
    for malformed in [
        json!(""),
        json!("has space"),
        json!("../outside"),
        json!("embedded\0nul"),
        json!("a".repeat(129)),
        json!("细胞"),
        json!(7),
        json!(null),
    ] {
        for field in ["run_id", "turn_id"] {
            let mut candidate = original.clone();
            candidate["binding"][field] = malformed.clone();
            assert!(serde_json::from_value::<Frame>(candidate).is_err());
        }
    }
    let original = ToolCall {
        call_id: id("call:1"),
        name: id("owned.read"),
        arguments: "{}".into(),
    };
    for field in ["call_id", "name"] {
        let mut value = serde_json::to_value(&original).expect("call");
        value[field] = json!("not an identifier");
        assert!(serde_json::from_value::<ToolCall>(value).is_err());
    }
}

#[test]
fn retained_generation_rejects_zero_and_non_u64_wire_values() {
    let original = serde_json::to_value(frame()).expect("frame");
    for malformed in [json!(0), json!(-1), json!(1.5), json!("7"), json!(null)] {
        let mut candidate = original.clone();
        candidate["binding"]["generation"] = malformed;
        assert!(serde_json::from_value::<Frame>(candidate).is_err());
    }
    for generation in [1, u64::MAX] {
        let mut candidate = original.clone();
        candidate["binding"]["generation"] = json!(generation);
        assert_eq!(
            serde_json::from_value::<Frame>(candidate)
                .expect("nonzero u64")
                .binding
                .generation,
            Generation::new(generation).expect("same constructor")
        );
    }
}

#[test]
fn retained_digests_require_canonical_shape_without_coercion() {
    let original = serde_json::to_value(frame()).expect("frame");
    for malformed in [
        json!(""),
        json!("a".repeat(63)),
        json!("a".repeat(65)),
        json!("A".repeat(64)),
        json!("g".repeat(64)),
        json!("界".repeat(32)),
        json!([0, 1]),
        json!(null),
    ] {
        let mut candidate = original.clone();
        candidate["binding"]["admission_digest"] = malformed;
        assert!(serde_json::from_value::<Frame>(candidate).is_err());
    }
    // Zero is a valid authority-free primitive. Native turn admission and
    // continuation checks still reject it at their existing semantic boundary.
    let mut candidate = original;
    candidate["binding"]["admission_digest"] = json!("0".repeat(64));
    assert_eq!(
        serde_json::from_value::<Frame>(candidate)
            .expect("primitive zero")
            .binding
            .admission_digest,
        Digest32::ZERO
    );
}

#[test]
fn observation_receipts_roundtrip_and_unknown_dto_fields_still_reject() {
    let call = ToolCall {
        call_id: id("call:1"),
        name: id("owned.read"),
        arguments: "{}".into(),
    };
    let completed = Transition::ModelCompleted(ModelOutput {
        request_id: id("model:1"),
        continuation_digest: Digest32::of_bytes(b"retained provider receipt"),
        text: "observed".into(),
        calls: vec![call],
        usage: Usage {
            input_tokens: 8,
            output_tokens: 2,
        },
    });
    for original in [
        completed,
        Transition::ToolCompleted {
            operation_key: Digest32::of_bytes(b"original operation"),
            output: "retained output".into(),
        },
    ] {
        let bytes = serde_json::to_vec(&original).expect("observation encode");
        assert_eq!(
            serde_json::from_slice::<Transition>(&bytes).expect("observation decode"),
            original
        );
    }
    let mut value = serde_json::to_value(frame()).expect("frame");
    value["binding"]["new_authority"] = json!(true);
    assert!(serde_json::from_value::<Frame>(value).is_err());
    let mut value = serde_json::to_value(frame()).expect("frame");
    value["unexpected"] = json!(true);
    assert!(serde_json::from_value::<Frame>(value).is_err());
}
