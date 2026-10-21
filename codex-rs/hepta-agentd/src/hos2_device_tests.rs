//! The real adapter's bounded frame and dispatch path, with explicit scripted
//! transport replies. These tests do not claim native kernel qualification.

use super::*;
use pretty_assertions::assert_eq;
use std::collections::VecDeque;
use std::error::Error;
use std::sync::Arc;
use std::sync::Mutex;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

/// Fixed A02 wire vectors shared with the OS consumer. This transport performs
/// no native call and grants no capability; the real adapter parses every byte.
struct A02Vectors {
    exchanges: Mutex<VecDeque<(Vec<u8>, Vec<u8>)>>,
}

impl ControlTransport for Arc<A02Vectors> {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String> {
        let mut exchanges = self.exchanges.lock().map_err(|error| error.to_string())?;
        let (expected, reply) = exchanges.pop_front().ok_or("unexpected HOS2 exchange")?;
        if input != expected || output.len() < reply.len() {
            return Err("adapter differs from the pinned A02 wire vector".to_string());
        }
        output[..reply.len()].copy_from_slice(&reply);
        Ok(())
    }
}

#[test]
fn production_owner_request_and_a02_wire_vectors_match() -> TestResult {
    use codex_hepta_operations::OperationIntentV1;
    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    let vector: serde_json::Value =
        serde_json::from_str(include_str!("../tests/fixtures/hos2_production_owner.json"))?;
    let bytes = |name: &str| -> TestResult<Vec<u8>> {
        let value = vector[name].as_str().ok_or("missing A02 bytes")?;
        if !value.len().is_multiple_of(2) {
            return Err("odd A02 hexadecimal length".into());
        }
        value
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| Ok(u8::from_str_radix(std::str::from_utf8(pair)?, 16)?))
            .collect()
    };
    let transport = Arc::new(A02Vectors {
        exchanges: Mutex::new(VecDeque::from([
            (bytes("abi_request_hex")?, bytes("abi_response_hex")?),
            (bytes("install_frame_hex")?, bytes("install_response_hex")?),
            (
                bytes("history_request_hex")?,
                bytes("history_response_hex")?,
            ),
        ])),
    });
    let device = AgentdHos2Device::attach(Box::new(transport.clone()), &bytes("bootstrap_hex")?)?;
    let request = device.install_request(
        /*sequence*/ 1, /*expected_revision*/ 1, /*cap_ns*/ 25_000_000,
    )?;
    let payload = vector["payload_json"]
        .as_str()
        .ok_or("missing owner payload")?;
    assert_eq!(request.to_json()?, payload);
    assert_eq!(Hos2InstallBudgetV1::from_json(payload)?, request);
    let operation = OperationIntentV1::new(
        StableId::new(vector["operation_id"].as_str().ok_or("missing K")?)?,
        StableId::new(vector["subject_id"].as_str().ok_or("missing subject")?)?,
        StableId::new(codex_hepta_memory::HOS2_DESTINATION_V1)?,
        Digest32::of_bytes(payload.as_bytes()),
        request.scope_digest(),
        Generation::new(
            vector["policy_generation"]
                .as_u64()
                .ok_or("missing policy generation")?,
        )?,
        /*expected_predecessor*/ None,
    )?;
    for (field, digest) in [
        ("payload_digest", operation.payload_digest()),
        ("scope_digest", operation.scope_digest()),
        ("semantic_digest", operation.semantic_digest()),
    ] {
        let expected: [u8; 32] = serde_json::from_value(vector[field].clone())?;
        assert_eq!(digest.into_array(), expected);
    }
    assert_eq!(
        device.install(&request)?,
        Hos2InstallOutcome::Observed(Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16],
            previous_revision: 1,
            revision: 2,
            effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
            consumed_ns: 999,
        })
    );
    assert!(
        transport
            .exchanges
            .lock()
            .map_err(|error| error.to_string())?
            .is_empty()
    );
    Ok(())
}

