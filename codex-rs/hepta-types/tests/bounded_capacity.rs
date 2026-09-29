use codex_hepta_types::BoundedBytes;
use codex_hepta_types::BoundedText;
use codex_hepta_types::BoundedValueError;

#[test]
fn owned_small_values_do_not_retain_oversized_capacity() {
    let mut text = String::with_capacity(1 << 20);
    text.push_str("hello");
    let text = BoundedText::<16>::new(text).expect("text").into_inner();
    assert_eq!(text, "hello");
    assert!(text.capacity() <= 16);
    let mut bytes = Vec::with_capacity(1 << 20);
    bytes.extend_from_slice(b"hello");
    let bytes = BoundedBytes::<16>::new(bytes).expect("bytes").into_inner();
    assert_eq!(bytes, b"hello");
    assert!(bytes.capacity() <= 16);
}

#[test]
fn within_bound_owned_allocations_are_reused() {
    let text = String::from("hello");
    let pointer = text.as_ptr();
    let value = BoundedText::<16>::new(text).expect("text").into_inner();
    assert_eq!(pointer, value.as_ptr());
    let bytes = b"hello".to_vec();
    let pointer = bytes.as_ptr();
    let value = BoundedBytes::<16>::new(bytes).expect("bytes").into_inner();
    assert_eq!(pointer, value.as_ptr());
}

#[test]
fn borrowed_and_cloned_values_keep_capacity_within_declared_bound() {
    let text = BoundedText::<16>::try_from_str("hello").expect("borrowed text");
    let text = text.clone().into_inner();
    assert_eq!(text, "hello");
    assert!(text.capacity() <= 16);

    let bytes = BoundedBytes::<16>::try_from_slice(b"hello").expect("borrowed bytes");
    let bytes = bytes.clone().into_inner();
    assert_eq!(bytes, b"hello");
    assert!(bytes.capacity() <= 16);
}

#[test]
fn borrowed_ingress_checks_encoded_bytes_and_preserves_rejections() {
    assert_eq!(
        BoundedText::<3>::try_from_str("éé"),
        Err(BoundedValueError::TooLarge {
            actual: 4,
            maximum: 3
        })
    );
    assert_eq!(
        BoundedText::<8>::try_from_str("a\0b"),
        Err(BoundedValueError::Nul)
    );
    assert_eq!(
        BoundedBytes::<8>::try_from_slice(&[]),
        Err(BoundedValueError::Empty)
    );
    assert_eq!(
        BoundedText::<0>::new("x"),
        Err(BoundedValueError::InvalidMaximum)
    );
}
