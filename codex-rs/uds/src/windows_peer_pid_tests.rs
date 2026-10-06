use super::*;

#[test]
fn exact_size_success_needs_one_query() {
    let mut calls = 0;
    let pid = query_peer_pid(|pid, returned| {
        calls += 1;
        assert_eq!((*pid, *returned), (0, 0));
        *pid = 1234;
        *returned = 4;
        Ok(())
    })
    .unwrap();
    assert_eq!((pid, calls), (1234, 1));
}

#[test]
fn zero_length_requires_complete_matching_confirmation() {
    for second_length in [0, 4] {
        let mut calls = 0;
        let pid = query_peer_pid(|pid, returned| {
            assert_eq!(*pid, if calls == 0 { 0 } else { !1234_u32 });
            assert_eq!(*returned, 0);
            *pid = 1234;
            *returned = if calls == 0 { 0 } else { second_length };
            calls += 1;
            Ok(())
        })
        .unwrap();
        assert_eq!((pid, calls), (1234, 2));
    }
}

#[test]
fn api_failure_preserves_original_os_error_before_output_validation() {
    for length in [0, 4, 9] {
        let error = query_peer_pid(|pid, returned| {
            *pid = 1234;
            *returned = length;
            Err(io::Error::from_raw_os_error(10045))
        })
        .unwrap_err();
        assert_eq!(error.raw_os_error(), Some(10045));
    }
}

#[test]
fn confirmation_api_failure_preserves_its_os_error() {
    let mut calls = 0;
    let error = query_peer_pid(|pid, _| {
        calls += 1;
        if calls == 1 {
            *pid = 1234;
            Ok(())
        } else {
            Err(io::Error::from_raw_os_error(10054))
        }
    })
    .unwrap_err();
    assert_eq!((calls, error.raw_os_error()), (2, Some(10054)));
}

#[test]
fn malformed_positive_lengths_reject_without_confirmation() {
    for length in [1, 2, 3, 5, 8, u32::MAX] {
        let mut calls = 0;
        let error = query_peer_pid(|pid, returned| {
            calls += 1;
            *pid = 1234;
            *returned = length;
            Ok(())
        })
        .unwrap_err();
        assert_eq!((calls, error.kind()), (1, io::ErrorKind::InvalidData));
    }
}

#[test]
fn zero_pid_rejects_with_either_accepted_length() {
    for length in [0, 4] {
        let error = query_peer_pid(|_, returned| {
            *returned = length;
            Ok(())
        })
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    }
}

#[test]
fn confirmation_changed_pid_or_length_rejects() {
    for (second_pid, second_length) in [(0, 0), (0, 4), (1235, 0), (1235, 4), (1234, 2)] {
        let mut calls = 0;
        let error = query_peer_pid(|pid, returned| {
            calls += 1;
            (*pid, *returned) = if calls == 1 {
                (1234, 0)
            } else {
                (second_pid, second_length)
            };
            Ok(())
        })
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    }
}

#[test]
fn partial_confirmation_writes_reject_every_short_width() {
    for bytes_written in 0..4 {
        let mut calls = 0;
        let error = query_peer_pid(|pid, _| {
            calls += 1;
            if calls == 1 {
                *pid = 0x1234_5678;
            } else {
                let mask = if bytes_written == 0 {
                    0
                } else {
                    (1_u32 << (bytes_written * 8)) - 1
                };
                *pid = (*pid & !mask) | (0x1234_5678 & mask);
            }
            Ok(())
        })
        .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::InvalidData);
    }
}

#[test]
fn every_partial_byte_subset_fails_for_both_reported_lengths_and_edge_pids() {
    for expected in [
        1_u32,
        0xff,
        0x100,
        0xffff,
        0x8000_0000,
        0x1234_5678,
        u32::MAX,
    ] {
        for reported in [0, 4] {
            for written_byte_mask in 0_u32..16 {
                let mut calls = 0;
                let result = query_peer_pid(|pid, length| {
                    calls += 1;
                    if calls == 1 {
                        *pid = expected;
                        *length = 0;
                    } else {
                        assert_eq!(*pid, !expected);
                        let mut mask = 0_u32;
                        for byte in 0..4 {
                            if written_byte_mask & (1 << byte) != 0 {
                                mask |= 0xff << (byte * 8);
                            }
                        }
                        *pid = (*pid & !mask) | (expected & mask);
                        *length = reported;
                    }
                    Ok(())
                });
                assert_eq!(calls, 2);
                if written_byte_mask == 15 {
                    assert_eq!(result.unwrap(), expected);
                } else {
                    assert_eq!(result.unwrap_err().kind(), std::io::ErrorKind::InvalidData);
                }
            }
        }
    }
}

#[test]
fn every_retained_single_bit_fails_even_if_length_claims_full_output() {
    for expected in [1_u32, 0x8000_0000, 0x1234_5678, u32::MAX] {
        for retained_bit in 0..32 {
            let mut calls = 0;
            let error = query_peer_pid(|pid, length| {
                calls += 1;
                if calls == 1 {
                    *pid = expected;
                } else {
                    *pid = expected ^ (1 << retained_bit);
                    *length = 4;
                }
                Ok(())
            })
            .unwrap_err();
            assert_eq!((calls, error.kind()), (2, std::io::ErrorKind::InvalidData));
        }
    }
}

#[test]
fn every_sampled_malformed_confirmation_length_fails_without_retry() {
    for bad_length in [1, 2, 3, 5, 6, 7, 8, 9, 0xffff_ffff] {
        let mut calls = 0;
        let error = query_peer_pid(|pid, length| {
            calls += 1;
            *pid = 1234;
            *length = if calls == 1 { 0 } else { bad_length };
            Ok(())
        })
        .unwrap_err();
        assert_eq!((calls, error.kind()), (2, std::io::ErrorKind::InvalidData));
    }
}

#[test]
fn windows_pending_wouldblock_and_failure_values_propagate_without_retry() {
    for os_error in [997, 10014, 10035, 10045, 10054] {
        for fail_call in [1, 2] {
            let mut calls = 0;
            let error = query_peer_pid(|pid, length| {
                calls += 1;
                *pid = 1234;
                *length = if calls == 1 { 0 } else { 4 };
                if calls == fail_call {
                    Err(std::io::Error::from_raw_os_error(os_error))
                } else {
                    Ok(())
                }
            })
            .unwrap_err();
            assert_eq!((calls, error.raw_os_error()), (fail_call, Some(os_error)));
        }
    }
}

#[test]
fn api_boundary_accepts_only_exact_success_and_preserves_captured_failure() {
    validate_ioctl_status(0, None).expect("zero status succeeds");
    for error in [997, 10014, 10035, 10045, 10054] {
        assert_eq!(
            validate_ioctl_status(-1, Some(error))
                .unwrap_err()
                .raw_os_error(),
            Some(error)
        );
    }
}

#[test]
fn api_boundary_rejects_unknown_nonzero_or_inconsistent_status() {
    for (result, error) in [
        (1, None),
        (4, None),
        (i32::MAX, None),
        (-2, None),
        (-1, None),
        (0, Some(10054)),
        (1, Some(10054)),
    ] {
        assert_eq!(
            validate_ioctl_status(result, error).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }
}
