//! Initial control is never Active before the independently signed boundary.
//! These file-custody tests do not stand in for privileged root deployment.

use codex_hepta_neuron::CellGenerationCurrentV1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationOpenModeV1;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use pretty_assertions::assert_eq;

use crate::AgentdError;
use crate::neuron_generation_current::NeuronGenerationInitialReadbackV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
use crate::neuron_v13_generation_initial::prepare_agentd_v13_generation_initial_forward_recovery_v1;
use crate::neuron_v13_generation_initial::recover_agentd_v13_generation_initial_v1;

#[path = "neuron_v13_generation_initial_runtime_tests.rs"]
mod runtime;
#[path = "neuron_v13_generation_initial_test_support.rs"]
mod support;

use support::Fixture;
use support::OPERATION;

#[test]
fn initial_unsigned_bad_signature_wrong_binding_and_changed_current_never_activate()
-> anyhow::Result<()> {
    for change in ["unsigned", "signature", "binding", "current"] {
        let f = Fixture::new()?;
        let binding = CellGenerationOwnerBindingV1::new(
            &f.host.config.generation, f.host.config.max_records,
        )?;
        assert_eq!(f.current.current.check_open(&binding)?, CellGenerationOpenModeV1::Preparing);
        assert_eq!(f.current.current.check_current(&binding), Err(CellGenerationErrorV2::Pending));
        let prepared = f.prepare()?;
        let intent_digest = prepared.intent_digest();
        let before = f.bytes()?;
        assert_eq!(&before[0][..8], b"HPTACG03");
        assert_eq!(before[0].len(), 40);
        assert!(before[2].is_empty());
        if change == "unsigned" {
            drop(prepared);
        } else {
            let mut signed = f.current.sign(prepared.final_use_binding())?;
            match change {
                "signature" => signed.signature[0] ^= 1,
                "binding" => {
                    let mut wrong = prepared.final_use_binding().clone();
                    wrong.payload_sha256[0] ^= 1;
                    signed = f.current.sign(&wrong)?;
                }
                "current" => f.current.advance_artifact_current()?,
                _ => unreachable!("fixed initial cases"),
            }
            assert!(prepared.publish(&signed).is_err());
        }
        let current = f.current.reopen_current()?;
        let original = current.recover_initial_operation(OPERATION, intent_digest)?;
        assert_eq!(current.read_initial_operation(&original)?, NeuronGenerationInitialReadbackV1::Prepared);
        assert_eq!(current.check_current(&binding), Err(CellGenerationErrorV2::Pending));
        if change != "current" {
            assert!(matches!(recover_agentd_v13_generation_initial_v1(
                current, f.current.authorities()?, f.current.selection()?, f.inputs()?,
                AgentdGenerationUpdateRecoveryV1 { operation_id: OPERATION.into(), intent_digest },
            ), Err(AgentdError::Invalid(message)) if message.contains("remains pending; no redispatch")));
        }
        assert_eq!(f.bytes()?, before, "{change}");
        assert_eq!(f.current.authority.capacity()?.used_nonces, 0);
    }
    Ok(())
}

#[test]
fn initial_lost_publication_ack_reopens_original_signed_result_without_new_claim_or_cost()
-> anyhow::Result<()> {
    let f = Fixture::new()?;
    let prepared = f.prepare()?;
    let intent_digest = prepared.intent_digest();
    let signed = f.current.sign(prepared.final_use_binding())?;
    let target_before = f.host.owner_bytes()?;
    f.current.lose_publication_ack();
    assert!(prepared.publish(&signed).is_err());
    assert_eq!(f.current.authority.capacity()?.used_nonces, 1);
    let before = f.bytes()?;
    let claims = f.current.bytes("final-use/authority.claims")?;
    let current = f.current.reopen_current()?;
    let original = current.recover_initial_operation(OPERATION, intent_digest)?;
    let NeuronGenerationInitialReadbackV1::Published(actual) = current.read_initial_operation(&original)?
    else { anyhow::bail!("actual initial CAS was mistaken for not applied") };
    assert_eq!(actual.signed_grant(), &signed);
    assert_eq!(actual.intent_digest(), intent_digest);
    let ready = recover_agentd_v13_generation_initial_v1(
        current, f.current.authorities()?, f.current.selection()?, f.inputs()?,
        AgentdGenerationUpdateRecoveryV1 { operation_id: OPERATION.into(), intent_digest },
    )?;
    assert_eq!(f.host.owner_bytes()?, target_before);
    assert_eq!(f.bytes()?, before);
    assert_eq!(f.current.bytes("final-use/authority.claims")?, claims);
    assert_eq!(f.current.authority.capacity()?.used_nonces, 1);
    drop(ready);
    Ok(())
}

#[test]
fn uncertain_initial_claim_remains_pending_until_new_signed_forward_publication()
-> anyhow::Result<()> {
    let f = Fixture::new()?;
    let prepared = f.prepare()?;
    let original_binding = prepared.final_use_binding().clone();
    let intent_digest = prepared.intent_digest();
    let signed = f.current.sign(&original_binding)?;
    f.current.reject_publication_write();
    assert!(prepared.publish(&signed).is_err());
    assert_eq!(f.current.authority.capacity()?.used_nonces, 1);
    let before = f.bytes()?;
    assert!(matches!(recover_agentd_v13_generation_initial_v1(
        f.current.reopen_current()?, f.current.authorities()?, f.current.selection()?,
        f.inputs()?, AgentdGenerationUpdateRecoveryV1 {
            operation_id: OPERATION.into(), intent_digest,
        },
    ), Err(AgentdError::Invalid(message)) if message.contains("remains pending; no redispatch")));
    assert_eq!(f.bytes()?, before);
    let target_before = f.host.owner_bytes()?;
    let forward = prepare_agentd_v13_generation_initial_forward_recovery_v1(
        f.current.reopen_current()?, f.current.authorities()?, f.current.selection()?,
        f.inputs()?, AgentdGenerationForwardRecoveryV1 {
            original_operation_id: OPERATION.into(), original_intent_digest: intent_digest,
            new_operation_id: "initial-v13-forward".into(),
        },
    )?;
    assert_ne!(forward.final_use_binding(), &original_binding);
    let next = f.current.sign(forward.final_use_binding())?;
    assert_ne!(next.grant.nonce, signed.grant.nonce);
    assert_eq!(f.host.owner_bytes()?, target_before);
    let ready = forward.publish(&next)?;
    assert_eq!(f.current.authority.capacity()?.used_nonces, 2);
    assert_eq!(f.host.owner_bytes()?, target_before);
    drop(ready);
    Ok(())
}
