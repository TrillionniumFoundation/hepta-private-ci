//! Original wire/parser paths with explicit transport fixtures, not native G2.

use super::*;
use crate::hos2_device::read_u16;
use pretty_assertions::assert_eq;
use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;

#[path = "hos2_history_owner_tests.rs"]
mod owner;

type Replies = VecDeque<(u16, Result<Vec<u8>, String>)>;

struct Script {
    requests: Mutex<Vec<Vec<u8>>>,
    replies: Mutex<Replies>,
}

impl ControlTransport for Arc<Script> {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String> {
        self.requests.lock().unwrap().push(input.to_vec());
        let (opcode, payload) = self
            .replies
            .lock()
            .unwrap()
            .pop_front()
            .ok_or("extra ioctl")?;
        assert_eq!(read_u16(input, /*offset*/ 8)?, opcode);
        let payload = payload?;
        output[..4].copy_from_slice(b"HOSR");
        output[4..6].copy_from_slice(&2_u16.to_le_bytes());
        output[8..10].copy_from_slice(&opcode.to_le_bytes());
        output[12..16].copy_from_slice(&64_u32.to_le_bytes());
        output[16..20].copy_from_slice(&(payload.len() as u32).to_le_bytes());
        output[24..40].copy_from_slice(&input[24..40]);
        output[40..56].fill(1);
        output[64..64 + payload.len()].copy_from_slice(&payload);
        Ok(())
    }
}

fn process() -> ProcessIdentity {
    ProcessIdentity {
        pid: 703,
        parent_pid: 1,
    }
}

fn page() -> Vec<u8> {
    let mut bytes = vec![0; 4096];
    bytes[..8].copy_from_slice(b"HOS2BOOT");
    for (offset, value) in [
        (8, 4_u64),
        (16, 5),
        (24, 240),
        (64, 3),
        (72, 1),
        (80, 4),
        (88, 1),
        (152, 701),
        (176, HOS2_CPU_PERIOD_NS),
        (192, 1),
        (200, 703),
        (224, 9),
    ] {
        bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    for (offset, value) in [(96, 1), (112, 2), (128, 3), (208, 4)] {
        bytes[offset..offset + 16].fill(value);
    }
    bytes
}

fn script(local_space: [u8; 16], following: Replies) -> Arc<Script> {
    let mut abi = vec![0; 48];
    abi[..16].copy_from_slice(&local_space);
    for (offset, value) in [(16, 4096_u32), (20, 40), (24, 64)] {
        abi[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    abi[32..40].copy_from_slice(&62_u64.to_le_bytes());
    let mut replies = VecDeque::from([(1, Ok(abi))]);
    replies.extend(following);
    Arc::new(Script {
        requests: Mutex::new(Vec::new()),
        replies: Mutex::new(replies),
    })
}

fn request(space: [u8; 16]) -> Result<Hos2InstallBudgetV1, String> {
    Ok(Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new([1; 16], space, /*sequence*/ 1)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: HOS2_CPU_PERIOD_NS,
        cap_ns: 25_000_000,
    })
}

fn applied() -> Vec<u8> {
    let mut bytes = vec![0; 64];
    bytes[..2].copy_from_slice(&1_u16.to_le_bytes());
    bytes[16..32].fill(9);
    for (offset, value) in [
        (8, 1_u64),
        (32, 2),
        (40, 1),
        (48, HOS2_CPU_PERIOD_NS + 1001),
        (56, 999),
    ] {
        bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    bytes
}

#[test]
fn g2_history_successor_queries_both_old_spaces_using_its_new_queryabi_space() -> Result<(), String>
{
    let io = script(
        [4; 16],
        VecDeque::from([(4, Ok(applied())), (4, Ok(applied()))]),
    );
    let device = AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &page(), process())?;
    for space in [[2; 16], [3; 16]] {
        assert_eq!(
            device.observe(&request(space)?)?,
            Hos2InstallOutcome::Observed(Hos2DeliveryObservation::Applied {
                stable_object_id: [9; 16],
                previous_revision: 1,
                revision: 2,
                effective_ns: HOS2_CPU_PERIOD_NS + 1001,
                consumed_ns: 999,
            })
        );
    }
    let requests = io.requests.lock().unwrap();
    assert_eq!(requests.len(), 3);
    for (index, slot, old_space) in [(1, 3, [2; 16]), (2, 4, [3; 16])] {
        assert_eq!(read_u16(&requests[index], /*offset*/ 8)?, 4);
        assert_eq!(read64(&requests[index], /*offset*/ 40)?, slot);
        assert_eq!(&requests[index][80..96], &old_space);
    }
    assert!(io.replies.lock().unwrap().is_empty());
    Ok(())
}

#[test]
fn g2_history_successor_rejects_role_process_slots_grants_and_page_corruption_before_io() {
    let original = page();
    for (offset, value) in [
        (8, 3_u64),
        (16, 1),
        (16, 2),
        (16, 3),
        (16, 4),
        (24, 232),
        (32, 1),
        (40, 1),
        (48, 2),
        (56, 1),
        (64, 0),
        (72, 2),
        (80, 0),
        (88, 2),
        (144, 700),
        (152, 0),
        (152, 703),
        (160, 702),
        (168, 50_000_000),
        (176, 1),
        (184, 300_000_000_000),
        (192, 2),
        (200, 702),
        (224, 0),
        (232, 1),
    ] {
        let mut changed = original.clone();
        changed[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
        let io = script([4; 16], VecDeque::new());
        assert!(
            AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &changed, process()).is_err()
        );
        assert!(io.requests.lock().unwrap().is_empty());
    }
    for offset in [0, 3000] {
        let mut changed = original.clone();
        changed[offset] ^= 1;
        let io = script([4; 16], VecDeque::new());
        assert!(
            AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &changed, process()).is_err()
        );
        assert!(io.requests.lock().unwrap().is_empty());
    }
    for size in [0, 8, 239, 4097] {
        let mut changed = original.clone();
        changed.resize(size, /*value*/ 0);
        let io = script([4; 16], VecDeque::new());
        assert!(
            AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &changed, process()).is_err()
        );
        assert!(io.requests.lock().unwrap().is_empty());
    }
    for actual in [
        ProcessIdentity {
            pid: 702,
            parent_pid: 1,
        },
        ProcessIdentity {
            pid: 703,
            parent_pid: 2,
        },
    ] {
        let io = script([4; 16], VecDeque::new());
        assert!(AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &original, actual).is_err());
        assert!(io.requests.lock().unwrap().is_empty());
    }
}

