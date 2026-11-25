//! Wire parsing negatives are separate from actual native qualification.

use super::*;
use pretty_assertions::assert_eq;

fn successor_page(role: u64) -> Vec<u8> {
    let mut bytes = g2_bootstrap_for_role(if role == 5 { 3 } else { role });
    for (offset, value) in [
        (8, 4_u64),
        (16, role),
        (24, 240),
        (144, 5),
        (160, 6),
        (200, if role == 1 { 5 } else { 6 }),
        (224, 1),
    ] {
        bytes[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    let local_space = if role == 1 { [2; 16] } else { [3; 16] };
    bytes[208..224].copy_from_slice(&local_space);
    if role == 5 {
        bytes[32..64].fill(0);
        for offset in [144, 160, 168, 184] {
            bytes[offset..offset + 8].fill(0);
        }
        bytes[200..208].copy_from_slice(&7_u64.to_le_bytes());
        bytes[208..224].copy_from_slice(&[4; 16]);
    }
    bytes
}

fn attach_successor(
    role: u64,
    replies: VecDeque<(u16, Result<Response, String>)>,
) -> TestResult<(AgentdHos2Device, Arc<Mutex<Script>>)> {
    let page = successor_page(role);
    let mut abi = vec![0; 48];
    abi[..16].copy_from_slice(&page[208..224]);
    for (offset, value) in [(16, 4096_u32), (20, 40), (24, 64)] {
        abi[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    abi[32..40].copy_from_slice(&62_u64.to_le_bytes());
    let mut exchanges = VecDeque::from([(
        1,
        Ok(Response {
            status: 0,
            revision: 0,
            payload: abi,
        }),
    )]);
    exchanges.extend(replies);
    let script = Arc::new(Mutex::new(Script {
        replies: exchanges,
        requests: vec![],
    }));
    let device = AgentdHos2Device::attach(Box::new(ScriptedTransport(script.clone())), &page)?;
    Ok((device, script))
}

fn old_request(space_id: [u8; 16]) -> TestResult<Hos2InstallBudgetV1> {
    Ok(Hos2InstallBudgetV1 {
        schema_version: 1,
        delivery: Hos2DeliveryId::new([1; 16], space_id, 1)?,
        manage_slot: 2,
        manage_generation: 1,
        expected_revision: 1,
        period_ns: HOS2_CPU_PERIOD_NS,
        cap_ns: 25_000_000,
    })
}

#[test]
fn v4_owner_uses_its_actual_fresh_namespace_and_launch_generation() -> TestResult {
    for role in [1, 3] {
        let (device, script) = attach_successor(role, VecDeque::new())?;
        assert!(!device.is_history_only());
        assert_eq!(device.kernel_launch_generation(), 1);
        let request = device.install_request(1, 1, 25_000_000)?;
        assert_eq!(
            request.delivery.space_id,
            if role == 1 { [2; 16] } else { [3; 16] }
        );
        assert_eq!((request.manage_slot, request.manage_generation), (2, 1));
        assert_eq!(script.lock().map_err(|e| e.to_string())?.requests.len(), 1);
    }
    Ok(())
}

#[test]
fn v4_history_only_keeps_old_request_constraints_without_cpu_authority() -> TestResult {
    for (space, slot) in [([2; 16], 3), ([3; 16], 4)] {
        let query = applied_query(1, HOS2_CPU_PERIOD_NS + 1_001, 999);
        let (device, script) = attach_successor(5, VecDeque::from([(4, Ok(query))]))?;
        assert!(device.is_history_only());
        assert_eq!(
            device.native_history_identity(),
            ([1; 16], [2; 16], [3; 16])
        );
        assert!(device.read_usage(1).is_err());
        assert!(device.install_request(1, 1, 0).is_err());
        let request = old_request(space)?;
        assert!(device.install(&request).is_err());
        assert_eq!(
            device.observe(&request)?,
            Hos2InstallOutcome::Observed(Hos2DeliveryObservation::Applied {
                stable_object_id: [9; 16],
                previous_revision: 1,
                revision: 2,
                effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
                consumed_ns: 999
            })
        );
        let script = script.lock().map_err(|e| e.to_string())?;
        assert_eq!(script.requests.len(), 2);
        assert!(script.replies.is_empty());
        assert_eq!(read_u16(&script.requests[1], 8)?, 4);
        assert_eq!(
            (
                read64(&script.requests[1], 40)?,
                read64(&script.requests[1], 48)?
            ),
            (slot, 1)
        );
        assert_eq!(read16(&script.requests[1], 80)?, space);
    }
    Ok(())
}

#[test]
fn v4_history_only_rejects_foreign_boot_namespace_or_changed_old_binding() -> TestResult {
    let (device, script) = attach_successor(5, VecDeque::new())?;
    for (boot, space) in [([9; 16], [2; 16]), ([1; 16], [4; 16]), ([1; 16], [8; 16])] {
        let mut request = old_request(space)?;
        request.delivery.boot_id = boot;
        assert!(device.observe(&request).is_err());
    }
    let mut request = old_request([2; 16])?;
    request.manage_slot = 9;
    assert_eq!(
        device.observe(&request)?,
        Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::RequestBindingMismatch)
    );
    request.manage_slot = 2;
    request.cap_ns = 50_000_001;
    assert_eq!(
        device.observe(&request)?,
        Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::BudgetExceedsGrant {
            maximum_cap_ns: 50_000_000
        })
    );
    assert_eq!(script.lock().map_err(|e| e.to_string())?.requests.len(), 1);
    Ok(())
}

#[test]
fn v4_rejects_confused_roles_topology_or_capabilities_before_any_exchange() -> TestResult {
    for role in [1, 3, 5] {
        let valid = successor_page(role);
        let mut pages = vec![];
        for offset in [
            8, 16, 24, 32, 40, 48, 56, 64, 72, 80, 88, 152, 168, 176, 184, 192, 232, 240, 4095,
        ] {
            let mut bad = valid.clone();
            bad[offset] ^= 0xff;
            pages.push(bad);
        }
        for offset in [200, 224] {
            let mut bad = valid.clone();
            bad[offset..offset + 8].fill(0);
            pages.push(bad);
        }
        for offset in [144, 160] {
            let mut bad = valid.clone();
            bad[offset..offset + 8]
                .copy_from_slice(&(if role == 5 { 1_u64 } else { 0 }).to_le_bytes());
            pages.push(bad);
        }
        for length in [0, 191, 192, 200, 239, 241, 4095] {
            pages.push(valid[..length].to_vec());
        }
        for offset in [96, 112, 128, 208] {
            let mut bad = valid.clone();
            bad[offset..offset + 16].fill(0);
            pages.push(bad);
        }
        for page in pages {
            let script = Arc::new(Mutex::new(Script {
                replies: VecDeque::new(),
                requests: vec![],
            }));
            assert!(
                AgentdHos2Device::attach(Box::new(ScriptedTransport(script.clone())), &page)
                    .is_err()
            );
            assert!(
                script
                    .lock()
                    .map_err(|e| e.to_string())?
                    .requests
                    .is_empty()
            );
        }
    }
    Ok(())
}

#[test]
fn v4_history_only_query_abi_must_match_its_local_space_not_old_history() -> TestResult {
    let page = successor_page(5);
    let mut abi = vec![0; 48];
    abi[..16].copy_from_slice(&[2; 16]);
    for (offset, value) in [(16, 4096_u32), (20, 40), (24, 64)] {
        abi[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    abi[32..40].copy_from_slice(&62_u64.to_le_bytes());
    let script = Arc::new(Mutex::new(Script {
        requests: vec![],
        replies: VecDeque::from([(
            1,
            Ok(Response {
                status: 0,
                revision: 0,
                payload: abi,
            }),
        )]),
    }));
    assert!(AgentdHos2Device::attach(Box::new(ScriptedTransport(script.clone())), &page).is_err());
    assert_eq!(script.lock().map_err(|e| e.to_string())?.requests.len(), 1);
    Ok(())
}
