//! Compare actual public crate builds, including the original regex matcher.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

const UUID: &str = "00112233-4455-6677-8899-aAbBcCdDeEfF";
static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare(source: &str) {
    assert_eq!(
        native_string::find_uuids(source),
        reference_string::find_uuids(source),
        "source bytes: {}",
        source.len()
    );
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report() {
    println!(
        "native_uuid_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn every_ascii_mutation_at_every_pattern_position_matches_the_regex() {
    for at in 0..UUID.len() {
        for byte in 0..=127 {
            let mut text = UUID.as_bytes().to_vec();
            text[at] = byte;
            let text = String::from_utf8(text).unwrap();
            compare(&text);
            compare(&format!("a{text}{UUID}Z"));
        }
    }
    for length in 0..UUID.len() {
        compare(&UUID[..length]);
        compare(&format!("{}x{UUID}", &UUID[..length]));
    }
    report();
}

#[test]
fn leftmost_non_overlapping_matches_preserve_case_without_word_boundaries() {
    for padding in 0..128 {
        for separator in ["", " ", "-", "f", "é", "汉", "😀", "\0"] {
            compare(&format!(
                "{}{UUID}{separator}{UUID}tail",
                "A".repeat(padding)
            ));
        }
    }
    for lower in 0..=36 {
        for upper in 0..=36 {
            compare(&format!("{}{UUID}{}", &UUID[..lower], &UUID[..upper]));
        }
    }
    for value in [
        "",
        "A",
        "---",
        "00000000-0000-0000-0000-000000000000",
        "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
    ] {
        compare(value);
    }
    report();
}

#[test]
fn matches_and_unicode_split_across_borrowed_windows() {
    for boundary in [4096, 8192, 12288] {
        for offset in boundary - 72..=boundary + 36 {
            for suffix in ["", "é", "汉", "😀"] {
                compare(&format!("{}{suffix}{UUID}{UUID}終", "x".repeat(offset)));
            }
        }
    }
    let mut text = String::new();
    let mut scalars = 0;
    for value in 0..=0x10_ffff {
        if let Some(ch) = char::from_u32(value) {
            text.push(ch);
            scalars += 1;
            if scalars == 128 {
                compare(&format!("{UUID}{text}{UUID}"));
                text.clear();
                scalars = 0;
            }
        }
    }
    assert_eq!(scalars, 0);
    report();
}

#[test]
fn deterministic_mixed_candidates_match_the_original_crate() {
    let alphabet = [
        '0', '9', 'A', 'F', 'a', 'f', '-', 'G', 'é', '汉', '😀', '\0',
    ];
    let mut seed = 0x30f1_59c8_d2a4_769b_u64;
    for sample in 0..4096 {
        let mut text = String::new();
        for at in 0..sample % 513 {
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            text.push(alphabet[((seed >> 17) % alphabet.len() as u64) as usize]);
            if at % 97 == 0 {
                text.push_str(UUID);
            }
        }
        compare(&text);
    }
    report();
}

#[test]
fn large_inputs_and_independent_callers_have_no_frame_total_limit() {
    for text in [
        format!("{}{UUID}", "A".repeat(2_097_153)),
        format!("{UUID}{}{UUID}", "é汉😀".repeat(233_019)),
        UUID.repeat(60_001),
    ] {
        compare(&text);
    }
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for count in 0..128 {
                    compare(&format!("{worker}-{UUID}-{}-{UUID}", "f".repeat(count)));
                }
            });
        }
    });
    report();
}

#[test]
fn measured_release_throughput_retains_exact_results() {
    for (name, text) in [
        ("no_match_ascii", "A".repeat(1_048_577)),
        ("unicode", format!("{}{UUID}", "é汉😀".repeat(116_509))),
        ("dense_matches", UUID.repeat(29_128)),
    ] {
        compare(&text);
        let native_start = std::time::Instant::now();
        for _ in 0..3 {
            std::hint::black_box(native_string::find_uuids(std::hint::black_box(&text)));
        }
        let native_nanos = native_start.elapsed().as_nanos();
        let reference_start = std::time::Instant::now();
        for _ in 0..3 {
            std::hint::black_box(reference_string::find_uuids(std::hint::black_box(&text)));
        }
        let reference_nanos = reference_start.elapsed().as_nanos();
        println!("native_uuid_benchmark name={name} bytes={} iterations=3 native_ns={native_nanos} reference_ns={reference_nanos}", text.len());
    }
    report();
}
