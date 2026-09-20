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
fn empty_and_nul_fail_closed() {
    assert_eq!(BoundedText::<4>::new(""), Err(BoundedValueError::Empty));
    assert_eq!(BoundedText::<4>::new("a\0"), Err(BoundedValueError::Nul));
}
