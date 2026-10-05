//! The original bounded public review payload codec; it grants no role authority.
type ReviewResult<T> = Result<T, Box<dyn std::error::Error>>;

pub fn decode_review_payload_hex(value: &str) -> ReviewResult<Vec<u8>> {
    if value.len() > 2 * 1024 * 1024
        || !value.len().is_multiple_of(2)
        || !value.bytes().all(|b| b.is_ascii_hexdigit())
    {
        return Err("review payload hex bound".into());
    }
    value
        .as_bytes()
        .as_chunks::<2>()
        .0
        .iter()
        .map(|s| Ok(u8::from_str_radix(std::str::from_utf8(s)?, 16)?))
        .collect()
}
