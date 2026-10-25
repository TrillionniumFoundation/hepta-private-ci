//! Validate one external edit against the actual original editor revision.
use super::text::Run;
use super::text::{self};
use accesskit::TextEdit;
use accesskit::TextEditOperation;
use std::ops::Range;

pub(super) fn validate(
    runs: &[Run],
    observed: &str,
    current: &str,
    edit: &TextEdit,
    limit: usize,
) -> Option<Range<usize>> {
    if observed != current
        || edit.expected.as_ref() != current
        || current.len() > limit
        || current.contains('\0')
    {
        return None;
    }
    let (start, end) = text::selection(runs, edit.range)?;
    if start > end
        || end > current.len()
        || !current.is_char_boundary(start)
        || !current.is_char_boundary(end)
    {
        return None;
    }
    if let TextEditOperation::Replace(replacement) = &edit.operation {
        if replacement.contains('\0')
            || current
                .len()
                .checked_sub(end - start)?
                .checked_add(replacement.len())?
                > limit
        {
            return None;
        }
    }
    Some(start..end)
}

#[cfg(test)]
mod tests {
    use super::*;
    use accesskit::NodeId;
    use accesskit::TextSelection;

    fn request(value: &str) -> (Vec<Run>, TextEdit) {
        let (_, runs) = text::build(value, |part| NodeId(10 + part as u64));
        let range = TextSelection {
            anchor: text::position(&runs, 0).unwrap(),
            focus: text::position(&runs, "中文".len()).unwrap(),
        };
        (
            runs,
            TextEdit {
                range,
                expected: value.into(),
                operation: TextEditOperation::Replace("你好".into()),
            },
        )
    }

    #[test]
    fn selected_cjk_replacement_preserves_surrounding_text() {
        let original = "中文 e\u{301} 👨‍👩‍👧‍👦";
        let (runs, edit) = request(original);
        let range = validate(&runs, original, original, &edit, 16384).unwrap();
        let mut changed = original.to_owned();
        changed.replace_range(range, "你好");
        assert_eq!(changed, "你好 e\u{301} 👨‍👩‍👧‍👦");
    }

    #[test]
    fn stale_text_and_old_run_identity_are_refused() {
        let original = "中文";
        let (runs, mut edit) = request(original);
        assert!(validate(&runs, original, "你好", &edit, 16384).is_none());
        edit.range.anchor.node = NodeId(999);
        assert!(validate(&runs, original, original, &edit, 16384).is_none());
    }

    #[test]
    fn oversized_nul_and_invalid_range_leave_editor_unmodified() {
        let original = "中文";
        let (runs, mut edit) = request(original);
        edit.operation = TextEditOperation::Replace("界".repeat(6000).into_boxed_str());
        assert!(validate(&runs, original, original, &edit, 16384).is_none());
        edit.operation = TextEditOperation::Replace("a\0b".into());
        assert!(validate(&runs, original, original, &edit, 16384).is_none());
        edit.operation = TextEditOperation::Cut;
        edit.range.focus.character_index = 3;
        assert!(validate(&runs, original, original, &edit, 16384).is_none());
        assert_eq!(original, "中文");
    }

    #[test]
    fn clipboard_reply_must_still_match_original_text_and_run_identity() {
        let original = "中文";
        let (runs, mut edit) = request(original);
        edit.range.focus = edit.range.anchor;
        edit.operation = TextEditOperation::Paste;
        assert_eq!(
            validate(&runs, original, original, &edit, 16384),
            Some(0..0)
        );
        edit.operation = TextEditOperation::Replace("你好".into());
        assert_eq!(
            validate(&runs, original, original, &edit, 16384),
            Some(0..0)
        );
        assert!(validate(&runs, original, "新稿", &edit, 16384).is_none());
        edit.range.anchor.node = NodeId(999);
        assert!(validate(&runs, original, original, &edit, 16384).is_none());
    }
}
