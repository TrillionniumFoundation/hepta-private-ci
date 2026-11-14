// Compile the exact Codex dispatcher and HIA ABI adapter against a real HIA ELF.
// This does not pretend to replace full Cargo application integration.
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
fn oversized_input_is_an_error_not_a_false_miss() {
    let lines = vec!["x".repeat(1_048_576)];
    let result = seek_sequence::seek_sequence_checked(
        &lines,
        &["x".to_owned()],
        0,
        false,
        ApplyPatchFileUpdateMode::NormalizeToLf,
    );
    assert!(matches!(
        result,
        Err(ApplyPatchError::ComputeReplacements(message))
            if message.contains("exceeds locked 1 MiB")
    ));
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
