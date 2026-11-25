//! Strict discovery for the original G1d and kernel-created G2 images.
//! Parsed fields select existing capabilities; every ioctl still authenticates
//! the actual Process and final image. No bootstrap value grants authority.

use super::read16;
use super::read64;
use codex_hepta_memory::HOS2_CPU_PERIOD_NS;

pub(super) const NATIVE_MAX_CAP_NS: u64 = 50_000_000;
const NATIVE_LEASE_NS: u64 = 300_000_000_000;

pub(super) fn validate_bootstrap(bootstrap: &[u8]) -> Result<(), String> {
    if bootstrap.len() < 192
        || &bootstrap[..8] != b"HOS2BOOT"
        || read64(bootstrap, 176)? != HOS2_CPU_PERIOD_NS
    {
        return Err("invalid sealed HOS2 bootstrap discovery page".to_string());
    }
    let bytes = match read64(bootstrap, 8)? {
        2 => 192,
        3 => {
            if !matches!(bootstrap.len(), 200 | 4096)
                || read64(bootstrap, 144)? != 2
                || read64(bootstrap, 152)? != 3
                || read64(bootstrap, 160)? != 4
                || read64(bootstrap, 192)? != 1
            {
                return Err("invalid G2 kernel-initial process topology".to_string());
            }
            200
        }
        4 => {
            validate_successor(bootstrap)?;
            240
        }
        _ => return Err("unsupported HOS2 bootstrap version".to_string()),
    };
    if read64(bootstrap, 24)? != bytes as u64 || bootstrap[bytes..].iter().any(|byte| *byte != 0) {
        return Err("invalid sealed HOS2 bootstrap discovery page".to_string());
    }
    Ok(())
}

fn validate_successor(bootstrap: &[u8]) -> Result<(), String> {
    let malformed = || "invalid G2 kernel successor discovery".to_string();
    if !matches!(bootstrap.len(), 240 | 4096) {
        return Err(malformed());
    }
    let word = |offset| read64(bootstrap, offset);
    let role = word(16)?;
    let manager = word(144)?;
    let recovery = word(160)?;
    let this_pid = word(200)?;
    let manager_space = read16(bootstrap, 112)?;
    let recovery_space = read16(bootstrap, 128)?;
    let local_space = read16(bootstrap, 208)?;
    let valid_pid = |pid: u64| (5..=i32::MAX as u64).contains(&pid);
    if !valid_pid(this_pid)
        || word(152)? != 3
        || word(192)? != 1
        || word(224)? == 0
        || word(232)? != 0
        || read16(bootstrap, 96)? == [0; 16]
        || local_space == [0; 16]
        || manager_space == [0; 16]
        || recovery_space == [0; 16]
        || manager_space == recovery_space
        || (word(64)?, word(72)?) != (3, 1)
    {
        return Err(malformed());
    }
    match role {
        1 | 3 => {
            if !valid_pid(manager)
                || !valid_pid(recovery)
                || manager == recovery
                || (word(32)?, word(40)?) != (1, 1)
                || (word(48)?, word(56)?) != (2, 1)
                || word(168)? != NATIVE_MAX_CAP_NS
                || word(184)? != NATIVE_LEASE_NS
                || this_pid != if role == 1 { manager } else { recovery }
                || local_space
                    != if role == 1 {
                        manager_space
                    } else {
                        recovery_space
                    }
                || (word(80)?, word(88)?) != if role == 1 { (0, 0) } else { (4, 1) }
            {
                return Err(malformed());
            }
        }
        5 => {
            // Workload PID is historical metadata. Its current liveness is
            // irrelevant to querying and draining these original namespaces.
            if manager != 0
                || recovery != 0
                || bootstrap[32..64].iter().any(|b| *b != 0)
                || (word(80)?, word(88)?) != (4, 1)
                || word(168)? != 0
                || word(184)? != 0
                || local_space == manager_space
                || local_space == recovery_space
            {
                return Err(malformed());
            }
        }
        _ => return Err(malformed()),
    }
    Ok(())
}
