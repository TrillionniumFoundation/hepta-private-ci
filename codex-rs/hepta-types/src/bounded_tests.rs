use super::*;

#[test]
fn text_and_bytes_enforce_exact_bound() {
    let text = BoundedText::<5>::try_from_str("hepta");
    let Ok(text) = text else {
        panic!("bounded text rejected exact maximum");
    };
    assert_eq!(text.as_str(), "hepta");
    assert_eq!(
        BoundedBytes::<4>::try_from_slice(&[1, 2, 3, 4, 5]),
        Err(BoundedValueError::TooLarge {
            actual: 5,
            maximum: 4,
        })
    );
}

#[test]
fn boundary_and_unicode_lengths_fail_closed() {
    assert_eq!(BoundedText::<0>::try_from_str("x"), Err(BoundedValueError::InvalidMaximum));
    assert_eq!(BoundedText::<1>::try_from_str(""), Err(BoundedValueError::Empty));
    assert_eq!(
        BoundedText::<1>::try_from_str("é"),
        Err(BoundedValueError::TooLarge {
            actual: 2,
            maximum: 1,
        })
    );
    assert_eq!(BoundedText::<2>::try_from_str("é").map(|v| v.as_str().to_owned()), Ok("é".into()));
}

#[test]
fn empty_and_nul_fail_closed() {
    assert_eq!(BoundedText::<4>::try_from_str(""), Err(BoundedValueError::Empty));
    assert_eq!(BoundedText::<4>::try_from_str("a\0"), Err(BoundedValueError::Nul));
    assert_eq!(BoundedBytes::<4>::try_from_slice(&[]), Err(BoundedValueError::Empty));
}
