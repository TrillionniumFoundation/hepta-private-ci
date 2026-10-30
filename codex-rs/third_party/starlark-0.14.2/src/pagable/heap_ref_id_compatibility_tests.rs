use super::Blake3StrongHasher;
use std::hash::Hasher;

#[test]
fn blake3_adapter_preserves_known_digest_and_chunked_writes() {
    // Independent official BLAKE3 1.8.7 vectors: input repeats bytes 0..=250.
    // The persistent HeapRefId contract uses the digest's first 8 bytes, big endian.
    // test_vectors/test_vectors.json SHA256:
    // dcb91ea8accc77e6d6e632af7cdc1a99a9f3ae78cf648da595c7d064db32f624.
    for (length, expected) in [(0, 0xaf13_49b9_f5f9_a1a6), (1025, 0xd002_78ae_47eb_27b3)] {
        let input: Vec<u8> = (0..length)
            .map(|index| u8::try_from(index % 251).unwrap())
            .collect();
        let mut contiguous = Blake3StrongHasher::new();
        contiguous.write(&input);
        let mut chunked = Blake3StrongHasher::new();
        for chunk in input.chunks(17) {
            chunked.write(chunk);
        }
        assert_eq!(contiguous.finish(), expected);
        assert_eq!(chunked.finish(), expected);
    }
}
