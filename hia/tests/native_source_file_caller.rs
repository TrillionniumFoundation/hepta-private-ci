//! Compare the actual native SourceFile owner with the complete pinned Rust file.

use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

#[path = "../../codex-rs/apply-patch/src/hia_native_text_file.rs"]
mod hia_native_text_file;
#[path = "../../codex-rs/apply-patch/src/text_file.rs"]
mod text_file;

use source_file_reference::SourceFile as OriginalSourceFile;
use text_file::Replacement;
use text_file::SourceFile;

static COMPARISONS: AtomicUsize = AtomicUsize::new(0);

fn compare_history(contents: &str, history: &[Vec<Replacement>]) {
    let before = contents.as_bytes().to_vec();
    let edits_before = history.to_vec();
    let mut native = SourceFile::parse(contents);
    let mut original = OriginalSourceFile::parse(contents);
    assert_eq!(native.line_texts(), original.line_texts());
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
    for edits in history {
        native.apply_replacements(edits);
        original.apply_replacements(edits);
        assert_eq!(native.line_texts(), original.line_texts());
        COMPARISONS.fetch_add(1, Ordering::Relaxed);
    }
    assert_eq!(native.into_contents(), original.into_contents());
    COMPARISONS.fetch_add(1, Ordering::Relaxed);
    assert_eq!(contents.as_bytes(), before);
    assert_eq!(history, edits_before);
}

fn compare_every_prefix(contents: &str, history: &[Vec<Replacement>]) {
    // Replaying from the original input preserves the same multi-apply state.
    // Re-parsing rendered intermediate contents would lose logical line and
    // preferred-ending information and must never be used as the oracle.
    for end in 0..=history.len() {
        compare_history(contents, &history[..end]);
    }
}

fn report() {
    println!(
        "native_source_file_original_rust_comparisons={}",
        COMPARISONS.load(Ordering::Relaxed)
    );
}

#[test]
fn newline_and_multi_apply_semantics_match_the_complete_original() {
    for contents in [
        "",
        "\n",
        "\r",
        "\r\n",
        "\r\r\n",
        "\n\r",
        "x",
        "x\n",
        "x\n\n",
        "\0",
        "a\r\nb\rc\nd",
        "\u{85}\u{2028}\u{2029}",
        "same\r\nsame\n",
    ] {
        let count = OriginalSourceFile::parse(contents).line_texts().len();
        let history = vec![
            vec![],
            vec![(count, 0, vec!["inside\r\nnew\rtext".into(), String::new()])],
            vec![(0, 0, vec!["first".into()]), (0, 0, vec!["second".into()])],
            vec![],
        ];
        compare_every_prefix(contents, &history);
    }
    for contents in ["one\r\ntwo\n", "one\rtwo\n", "one\ntwo\r\n"] {
        compare_every_prefix(
            contents,
            &[
                vec![(0, usize::MAX, Vec::new())],
                vec![],
                vec![(0, 0, vec!["restored after total deletion".into()])],
            ],
        );
    }
    compare_every_prefix(
        "a\r\nb\nc",
        &[
            vec![(1, 1, vec!["one\r\nlogical\nline\r".into(), String::new()])],
            vec![(
                1,
                1,
                vec!["replace exactly one inserted logical line".into()],
            )],
            vec![],
        ],
    );
    for prefix in 0..=32 {
        let contents = format!("{}\r\né\n😀\rtail", "a".repeat(prefix));
        compare_every_prefix(&contents, &[vec![], vec![(1, 1, vec!["changed".into()])]]);
    }
    report();
}

