//! Differential tests of the actual public truncation API and original Rust.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "../../codex-rs/utils/string/src/hia_native_truncate.rs"]
mod hia_native_truncate;
include!(env!("CODEX_HIA_TRUNCATE_SOURCE"));

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare(text: &str, budget: usize) {
    let before = text.as_bytes().to_vec();
    let expected_chars = truncate_reference::truncate_middle_chars(text, budget);
    let expected_tokens = truncate_reference::truncate_middle_with_token_budget(text, budget);
    assert_eq!(
        truncate_middle_chars(text, budget),
        expected_chars,
        "bytes={}, budget={budget}",
        text.len()
    );
    assert_eq!(
        truncate_middle_with_token_budget(text, budget),
        expected_tokens,
        "bytes={}, budget={budget}",
        text.len()
    );
    assert_eq!(
        approx_token_count(text),
        truncate_reference::approx_token_count(text)
    );
    assert_eq!(
        text.as_bytes(),
        before,
        "native calls must preserve borrowed input"
    );
    COMPARISONS.fetch_add(3, Ordering::Relaxed);
}

fn report() {
    println!(
        "native_truncate_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn every_cut_in_short_unicode_strings_matches_original_rust() {
    let alphabet = ['a', 'é', '汉', '😀', '\0'];
    for length in 0..=4 {
        for mut code in 0..alphabet.len().pow(length) {
            let mut text = String::new();
            for _ in 0..length {
                text.push(alphabet[code % alphabet.len()]);
                code /= alphabet.len();
            }
            for budget in 0..=text.len() + 1 {
                compare(&text, budget);
            }
        }
    }
    report();
}

#[test]
fn all_unicode_scalars_participate_in_original_rust_comparisons() {
    let mut text = String::new();
    let mut count = 0;
    for scalar in 0..=0x10_ffff {
        if let Some(ch) = char::from_u32(scalar) {
            text.push(ch);
            count += 1;
            if count == 128 {
                for budget in [
                    0,
                    1,
                    text.len() / 2 - 1,
                    text.len() / 2,
                    text.len() - 1,
                    text.len(),
                ] {
                    compare(&text, budget);
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
fn semantic_edge_cases_and_marker_collisions_match_original_rust() {
    for text in [
        "",
        "a",
        "a\u{301}",
        "👩\u{200d}🔬",
        "\0\r\n\u{7f}",
        "\u{7f}\u{80}\u{7ff}\u{800}\u{d7ff}\u{e000}\u{ffff}\u{10000}\u{10ffff}",
        "…6 tokens truncated…",
        "ab…6 tokens truncated…cd",
        "😀😀😀",
        "é汉😀aé汉😀",
    ] {
        for budget in (0..=text.len() + 2).chain([
            usize::MAX / 4 - 1,
            usize::MAX / 4,
            usize::MAX / 4 + 1,
            usize::MAX,
        ]) {
            compare(text, budget);
        }
    }
    assert_eq!(
        truncate_middle_with_token_budget("…6 tokens truncated…", 0),
        ("…6 tokens truncated…".into(), None)
    );
    assert_eq!(
        truncate_middle_with_token_budget("ab…6 tokens truncated…cd", 1),
        ("ab…6 tokens truncated…cd".into(), None)
    );
    report();
}

#[test]
fn saturating_arithmetic_matches_original_rust_at_machine_limits() {
    let values = (0..1024).chain([
        usize::MAX / 4 - 1,
        usize::MAX / 4,
        usize::MAX / 4 + 1,
        usize::MAX - 4,
        usize::MAX - 3,
        usize::MAX - 2,
        usize::MAX - 1,
        usize::MAX,
    ]);
    for value in values {
        assert_eq!(
            approx_bytes_for_tokens(value),
            truncate_reference::approx_bytes_for_tokens(value),
            "tokens={value}"
        );
        assert_eq!(
            approx_tokens_from_byte_count(value),
            truncate_reference::approx_tokens_from_byte_count(value),
            "bytes={value}"
        );
        COMPARISONS.fetch_add(2, Ordering::Relaxed);
    }
    report();
}

#[test]
fn deterministic_mixed_strings_match_original_rust() {
    let alphabet = [
        'a', ' ', '\0', '\r', '\n', 'é', '汉', '😀', '\u{301}', '\u{200d}',
    ];
    let mut state = 0xa90d_9f38_317c_b126_u64;
    for sample in 0..2048 {
        let mut text = String::new();
        for _ in 0..sample % 97 {
            state = state
                .wrapping_mul(6_364_136_223_846_793_005)
                .wrapping_add(1);
            text.push(alphabet[((state >> 17) % alphabet.len() as u64) as usize]);
        }
        for budget in [
            0,
            1,
            3,
            text.len() / 2,
            text.len().saturating_sub(1),
            text.len(),
            usize::MAX,
        ] {
            compare(&text, budget);
        }
    }
    report();
}

#[test]
fn multi_megabyte_input_is_not_limited_by_bootstrap_buffer_capacity() {
    let text = "é😀汉a".repeat(210_000);
    assert!(text.len() > 2 * 1024 * 1024);
    for budget in [
        0,
        1,
        3,
        (1 << 20) - 1,
        1 << 20,
        (1 << 20) + 1,
        text.len() - 3,
        text.len() - 1,
        text.len(),
        usize::MAX,
    ] {
        compare(&text, budget);
    }
    report();
}

#[test]
fn concurrent_and_repeated_calls_have_independent_requests() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                let text = format!("worker={worker}\0é汉😀a\r\n").repeat(31);
                for iteration in 0..128 {
                    compare(&text, (iteration * 13 + worker) % (text.len() + 7));
                }
            });
        }
    });
    report();
}
