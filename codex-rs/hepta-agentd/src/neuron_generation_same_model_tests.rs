//! Same-model continuation retains the actual owner and independent signature
//! boundary. The journal proposals are explicit synthetic mechanism fixtures.

use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

use super::super::Fixture;
use super::super::RECORDS;
use super::super::config;
use super::support::append_advanced;
use super::support::deliver;
use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateRequestV1;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::NeuronGenerationUpdatePublicationV1;
use crate::neuron_generation_current::NeuronGenerationUpdateReadbackV1;
use crate::prepare_agentd_generation_same_model_task_v1;
use crate::recover_agentd_generation_update_v1;

fn fixture(change: &str) -> anyhow::Result<Fixture> {
    let old = config()?;
    let mut next = old.clone();
    next.initial.scope.run_id.push_str("-same-model-task");
    next.task_digest = Digest32::of_bytes(b"different task, unchanged model").into_array();
    next.initial.generation += 1;
    next.initial.writer_epoch += 1;
    match change {
        "task" => next.task_digest = old.task_digest,
        "run" => next.initial.scope.run_id = old.initial.scope.run_id.clone(),
        "generation" => next.initial.generation += 1,
        "epoch" => next.initial.writer_epoch += 1,
        "manifest" => {
            next.manifest.evolution.adoption_receipt = [99; 32];
            next.initial.manifest_digest = next.manifest.digest()?;
        }
        "none" => {}
        _ => anyhow::bail!("unknown fixture mutation"),
    }
    Fixture::new_with_target(old, next)
}

#[test]
fn same_model_requires_distinct_task_run_exact_epoch_and_complete_unchanged_manifest()
-> anyhow::Result<()> {
    for change in ["task", "run", "generation", "epoch", "manifest"] {
        let f = fixture(change)?;
        let mut old = f.old_journal()?;
        append_advanced(&f, &mut old)?;
        deliver(&f, &mut old)?;
        old.drain()?;
        let before = (f.bytes("current.json")?, f.bytes("old-journal")?);
        let selected = f.selection()?;
        let binding = CellGenerationOwnerBindingV1::new(&f.target_config, RECORDS)?;
        assert!(
            f.current
                .prepare_same_model_task(&old, "rejected-same-model".into(), binding, &selected)
                .is_err(),
            "{change}"
        );
        assert!(
            prepare_agentd_generation_same_model_task_v1(
                f.current.clone(),
                f.authorities()?,
                old,
                selected,
                f.target_create()?,
                AgentdGenerationUpdateRequestV1 {
                    operation_id: "rejected-handoff".into()
                },
            )
            .is_err(),
            "{change}"
        );
        assert_eq!((f.bytes("current.json")?, f.bytes("old-journal")?), before);
        assert!(f.bytes("target-journal")?.is_empty());
        assert_eq!(f.authority.capacity()?.used_nonces, 0);
    }
    Ok(())
}

#[test]
fn same_model_cannot_bypass_ack_or_drain_and_original_updates_keep_rejecting_it()
-> anyhow::Result<()> {
    for incomplete in ["ack", "drain"] {
        let f = fixture("none")?;
        let mut old = f.old_journal()?;
        append_advanced(&f, &mut old)?;
        if incomplete == "ack" {
            old.drain()?;
        } else {
            deliver(&f, &mut old)?;
        }
        let before = (f.bytes("current.json")?, f.bytes("old-journal")?);
        assert!(
            prepare_agentd_generation_same_model_task_v1(
                f.current.clone(),
                f.authorities()?,
                old,
                f.selection()?,
                f.target_create()?,
                AgentdGenerationUpdateRequestV1 {
                    operation_id: "incomplete-handoff".into()
                },
            )
            .is_err()
        );
        assert_eq!((f.bytes("current.json")?, f.bytes("old-journal")?), before);
        assert_eq!(f.authority.capacity()?.used_nonces, 0);
    }
    let f = fixture("none")?;
    let old = f.stopped_old()?;
    let selected = f.selection()?;
    let binding = CellGenerationOwnerBindingV1::new(&f.target_config, RECORDS)?;
    let before = f.bytes("current.json")?;
    assert!(
        f.current
            .prepare(&old, "strict-update".into(), binding.clone(), &selected)
            .is_err()
    );
    assert!(
        f.current
            .prepare_drained_retirement(&old, "drained-update".into(), binding, &selected)
            .is_err()
    );
    assert_eq!(f.bytes("current.json")?, before);
    assert_eq!(f.authority.capacity()?.used_nonces, 0);
    Ok(())
}