#[test]
fn dense_lines_and_insertions_preserve_capacity_boundary_semantics() {
    for length in [0, 1, 31, 32, 63, 64, 127, 128, 255, 256, 257, 511, 512, 513] {
        let unicode = format!("{}{}", "é".repeat(length / 2), "x".repeat(length % 2));
        for contents in ["x".repeat(length), "\n".repeat(length), unicode] {
            compare_every_prefix(
                &contents,
                &[vec![], vec![(0, 0, vec!["one\r\nrow".into()])]],
            );
        }
    }
    for line_count in [0, 1, 127, 128, 255, 256, 257, 511] {
        let contents = "row\r\n".repeat(line_count);
        for inserted_count in [0, 1, 2, 255, 256, 257] {
            let inserted = (0..inserted_count)
                .map(|index| format!("{index}\nembedded\rtext"))
                .collect();
            compare_every_prefix(
                &contents,
                &[
                    vec![(line_count / 2, 0, inserted)],
                    vec![],
                    vec![(0, usize::MAX, vec![])],
                    vec![(usize::MAX, 0, vec!["restored".into()])],
                ],
            );
        }
    }
    report();
}

#[test]
fn every_short_line_break_arrangement_and_edit_window_matches() {
    let alphabet = ['a', '\r', '\n', '\0', 'é', '😀'];
    for length in 0..=5 {
        for mut encoding in 0..alphabet.len().pow(length) {
            let mut contents = String::new();
            for _ in 0..length {
                contents.push(alphabet[encoding % alphabet.len()]);
                encoding /= alphabet.len();
            }
            let count = OriginalSourceFile::parse(&contents).line_texts().len();
            compare_history(&contents, &[]);
            compare_history(&contents, &[Vec::new()]);
            for start in 0..=count {
                compare_history(
                    &contents,
                    &[vec![(start, 0, vec!["x\r\ny".into(), String::new()])]],
                );
                if start < count {
                    compare_history(
                        &contents,
                        &[vec![(start, count - start, vec!["tail".into()])]],
                    );
                }
            }
        }
    }
    report();
}

fn random_word(state: &mut u64) -> u64 {
    *state ^= *state << 13;
    *state ^= *state >> 7;
    *state ^= *state << 17;
    *state
}

fn random_text(state: &mut u64, limit: usize) -> String {
    let alphabet = ['a', 'β', '汉', '😀', '\r', '\n', '\0', '\u{2028}'];
    let length = random_word(state) as usize % (limit + 1);
    (0..length)
        .map(|_| alphabet[random_word(state) as usize % alphabet.len()])
        .collect()
}

#[test]
fn deterministic_edit_histories_preserve_original_state() {
    let mut seed = 0x534f_5552_4345_4649;
    for _ in 0..1_024 {
        let contents = random_text(&mut seed, 64);
        let mut original = OriginalSourceFile::parse(&contents);
        let mut history = Vec::new();
        for _ in 0..4 {
            let lines = original.line_texts().len();
            let edits = random_word(&mut seed) as usize % 4;
            let mut cursor = 0;
            let mut replacements = Vec::new();
            for _ in 0..edits {
                let start = cursor + random_word(&mut seed) as usize % (lines - cursor + 1);
                let old_len = random_word(&mut seed) as usize % (lines - start + 1);
                let inserted = random_word(&mut seed) as usize % 4;
                let segment = (0..inserted).map(|_| random_text(&mut seed, 16)).collect();
                replacements.push((start, old_len, segment));
                cursor = start + old_len;
            }
            original.apply_replacements(&replacements);
            history.push(replacements);
        }
        compare_every_prefix(&contents, &history);
    }
    report();
}

#[test]
fn maximum_skip_and_delete_counts_are_finite_valid_operations() {
    let cases = [
        vec![(usize::MAX, 0, vec!["append".into()])],
        vec![(0, usize::MAX, vec!["replace everything".into()])],
        vec![(usize::MAX - 3, 3, vec!["after exhausted input".into()])],
        vec![
            (0, usize::MAX, Vec::new()),
            (usize::MAX, 0, vec!["tail".into()]),
        ],
        vec![
            (usize::MAX, 0, vec!["first".into()]),
            (usize::MAX, 0, vec!["second".into()]),
        ],
        vec![(1, usize::MAX - 1, vec!["last".into()])],
    ];
    for contents in ["", "a", "a\r\nb", "a\nb\n"] {
        for edits in &cases {
            compare_every_prefix(
                contents,
                &[edits.clone(), vec![], vec![(0, 0, vec!["later".into()])]],
            );
        }
    }
    report();
}

