use super::ChatComposer;
use super::TextElement;
use pretty_assertions::assert_eq;

#[test]
fn signed_shifts_preserve_the_complete_text_element() {
    let original = TextElement::new((2..6).into(), Some("attachment".to_string()));
    for (shift, expected) in [(3, 5..9), (0, 2..6), (-2, 0..4)] {
        assert_eq!(
            ChatComposer::shift_text_element(original.clone(), shift),
            Some(TextElement::new(
                expected.into(),
                Some("attachment".to_string())
            )),
            "shift {shift}"
        );
    }
}

#[test]
fn signed_shifts_reject_underflow_overflow_and_empty_ranges() {
    for (range, shift) in [
        (0..1, -1),
        (1..2, -2),
        (0..1, isize::MIN),
        (usize::MAX - 1..usize::MAX, 1),
        (usize::MAX - 1..usize::MAX, isize::MAX),
        (4..4, 0),
    ] {
        let element = TextElement::new(range.into(), /*placeholder*/ None);
        assert_eq!(ChatComposer::shift_text_element(element, shift), None);
    }
}
