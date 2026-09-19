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
fn empty_nul_and_zero_maximum_fail_closed() {
    assert_eq!(BoundedText::<4>::new(""), Err(BoundedValueError::Empty));
    assert_eq!(BoundedText::<4>::new("a\0"), Err(BoundedValueError::Nul));
    assert_eq!(
        BoundedText::<0>::new("a"),
        Err(BoundedValueError::InvalidMaximum)
    );
    assert_eq!(
        BoundedBytes::<0>::copy_from_slice(&[1]),
        Err(BoundedValueError::InvalidMaximum)
    );
}

#[test]
fn borrowed_constructors_check_bound_before_copy_and_cover_utf8_bytes() {
    for length in 1..=8 {
        let source = vec![b'x'; length];
        let value = BoundedBytes::<8>::copy_from_slice(&source);
        assert!(value.is_ok(), "length {length} should be accepted");
    }
    assert_eq!(
        BoundedBytes::<8>::copy_from_slice(&[0; 9]),
        Err(BoundedValueError::TooLarge {
            actual: 9,
            maximum: 8,
        })
    );
    assert!(BoundedText::<4>::copy_from_str("éé").is_ok());
    assert_eq!(
        BoundedText::<3>::copy_from_str("éé"),
        Err(BoundedValueError::TooLarge {
            actual: 4,
            maximum: 3,
        })
    );
}
