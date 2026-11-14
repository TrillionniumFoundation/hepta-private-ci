use super::SOURCE_LIMIT;
use super::take_bytes_at_char_boundary;

fn original_boundary(s: &str, maxb: usize) -> &str {
    if s.len() <= maxb {
        return s;
    }
    let mut end = 0;
    for (index, ch) in s.char_indices() {
        let next = index + ch.len_utf8();
        if next > maxb {
            break;
        }
        end = next;
    }
    &s[..end]
}

#[test]
fn actual_public_caller_matches_original_for_unicode_budgets() {
    for s in ["", "ASCII", "é😀中", "𐀀🧪z", "a\r\nb", "\u{10ffff}"] {
        for budget in 0..=s.len() + 2 {
            assert_eq!(
                take_bytes_at_char_boundary(s, budget),
                original_boundary(s, budget)
            );
        }
        assert_eq!(take_bytes_at_char_boundary(s, usize::MAX), s);
    }
}

#[test]
fn actual_public_caller_accepts_exact_wire_limit() {
    let input = "x".repeat(SOURCE_LIMIT - 8);
    assert_eq!(
        take_bytes_at_char_boundary(&input, input.len()),
        input.as_str()
    );
}

#[test]
#[should_panic(expected = "input exceeds locked 1 MiB")]
fn oversize_native_input_is_not_silently_fallback_to_rust() {
    let input = "x".repeat(SOURCE_LIMIT - 7);
    let _ = take_bytes_at_char_boundary(&input, input.len());
}
