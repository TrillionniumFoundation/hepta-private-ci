//! Checked HIA freshness comparison. The original Chrono clock and serialization
//! remain owned by ModelsCacheEntry; this boundary replaces only the TTL decision.

use chrono::Duration;

unsafe extern "C" {
    fn codex_hia_model_cache_ttl(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

fn invoke(source: &[u8], output: &mut [u8]) -> u64 {
    // The workspace is not used by this HIA entry. Give it a separate,
    // non-null, guarded allocation while exposing zero logical bytes.
    let mut workspace = [0x6d_u8; 1];
    let source_length = u64::try_from(source.len())
        .unwrap_or_else(|_| panic!("HIA model-cache TTL source exceeds u64"));
    let output_capacity = u64::try_from(output.len())
        .unwrap_or_else(|_| panic!("HIA model-cache TTL output exceeds u64"));
    let code = unsafe {
        codex_hia_model_cache_ttl(
            source.as_ptr(),
            source_length,
            output.as_mut_ptr(),
            output_capacity,
            workspace.as_mut_ptr(),
            0,
        )
    };
    assert_eq!(
        workspace,
        [0x6d],
        "HIA model-cache TTL modified the zero-length workspace"
    );
    code
}

/// The original caller has already rejected zero and unrepresentable TTLs.
pub(crate) fn is_fresh(age: Duration, ttl: Duration) -> bool {
    let ttl_seconds = u64::try_from(ttl.num_seconds())
        .unwrap_or_else(|_| panic!("HIA model-cache TTL requires nonnegative seconds"));
    let ttl_nanos = u64::try_from(ttl.subsec_nanos())
        .unwrap_or_else(|_| panic!("HIA model-cache TTL requires nonnegative nanoseconds"));
    let words = [
        1_u64,
        age.num_seconds() as u64,
        i64::from(age.subsec_nanos()) as u64,
        ttl_seconds,
        ttl_nanos,
    ];
    let mut source = [0_u8; 40];
    for (bytes, word) in source.chunks_exact_mut(8).zip(words) {
        bytes.copy_from_slice(&word.to_le_bytes());
    }
    let original_source = source;
    let mut output = [0xa5_u8; 8];
    let code = invoke(&source, &mut output);
    assert_eq!(
        source, original_source,
        "HIA model-cache TTL changed borrowed input"
    );
    assert_eq!(code, 8, "HIA model-cache TTL returned a non-success status");
    match u64::from_le_bytes(output) {
        0 => false,
        1 => true,
        other => panic!("HIA model-cache TTL returned an invalid decision {other}"),
    }
}

#[cfg(test)]
mod tests {
    use super::invoke;
    use super::is_fresh;
    use chrono::Duration;

    #[test]
    fn native_ttl_matches_original_chrono_ordering() {
        let ages = [
            Duration::nanoseconds(-999_999_999),
            Duration::seconds(-2) - Duration::nanoseconds(1),
            Duration::zero(),
            Duration::nanoseconds(1),
            Duration::nanoseconds(999_999_999),
            Duration::seconds(1),
            Duration::seconds(1) + Duration::nanoseconds(1),
            Duration::days(2),
        ];
        let ttls = [
            Duration::zero(),
            Duration::nanoseconds(1),
            Duration::nanoseconds(999_999_999),
            Duration::seconds(1),
            Duration::seconds(1) + Duration::nanoseconds(1),
            Duration::days(1),
            Duration::days(3),
        ];
        for age in ages {
            for ttl in ttls {
                assert_eq!(
                    is_fresh(age, ttl),
                    !ttl.is_zero() && age <= ttl,
                    "HIA and the original Chrono comparator differ for {age:?} / {ttl:?}"
                );
            }
        }
    }

    #[test]
    fn malformed_native_packets_never_write_output() {
        let mut valid = [0_u8; 40];
        valid[..8].copy_from_slice(&1_u64.to_le_bytes());
        valid[24..32].copy_from_slice(&1_u64.to_le_bytes());
        let mut positive = [0xa5_u8; 16];
        assert_eq!(invoke(&valid, &mut positive), 8);
        assert_eq!(&positive[..8], &1_u64.to_le_bytes());
        assert_eq!(&positive[8..], &[0xa5; 8]);

        let mut short = [0xa5_u8; 7];
        assert_eq!(invoke(&valid, &mut short), u64::from(u32::MAX - 1));
        assert_eq!(short, [0xa5; 7]);

        let mut invalid_version = valid;
        invalid_version[..8].copy_from_slice(&2_u64.to_le_bytes());
        let mut invalid_fraction = valid;
        invalid_fraction[16..24].copy_from_slice(&1_000_000_000_u64.to_le_bytes());
        let mut mixed_sign = valid;
        mixed_sign[8..16].copy_from_slice(&1_u64.to_le_bytes());
        mixed_sign[16..24].copy_from_slice(&(-1_i64).to_le_bytes());
        for source in [
            &valid[..32],
            &invalid_version[..],
            &invalid_fraction[..],
            &mixed_sign[..],
        ] {
            let mut result = [0xa5_u8; 8];
            assert_eq!(invoke(source, &mut result), u64::from(u32::MAX));
            assert_eq!(result, [0xa5; 8]);
        }
    }
}