struct Script {
    replies: VecDeque<(u16, Result<Response, String>)>,
    requests: Vec<Vec<u8>>,
}

struct ScriptedTransport(Arc<Mutex<Script>>);

impl ControlTransport for ScriptedTransport {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String> {
        let mut script = self.0.lock().map_err(|error| error.to_string())?;
        script.requests.push(input.to_vec());
        let (opcode, response) = script
            .replies
            .pop_front()
            .ok_or_else(|| "unexpected native exchange".to_string())?;
        assert_eq!(read_u16(input, /*offset*/ 8)?, opcode);
        assert_eq!(
            (read64(input, /*offset*/ 24)?, read64(input, /*offset*/ 32)?),
            (1, 0)
        );
        let response = response?;
        output[..4].copy_from_slice(b"HOSR");
        output[4..6].copy_from_slice(&2_u16.to_le_bytes());
        output[8..10].copy_from_slice(&opcode.to_le_bytes());
        output[10..12].copy_from_slice(&response.status.to_le_bytes());
        output[12..16].copy_from_slice(&64_u32.to_le_bytes());
        output[16..20].copy_from_slice(&(response.payload.len() as u32).to_le_bytes());
        output[24..40].copy_from_slice(&input[24..40]);
        output[40..56].copy_from_slice(&[1; 16]);
        output[56..64].copy_from_slice(&response.revision.to_le_bytes());
        output[64..64 + response.payload.len()].copy_from_slice(&response.payload);
        Ok(())
    }
}

fn fixture(
    install: Result<Response, String>,
    query: Response,
) -> TestResult<(AgentdHos2Device, Hos2InstallBudgetV1, Arc<Mutex<Script>>)> {
    fixture_for_role(/*role*/ 1, Some(install), query)
}

fn fixture_for_role(
    role: u64,
    install: Option<Result<Response, String>>,
    query: Response,
) -> TestResult<(AgentdHos2Device, Hos2InstallBudgetV1, Arc<Mutex<Script>>)> {
    let mut bootstrap = vec![0; 4096];
    bootstrap[..8].copy_from_slice(b"HOS2BOOT");
    for (offset, value) in [
        (8, 2_u64),
        (16, role),
        (24, 192),
        (32, 1),
        (40, 1),
        (48, 2),
        (56, 1),
        (64, 3),
        (72, 1),
        (144, 1),
        (152, 2),
        (160, 3),
        (168, 50_000_000),
        (176, HOS2_CPU_PERIOD_NS),
        (184, 300_000_000_000),
    ] {
        bootstrap[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    bootstrap[96..112].copy_from_slice(&[1; 16]);
    bootstrap[112..128].copy_from_slice(&[2; 16]);
    bootstrap[128..144].copy_from_slice(&[3; 16]);
    if role == 3 {
        bootstrap[80..88].copy_from_slice(&4_u64.to_le_bytes());
        bootstrap[88..96].copy_from_slice(&1_u64.to_le_bytes());
    }
    let mut abi = vec![0; 48];
    abi[..16].copy_from_slice(if role == 1 { &[2; 16] } else { &[3; 16] });
    for (offset, value) in [(16, 4096_u32), (20, 40), (24, 64)] {
        abi[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
    }
    abi[32..40].copy_from_slice(&62_u64.to_le_bytes());
    let mut replies = VecDeque::from([(
        1,
        Ok(Response {
            status: 0,
            revision: 0,
            payload: abi,
        }),
    )]);
    if let Some(install) = install {
        replies.push_back((3, install));
    }
    replies.push_back((4, Ok(query)));
    let script = Arc::new(Mutex::new(Script {
        replies,
        requests: Vec::new(),
    }));
    let device = AgentdHos2Device::attach(Box::new(ScriptedTransport(script.clone())), &bootstrap)?;
    let request = device.install_request(
        /*sequence*/ 1, /*expected_revision*/ 1, /*cap_ns*/ 25_000_000,
    )?;
    Ok((device, request, script))
}

fn acknowledgement() -> Response {
    let mut payload = Vec::new();
    for value in [1_u64, HOS2_CPU_PERIOD_NS + 1_001, 999] {
        payload.extend_from_slice(&value.to_le_bytes());
    }
    Response {
        status: 0,
        revision: 2,
        payload,
    }
}

fn applied_query(previous_revision: u64, effective_ns: u64, consumed_ns: u64) -> Response {
    let mut payload = vec![0; 64];
    payload[..2].copy_from_slice(&1_u16.to_le_bytes());
    payload[8..16].copy_from_slice(&1_u64.to_le_bytes());
    payload[16..32].copy_from_slice(&[9; 16]);
    for (offset, value) in [
        (32, previous_revision + 1),
        (40, previous_revision),
        (48, effective_ns),
        (56, consumed_ns),
    ] {
        payload[offset..offset + 8].copy_from_slice(&value.to_le_bytes());
    }
    Response {
        status: 0,
        revision: 0,
        payload,
    }
}

#[test]
fn conflict_does_not_query_or_commit_the_previous_request_using_the_same_d() -> TestResult {
    let (device, request, script) = fixture(
        Ok(Response {
            status: 5,
            revision: 0,
            payload: Vec::new(),
        }),
        applied_query(
            /*previous_revision*/ 1,
            /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
            /*consumed_ns*/ 999,
        ),
    )?;
    assert_eq!(
        device.install(&request)?,
        Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::ConflictStatus)
    );
    {
        let script = script.lock().map_err(|error| error.to_string())?;
        assert_eq!((script.requests.len(), script.replies.len()), (2, 1));
        assert_eq!(read64(&script.requests[1], /*offset*/ 80)?, request.cap_ns);
    }
    // The native history still returns the older result without a cap/digest.
    // A source that has recorded the conflict must not treat this as repair.
    assert_eq!(
        device.query(&request.delivery)?,
        Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16],
            previous_revision: 1,
            revision: 2,
            effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
            consumed_ns: 999,
        }
    );
    Ok(())
}

