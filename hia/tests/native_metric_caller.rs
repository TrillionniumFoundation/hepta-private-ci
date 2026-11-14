//! Compare actual public HIA dispatch with the separately compiled Rust branch.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "../../codex-rs/utils/string/src/hia_native_metric.rs"]
mod hia_native_metric;
include!(env!("CODEX_HIA_METRIC_SOURCE"));

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare(text: &str) {
    let expected = metric_reference::sanitize_metric_tag_value(text);
    let actual = sanitize_metric_tag_value(text);
    assert_eq!(actual, expected, "input bytes={}", text.len());
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report_comparisons() {
    println!(
        "native_metric_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn every_ascii_character_matches_the_original_rust() {
    for byte in 0..=127 {
        let ch = char::from(byte);
        for text in [
            ch.to_string(),
            format!("a{ch}z"),
            format!("__{ch}__"),
            format!("{ch}a{ch}"),
            format!("./-{ch}-/."),
        ] {
            compare(&text);
        }
    }
    report_comparisons();
}

#[test]
fn every_unicode_scalar_matches_the_original_rust() {
    let mut text = String::from("A");
    let mut count = 0;
    for scalar in 0..=0x10_ffff {
        if let Some(ch) = char::from_u32(scalar) {
            text.push(ch);
            count += 1;
            if count == 32 {
                text.push('Z');
                compare(&text);
                text.clear();
                text.push('A');
                count = 0;
            }
        }
    }
    if count > 0 {
        compare(&text);
    }
    report_comparisons();
}

#[test]
fn trim_default_and_cap_order_match_the_original_rust() {
    for size in [0, 1, 254, 255, 256, 257, 258, 511, 512, 513, 4097] {
        for repeated in ["_", ".", "/-", "a", "é", "汉", "😀"] {
            let middle = repeated.repeat(size);
            for text in [
                middle.clone(),
                format!("_{middle}_"),
                format!("A{middle}_"),
                format!("_{middle}Z"),
                format!("{middle}A{middle}"),
                format!("__{middle}é汉😀Z___"),
            ] {
                compare(&text);
            }
        }
    }
    report_comparisons();
}

#[test]
fn multi_megabyte_and_split_scalars_match_the_original_rust() {
    for split in 1..=3 {
        let leading = "_".repeat(1_048_575 - split);
        compare(&format!("{leading}A😀B__"));
    }
    for middle in ["_", ".", "a", "汉", "😀"] {
        let text = middle.repeat(2_097_155);
        compare(&text);
        compare(&format!("A{text}"));
        compare(&format!("{text}Z"));
    }
    report_comparisons();
}

#[test]
fn deterministic_mixed_input_matches_the_original_rust() {
    let alphabet = [
        'a', 'Z', '0', '_', '.', '-', '/', ' ', '\0', 'é', '汉', '😀',
    ];
    let mut state = 0x9a51_376e_1f08_24bc_u64;
    for sample in 0..4096 {
        let mut text = String::new();
        for _ in 0..sample % 521 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            text.push(alphabet[((state >> 17) % alphabet.len() as u64) as usize]);
        }
        compare(&text);
    }
    report_comparisons();
}

#[test]
fn concurrent_calls_do_not_share_state() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for iteration in 0..128 {
                    compare(&format!("__{worker}/é汉😀/tag-{iteration}__"));
                }
            });
        }
    });
    report_comparisons();
}
