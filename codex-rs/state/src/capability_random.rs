use uuid::Uuid;

/// Mint an opaque 32-byte process-local capability from two independent UUIDv4 draws.
///
/// UUIDv4 fixes its version and variant bits, so this value carries 244 bits of
/// OS-seeded randomness rather than claiming 256 bits of entropy. The complete
/// 32-byte value is still suitable as an unguessable local fencing capability;
/// callers should persist only a digest and keep the raw bytes process-private.
pub fn random_capability_bytes() -> [u8; 32] {
    let first = Uuid::new_v4();
    let second = Uuid::new_v4();
    let mut output = [0_u8; 32];
    output[..16].copy_from_slice(first.as_bytes());
    output[16..].copy_from_slice(second.as_bytes());
    output
}

#[cfg(test)]
mod tests {
    use super::random_capability_bytes;

    #[test]
    fn capability_draws_are_nonzero_and_distinct() {
        let first = random_capability_bytes();
        let second = random_capability_bytes();
        assert_ne!(first, [0_u8; 32]);
        assert_ne!(first, second);
    }
}
