//! Bounded transport for HIA-owned retry selection and attempt progression.

use crate::RetryOn;
use codex_http_client::TransportError;

unsafe extern "C" {
    fn codex_hia_retry_decision(
        source: *const u8,
        source_len: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_len: u64,
    ) -> u64;
}

pub(crate) fn next_attempt(
    policy: &RetryOn,
    error: &TransportError,
    attempt: u64,
    max_attempts: u64,
) -> Option<u64> {
    // Preserve opaque error payloads; only the original discriminant/status
    // crosses the native boundary. No Display, cloning or payload allocation.
    let (kind, status) = match error {
        TransportError::Http { status, .. } => (0, u64::from(status.as_u16())),
        TransportError::Timeout => (1, 0),
        TransportError::Connection(_) => (2, 0),
        TransportError::Network(_) => (3, 0),
        TransportError::Build(_) | TransportError::RetryLimit => (4, 0),
    };
    let words = [
        1,
        attempt,
        max_attempts,
        u64::from(policy.retry_429),
        u64::from(policy.retry_5xx),
        u64::from(policy.retry_transport),
        kind,
        status,
    ];
    let mut source = [0_u8; 64];
    for (bytes, word) in source.chunks_exact_mut(8).zip(words) {
        bytes.copy_from_slice(&word.to_le_bytes());
    }
    let mut output = [0_u8; 16];
    let mut workspace = [];
    // SAFETY: the complete initialized request, output and zero-byte workspace
    // are live and disjoint. HIA writes only output[0..16], keeps the request
    // unchanged and does not retain a pointer.
    let returned = unsafe {
        codex_hia_retry_decision(
            source.as_ptr(),
            source.len() as u64,
            output.as_mut_ptr(),
            output.len() as u64,
            workspace.as_mut_ptr(),
            workspace.len() as u64,
        )
    };
    assert_eq!(returned, 16, "HIA retry decision failed");
    let mut decision_bytes = [0; 8];
    decision_bytes.copy_from_slice(&output[..8]);
    let mut attempt_bytes = [0; 8];
    attempt_bytes.copy_from_slice(&output[8..]);
    let decision = u64::from_le_bytes(decision_bytes);
    let next = u64::from_le_bytes(attempt_bytes);
    match decision {
        0 => {
            assert_eq!(next, 0, "HIA stopped retry carries an attempt");
            None
        }
        1 => {
            assert_eq!(
                Some(next),
                attempt.checked_add(/*rhs*/ 1),
                "HIA retry step differs"
            );
            assert!(next <= max_attempts, "HIA retry step exceeds policy limit");
            Some(next)
        }
        _ => panic!("invalid HIA retry decision"),
    }
}
