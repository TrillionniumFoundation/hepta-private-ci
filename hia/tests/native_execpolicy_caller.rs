//! Exercise the actual public matcher and transport against separately
//! compiled, token-pinned original Rust. Policy/CLI owner tests are separate.

use std::hint::black_box;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Instant;

#[path = "../../codex-rs/execpolicy/src/hia_native_prefix.rs"]
mod hia_native_prefix;
mod rule {
    include!(env!("CODEX_HIA_EXECPOLICY_SOURCE"));
}

use rule::PatternToken;
use rule::PrefixPattern;

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn reference(pattern: &PrefixPattern) -> execpolicy_reference::PrefixPattern {
    execpolicy_reference::PrefixPattern {
        first: Arc::clone(&pattern.first),
        rest: pattern
            .rest
            .iter()
            .map(|token| match token {
                PatternToken::Single(value) => {
                    execpolicy_reference::PatternToken::Single(value.clone())
                }
                PatternToken::Alts(values) => {
                    execpolicy_reference::PatternToken::Alts(values.clone())
                }
            })
            .collect::<Vec<_>>()
            .into(),
    }
}

fn compare(pattern: &PrefixPattern, command: &[String]) {
    let before_pattern = pattern.clone();
    let before_command = command.to_vec();
    let expected = reference(pattern).matches_prefix(command);
    let actual = pattern.matches_prefix(command);
    assert_eq!(
        actual,
        expected,
        "pattern tokens={}, command tokens={}",
        pattern.rest.len() + 1,
        command.len()
    );
    assert_eq!(pattern, &before_pattern);
    assert_eq!(command, before_command);
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
}