#[test]
fn input_and_projection_ownership_match_the_original() {
    let mut source = "original\r\nunterminated".to_owned();
    let mut native = SourceFile::parse(&source);
    let mut original = OriginalSourceFile::parse(&source);
    source.replace_range(.., &"X".repeat(source.len()));
    drop(source);
    let mut edits = vec![(1, 1, vec!["owned\r\ninsert".to_owned()])];
    native.apply_replacements(&edits);
    original.apply_replacements(&edits);
    let inserted_len = edits[0].2[0].len();
    edits[0].2[0].replace_range(.., &"Y".repeat(inserted_len));
    drop(edits);
    let mut projection = native.line_texts();
    let projected_len = projection[0].len();
    projection[0].replace_range(.., &"Z".repeat(projected_len));
    projection.clear();
    drop(projection);
    assert_eq!(native.line_texts(), original.line_texts());
    assert_eq!(native.into_contents(), original.into_contents());
    COMPARISONS.fetch_add(2, Ordering::Relaxed);
    report();
}

#[test]
fn every_unicode_scalar_large_sources_and_large_line_tables_match() {
    let mut all_scalars = String::new();
    for value in 0..=0x10_ffff {
        if let Some(character) = char::from_u32(value) {
            all_scalars.push(character);
        }
    }
    assert!(all_scalars.len() > 1 << 20);
    let count = OriginalSourceFile::parse(&all_scalars).line_texts().len();
    compare_history(
        &all_scalars,
        &[
            vec![],
            vec![(count, 0, vec!["all scalar bytes retained".into()])],
        ],
    );
    let long_line = "é汉😀a".repeat(220_000);
    compare_every_prefix(&long_line, &[vec![], vec![(1, 0, vec!["tail".into()])]]);
    let dense = "x\n".repeat(70_000);
    compare_history(
        &dense,
        &[vec![
            (0, 1, vec!["head\r\ninside".into()]),
            (69_999, 1, vec!["tail".into()]),
        ]],
    );
    report();
}

#[test]
fn independent_source_files_remain_reentrant_across_threads() {
    std::thread::scope(|scope| {
        for worker in 0..8 {
            scope.spawn(move || {
                for iteration in 0..64 {
                    let ending = ["\r\n", "\r", "\n"][(worker + iteration) % 3];
                    let contents = format!("{worker}{ending}é汉😀{ending}tail");
                    compare_every_prefix(
                        &contents,
                        &[
                            vec![],
                            vec![(0, usize::MAX, Vec::new())],
                            vec![(0, 0, vec![format!("{iteration}\r\ninside"), String::new()])],
                        ],
                    );
                }
            });
        }
    });
    report();
}

#[test]
fn invalid_order_and_index_overflow_are_separate_precondition_failures() {
    // This compares only failure, not the post-panic state or diagnostic text.
    // Both crates are compiled with debug assertions and overflow checks on.
    // These inputs are outside the valid replacement contract tested above.
    for edits in [
        vec![(2, 0, Vec::new()), (1, 0, Vec::new())],
        vec![(usize::MAX, 1, Vec::new())],
    ] {
        let mut native = SourceFile::parse("a\r\nb");
        let mut original = OriginalSourceFile::parse("a\r\nb");
        let expected = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            original.apply_replacements(&edits);
        }));
        let actual = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            native.apply_replacements(&edits);
        }));
        assert!(expected.is_err() && actual.is_err());
    }
    println!("native_source_file_separate_precondition_failures=2");
    report();
}
