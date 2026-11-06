//! Guarded V13 assembly keeps actual file/boot checks and signed publication.
//! Tests use real owners and deliberately invalid closure assets, not a model
//! qualification or a substitute authority for a production host.

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;

use codex_hepta_neuron::CellLearningBindingV2;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use crate::AgentdError;
use crate::neuron_generation_update::AgentdGenerationUpdateRecoveryV1;
use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_update_forward::AgentdGenerationForwardRecoveryV1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_forward_recovery_v1;
use crate::neuron_v13_generation_update::prepare_agentd_v13_generation_update_v1;
use crate::neuron_v13_generation_update::recover_agentd_v13_generation_update_v1;

#[path = "neuron_v13_generation_initial_tests.rs"]
mod initial;
#[path = "neuron_v13_generation_guarded_runtime_tests.rs"]
mod runtime;
#[path = "neuron_v13_generation_guarded_test_support.rs"]
mod support;

use support::Fixture;

#[test]
fn guarded_preflight_rejects_identity_epoch_binding_and_actual_fd_aliases_before_writes()
-> anyhow::Result<()> {
    let f = Fixture::new()?;
    let before = f.bytes()?;
    let asset_before = fs::read(&f.host.model_path)?;
    let alias = f.host.paths[0].with_file_name("asset-owner-alias");
    fs::hard_link(&f.host.model_path, &alias)?;
    for case in 0..8 {
        let mut inputs = f.inputs()?;
        let mut identity = f.host.identity.clone();
        match case {
            0 => identity.resources.memory_limit_mib += 1,
            1 => inputs.config.expected_boot_id_digest = Digest32::of_bytes(b"wrong boot"),
            2 => inputs.config.generation.source_frontier = [99; 32],
            3 => {
                inputs.config.generation.manifest.learning =
                    CellLearningBindingV2::Frozen { weights: [25; 32] };
            }
            4 => inputs.files.journal = File::open(&f.host.paths[0])?,
            5 => {
                inputs.files.control = OpenOptions::new()
                    .read(true).write(true).open(&f.host.paths[2])?;
            }
            6 => {
                inputs.files.witness = OpenOptions::new()
                    .read(true).write(true).open(&f.host.paths[0])?;
            }
            7 => {
                inputs.files.journal = OpenOptions::new()
                    .read(true).write(true).open(&alias)?;
            }
            _ => unreachable!("fixed preflight cases"),
        }
        inputs.identity = &identity;
        let result = prepare_agentd_v13_generation_update_v1(
            f.update.current.clone(), f.update.authorities()?, f.update.old_journal()?,
            f.update.selection()?, inputs,
            AgentdGenerationUpdateRequestV1 { operation_id: "rejected-preflight".into() },
        );
        let Err(error) = result else { anyhow::bail!("preflight case {case} was accepted") };
        if case >= 4 {
            assert!(error.to_string().contains("distinct regular read/write files"), "{error}");
        }
        assert_eq!(f.bytes()?, before, "case {case}");
        assert_eq!(fs::read(&f.host.model_path)?, asset_before);
        assert_eq!(f.update.authority.capacity()?.used_nonces, 0);
    }
    // A valid preparation still works after rejected probes. It creates the
    // real guarded genesis but neither a preparation cost nor dispatch record.
    let prepared = f.prepare("valid-after-preflight")?;
    let target = f.host.owner_bytes()?;
    assert_eq!(&target[0][..8], b"HPTACG03");
    assert_eq!(target[0].len(), 40);
    assert!(target[2].is_empty());
    assert_eq!(f.update.authority.capacity()?.used_nonces, 0);
    drop(prepared);
    Ok(())
}

#[test]
fn guarded_control_lock_failure_keeps_preparation_bound_to_its_original_task()
-> anyhow::Result<()> {
    let f = Fixture::new()?;
    let before = f.bytes()?;
    let locked = OpenOptions::new().read(true).append(true).open(&f.host.paths[2])?;
    locked.try_lock()?;
    let error = f.prepare("locked-control").err()
        .ok_or_else(|| anyhow::anyhow!("a second writer was admitted"))?;
    assert!(error.to_string().contains("WriterUnavailable"));
    assert_eq!(f.bytes()?, before);
    drop(locked);
    let mut inputs = f.inputs()?;
    inputs.config.generation.task_digest = [18; 32];
    assert!(matches!(prepare_agentd_v13_generation_update_v1(
        f.update.current.clone(), f.update.authorities()?, f.update.old_journal()?,
        f.update.selection()?, inputs,
        AgentdGenerationUpdateRequestV1 { operation_id: "different-task".into() },
    ), Err(AgentdError::Invalid(message)) if message.contains("another task scope")));
    assert_eq!(f.bytes()?, before);
    let same_task = f.prepare("same-task-retry")?;
    assert_eq!(f.update.authority.capacity()?.used_nonces, 0);
    assert!(fs::read(&f.host.paths[2])?.is_empty());
    drop(same_task);
    Ok(())
}

