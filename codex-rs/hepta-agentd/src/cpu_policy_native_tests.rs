//! Original frame adapter tests with its existing explicit scripted transport.
//! These are neither native execution nor benchmark measurements.
use super::*;
use crate::cpu_policy::CpuDemandSample;
use crate::cpu_policy::CpuPolicy;
use crate::cpu_policy::CpuPolicyError;
use crate::cpu_policy::CpuPolicyKind;
use crate::cpu_policy::ObservedCpuDemand;

#[test]
fn cpu_policy_preparation_reads_original_device_and_never_installs_or_allocates_d() -> TestResult {
    let values = [10_000_000_000, 2_000_000_000, 10_000_000_000, 0, 20_000_000, HOS2_CPU_PERIOD_NS, 9, 0];
    let (device, script) = usage_fixture(1, Ok(usage_response(values, 7)))?;
    let initial = device.read_usage(41)?;
    let mut policy = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: 50_000_000 }, 50_000_000, &initial)?;
    let proposal = policy.propose(&initial, &CpuDemandSample {
            boot_id: initial.boot_id,
            observer_space_id: initial.observer_space_id,
            sample_boottime_ns: initial.sample_boottime_ns,
            demand: ObservedCpuDemand::Stable,
        }, values[0])?.ok_or("missing fixed proposal")?;
    script.lock().map_err(|error| error.to_string())?.replies.push_back((2, Ok(usage_response(values, 7))));
    let request = proposal.original_request(&device, 77, 42, || Ok(values[0]))?;
    assert_eq!(request.delivery.sequence()?, 77);
    assert_eq!(request.expected_revision, 7);
    assert_eq!(request.cap_ns, 25_000_000);
    assert_eq!(request.period_ns, HOS2_CPU_PERIOD_NS);
    let script = script.lock().map_err(|error| error.to_string())?;
    assert_eq!(script.requests.len(), 3);
    assert_eq!(script.requests.iter().map(|frame| read_u16(frame, 8)).collect::<Result<Vec<_>, _>>()?, vec![1, 2, 2]);
    Ok(())
}

#[test]
fn cpu_policy_native_recheck_refuses_revision_drift_and_post_io_expiry() -> TestResult {
    for revision in [7, 8] {
        let values = [10_000_000_000, 2_000_000_000, 10_000_000_000, 0, 20_000_000, HOS2_CPU_PERIOD_NS, 9, 0];
        let (device, script) = usage_fixture(1, Ok(usage_response(values, 7)))?;
        let initial = device.read_usage(41)?;
        let mut policy = CpuPolicy::new(CpuPolicyKind::Fixed { cap_ns: 50_000_000 }, 50_000_000, &initial)?;
        let proposal = policy.propose(&initial, &CpuDemandSample {
            boot_id: initial.boot_id,
            observer_space_id: initial.observer_space_id,
            sample_boottime_ns: initial.sample_boottime_ns,
            demand: ObservedCpuDemand::Stable,
        }, values[0])?.ok_or("missing fixed proposal")?;
        script.lock().map_err(|error| error.to_string())?.replies.push_back((2, Ok(usage_response(values, revision))));
        let now = if revision == 7 { values[0] + 2_000_000_001 } else { values[0] };
        let expected = if revision == 7 { CpuPolicyError::Stale } else { CpuPolicyError::Conflict };
        assert_eq!(proposal.original_request(&device, 77, 42, || Ok(now)).unwrap_err(), expected);
        let script = script.lock().map_err(|error| error.to_string())?;
        assert_eq!(script.requests.len(), 3);
        assert!(script.requests.iter().all(|frame| read_u16(frame, 8).is_ok_and(|opcode| opcode != 3)));
    }
    Ok(())
}
