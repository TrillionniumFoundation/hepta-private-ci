//! Protocol shape checks; these bytes are inert and never qualify a guest.

use super::*;
use pretty_assertions::assert_eq;

fn put(bytes: &mut [u8; BYTES], offset: usize, value: u64) {
    bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
}

fn launch_bytes(generation: u64, history: bool) -> [u8; BYTES] {
    let mut bytes = [0; BYTES];
    bytes[..8].copy_from_slice(b"HOS2LRES");
    for (offset, value) in [
        (8, 1),
        (16, if history { 2 } else { 1 }),
        (24, generation),
        (32, 1),
        (40, 3),
        (72, generation.saturating_sub(1)),
    ] {
        put(&mut bytes, offset, value);
    }
    if history {
        put(&mut bytes, 64, 7);
    } else {
        put(&mut bytes, 48, if generation == 0 { 2 } else { 5 });
        put(&mut bytes, 56, if generation == 0 { 4 } else { 6 });
    }
    bytes[80..96].copy_from_slice(&[4; 16]);
    bytes[96..112].copy_from_slice(&[5; 16]);
    bytes
}

fn retirement_bytes(launch: &KernelLaunchReceipt) -> [u8; BYTES] {
    let mut bytes = [0; BYTES];
    bytes[..8].copy_from_slice(b"HOS2LWDR");
    put(&mut bytes, 8, 1);
    put(&mut bytes, 16, launch.generation());
    if launch.mode() == KernelLaunchMode::HistoryOnly {
        bytes[88..104].copy_from_slice(&launch.history_spaces()[0]);
        bytes[104..120].copy_from_slice(&launch.history_spaces()[1]);
    } else {
        bytes[88..104].copy_from_slice(&[2; 16]);
        bytes[104..120].copy_from_slice(&[3; 16]);
        put(&mut bytes, 120, 1);
    }
    bytes
}

#[test]
fn launcher_receipt_binds_actual_role_set_and_contiguous_generation() -> io::Result<()> {
    let initial = parse_launch([1; 16], launch_bytes(0, false))?;
    assert_eq!((initial.root_pid(), initial.workload_pid()), (1, 3));
    assert_eq!(
        (
            initial.manager_pid(),
            initial.recovery_pid(),
            initial.history_pid()
        ),
        (Some(2), Some(4), None)
    );
    let pair = parse_launch([1; 16], launch_bytes(1, false))?;
    let history = parse_launch([1; 16], launch_bytes(2, true))?;
    assert_eq!(pair.generation(), 1);
    assert_eq!(history.previous_generation(), 1);
    assert_eq!(
        (
            history.manager_pid(),
            history.recovery_pid(),
            history.history_pid()
        ),
        (None, None, Some(7))
    );
    for (offset, value) in [
        (8, 2),
        (16, 0),
        (32, 2),
        (40, 8),
        (48, 6),
        (56, 3),
        (64, 9),
        (72, 1),
        (112, 1),
    ] {
        let mut invalid = *pair.bytes();
        put(&mut invalid, offset, value);
        assert!(parse_launch([1; 16], invalid).is_err());
    }
    assert!(parse_launch([0; 16], *pair.bytes()).is_err());
    assert!(parse_launch([1; 16], launch_bytes(0, true)).is_err());
    Ok(())
}

#[test]
fn retirement_distinguishes_live_policy_from_retired_untriggered_policy() -> io::Result<()> {
    let pair = parse_launch([1; 16], launch_bytes(1, false))?;
    let history = parse_launch([1; 16], launch_bytes(1, true))?;
    let retired = parse_retirement(&pair, retirement_bytes(&pair))?;
    let retained = parse_retirement(&history, retirement_bytes(&history))?;
    assert!(retired.policy_retired());
    assert!(!retained.policy_retired());
    assert_eq!(retired.watchdog_status(), 0);
    assert_eq!(retained.watchdog_status(), 0);
    assert_eq!(retired.evaluated_ns(), None);
    let mut wrong = retirement_bytes(&history);
    put(&mut wrong, 120, 1);
    assert!(parse_retirement(&history, wrong).is_err());
    let mut wrong = retirement_bytes(&pair);
    put(&mut wrong, 120, 0);
    assert!(parse_retirement(&pair, wrong).is_err());
    Ok(())
}

#[test]
fn retirement_keeps_some_zero_distinct_from_unavailable_time() -> io::Result<()> {
    let pair = parse_launch([1; 16], launch_bytes(1, false))?;
    let mut bytes = retirement_bytes(&pair);
    put(&mut bytes, 24, 5); // The original ClockUnavailable status.
    assert_eq!(parse_retirement(&pair, bytes)?.evaluated_ns(), None);
    put(&mut bytes, 120, 3);
    assert_eq!(parse_retirement(&pair, bytes)?.evaluated_ns(), Some(0));
    put(&mut bytes, 32, 50);
    assert_eq!(parse_retirement(&pair, bytes)?.evaluated_ns(), Some(50));
    put(&mut bytes, 120, 1);
    assert!(parse_retirement(&pair, bytes).is_err());
    Ok(())
}

#[test]
fn retirement_preserves_full_original_restored_receipt_and_rejects_shape_changes() -> io::Result<()>
{
    let pair = parse_launch([1; 16], launch_bytes(1, false))?;
    let mut bytes = retirement_bytes(&pair);
    bytes[40..56].copy_from_slice(&[9; 16]);
    for (offset, value) in [
        (24, 1),
        (32, 100_001_001),
        (56, 7),
        (64, 8),
        (72, 100_001_000),
        (80, 999),
        (120, 3),
    ] {
        put(&mut bytes, offset, value);
    }
    let receipt = parse_retirement(&pair, bytes)?;
    assert_eq!(receipt.bytes(), &bytes);
    assert_eq!(receipt.boot_id(), [1; 16]);
    assert_eq!(receipt.previous_history_spaces(), [[2; 16], [3; 16]]);
    for (offset, value) in [
        (8, 2),
        (16, 2),
        (24, 8),
        (32, 0),
        (56, 6),
        (64, 9),
        (72, 100_001_002),
        (80, 1_001),
        (120, 7),
    ] {
        let mut wrong = bytes;
        put(&mut wrong, offset, value);
        assert!(parse_retirement(&pair, wrong).is_err());
    }
    for status in [0, 2, 3, 4, 5, 6, 7] {
        let mut wrong = bytes;
        put(&mut wrong, 24, status);
        assert!(parse_retirement(&pair, wrong).is_err());
    }
    let mut wrong = bytes;
    wrong[88..104].copy_from_slice(&pair.history_spaces()[0]);
    assert!(parse_retirement(&pair, wrong).is_err());
    Ok(())
}

#[test]
fn ordinary_process_cannot_open_the_kernel_root_factory_from_discovery_bytes() {
    let mut bootstrap = [0; 4096];
    bootstrap[..8].copy_from_slice(b"HOS2BOOT");
    for (offset, value) in [
        (8, 3_u64),
        (16, 4),
        (24, 200),
        (144, 2),
        (152, 3),
        (160, 4),
        (192, 1),
    ] {
        bootstrap[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    bootstrap[96..112].copy_from_slice(&[1; 16]);
    assert!(RootKernelLauncher::open(&bootstrap).is_err());
}
