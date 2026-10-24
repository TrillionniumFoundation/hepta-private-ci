//! Actual refused Linux ioctls exercise the same syscall counter boundary.
//! These tests do not assert an Asterinas history or CPU effect.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn original_transport_counts_history_queries_and_installs_independently() {
    let file = File::open("/dev/null").unwrap();
    let probe = NativeCopyoutProbe::default();
    let mut output = [0; OUTPUT_CAPACITY];
    let (abi, len) = super::super::encode_frame(1, 1, 0, 0, &[]).unwrap();
    assert!(probe.exchange(&file, &abi[..len], &mut output).is_err());
    assert_eq!(
        probe.ioctl_counts().unwrap(),
        NativeIoctlCounts {
            install_ioctl_count: 0,
            query_ioctl_count: 0,
        }
    );
    let (query, len) = super::super::encode_frame(4, 1, 3, 1, &[0; 40]).unwrap();
    assert!(probe.exchange(&file, &query[..len], &mut output).is_err());
    assert_eq!(
        probe.ioctl_counts().unwrap(),
        NativeIoctlCounts {
            install_ioctl_count: 0,
            query_ioctl_count: 1,
        }
    );
    let (install, len) = super::super::encode_frame(3, 1, 2, 1, &[0; 32]).unwrap();
    assert!(probe.exchange(&file, &install[..len], &mut output).is_err());
    assert_eq!(
        probe.ioctl_counts().unwrap(),
        NativeIoctlCounts {
            install_ioctl_count: 1,
            query_ioctl_count: 1,
        }
    );
    assert_eq!(probe.snapshot().unwrap().install_ioctl_count, 1);
}

#[test]
fn refused_before_ioctl_does_not_increment_either_syscall_counter() {
    let file = File::open("/dev/null").unwrap();
    let probe = NativeCopyoutProbe::default();
    let (install, len) = super::super::encode_frame(3, 1, 2, 1, &[0; 32]).unwrap();
    probe.arm(&install[..len], None).unwrap();
    assert!(
        probe
            .exchange(&file, &install[..len], &mut [0; 64])
            .is_err()
    );
    assert_eq!(
        probe.ioctl_counts().unwrap(),
        NativeIoctlCounts {
            install_ioctl_count: 0,
            query_ioctl_count: 0,
        }
    );
    assert!(probe.snapshot().unwrap().armed);
}
