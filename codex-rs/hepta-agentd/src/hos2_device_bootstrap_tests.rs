//! Exercise the original adapter, with a bounded QueryAbi transport only.
//! These packet/process-binding tests do not claim a native G2 owner execution.

use super::*;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::Mutex;

struct AbiTransport {
    requests: Arc<Mutex<Vec<Vec<u8>>>>,
    local_space: [u8; 16],
}

impl ControlTransport for AbiTransport {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String> {
        self.requests.lock().unwrap().push(input.to_vec());
        if read_u16(input, /*offset*/ 8)? != 1 {
            return Err("bootstrap attachment attempted an effect".to_string());
        }
        output[..4].copy_from_slice(b"HOSR");
        output[4..6].copy_from_slice(&2_u16.to_le_bytes());
        output[8..10].copy_from_slice(&1_u16.to_le_bytes());
        output[12..16].copy_from_slice(&64_u32.to_le_bytes());
        output[16..20].copy_from_slice(&48_u32.to_le_bytes());
        output[24..40].copy_from_slice(&input[24..40]);
        output[40..56].copy_from_slice(&[1; 16]);
        output[64..80].copy_from_slice(&self.local_space);
        for (offset, value) in [(80, 4096_u32), (84, 40), (88, 64)] {
            output[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
        }
        output[96..104].copy_from_slice(&62_u64.to_le_bytes());
        Ok(())
    }
}

fn page(version: u64, role: u64) -> Vec<u8> {
    let mut bytes = vec![0; 4096];
    bytes[..8].copy_from_slice(b"HOS2BOOT");
    for (offset, value) in [
        (8, version), (16, role), (24, if version == 3 { 200 } else { 240 }),
        (32, 1), (40, 1), (48, 2), (56, 1), (64, 3), (72, 1),
        (80, if role == 3 { 4 } else { 0 }), (88, if role == 3 { 1 } else { 0 }),
        (144, 700), (152, 701), (160, 702), (168, 50_000_000),
        (176, HOS2_CPU_PERIOD_NS), (184, 300_000_000_000), (192, 1),
    ] {
        bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    bytes[96..112].fill(/*value*/ 1);
    bytes[112..128].fill(/*value*/ 2);
    bytes[128..144].fill(/*value*/ 3);
    if version == 4 {
        bytes[200..208].copy_from_slice(&(if role == 1 { 700_u64 } else { 702 }).to_le_bytes());
        bytes[208..224].fill(if role == 1 { 2 } else { 3 });
        bytes[224..232].copy_from_slice(&9_u64.to_le_bytes());
    }
    bytes
}

fn transport(local_space: [u8; 16]) -> (Box<dyn ControlTransport>, Arc<Mutex<Vec<Vec<u8>>>>) {
    let requests = Arc::new(Mutex::new(Vec::new()));
    (Box::new(AbiTransport { requests: requests.clone(), local_space }), requests)
}

#[test]
fn g2_initial_and_successor_attach_only_the_original_matching_role() -> Result<(), String> {
    for role in [1, 3] {
        let process = ProcessIdentity { pid: if role == 1 { 700 } else { 702 }, parent_pid: 1 };
        for (version, attachment) in [
            (3, Attachment::InitialOwnerV3(process)),
            (4, Attachment::SuccessorOwnerV4(process)),
        ] {
            let local_space = if role == 1 { [2; 16] } else { [3; 16] };
            let (io, requests) = transport(local_space);
            let device = AgentdHos2Device::attach_profile(io, &page(version, role), attachment)?;
            let expected = Hos2InstallBudgetV1 {
                schema_version: 1,
                delivery: Hos2DeliveryId::new([1; 16], local_space, /*sequence*/ 1)?,
                manage_slot: 2, manage_generation: 1, expected_revision: 7,
                period_ns: HOS2_CPU_PERIOD_NS, cap_ns: 25_000_000,
            };
            assert_eq!(device.install_request(/*sequence*/ 1, /*expected_revision*/ 7, /*cap_ns*/ 25_000_000)?, expected);
            let requests = requests.lock().unwrap();
            assert_eq!(requests.len(), 1);
            assert_eq!(read_u16(&requests[0], /*offset*/ 8)?, 1);
        }
    }
    Ok(())
}

#[test]
fn g2_wrong_process_root_role_slot_or_page_is_rejected_before_transport() {
    let process = ProcessIdentity { pid: 700, parent_pid: 1 };
    for (version, attachment) in [
        (3, Attachment::InitialOwnerV3(process)),
        (4, Attachment::SuccessorOwnerV4(process)),
    ] {
        let original = page(version, /*role*/ 1);
        let mut changes = vec![(8, 2_u64), (24, 192), (16, 2), (16, 4), (16, 5), (32, 0),
            (56, 2), (80, 4), (144, 701), (152, 702), (160, 0), (168, 100_000_000),
            (176, 1), (184, 0), (192, 2)];
        if version == 4 {
            changes.extend([(24, 232), (200, 702), (224, 0), (232, 1)]);
        }
        for (offset, value) in changes {
            let mut bytes = original.clone();
            bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
            let (io, requests) = transport([2; 16]);
            assert!(AgentdHos2Device::attach_profile(io, &bytes, attachment).is_err());
            assert!(requests.lock().unwrap().is_empty());
        }
        for offset in [0, 4000] {
            let mut bytes = original.clone();
            bytes[offset] ^= 1;
            let (io, requests) = transport([2; 16]);
            assert!(AgentdHos2Device::attach_profile(io, &bytes, attachment).is_err());
            assert!(requests.lock().unwrap().is_empty());
        }
        for process in [ProcessIdentity { pid: 702, parent_pid: 1 }, ProcessIdentity { pid: 700, parent_pid: 9 }] {
            let attachment = if version == 3 { Attachment::InitialOwnerV3(process) } else { Attachment::SuccessorOwnerV4(process) };
            let (io, requests) = transport([2; 16]);
            assert!(AgentdHos2Device::attach_profile(io, &original, attachment).is_err());
            assert!(requests.lock().unwrap().is_empty());
        }
    }
}

#[test]
fn g2_truncated_oversized_or_other_version_records_never_reach_ioctl() {
    let process = ProcessIdentity { pid: 700, parent_pid: 1 };
    for (version, length, attachment) in [
        (3, 200, Attachment::InitialOwnerV3(process)),
        (4, 240, Attachment::SuccessorOwnerV4(process)),
    ] {
        for size in [0, 8, length - 1, 4097] {
            let mut bytes = page(version, /*role*/ 1);
            bytes.resize(size, /*value*/ 0);
            let (io, requests) = transport([2; 16]);
            assert!(AgentdHos2Device::attach_profile(io, &bytes, attachment).is_err());
            assert!(requests.lock().unwrap().is_empty());
        }
        let other_version = if version == 3 { 4 } else { 3 };
        let (io, requests) = transport([2; 16]);
        assert!(AgentdHos2Device::attach_profile(io, &page(other_version, /*role*/ 1), attachment).is_err());
        assert!(requests.lock().unwrap().is_empty());
    }
}

#[test]
fn g2_successor_local_identity_and_queryabi_cannot_alias_old_history() {
    let process = ProcessIdentity { pid: 700, parent_pid: 1 };
    let mut bytes = page(/*version*/ 4, /*role*/ 1);
    bytes[208..224].fill(/*value*/ 3);
    let (io, requests) = transport([2; 16]);
    assert!(AgentdHos2Device::attach_profile(io, &bytes, Attachment::SuccessorOwnerV4(process)).is_err());
    assert!(requests.lock().unwrap().is_empty());
    let (io, requests) = transport([3; 16]);
    assert!(AgentdHos2Device::attach_profile(io, &page(/*version*/ 4, /*role*/ 1), Attachment::SuccessorOwnerV4(process)).is_err());
    assert_eq!(requests.lock().unwrap().len(), 1);
}

#[test]
fn legacy_v2_constructor_does_not_silently_admit_g2() {
    for version in [3, 4] {
        let (io, requests) = transport([2; 16]);
        assert!(AgentdHos2Device::attach(io, &page(version, /*role*/ 1)).is_err());
        assert!(requests.lock().unwrap().is_empty());
    }
}
