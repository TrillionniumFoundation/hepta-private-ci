//! Differential tests of the actual public caller and separately compiled Rust.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "../../codex-rs/utils/string/src/hia_native_markdown.rs"]
mod hia_native_markdown;
include!(env!("CODEX_HIA_MARKDOWN_SOURCE"));

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare(text: &str) {
    let expected = markdown_reference::normalize_markdown_hash_location_suffix(text);
    assert_eq!(
        normalize_markdown_hash_location_suffix(text),
        expected,
        "input bytes={}",
        text.len()
    );
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report() {
    println!(
        "native_markdown_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn exhaustive_short_grammar_matches_the_original_rust() {
    let alphabet = ['#', 'L', 'C', '-', '0', 'é'];
    for length in 0..=6 {
        for mut code in 0..alphabet.len().pow(length) {
            let mut text = String::new();
            for _ in 0..length {
                text.push(alphabet[code % alphabet.len()]);
                code /= alphabet.len();
            }
            compare(&text);
            compare(&format!("#L{text}"));
        }
    }
    report();
}

#[test]
fn every_unicode_scalar_matches_in_all_four_point_fields() {
    let mut text = String::new();
    let mut count = 0;
    for scalar in 0..=0x10_ffff {
        if let Some(ch) = char::from_u32(scalar) {
            text.push(ch);
            count += 1;
            if count == 128 {
                for prefix in ["#L", "#LC", "#L1-L", "#L1-L2C"] {
                    compare(&format!("{prefix}{text}"));
                }
                text.clear();
                count = 0;
            }
        }
    }
    assert_eq!(count, 0);
    report();
}

#[test]
fn numeric_text_and_range_order_are_not_reinterpreted() {
    for start in [
        "",
        "0",
        "000",
        "4294967296",
        "18446744073709551615",
        "18446744073709551616",
        "9999999999999999999999999999999999999999",
        "+5",
    ] {
        for end in ["", "0", "0001", "-2", "9C8C7-L6"] {
            compare(&format!("#L{start}"));
            compare(&format!("#L{start}C{end}"));
            compare(&format!("#L{start}C2-L{end}C0"));
        }
    }
    report();
}

#[test]
fn delimiter_and_unicode_boundaries_match_the_original_rust() {
    for padding in (4089..=4100).chain(8187..=8198) {
        let text = "0".repeat(padding);
        for suffix in [
            "",
            "C",
            "-L",
            "-LC",
            "C2-L3C4",
            "-L3C4",
            "C2C3-L4C5C6-L7",
            "😀Cé-L汉C😀",
            "-",
            "-X",
            "C2-X",
        ] {
            compare(&format!("#L{text}{suffix}"));
            compare(&format!("#L1-L{text}{suffix}"));
        }
    }
    report();
}

#[test]
fn arbitrary_total_lengths_match_the_original_rust() {
    for text in [
        "9".repeat(2_097_155),
        "汉".repeat(699_053),
        "😀".repeat(524_289),
    ] {
        compare(&format!("#L{text}C0-L{text}C1"));
        compare(&format!("#L1C{text}-L2C{text}"));
        compare(&format!("#L{text}-"));
    }
    report();
}

#[test]
fn deterministic_mixed_inputs_match_the_original_rust() {
    let alphabet = [
        '#', 'L', 'C', '-', '0', '9', '+', ':', ' ', '\0', 'é', '汉', '😀',
    ];
    let mut state = 0x746a_01b8_c953_2d6f_u64;
    for sample in 0..4096 {
        let mut text = String::new();
        for _ in 0..sample % 521 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            text.push(alphabet[((state >> 17) % alphabet.len() as u64) as usize]);
        }
        for prefix in ["", "#L", "#L1C", "#L1-L2C"] {
            compare(&format!("{prefix}{text}"));
        }
    }
    report();
}

#[test]
fn concurrent_calls_have_independent_streams() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for iteration in 0..128 {
                    compare(&format!("#L{worker}Cé汉😀-L{iteration}C0C1-L2"));
                }
            });
        }
    });
    report();
}
