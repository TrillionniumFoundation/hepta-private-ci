//! Real Linux syscall refusal and one-shot selection tests. A successful HOS2
//! effect followed by EFAULT requires the actual Asterinas guest separately.
use super::*;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

fn install_frame(sequence: u64) -> Vec<u8> {
    let (frame, length) = super::super::encode_frame(3, sequence, 2, 1, &[0; 32]).unwrap();
    frame[..length].to_vec()
}

#[test]
fn actual_non_hos2_ioctl_refusal_is_not_reported_as_a_copyout_fault() {
    let file = File::open("/dev/null").unwrap();
    let probe = NativeCopyoutProbe::default();
    let called = Arc::new(AtomicBool::new(false));
    let callback_called = called.clone();
    let input = install_frame(1);
    probe
        .arm(
            &input,
            Some(Box::new(move |_| {
                callback_called.store(true, Ordering::SeqCst);
                Ok(())
            })),
        )
        .unwrap();
    let mut output = [0_u8; OUTPUT_CAPACITY];
    assert!(probe.exchange(&file, &input, &mut output).is_err());
    let observation = probe.snapshot().unwrap();
    assert_eq!(observation.install_ioctl_count, 1);
    assert_eq!(observation.selected_ioctl_count, 1);
    assert_eq!(observation.efault_count, 0);
    assert!(!observation.armed);
    assert!(!called.load(Ordering::SeqCst));
    let last = observation.last.unwrap();
    assert_eq!(last.syscall_return, -1);
    assert_eq!(last.errno, Some(libc::ENOTTY));
    assert_eq!(
        last.request_sha256,
        <[u8; 32]>::from(Sha256::digest(&input))
    );
    assert_eq!(last.request_bytes, 96);
    assert_eq!(last.response_capacity, 128);
    // A second actual call is ordinary and does not repeat the selected fault.
    assert!(probe.exchange(&file, &input, &mut output).is_err());
    let after = probe.snapshot().unwrap();
    assert_eq!(after.install_ioctl_count, 2);
    assert_eq!(after.selected_ioctl_count, 1);
    assert_eq!(after.efault_count, 0);
}

#[test]
fn query_and_changed_install_frame_do_not_consume_the_exact_arm() {
    let file = File::open("/dev/null").unwrap();
    let probe = NativeCopyoutProbe::default();
    let input = install_frame(1);
    probe.arm(&input, None).unwrap();
    let (query, length) = super::super::encode_frame(1, 1, 0, 0, &[]).unwrap();
    let mut output = [0; OUTPUT_CAPACITY];
    assert!(
        probe
            .exchange(&file, &query[..length], &mut output)
            .is_err()
    );
    let after_query = probe.snapshot().unwrap();
    assert!(after_query.armed);
    assert_eq!(after_query.install_ioctl_count, 0);
    assert_eq!(after_query.selected_ioctl_count, 0);
    let mut changed = input.clone();
    // Same sequence, changed original payload: a sequence-only arm would be wrong.
    changed[80] = 1;
    assert!(probe.exchange(&file, &changed, &mut output).is_err());
    let after_changed = probe.snapshot().unwrap();
    assert!(after_changed.armed);
    assert_eq!(after_changed.install_ioctl_count, 1);
    assert_eq!(after_changed.selected_ioctl_count, 0);
    assert!(probe.exchange(&file, &input, &mut output).is_err());
    let final_observation = probe.snapshot().unwrap();
    assert!(!final_observation.armed);
    assert_eq!(final_observation.install_ioctl_count, 2);
    assert_eq!(final_observation.selected_ioctl_count, 1);
    assert_eq!(final_observation.efault_count, 0);
}

#[test]
fn invalid_or_second_arm_preserves_the_first_original_request() {
    let probe = NativeCopyoutProbe::default();
    assert!(probe.arm(&[0; INSTALL_FRAME_BYTES], None).is_err());
    let input = install_frame(1);
    probe.arm(&input, None).unwrap();
    assert!(probe.arm(&install_frame(2), None).is_err());
    let state = probe.state.lock().unwrap();
    assert_eq!(state.armed.as_ref().unwrap().frame.as_slice(), input);
    assert_eq!(state.install_ioctl_count, 0);
    assert_eq!(state.selected_ioctl_count, 0);
    assert_eq!(state.efault_count, 0);
}

#[test]
fn wrong_response_capacity_refuses_before_the_actual_ioctl() {
    let file = File::open("/dev/null").unwrap();
    let probe = NativeCopyoutProbe::default();
    let input = install_frame(1);
    probe.arm(&input, None).unwrap();
    assert!(probe.exchange(&file, &input, &mut [0; 64]).is_err());
    let state = probe.snapshot().unwrap();
    assert!(state.armed);
    assert_eq!(state.install_ioctl_count, 0);
    assert_eq!(state.selected_ioctl_count, 0);
    assert!(state.last.is_none());
}
