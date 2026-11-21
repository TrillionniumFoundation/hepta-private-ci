use super::ChatComposer;
use super::tests::new_test_composer;
use codex_protocol::user_input::TextElement;
use pretty_assertions::assert_eq;

#[test]
fn shell_draft_round_trip_preserves_unicode_element_ranges() {
    let (mut composer, _rx) = new_test_composer();
    let visible_text = "🦀 echo [日本語]";
    let canonical_text = format!("!{visible_text}");
    let placeholder = "[日本語]";
    let start = visible_text.find(placeholder).expect("placeholder in draft");
    let visible_element = TextElement::new(
        (start..visible_text.len()).into(),
        Some(placeholder.to_string()),
    );
    let canonical_element = TextElement::new(
        ((start + 1)..canonical_text.len()).into(),
        Some(placeholder.to_string()),
    );

    composer.set_text_content(
        canonical_text.clone(),
        vec![canonical_element.clone()],
        Vec::new(),
    );
    assert_eq!(
        (
            composer.draft.is_bash_mode,
            composer.draft.textarea.text(),
            composer.draft.textarea.text_elements(),
        ),
        (true, visible_text, vec![visible_element.clone()]),
    );
    assert_eq!(
        (composer.current_text(), composer.current_text_elements()),
        (canonical_text, vec![canonical_element]),
    );

    composer.set_text_content(
        visible_text.to_string(),
        vec![visible_element.clone()],
        Vec::new(),
    );
    assert_eq!(
        (
            composer.draft.is_bash_mode,
            composer.current_text(),
            composer.current_text_elements(),
        ),
        (false, visible_text.to_string(), vec![visible_element]),
    );
}

#[test]
fn signed_element_shift_rejects_underflow_and_overflow() {
    for (range, shift) in [
        (0..1, -1),
        ((usize::MAX - 1)..usize::MAX, 1),
        (1..2, isize::MIN),
    ] {
        let element = TextElement::new(range.into(), /*placeholder*/ None);
        assert_eq!(ChatComposer::shift_text_element(element, shift), None);
    }
}

#[test]
fn negative_element_shift_preserves_large_unsigned_offsets() {
    let element = TextElement::new(
        ((usize::MAX - 1)..usize::MAX).into(),
        Some("retained placeholder".to_string()),
    );
    let expected = TextElement::new(
        ((usize::MAX - 2)..(usize::MAX - 1)).into(),
        Some("retained placeholder".to_string()),
    );
    assert_eq!(
        ChatComposer::shift_text_element(element, /*shift*/ -1),
        Some(expected),
    );
}
