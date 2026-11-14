// Compile the exact Codex dispatcher and HIA ABI adapter with the static HIA
// archive. Full crate integration is also exercised by just test in CI.
#[derive(Clone, Copy, Debug)]
enum ApplyPatchFileUpdateMode {
    NormalizeToLf,
    PreserveLineEndings,
}
#[derive(Debug)]
enum ApplyPatchError {
    ComputeReplacements(String),
}
#[path = "../../codex-rs/apply-patch/src/hia_native.rs"]
mod hia_native;
#[path = "../../codex-rs/apply-patch/src/seek_sequence.rs"]
mod seek_sequence;

fn compare_with_rust(lines: &[String], pattern: &[String], starts: &[usize]) {
    for mode in [
        ApplyPatchFileUpdateMode::NormalizeToLf,
        ApplyPatchFileUpdateMode::PreserveLineEndings,
    ] {
        for eof in [false, true] {
            for &start in starts {
                let expected = seek_sequence::seek_sequence(lines, pattern, start, eof, mode);
                let actual = seek_sequence::seek_sequence_checked(lines, pattern, start, eof, mode)
                    .unwrap_or_else(|ApplyPatchError::ComputeReplacements(message)| {
                        panic!("valid HIA frame rejected: {message}")
                    });
                assert_eq!(actual, expected, "{mode:?}, start={start}, eof={eof}");
            }
        }
    }
}

#[test]
fn real_dispatch_matches_original_search() {
    for mode in [
        ApplyPatchFileUpdateMode::NormalizeToLf,
        ApplyPatchFileUpdateMode::PreserveLineEndings,
    ] {
        let cases = [
            (vec!["x", "foo", "bar"], vec!["foo", "bar"], 0, false),
            (vec!["x", "foo  ", "bar\t"], vec!["foo", "bar"], 0, false),
            (vec!["x", "  foo", "  bar "], vec!["foo", "bar"], 0, false),
            (vec!["x", "alpha—beta", "y"], vec!["alpha-beta"], 0, false),
            (vec!["x", "“hi”", "y"], vec!["\"hi\""], 0, false),
            (vec!["x", "same", "same"], vec!["same"], 0, true),
            (vec!["x", "same", "same"], vec!["same"], 3, true),
            (vec!["x"], vec![], usize::MAX, false),
            (vec![], vec!["y"], 0, true),
            (vec!["x"], vec!["no"], usize::MAX, false),
        ];
        for (lines, pattern, start, eof) in cases {
            let lines: Vec<String> = lines.into_iter().map(str::to_string).collect();
            let pattern: Vec<String> = pattern.into_iter().map(str::to_string).collect();
            let expected = seek_sequence::seek_sequence(&lines, &pattern, start, eof, mode);
            let actual = seek_sequence::seek_sequence_checked(&lines, &pattern, start, eof, mode)
                .expect("valid HIA frame must be accepted");
            assert_eq!(actual, expected, "{mode:?}, start={start}, eof={eof}");
        }
    }
}

#[test]
fn multi_megabyte_line_and_pattern_match_original_search() {
    let long_line = "一😀a".repeat(262_144);
    assert_eq!(long_line.len(), 2 * 1024 * 1024);
    let pattern = vec![long_line.clone()];
    let lines = vec!["before".to_owned(), long_line, "after".to_owned()];
    compare_with_rust(&lines, &pattern, &[0, 1, 2, usize::MAX]);
    compare_with_rust(&lines, &[], &[0, 2, usize::MAX]);
}

#[test]
fn offset_table_larger_than_one_megabyte_matches_original_search() {
    let count = 140_000;
    let mut lines = vec![String::new(); count];
    lines[count - 1] = "tail".to_owned();
    compare_with_rust(
        &lines,
        &["tail".to_owned()],
        &[0, count - 1, count, usize::MAX],
    );

    // A large pattern exercises both counts and the transition between the
    // line offsets and pattern offsets, even with an almost-empty payload.
    compare_with_rust(&lines, &lines, &[0, 1, usize::MAX]);
}
#[test]
fn native_library_is_really_linked() {
    let lines = vec!["word".to_owned()];
    assert_eq!(
        hia_native::seek_sequence_checked(
            &lines,
            &lines,
            0,
            false,
            ApplyPatchFileUpdateMode::NormalizeToLf
        )
        .expect("ABI status must be success"),
        Some(0)
    );
}