#[test]
fn successful_acknowledgement_matches_all_four_shared_history_values() -> TestResult {
    let effective = HOS2_CPU_PERIOD_NS + 1_001;
    for (previous_revision, effective_ns, consumed_ns) in [
        (1, effective, 999),
        (3, effective, 999),
        (1, effective + 1, 999),
        (1, effective, 1_000),
    ] {
        let observation = Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16],
            previous_revision,
            revision: previous_revision + 1,
            effective_ns,
            consumed_ns,
        };
        let (device, request, script) = fixture(
            Ok(acknowledgement()),
            applied_query(previous_revision, effective_ns, consumed_ns),
        )?;
        let expected = if (previous_revision, effective_ns, consumed_ns) == (1, effective, 999) {
            Hos2InstallOutcome::Observed(observation)
        } else {
            Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::AcknowledgementMismatch {
                previous_revision: 1,
                revision: 2,
                effective_ns: effective,
                consumed_ns: 999,
                observation,
            })
        };
        assert_eq!(device.install(&request)?, expected);
        let script = script.lock().map_err(|error| error.to_string())?;
        assert_eq!((script.requests.len(), script.replies.len()), (3, 0));
    }
    Ok(())
}

#[test]
fn malformed_success_is_a_contradiction_and_lost_transport_reply_remains_unknown() -> TestResult {
    let mut invalid = acknowledgement();
    invalid.revision = 4;
    let expected =
        Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::InvalidAcknowledgement {
            revision: invalid.revision,
            payload: invalid.payload.clone(),
        });
    let (device, request, script) = fixture(
        Ok(invalid),
        applied_query(
            /*previous_revision*/ 1,
            /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
            /*consumed_ns*/ 999,
        ),
    )?;
    assert_eq!(device.install(&request)?, expected);
    assert_eq!(
        script
            .lock()
            .map_err(|error| error.to_string())?
            .requests
            .len(),
        2
    );
    let (device, request, script) = fixture(
        Err("reply lost after ioctl entry".to_string()),
        applied_query(
            /*previous_revision*/ 1,
            /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
            /*consumed_ns*/ 999,
        ),
    )?;
    assert_eq!(
        device.install(&request),
        Err("reply lost after ioctl entry".to_string())
    );
    assert_eq!(
        script
            .lock()
            .map_err(|error| error.to_string())?
            .requests
            .len(),
        2
    );
    Ok(())
}

