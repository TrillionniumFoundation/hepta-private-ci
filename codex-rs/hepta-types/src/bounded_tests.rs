use super::*;

#[test]
fn text_and_bytes_enforce_exact_bound() {
    let text = BoundedText::<5>::new("hepta");
    let Ok(text) = text else {
        panic!("bounded text rejected exact maximum");
    };
    assert_eq!(text.as_str(), "hepta");
    assert_eq!(
        BoundedBytes::<4>::new(vec![1, 2, 3, 4, 5]),
        Err(BoundedValueError::TooLarge {
            actual: 5,
            maximum: 4,
        })
    );
}

#[test]
fn empty_zero_max_and_nul_fail_closed() {
    assert_eq!(BoundedText::<4>::new(""), Err(BoundedValueError::Empty));
    assert_eq!(BoundedText::<4>::new("a\0"), Err(BoundedValueError::Nul));
    assert_eq!(
        BoundedText::<0>::new("x"),
        Err(BoundedValueError::InvalidMaximum)
    );
    assert_eq!(
        BoundedBytes::<0>::new(vec![1]),
        Err(BoundedValueError::InvalidMaximum)
    );
}

#[test]
fn utf8_bounds_are_encoded_bytes_not_scalar_count() {
    let exact = BoundedText::<4>::try_from_str("éé");
    let Ok(exact) = exact else {
        panic!("four-byte UTF-8 value rejected at exact bound");
    };
    assert_eq!(exact.as_str(), "éé");
    assert_eq!(
        BoundedText::<3>::try_from_str("éé"),
        Err(BoundedValueError::TooLarge {
            actual: 4,
            maximum: 3,
        })
    );
}

#[test]
fn borrowed_preflight_constructors_cover_max_and_max_plus_one() {
    let exact = [7_u8; 8];
    let too_large = [7_u8; 9];
    let bytes = BoundedBytes::<8>::try_from_slice(&exact);
    let Ok(bytes) = bytes else {
        panic!("exact borrowed byte bound rejected");
    };
    assert_eq!(bytes.as_slice(), exact);
    assert_eq!(
        BoundedBytes::<8>::try_from_slice(&too_large),
        Err(BoundedValueError::TooLarge {
            actual: 9,
            maximum: 8,
        })
    );

    let exact_text = "x".repeat(8);
    let too_large_text = "x".repeat(9);
    assert!(BoundedText::<8>::try_from_str(&exact_text).is_ok());
    assert_eq!(
        BoundedText::<8>::try_from_str(&too_large_text),
        Err(BoundedValueError::TooLarge {
            actual: 9,
            maximum: 8,
        })
    );
}
