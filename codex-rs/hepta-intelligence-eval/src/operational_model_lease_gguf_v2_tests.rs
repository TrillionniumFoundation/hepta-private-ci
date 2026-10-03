#![allow(clippy::unwrap_used)]
use super::*;
fn string(bytes: &[u8]) -> Vec<u8> {
    [
        u64::try_from(bytes.len()).unwrap().to_le_bytes().as_slice(),
        bytes,
    ]
    .concat()
}
fn scalar(key: &[u8], value: u32) -> Vec<u8> {
    [
        string(key),
        4_u32.to_le_bytes().to_vec(),
        value.to_le_bytes().to_vec(),
    ]
    .concat()
}
fn gguf(entries: &[Vec<u8>]) -> Vec<u8> {
    [
        b"GGUF".to_vec(),
        3_u32.to_le_bytes().to_vec(),
        0_u64.to_le_bytes().to_vec(),
        u64::try_from(entries.len()).unwrap().to_le_bytes().to_vec(),
        entries.concat(),
    ]
    .concat()
}
#[test]
fn original_tokenizer_bytes_in_file_order_define_the_pin() {
    let tokenizer = scalar(b"tokenizer.ggml.token_type_count", 7);
    let first = gguf(&[scalar(b"general.alignment", 32), tokenizer.clone()]);
    assert_eq!(
        tokenizer_digest(first.as_slice()).unwrap(),
        Digest32::of_bytes(&tokenizer)
    );
    let unrelated = gguf(&[scalar(b"general.alignment", 64), tokenizer]);
    assert_eq!(
        tokenizer_digest(first.as_slice()).unwrap(),
        tokenizer_digest(unrelated.as_slice()).unwrap()
    );
    let changed = gguf(&[scalar(b"tokenizer.ggml.token_type_count", 8)]);
    assert_ne!(
        tokenizer_digest(first.as_slice()).unwrap(),
        tokenizer_digest(changed.as_slice()).unwrap()
    );
}
#[test]
fn malformed_or_duplicate_metadata_cannot_substitute_a_tokenizer() {
    let entry = scalar(b"tokenizer.test", 1);
    let original = gguf(std::slice::from_ref(&entry));
    for cut in [0, 3, 20, original.len() - 1] {
        assert!(tokenizer_digest(&original[..cut]).is_err());
    }
    assert!(tokenizer_digest(gguf(&[entry.clone(), entry]).as_slice()).is_err());
    assert!(tokenizer_digest(gguf(&[scalar(b"general.alignment", 32)]).as_slice()).is_err());
    let mut version = original;
    version[4..8].copy_from_slice(&2_u32.to_le_bytes());
    assert!(tokenizer_digest(version.as_slice()).is_err());
}
#[test]
fn array_and_string_budgets_reject_before_reading_unbounded_payload() {
    let array = [
        string(b"tokenizer.tokens"),
        9_u32.to_le_bytes().to_vec(),
        8_u32.to_le_bytes().to_vec(),
        65_537_u64.to_le_bytes().to_vec(),
    ]
    .concat();
    assert!(tokenizer_digest(gguf(&[array]).as_slice()).is_err());
    let nested = [
        string(b"tokenizer.tokens"),
        9_u32.to_le_bytes().to_vec(),
        9_u32.to_le_bytes().to_vec(),
        1_u64.to_le_bytes().to_vec(),
    ]
    .concat();
    assert!(tokenizer_digest(gguf(&[nested]).as_slice()).is_err());
    let huge = [
        string(b"tokenizer.tokens"),
        8_u32.to_le_bytes().to_vec(),
        1_048_577_u64.to_le_bytes().to_vec(),
    ]
    .concat();
    assert!(tokenizer_digest(gguf(&[huge]).as_slice()).is_err());
}
#[test]
fn string_array_retains_its_exact_original_lengths_and_element_type() {
    let entry = [
        string(b"tokenizer.tokens"),
        9_u32.to_le_bytes().to_vec(),
        8_u32.to_le_bytes().to_vec(),
        2_u64.to_le_bytes().to_vec(),
        string(b"yes"),
        string(b"no"),
    ]
    .concat();
    assert_eq!(
        tokenizer_digest(gguf(std::slice::from_ref(&entry)).as_slice()).unwrap(),
        Digest32::of_bytes(&entry)
    );
}