#[test]
fn typed_forward_reopens_original_prepared_files_and_requires_a_distinct_signed_operation()
-> anyhow::Result<()> {
    let f = Fixture::new()?;
    let prepared = f.prepare("pending-v13-update")?;
    let intent_digest = prepared.intent_digest();
    let original_binding = prepared.final_use_binding().clone();
    let original = f.update.sign(&original_binding)?;
    f.update.reject_publication_write();
    assert!(prepared.publish(&original).is_err());
    assert_eq!(f.update.authority.capacity()?.used_nonces, 1);
    let pending = f.bytes()?;
    assert!(matches!(recover_agentd_v13_generation_update_v1(
        f.update.reopen_current()?, f.update.authorities()?, f.update.selection()?,
        f.inputs()?, AgentdGenerationUpdateRecoveryV1 {
            operation_id: "pending-v13-update".into(), intent_digest,
        },
    ), Err(AgentdError::Invalid(message)) if message.contains("remains pending; no redispatch")));
    assert_eq!(f.bytes()?, pending);
    let target_before = f.host.owner_bytes()?;
    let forward = prepare_agentd_v13_generation_forward_recovery_v1(
        f.update.reopen_current()?, f.update.authorities()?, f.update.old_journal()?,
        f.update.selection()?, f.inputs()?, AgentdGenerationForwardRecoveryV1 {
            original_operation_id: "pending-v13-update".into(),
            original_intent_digest: intent_digest,
            new_operation_id: "operator-forward-v13".into(),
        },
    )?;
    assert_ne!(forward.final_use_binding(), &original_binding);
    assert_ne!(forward.intent_digest(), intent_digest);
    assert_eq!(f.host.owner_bytes()?, target_before);
    let signed = f.update.sign(forward.final_use_binding())?;
    assert_ne!(signed.grant.nonce, original.grant.nonce);
    let forward_intent = forward.intent_digest();
    f.update.lose_publication_ack();
    assert!(forward.publish(&signed).is_err());
    assert_eq!(f.update.authority.capacity()?.used_nonces, 2);
    assert_eq!(f.host.owner_bytes()?, target_before);
    let published = f.bytes()?;
    let claims = f.update.bytes("final-use/authority.claims")?;
    let ready = recover_agentd_v13_generation_update_v1(
        f.update.reopen_current()?, f.update.authorities()?, f.update.selection()?,
        f.inputs()?, AgentdGenerationUpdateRecoveryV1 {
            operation_id: "operator-forward-v13".into(), intent_digest: forward_intent,
        },
    )?;
    assert_eq!(f.bytes()?, published);
    assert_eq!(f.update.bytes("final-use/authority.claims")?, claims);
    assert_eq!(f.update.authority.capacity()?.used_nonces, 2);
    assert!(target_before[2].is_empty());
    drop(ready);
    Ok(())
}

#[test]
fn ready_rechecks_actual_runtime_identity_queue_and_live_authority_before_charging_or_spawning()
-> anyhow::Result<()> {
    for change in ["identity", "queue", "current", "withdrawal"] {
        let f = Fixture::new()?;
        let prepared = f.prepare("deferred-v13-runtime")?;
        let signed = f.update.sign(prepared.final_use_binding())?;
        let ready = prepared.publish(&signed)?;
        let before = f.bytes()?;
        let mut options = f.options();
        let other = if change == "identity" {
            Some(super::support::Fixture::new()?)
        } else {
            None
        };
        let config = support::runtime_config(
            other.as_ref().map_or(&f.host.identity, |other| &other.identity),
        )?;
        match change {
            "queue" => options.queue_capacity += 1,
            "current" => f.update.advance_artifact_current()?,
            "withdrawal" => f.update.withdraw()?,
            "identity" => {}
            _ => unreachable!("fixed runtime boundary cases"),
        }
        let result = ready.into_runtime(config, options);
        match change {
            "identity" => assert!(matches!(result, Err(AgentdError::GenerationFenced(_)))),
            "queue" => assert!(matches!(result, Err(AgentdError::Invalid(message))
                if message == "V13 runtime queue differs from its preflighted configuration")),
            _ => assert!(matches!(result, Err(AgentdError::Invalid(message))
                if message == "Unavailable")),
        }
        assert_eq!(f.bytes()?, before, "{change}");
        assert_eq!(f.update.authority.capacity()?.used_nonces, 1);
        // No actor owns a delayed lower lock after this pre-spawn rejection.
        let control = OpenOptions::new().read(true).append(true).open(&f.host.paths[2])?;
        control.try_lock()?;
        assert_eq!(control.metadata()?.len(), 0);
    }
    Ok(())
}