#[test]
fn same_model_requires_own_signed_purpose_and_lost_ack_recovery_never_claims_again()
-> anyhow::Result<()> {
    let f = fixture("none")?;
    let mut old = f.old_journal()?;
    append_advanced(&f, &mut old)?;
    deliver(&f, &mut old)?;
    old.drain()?;
    assert!(!old.snapshot()?.stopped);
    assert!(!old.observe_generation()?.is_terminal());
    let old_bytes = (f.bytes("old-journal")?, f.bytes("old-witness")?);
    let mut selected = f.selection()?;
    let prepared = f.current.prepare_same_model_task(
        &old,
        "same-model-publication".into(),
        CellGenerationOwnerBindingV1::new(&f.target_config, RECORDS)?,
        &selected,
    )?;
    assert_eq!(
        prepared.completion(),
        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
    );
    assert_eq!(
        prepared.final_use_binding().destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let target = f.target_create()?;
    let new = CellGenerationJournalV2::open_guarded(
        target.file,
        target.witness,
        target.config,
        target.max_records,
        f.current.clone(),
    )?;
    let before = f.bytes("current.json")?;
    let mut binding = prepared.final_use_binding().clone();
    binding.destination_id = "agentd.cell-generation.replace-drained".into();
    let wrong = f.sign(&binding)?;
    let signed = f.sign(prepared.final_use_binding())?;
    {
        let mut artifacts = f
            .artifacts
            .lock()
            .map_err(|_| anyhow::anyhow!("artifact lock"))?;
        assert!(
            f.current
                .publish(
                    &prepared,
                    &old,
                    &new,
                    &mut selected,
                    NeuronGenerationUpdatePublicationV1 {
                        artifacts: &mut artifacts,
                        authority: &f.authority,
                        signed: &wrong,
                        clock: f.clock.as_ref()
                    },
                )
                .is_err()
        );
        assert_eq!(f.bytes("current.json")?, before);
        assert_eq!(f.authority.capacity()?.used_nonces, 0);
        f.lose_publication_ack();
        assert!(
            f.current
                .publish(
                    &prepared,
                    &old,
                    &new,
                    &mut selected,
                    NeuronGenerationUpdatePublicationV1 {
                        artifacts: &mut artifacts,
                        authority: &f.authority,
                        signed: &signed,
                        clock: f.clock.as_ref()
                    },
                )
                .is_err()
        );
    }
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    assert!(old.resume().is_err());
    assert_eq!(
        (f.bytes("old-journal")?, f.bytes("old-witness")?),
        old_bytes
    );
    drop(old);
    drop(new);
    let retained = f
        .reopen_current()?
        .recover_operation("same-model-publication", prepared.intent_digest())?;
    let NeuronGenerationUpdateReadbackV1::Published(publication) =
        f.current.read_operation(&retained)?
    else {
        anyhow::bail!("lost ACK did not retain the published owner");
    };
    assert_eq!(
        publication.completion(),
        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
    );
    let before = (
        f.bytes("current.json")?,
        f.bytes("final-use/authority.claims")?,
        f.bytes("target-journal")?,
    );
    let recovered = recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "same-model-publication".into(),
            intent_digest: prepared.intent_digest(),
        },
    )?;
    assert_eq!(
        (
            f.bytes("current.json")?,
            f.bytes("final-use/authority.claims")?,
            f.bytes("target-journal")?
        ),
        before
    );
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    drop(recovered);
    Ok(())
}