fn report() {
    println!(
        "native_execpolicy_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn exhaustive_short_patterns_preserve_tokens_and_alternatives() {
    let atoms = [
        "", "git", "Git", "status", "sta", "status\0", "é", "e\u{301}", "汉", "😀", "\n", "-",
    ];
    let mut tails = vec![PatternToken::Alts(Vec::new())];
    for atom in atoms {
        tails.push(PatternToken::Single(atom.to_string()));
        tails.push(PatternToken::Alts(vec![atom.to_string()]));
        tails.push(PatternToken::Alts(vec![
            atom.to_string(),
            atom.to_string(),
            "".to_string(),
        ]));
    }
    for first in atoms {
        let first_only = PrefixPattern {
            first: first.into(),
            rest: Vec::new().into(),
        };
        compare(&first_only, &[]);
        for token in atoms {
            compare(&first_only, &[token.to_string()]);
            compare(
                &first_only,
                &[token.to_string(), "ignored tail".to_string()],
            );
        }
        for tail in &tails {
            let pattern = PrefixPattern {
                first: first.into(),
                rest: vec![tail.clone()].into(),
            };
            compare(&pattern, &[]);
            compare(&pattern, &[first.to_string()]);
            for token in atoms {
                compare(&pattern, &[first.to_string(), token.to_string()]);
                compare(
                    &pattern,
                    &[first.to_string(), token.to_string(), "extra".to_string()],
                );
                compare(&pattern, &[format!("{first}x"), token.to_string()]);
            }
        }
    }
    report();
}

#[test]
fn command_boundaries_and_each_mismatched_position_match_original() {
    let pattern = PrefixPattern {
        first: "git".into(),
        rest: vec![
            PatternToken::Alts(vec!["add".into(), "commit".into()]),
            PatternToken::Single("é".into()),
            PatternToken::Alts(vec!["".into(), "汉".into()]),
            PatternToken::Single("\0x".into()),
        ]
        .into(),
    };
    let command = ["git", "commit", "é", "汉", "\0x"].map(String::from);
    for length in 0..=command.len() {
        compare(&pattern, &command[..length]);
    }
    for position in 0..command.len() {
        for codepoint in 0..=127 {
            let mut changed = command.to_vec();
            changed[position] = char::from_u32(codepoint).unwrap().to_string();
            compare(&pattern, &changed);
            changed[position].push_str(&command[position]);
            compare(&pattern, &changed);
        }
        let mut changed = command.to_vec();
        changed[position].push('x');
        compare(&pattern, &changed);
    }
    let mut extra = command.to_vec();
    extra.extend(["suffix", "git", "different command", "\0"].map(String::from));
    compare(&pattern, &extra);
    report();
}

#[test]
fn unicode_bytes_are_exact_without_normalization_or_case_folding() {
    for codepoint in (0..=0x10_ffff).step_by(257).chain([
        0, 1, 0x7f, 0x80, 0x7ff, 0x800, 0xd7ff, 0xe000, 0xffff, 0x10000, 0x10ffff,
    ]) {
        let Some(character) = char::from_u32(codepoint) else {
            continue;
        };
        let text = format!("a{character}z");
        let pattern = PrefixPattern {
            first: text.as_str().into(),
            rest: vec![PatternToken::Alts(vec![
                "".into(),
                text.clone(),
                "\0".into(),
            ])]
            .into(),
        };
        compare(&pattern, &[text.clone(), text.clone()]);
        compare(&pattern, &[text.clone(), format!("{text}\0")]);
        compare(&pattern, &[format!("{text}x"), text]);
    }
    for (expected, actual) in [
        ("é", "e\u{301}"),
        ("Σ", "σ"),
        ("ß", "ss"),
        ("Ａ", "A"),
        ("a\0b", "a"),
    ] {
        let pattern = PrefixPattern {
            first: expected.into(),
            rest: Vec::new().into(),
        };
        compare(&pattern, &[actual.to_string()]);
    }
    report();
}

#[test]
fn generated_multi_token_patterns_match_original_including_empty_alternatives() {
    let atoms = [
        "", "a", "ab", "git", "add", "commit", "é", "汉", "😀", "\0", "\n", "\\", "'", "a b",
    ];
    let mut seed = 0x8a17_2d63_40cb_9ef5_u64;
    for sample in 0..4096 {
        let mut next = || {
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            (seed >> 17) as usize
        };
        let first = atoms[next() % atoms.len()].to_string();
        let mut rest = Vec::new();
        let mut command = vec![first.clone()];
        for position in 0..sample % 11 {
            let count = next() % 6;
            let values = (0..count)
                .map(|_| atoms[next() % atoms.len()].to_string())
                .collect::<Vec<_>>();
            command.push(values.first().cloned().unwrap_or_default());
            if count == 1 && position % 2 == 0 {
                rest.push(PatternToken::Single(values[0].clone()));
            } else {
                rest.push(PatternToken::Alts(values));
            }
        }
        let pattern = PrefixPattern {
            first: first.into(),
            rest: rest.into(),
        };
        compare(&pattern, &command);
        compare(&pattern, &command[..command.len() - 1]);
        let position = next() % command.len();
        command[position].push('!');
        compare(&pattern, &command);
        command[position].pop();
        command.extend(["ignored tail".to_string(), "\0".to_string()]);
        compare(&pattern, &command);
    }
    report();
}

#[test]
fn large_tokens_long_patterns_and_owned_results_preserve_the_public_contract() {
    for text in ["x".repeat(2_097_153), "é汉😀\0".repeat(209_716)] {
        let pattern = PrefixPattern {
            first: "program".into(),
            rest: vec![PatternToken::Alts(vec![
                "first mismatch".into(),
                text.clone(),
            ])]
            .into(),
        };
        let command = vec!["program".into(), text.clone(), "ignored".repeat(400_000)];
        compare(&pattern, &command);
        let mut changed = command.clone();
        changed[1].push('!');
        compare(&pattern, &changed);
        let mut result = pattern.matches_prefix(&command).unwrap();
        result[1].clear();
        assert_eq!(command[1], text);
    }
    for length in [31, 256, 1025] {
        let mut command = vec!["p".to_string()];
        let rest = (0..length)
            .map(|index| {
                let value = format!("token-{index}");
                command.push(value.clone());
                PatternToken::Alts(vec!["".into(), "wrong".into(), value.clone(), value])
            })
            .collect::<Vec<_>>();
        let pattern = PrefixPattern {
            first: "p".into(),
            rest: rest.into(),
        };
        compare(&pattern, &command);
        command.extend((0..4096).map(|index| format!("unexamined-{index}")));
        compare(&pattern, &command);
        command[length / 2].push('!');
        compare(&pattern, &command);
    }
    report();
}

#[test]
fn concurrent_calls_do_not_share_match_state() {
    let pattern = Arc::new(PrefixPattern {
        first: "git".into(),
        rest: vec![PatternToken::Alts(vec![
            "add".into(),
            "commit".into(),
            "".into(),
        ])]
        .into(),
    });
    std::thread::scope(|scope| {
        for worker in 0..8 {
            let shared = Arc::clone(&pattern);
            scope.spawn(move || {
                for iteration in 0..256 {
                    let token = ["add", "commit", "", "Add", "add\0", "git", "汉", "😀"]
                        [(worker + iteration) % 8];
                    compare(
                        &shared,
                        &["git".into(), token.into(), format!("{worker}:{iteration}")],
                    );
                }
            });
        }
    });
    report();
}

#[test]
fn bounded_optimized_latency_is_recorded_without_qualifying_product_performance() {
    for (name, pattern, command, iterations) in [
        (
            "short_match",
            PrefixPattern {
                first: "git".into(),
                rest: vec![PatternToken::Single("status".into())].into(),
            },
            vec!["git".into(), "status".into(), "--short".into()],
            10_000,
        ),
        (
            "first_mismatch",
            PrefixPattern {
                first: "git".into(),
                rest: vec![PatternToken::Single("status".into())].into(),
            },
            vec!["hg".into(), "status".into()],
            10_000,
        ),
        (
            "many_alternatives",
            PrefixPattern {
                first: "p".into(),
                rest: vec![PatternToken::Alts(
                    (0..128).map(|index| format!("token-{index}")).collect(),
                )]
                .into(),
            },
            vec!["p".into(), "token-127".into()],
            1_000,
        ),
        (
            "large_match",
            PrefixPattern {
                first: "p".into(),
                rest: vec![PatternToken::Single("x".repeat(2_097_153))].into(),
            },
            vec!["p".into(), "x".repeat(2_097_153)],
            3,
        ),
        (
            "large_pattern_empty_command",
            PrefixPattern {
                first: "p".into(),
                rest: vec![PatternToken::Single("x".repeat(2_097_153))].into(),
            },
            Vec::new(),
            3,
        ),
        (
            "large_pattern_short_command",
            PrefixPattern {
                first: "p".into(),
                rest: vec![PatternToken::Single("x".repeat(2_097_153))].into(),
            },
            vec!["p".into()],
            3,
        ),
        (
            "first_mismatch_large_alternatives",
            PrefixPattern {
                first: "p".into(),
                rest: vec![PatternToken::Alts(
                    (0..32).map(|_| "x".repeat(65_536)).collect(),
                )]
                .into(),
            },
            vec!["q".into(), "unused".into()],
            3,
        ),
    ] {
        compare(&pattern, &command);
        let original = reference(&pattern);
        let start = Instant::now();
        for _ in 0..iterations {
            black_box(black_box(&pattern).matches_prefix(black_box(&command)));
        }
        let native_ns = start.elapsed().as_nanos();
        let start = Instant::now();
        for _ in 0..iterations {
            black_box(black_box(&original).matches_prefix(black_box(&command)));
        }
        let reference_ns = start.elapsed().as_nanos();
        println!(
            "native_execpolicy_benchmark name={name} iterations={iterations} native_ns={native_ns} reference_ns={reference_ns}"
        );
    }
    report();
}
