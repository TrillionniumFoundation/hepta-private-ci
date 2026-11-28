//! Transport for the native cache-duration contract. All date arithmetic,
//! duration admission and freshness decisions execute in HIA.

unsafe extern "C" {
    fn codex_hia_datetime_cache(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_len: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

/// Transfers eight little-endian words and validates the complete result frame.
pub(crate) fn evaluate(words: [u64; 8]) -> [u64; 4] {
    let mut source = [0_u8; 64];
    for (slot, word) in source.chunks_exact_mut(8).zip(words) {
        slot.copy_from_slice(&word.to_le_bytes());
    }
    let mut output = [0_u8; 32];
    // SAFETY: source and output are separate live allocations with exact ABI
    // lengths. This entry needs no workspace. The build script verifies the
    // source, fixed-point compiler, static object and unique native symbol.
    let status = unsafe {
        codex_hia_datetime_cache(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            std::ptr::null_mut(),
            /*workspace_len*/ 0,
        )
    };
    assert_eq!(status, 0, "native cache-duration ABI rejected its frame");
    let result = std::array::from_fn(|index| {
        let start = index * 8;
        u64::from_le_bytes(
            output[start..start + 8]
                .try_into()
                .expect("complete native cache-duration word"),
        )
    });
    assert_eq!(result[0], 1, "native cache-duration result version");
    assert!(
        result[1..].iter().all(|word| *word <= 1),
        "native cache-duration result flags"
    );
    result
}