#[test]
fn known_request_refusals_cannot_query_an_older_applied_delivery() -> TestResult {
    for changed_field in ["cap", "slot", "generation"] {
        let (device, mut request, script) = fixture_for_role(
            /*role*/ 1,
            /*install*/ None,
            applied_query(
                /*previous_revision*/ 1,
                /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
                /*consumed_ns*/ 999,
            ),
        )?;
        let contradiction = match changed_field {
            "cap" => {
                request.cap_ns = 75_000_000;
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: 50_000_000,
                }
            }
            "slot" => {
                request.manage_slot += 1;
                Hos2InstallContradiction::RequestBindingMismatch
            }
            "generation" => {
                request.manage_generation += 1;
                Hos2InstallContradiction::RequestBindingMismatch
            }
            _ => return Err("unexpected fixture field".into()),
        };
        request.to_json()?;
        let expected = Hos2InstallOutcome::Contradiction(contradiction);
        assert_eq!(device.install(&request)?, expected);
        assert_eq!(device.observe(&request)?, expected);
        let script = script.lock().map_err(|error| error.to_string())?;
        assert_eq!((script.requests.len(), script.replies.len()), (1, 1));
    }
    Ok(())
}

#[test]
fn recovery_observes_original_manager_namespace_without_reinstalling_it() -> TestResult {
    let (device, mut request, script) = fixture_for_role(
        /*role*/ 3,
        /*install*/ None,
        applied_query(
            /*previous_revision*/ 1,
            /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
            /*consumed_ns*/ 999,
        ),
    )?;
    request.delivery = Hos2DeliveryId::new([1; 16], [2; 16], /*sequence*/ 1)?;
    assert_eq!(
        device.install(&request)?,
        Hos2InstallOutcome::Contradiction(Hos2InstallContradiction::RequestBindingMismatch)
    );
    assert_eq!(
        device.observe(&request)?,
        Hos2InstallOutcome::Observed(Hos2DeliveryObservation::Applied {
            stable_object_id: [9; 16],
            previous_revision: 1,
            revision: 2,
            effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
            consumed_ns: 999,
        })
    );
    let script = script.lock().map_err(|error| error.to_string())?;
    assert_eq!((script.requests.len(), script.replies.len()), (2, 0));
    assert_eq!(
        (
            read64(&script.requests[1], /*offset*/ 40)?,
            read64(&script.requests[1], /*offset*/ 48)?
        ),
        (3, 1)
    );
    assert_eq!(read16(&script.requests[1], /*offset*/ 80)?, [2; 16]);
    Ok(())
}

#[test]
fn changed_boot_and_inaccessible_history_remain_unavailable() -> TestResult {
    for delivery in [
        Hos2DeliveryId::new([4; 16], [2; 16], /*sequence*/ 1)?,
        Hos2DeliveryId::new([1; 16], [4; 16], /*sequence*/ 1)?,
    ] {
        let (device, mut request, script) = fixture_for_role(
            /*role*/ 1,
            /*install*/ None,
            applied_query(
                /*previous_revision*/ 1,
                /*effective_ns*/ HOS2_CPU_PERIOD_NS + 1_001,
                /*consumed_ns*/ 999,
            ),
        )?;
        request.delivery = delivery;
        assert!(device.observe(&request).is_err());
        let script = script.lock().map_err(|error| error.to_string())?;
        assert_eq!((script.requests.len(), script.replies.len()), (1, 1));
    }
    Ok(())
}
