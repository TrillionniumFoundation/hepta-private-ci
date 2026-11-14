//! Compare both actual public crate builds, retaining the original Rust oracle.

use std::collections::BTreeMap;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use serde::Serialize;

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare<T: Serialize + ?Sized>(value: &T) {
    let native = native_string::to_ascii_json_string(value);
    let original = reference_string::to_ascii_json_string(value);
    assert_eq!(
        native
            .as_ref()
            .map(String::as_str)
            .map_err(ToString::to_string),
        original
            .as_ref()
            .map(String::as_str)
            .map_err(ToString::to_string)
    );
    if let Ok(text) = native {
        assert!(text.is_ascii());
    }
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report() {
    println!(
        "native_ascii_json_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn every_unicode_scalar_matches_the_original_formatter() {
    let mut text = String::new();
    let mut count = 0;
    for scalar in 0..=0x10_ffff {
        if let Some(ch) = char::from_u32(scalar) {
            text.push(ch);
            count += 1;
            if count == 128 {
                compare(&text);
                compare(&BTreeMap::from([(text.clone(), text.clone())]));
                text.clear();
                count = 0;
            }
        }
    }
    assert_eq!(count, 0);
    report();
}

#[test]
fn ascii_controls_and_json_punctuation_remain_serde_owned() {
    for byte in 0..=127 {
        let text = format!("A{}é汉😀Z", char::from(byte));
        compare(&text);
        compare(&[text.clone(), String::new(), text]);
    }
    for ch in [
        '\u{80}',
        '\u{7ff}',
        '\u{800}',
        '\u{d7ff}',
        '\u{e000}',
        '\u{ffff}',
        '\u{10000}',
        '\u{10ffff}',
    ] {
        compare(&ch.to_string());
    }
    report();
}

#[test]
fn borrowed_windows_keep_unicode_scalars_intact() {
    for length in (4089..=4100).chain(8185..=8198) {
        for scalar in ["é", "汉", "😀", "\u{10ffff}"] {
            let text = format!("{}{scalar}Z\n{scalar}", "A".repeat(length));
            compare(&text);
            compare(&BTreeMap::from([(text.clone(), vec![text])]));
        }
    }
    report();
}

#[test]
fn large_ascii_and_unicode_inputs_have_no_total_frame_limit() {
    for text in [
        "A".repeat(2_097_155),
        "é".repeat(1_048_579),
        "😀".repeat(524_291),
    ] {
        compare(&text);
        compare(&vec![text.as_str(), "\"\\\n", "東京"]);
    }
    report();
}

#[test]
fn generic_serde_values_and_errors_keep_their_contract() {
    compare(&serde_json::json!({"東京": [true, false, null, -1, 1.5, "🚀"], "a": {"é": 3}}));
    compare(&((), Some("汉"), None::<String>, u64::MAX, i64::MIN));
    compare(&[f64::NAN, f64::INFINITY, f64::NEG_INFINITY, -0.0]);
    compare(&BTreeMap::from([(vec![1_u8, 2], "invalid JSON key")]));
    struct Failure;
    impl Serialize for Failure {
        fn serialize<S: serde::Serializer>(&self, _: S) -> Result<S::Ok, S::Error> {
            Err(serde::ser::Error::custom("stop serialization 東京"))
        }
    }
    compare(&Failure);
    assert!(native_string::to_ascii_json_string(&Failure).is_err());
    report();
}

#[test]
fn deterministic_mixed_values_match_the_original_rust() {
    let alphabet = ['A', '\0', '\n', '"', '\\', '/', '\u{7f}', 'é', '汉', '😀'];
    let mut state = 0x6159_d0e2_83f4_7c6b_u64;
    for sample in 0..4096 {
        let mut text = String::new();
        for _ in 0..sample % 521 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            text.push(alphabet[((state >> 17) % alphabet.len() as u64) as usize]);
        }
        compare(&text);
        compare(&BTreeMap::from([(text.clone(), vec![text])]));
    }
    report();
}

#[test]
fn concurrent_serializations_have_independent_fragment_state() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for iteration in 0..128 {
                    compare(&BTreeMap::from([(
                        format!("東京{worker}"),
                        format!("é汉😀\n{iteration}"),
                    )]));
                }
            });
        }
    });
    report();
}
