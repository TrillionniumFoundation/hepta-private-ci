//! Checked transport for the complete HIA network-host normalization owner.

use crate::error::Error;
use crate::error::Result;

unsafe extern "C" {
    fn codex_hia_network_host(
        source: *const u8,
        source_length: u64,
        output: *mut u8,
        output_capacity: u64,
        workspace: *mut u8,
        workspace_length: u64,
    ) -> u64;
}

fn invoke(raw: &[u8], output: &mut [u8], mode: u64, expected_length: u64) {
    let mut control = [0_u8; 32];
    control[..8].copy_from_slice(&1_u64.to_le_bytes());
    control[8..16].copy_from_slice(&mode.to_le_bytes());
    control[16..24].copy_from_slice(&expected_length.to_le_bytes());
    let original_control = control;
    let source_length = u64::try_from(raw.len())
        .unwrap_or_else(|_| panic!("HIA network-host source length exceeds u64"));
    let output_capacity = u64::try_from(output.len())
        .unwrap_or_else(|_| panic!("HIA network-host output capacity exceeds u64"));
    // The three buffers are disjoint, remain borrowed for the call, and carry
    // their exact lengths. HIA validates the complete input before publishing.
    let code = unsafe {
        codex_hia_network_host(
            raw.as_ptr(),
            source_length,
            output.as_mut_ptr(),
            output_capacity,
            control.as_mut_ptr(),
            32,
        )
    };
    if code != 0 {
        panic!("HIA network-host native call failed with code {code}");
    }
    if control != original_control {
        panic!("HIA network-host changed its read-only control buffer");
    }
}

pub(crate) fn normalize(raw: &str) -> Result<String> {
    let mut plan = [0_u8; 16];
    invoke(raw.as_bytes(), &mut plan, 0, 0);
    let tag = u64::from_le_bytes(
        plan[..8]
            .try_into()
            .unwrap_or_else(|_| panic!("HIA network-host tag has the wrong width")),
    );
    let length = u64::from_le_bytes(
        plan[8..]
            .try_into()
            .unwrap_or_else(|_| panic!("HIA network-host length has the wrong width")),
    );
    if tag != 0 {
        if length != 0 {
            panic!("HIA network-host error response contains a payload length");
        }
        let message = match tag {
            1 => "network_rule host cannot be empty".to_string(),
            2 => "network_rule host must be a hostname or IP literal (without scheme or path)"
                .to_string(),
            3 => "network_rule host has an invalid bracketed IPv6 literal".to_string(),
            4 => format!("network_rule host contains an unsupported suffix: {raw}"),
            5 => "network_rule host must be a specific host; wildcards are not allowed".to_string(),
            6 => "network_rule host cannot contain whitespace".to_string(),
            other => panic!("HIA network-host returned an unknown semantic tag {other}"),
        };
        return Err(Error::InvalidRule(message));
    }
    let length_usize = usize::try_from(length)
        .unwrap_or_else(|_| panic!("HIA network-host output length exceeds usize"));
    if length_usize == 0 || length_usize > raw.len() {
        panic!("HIA network-host output length is outside the input bound");
    }
    let mut output = Vec::new();
    output
        .try_reserve_exact(length_usize)
        .unwrap_or_else(|error| panic!("HIA network-host output allocation failed: {error}"));
    output.resize(length_usize, 0);
    invoke(raw.as_bytes(), &mut output, 1, length);
    Ok(String::from_utf8(output)
        .unwrap_or_else(|error| panic!("HIA network-host output is not UTF-8: {error}")))
}