#[test]
fn g2_history_successor_never_uses_old_space_as_its_local_process_identity() {
    for (offset, space) in [
        (96, [0; 16]),
        (112, [0; 16]),
        (128, [2; 16]),
        (208, [0; 16]),
        (208, [2; 16]),
        (208, [3; 16]),
    ] {
        let mut changed = page();
        changed[offset..offset + 16].copy_from_slice(&space);
        let io = script([4; 16], VecDeque::new());
        assert!(
            AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &changed, process()).is_err()
        );
        assert!(io.requests.lock().unwrap().is_empty());
    }
    for reported in [[2; 16], [3; 16], [5; 16]] {
        let io = script(reported, VecDeque::new());
        assert!(AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &page(), process()).is_err());
        assert_eq!(io.requests.lock().unwrap().len(), 1);
    }
}

#[test]
fn g2_history_successor_refuses_every_install_and_contradictory_old_request_without_io()
-> Result<(), String> {
    let io = script([4; 16], VecDeque::new());
    let device = AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &page(), process())?;
    let original = request([2; 16])?;
    assert!(device.install(&original).is_err());
    for field in ["slot", "generation", "cap"] {
        let mut changed = original.clone();
        let expected = match field {
            "slot" => {
                changed.manage_slot = 3;
                Hos2InstallContradiction::RequestBindingMismatch
            }
            "generation" => {
                changed.manage_generation = 2;
                Hos2InstallContradiction::RequestBindingMismatch
            }
            "cap" => {
                changed.cap_ns = 50_000_001;
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: 50_000_000,
                }
            }
            _ => unreachable!(),
        };
        assert!(device.install(&changed).is_err());
        assert_eq!(
            device.observe(&changed)?,
            Hos2InstallOutcome::Contradiction(expected)
        );
    }
    for delivery in [
        Hos2DeliveryId::new([8; 16], [2; 16], /*sequence*/ 1)?,
        Hos2DeliveryId::new([1; 16], [4; 16], /*sequence*/ 1)?,
    ] {
        let mut changed = original.clone();
        changed.delivery = delivery;
        assert!(device.install(&changed).is_err());
        assert!(device.observe(&changed).is_err());
    }
    assert_eq!(io.requests.lock().unwrap().len(), 1);
    Ok(())
}

#[test]
fn g2_history_successor_preserves_kernel_process_or_image_epoch_refusal_without_retry()
-> Result<(), String> {
    let io = script(
        [4; 16],
        VecDeque::from([(
            4,
            Err("kernel ESTALE: different process/image epoch".into()),
        )]),
    );
    let device = AgentdHos2HistoryDevice::attach(Box::new(io.clone()), &page(), process())?;
    assert_eq!(
        device.observe(&request([2; 16])?),
        Err("kernel ESTALE: different process/image epoch".into())
    );
    assert_eq!(io.requests.lock().unwrap().len(), 2);
    assert!(io.replies.lock().unwrap().is_empty());
    Ok(())
}
