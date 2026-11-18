use crate::TruncationPolicy;
use crate::truncate_function_output_items_with_policy;
use codex_protocol::models::DEFAULT_IMAGE_DETAIL;
use codex_protocol::models::FunctionCallOutputContentItem;
use pretty_assertions::assert_eq;
use std::cell::RefCell;
use std::panic::AssertUnwindSafe;
use std::panic::catch_unwind;

fn text(value: &str) -> FunctionCallOutputContentItem {
    FunctionCallOutputContentItem::InputText {
        text: value.to_string(),
    }
}

fn audio(value: &str) -> FunctionCallOutputContentItem {
    FunctionCallOutputContentItem::InputAudio {
        audio_url: value.to_string(),
    }
}

#[test]
fn empty_input_never_calls_the_audio_estimator() {
    assert_eq!(
        truncate_function_output_items_with_policy(&[], TruncationPolicy::Bytes(0), |_| {
            panic!("empty input has no audio");
        }),
        Vec::<FunctionCallOutputContentItem>::new()
    );
}

#[test]
fn zero_budget_retains_opaque_items_and_zero_cost_audio_in_order() {
    let image = FunctionCallOutputContentItem::InputImage {
        image_url: "image:opaque".to_string(),
        detail: Some(DEFAULT_IMAGE_DETAIL),
    };
    let encrypted = FunctionCallOutputContentItem::EncryptedContent {
        encrypted_content: "opaque ciphertext".to_string(),
    };
    let items = [
        text(""),
        audio("free"),
        image.clone(),
        text("omitted"),
        encrypted.clone(),
        audio("costly"),
    ];
    let calls = RefCell::new(Vec::new());
    let output =
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Bytes(0), |url| {
            calls.borrow_mut().push(url.to_string());
            usize::from(url == "costly")
        });
    assert_eq!(
        output,
        vec![
            audio("free"),
            image,
            encrypted,
            text("[omitted 2 text items ...]"),
            text("[omitted 1 audio items ...]"),
        ]
    );
    assert_eq!(calls.into_inner(), vec!["free", "costly"]);
}

#[test]
fn positive_budget_keeps_empty_text_and_equality_fits() {
    let items = [text(""), text("a"), text(""), audio("free")];
    let output =
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Bytes(1), |_| 0);
    assert_eq!(
        output,
        vec![
            text(""),
            text("a"),
            audio("free"),
            text("[omitted 1 text items ...]"),
        ]
    );
}

#[test]
fn omitted_audio_leaves_text_budget_and_marker_is_not_recharged() {
    let items = [
        audio("costly"),
        text("ab"),
        text("cdef"),
        text(""),
        audio("free"),
    ];
    let calls = RefCell::new(Vec::new());
    let output =
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Bytes(4), |url| {
            calls.borrow_mut().push(url.to_string());
            if url == "costly" { 2 } else { 0 }
        });
    assert_eq!(
        output,
        vec![
            text("ab"),
            text("c…2 chars truncated…f"),
            audio("free"),
            text("[omitted 1 text items ...]"),
            text("[omitted 1 audio items ...]"),
        ]
    );
    assert_eq!(calls.into_inner(), vec!["costly", "free"]);
}

#[test]
fn token_cost_uses_utf8_bytes_before_truncating() {
    let items = [text("ééé"), text(""), audio("free")];
    let output =
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Tokens(1), |_| 0);
    assert_eq!(
        output,
        vec![
            text("é…1 tokens truncated…é"),
            audio("free"),
            text("[omitted 1 text items ...]"),
        ]
    );
}

#[test]
fn full_text_larger_than_a_native_frame_keeps_its_original_utf8_oracle() {
    let value = "é".repeat(524_289);
    assert!(value.len() > 1_048_576);
    let items = [FunctionCallOutputContentItem::InputText { text: value }];
    let output =
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Bytes(4), |_| {
            panic!("text has no audio");
        });
    assert_eq!(output, vec![text("é…524287 chars truncated…é")]);
}

#[test]
fn audio_cost_saturates_and_zero_cost_still_survives_exhaustion() {
    for policy in [
        TruncationPolicy::Bytes(usize::MAX),
        TruncationPolicy::Tokens(usize::MAX),
    ] {
        let calls = RefCell::new(Vec::new());
        let items = [audio("maximum"), text(""), audio("free")];
        let output = truncate_function_output_items_with_policy(&items, policy, |url| {
            calls.borrow_mut().push(url.to_string());
            if url == "maximum" { usize::MAX } else { 0 }
        });
        assert_eq!(
            output,
            vec![
                audio("maximum"),
                audio("free"),
                text("[omitted 1 text items ...]"),
            ]
        );
        assert_eq!(calls.into_inner(), vec!["maximum", "free"]);
    }
}

#[test]
fn estimator_panic_preserves_the_observed_callback_prefix() {
    let calls = RefCell::new(Vec::new());
    let items = [
        text("head"),
        audio("first"),
        text("middle-long"),
        audio("stop"),
        audio("unreachable"),
    ];
    let outcome = catch_unwind(AssertUnwindSafe(|| {
        truncate_function_output_items_with_policy(&items, TruncationPolicy::Bytes(8), |url| {
            calls.borrow_mut().push(url.to_string());
            if url == "stop" {
                panic!("estimator stopped");
            }
            0
        })
    }));
    assert!(outcome.is_err());
    assert_eq!(calls.into_inner(), vec!["first", "stop"]);
}
