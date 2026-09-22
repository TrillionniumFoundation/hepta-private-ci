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
        BoundedBytes::<0>::try_from_slice(&[1]),
        Err(BoundedValueError::InvalidMaximum)
    );
}

#[test]
fn borrowed_constructors_validate_before_copy_and_count_utf8_bytes() {
    let source = "éé";
    let value = BoundedText::<4>::try_from_str(source);
    let Ok(value) = value else {
        panic!("four UTF-8 bytes should satisfy the exact bound");
    };
    assert_eq!(value.as_str(), source);
    assert_eq!(
        BoundedText::<3>::try_from_str(source),
        Err(BoundedValueError::TooLarge {
            actual: 4,
            maximum: 3,
        })
    );

    let bytes = [1_u8, 2, 3, 4];
    let copied = BoundedBytes::<4>::try_from_slice(&bytes);
    let Ok(copied) = copied else {
        panic!("four bytes should satisfy the exact bound");
    };
    assert_eq!(copied.as_slice(), bytes);
    assert_eq!(
        BoundedBytes::<3>::try_from_slice(&bytes),
        Err(BoundedValueError::TooLarge {
            actual: 4,
            maximum: 3,
        })
    );
}
