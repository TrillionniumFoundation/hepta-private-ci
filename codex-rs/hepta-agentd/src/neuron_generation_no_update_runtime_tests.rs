//! Native evaluated NoUpdate -> same incumbent -> actual numeric inference.
//! Learning stages and issuer custody are explicit engineering fixtures. This
//! is not five-family evaluation, production authorization or model adoption.

use std::fs;
use std::fs::File;
use std::io::Write;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationDispositionV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellGenerationJournalV2;
use codex_hepta_neuron::CellLearningBindingV2;
use codex_hepta_neuron::CellTaskCostV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::super::support as host;
use super::support;
use crate::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::AgentdLearningNoUpdateInputsV1;
use crate::LearningIterationOwnerPortsV1;
use crate::neuron_generation_current::NeuronGenerationPredecessorCompletionV1;
use crate::neuron_generation_current::test_support::Fixture;
use crate::neuron_generation_current::test_support::RECORDS;
use crate::observe_agentd_evaluated_no_update_next_use_v1 as observe_next_use;
use crate::plasticity_runtime::lifetime_tests::learning_iteration_tests::IterationPorts;
use crate::plasticity_runtime::lifetime_tests::learning_iteration_tests::iteration_request;
use crate::prepare_agentd_generation_evaluated_no_update_task_v1;
use crate::recover_agentd_generation_update_v1;

#[path = "neuron_generation_no_update_test_model.rs"]
mod model;

#[path = "neuron_generation_no_update_test_support.rs"]
mod checks;

#[tokio::test]
async fn evaluated_no_update_runs_incumbent_recovers_and_obeys_revocation() -> anyhow::Result<()> {
    run_no_update_case(checks::LiveInvalidation::FinalUseRevocation).await
}

#[tokio::test]
async fn evaluated_no_update_runs_incumbent_and_obeys_current_change() -> anyhow::Result<()> {
    run_no_update_case(checks::LiveInvalidation::ArtifactCurrent).await
}

async fn run_no_update_case(change: checks::LiveInvalidation) -> anyhow::Result<()> {
    let mut host = host::Fixture::new().await;
    let mut request = iteration_request(&host.identity);
    let weights: Vec<u8> = [0.5_f32, -0.25_f32]
        .into_iter()
        .flat_map(f32::to_le_bytes)
        .collect();
    fs::write(host.directory.path().join("incumbent.f32le"), &weights)?;
    host.config.manifest.learning = CellLearningBindingV2::Frozen {
        weights: Digest32::of_bytes(&weights).into_array(),
    };
    host.config.manifest.bundle_digest = request.selected_bundle.digest()?.into_array();
    host.config.initial.manifest_digest = host.config.manifest.digest()?;
    let mut next = host.config.clone();
    next.initial.scope.run_id.push_str("-after-no-update");
    next.initial.generation += 1;
    next.initial.writer_epoch += 1;
    next.task_digest = Digest32::of_bytes(b"actual next input with incumbent").into_array();
    let f = Fixture::new_with_target(host.config.clone(), next)?;
    let old = f.stopped_old()?;
    let source = old.observe_generation()?;
    drop(old);
    let selected = f.selection()?;
    let selection = selected.observation().clone();
    let ports = Arc::new(IterationPorts::new(
        /*proposal*/ None,
        LearningEvaluationDispositionV1::NoUpdate,
    ));
    let owners = ports.owners();
    request.cell_id = StableId::new(&f.old_config.initial.scope.cell_id)?;
    request.source_run_id = StableId::new(&f.old_config.initial.scope.run_id)?;
    request.completed_task_receipt = source.owner_checkpoint();
    request.selected_artifact_digest = selected.observation().payload_digest();
    let learning = checks::submit_retained(&host, &ports, request.clone()).await?;
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(learning.clone())?.disposition(),
        LearningIterationDispositionV1::NoUpdate
    );
    let inputs = AgentdLearningNoUpdateInputsV1 {
        ports: ports.as_ref(),
        verifier: &ports.verifier,
        request: &request,
        owners: &owners,
        expected_head: learning.head_digest,
        now_unix_seconds: 50,
    };
    // Refused reads must not publish, consume FinalUse or write either journal.
    drop(f.target_create()?);
    let before = (
        f.bytes("current.json")?,
        f.bytes("old-journal")?,
        f.bytes("target-journal")?,
    );
    let witnesses_before = (f.bytes("old-witness")?, f.bytes("target-witness")?);
    for bad in [
        AgentdLearningNoUpdateInputsV1 {
            expected_head: Digest32::ZERO,
            ..inputs
        },
        AgentdLearningNoUpdateInputsV1 {
            expected_head: Digest32::of_bytes(b"stale"),
            ..inputs
        },
        AgentdLearningNoUpdateInputsV1 {
            now_unix_seconds: 49,
            ..inputs
        },
        AgentdLearningNoUpdateInputsV1 {
            now_unix_seconds: 101,
            ..inputs
        },
    ] {
        assert!(
            prepare_agentd_generation_evaluated_no_update_task_v1(
                bad,
                f.current.clone(),
                f.authorities()?,
                f.old_journal()?,
                f.selection()?,
                f.target_reopen()?,
            )
            .await
            .is_err()
        );
    }
    ports
        .corrupt_signature
        .store(/*val*/ true, Ordering::SeqCst);
    assert!(
        prepare_agentd_generation_evaluated_no_update_task_v1(
            inputs,
            f.current.clone(),
            f.authorities()?,
            f.old_journal()?,
            f.selection()?,
            f.target_reopen()?,
        )
        .await
        .is_err()
    );
    ports
        .corrupt_signature
        .store(/*val*/ false, Ordering::SeqCst);
    // This is a separate fully signed four-stage NoUpdate, not a corrupted
    // snapshot. Only the complete bundle's heads component differs.
    let mut mismatched = request.clone();
    mismatched.selected_bundle.components.heads = Digest32::of_bytes(b"different model heads");
    let wrong_bundle = checks::SignedLearning::new(&host, mismatched).await?;
    checks::require_bundle_error(
        prepare_agentd_generation_evaluated_no_update_task_v1(
            wrong_bundle.inputs(),
            f.current.clone(),
            f.authorities()?,
            f.old_journal()?,
            f.selection()?,
            f.target_reopen()?,
        )
        .await,
    )?;
    assert_eq!(
        (
            f.bytes("current.json")?,
            f.bytes("old-journal")?,
            f.bytes("target-journal")?
        ),
        before
    );
    assert_eq!(
        (f.bytes("old-witness")?, f.bytes("target-witness")?),
        witnesses_before
    );
    assert_eq!(f.authority.capacity()?.used_nonces, 0);

    let prepared = prepare_agentd_generation_evaluated_no_update_task_v1(
        inputs,
        f.current.clone(),
        f.authorities()?,
        f.old_journal()?,
        f.selection()?,
        f.target_reopen()?,
    )
    .await?;
    assert_eq!(
        prepared.final_use_binding().destination_id,
        "agentd.cell-generation.next-task-same-model"
    );
    let recovery = prepared.recovery();
    let signed = f.sign(prepared.final_use_binding())?;
    // Lose the ACK after the real Control CAS. Recovery reads that publication
    // without issuing a new nonce or dispatching the already entered grant.
    f.lose_publication_ack();
    assert!(prepared.publish(&signed).is_err());
    let ready = recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        crate::AgentdGenerationUpdateRecoveryV1 {
            operation_id: recovery.operation_id.clone(),
            intent_digest: recovery.intent_digest,
        },
    )?;
    let control = model::FrozenModel {
        directory: host.directory.path().to_owned(),
        executions: Arc::new(AtomicUsize::new(/*v*/ 0)),
    };
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, /*running_generation*/ 2).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    assert_eq!(
        runtime.publication.completion(),
        NeuronGenerationPredecessorCompletionV1::OwnerDrainedSameModel
    );
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    let initial = runtime.handle.observe_generation().await?;
    assert!(
        observe_next_use(inputs, &selection, &runtime.publication, &initial)
            .await
            .is_err()
    );
    let mut next_request = support::request(&f.target_config, initial.snapshot().clone());
    next_request.input = vec![6, 4];
    let receipt = runtime.handle.step(next_request.clone()).await?;
    let undelivered = runtime.handle.observe_generation().await?;
    assert_eq!(undelivered.snapshot().prefix, 2.0_f32.to_le_bytes());
    assert!(
        observe_next_use(inputs, &selection, &runtime.publication, &undelivered)
            .await
            .is_err()
    );
    let chunk = undelivered
        .pending_output()
        .cloned()
        .ok_or_else(|| anyhow::anyhow!("missing actual output"))?;
    let delivered = host.directory.path().join("delivered-next-task.f32le");
    let mut receiver = File::create(&delivered)?;
    receiver.write_all(&chunk.bytes)?;
    receiver.sync_all()?;
    File::open(host.directory.path())?.sync_all()?;
    runtime
        .handle
        .acknowledge(
            chunk,
            Digest32::of_bytes(&fs::read(&delivered)?).into_array(),
            CellTaskCostV2::new(undelivered.cost().identity())?,
        )
        .await?;
    assert!(runtime.handle.drain().await?);
    let complete = runtime.handle.observe_generation().await?;
    let proof = observe_next_use(inputs, &selection, &runtime.publication, &complete).await?;
    assert_eq!(proof.authority(), AuthorityPosture::DENY_ALL);
    let retained = (
        f.bytes("target-journal")?,
        f.bytes("target-witness")?,
        f.bytes("final-use/authority.claims")?,
        f.bytes("current.json")?,
    );
    checks::require_bundle_error(
        observe_next_use(
            wrong_bundle.inputs(),
            &selection,
            &runtime.publication,
            &complete,
        )
        .await,
    )?;
    // A different genuine signed learning head cannot claim this publication.
    let mut other_request = request.clone();
    other_request.operation_id = StableId::new("learning:other-completed-operation")?;
    let other_learning = checks::SignedLearning::new(&host, other_request).await?;
    assert_ne!(other_learning.inputs().expected_head, learning.head_digest);
    checks::require_publication_error(
        observe_next_use(
            other_learning.inputs(),
            &selection,
            &runtime.publication,
            &complete,
        )
        .await,
    )?;
    assert_eq!(
        (
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?,
            f.bytes("current.json")?,
        ),
        retained
    );
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);

    let ready = recover_agentd_generation_update_v1(
        f.reopen_current()?,
        f.authorities()?,
        f.selection()?,
        f.target_reopen()?,
        crate::AgentdGenerationUpdateRecoveryV1 {
            operation_id: recovery.operation_id.clone(),
            intent_digest: recovery.intent_digest,
        },
    )?;
    let mut runtime = ready.into_runtime(
        support::next_config(&mut host, /*running_generation*/ 6).await?,
        control.clone(),
        host.clock(),
        AgentdGenerationUpdateRuntimeOptionsV1::default(),
    )?;
    let (mut tasks, _lifetime) = support::start(&mut runtime, &host)?;
    assert_eq!(runtime.handle.step(next_request.clone()).await?, receipt);
    let recovered = runtime.handle.observe_generation().await?;
    assert_eq!(recovered, complete);
    assert_eq!(
        observe_next_use(inputs, &selection, &runtime.publication, &recovered).await?,
        proof
    );
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(
        ports
            .executed
            .lock()
            .map_err(|e| anyhow::anyhow!("{e}"))?
            .len(),
        4
    );
    assert_eq!(f.selection()?.observation(), &selection);
    assert_eq!(f.old_config.manifest, f.target_config.manifest);
    assert_eq!(
        fs::read(host.directory.path().join("incumbent.f32le"))?,
        weights
    );
    assert_eq!(
        (
            f.bytes("target-journal")?,
            f.bytes("target-witness")?,
            f.bytes("final-use/authority.claims")?,
            f.bytes("current.json")?,
        ),
        retained
    );
    assert_eq!(f.bytes("old-journal")?, before.1);
    assert_eq!(f.authority.capacity()?.used_nonces, 1);
    assert_eq!(
        CellGenerationJournalV2::open_guarded(
            f.file("old-journal")?,
            f.witness("old-witness", &f.old_config)?,
            f.old_config.clone(),
            RECORDS,
            f.reopen_current()?
        )
        .err(),
        Some(CellGenerationErrorV2::InvalidBinding)
    );

    // Export original bytes only when explicitly requested by the test runner.
    // There is no learning checkpoint decoder or external certification here.
    if let Some(path) = std::env::var_os("HEPTA_NO_UPDATE_EVIDENCE_DIR") {
        let path = std::path::PathBuf::from(path).join(change.directory());
        fs::create_dir_all(&path)?;
        for name in [
            "current.json",
            "old-journal",
            "old-witness",
            "target-journal",
            "target-witness",
            "final-use/authority.claims",
            "final-use-frontier.json",
        ] {
            fs::write(path.join(name.replace('/', "-")), f.bytes(name)?)?;
        }
        for name in [
            "incumbent.f32le",
            "original-model-result.json",
            "delivered-next-task.f32le",
        ] {
            fs::copy(host.directory.path().join(name), path.join(name))?;
        }
        let payload = serde_json::to_vec(&f.old_config.manifest)?;
        assert_eq!(Digest32::of_bytes(&payload), selection.payload_digest());
        fs::write(path.join("selected-canonical-manifest.json"), payload)?;
        fs::write(
            path.join("learning-snapshot.debug.txt"),
            format!("{learning:#?}"),
        )?;
        for (index, item) in learning.receipts.iter().enumerate() {
            let attestation = ports
                .receipt_attestation(&learning, item, /*_now*/ 50)
                .await?;
            fs::write(
                path.join(format!("learning-{index}-payload.bin")),
                learning_iteration_receipt_signing_bytes_v1(item)?,
            )?;
            fs::write(
                path.join(format!("learning-{index}-attestation-payload.bin")),
                attestation.signing_bytes(),
            )?;
            fs::write(
                path.join(format!("learning-{index}-signature.bin")),
                attestation.signature,
            )?;
        }
        fs::write(
            path.join("readback.json"),
            serde_json::to_vec_pretty(&serde_json::json!({
                "classification": "native_engineering_fixture_not_scientific_qualification",
                "proof": proof, "source": source, "next": complete, "recovered": recovered,
                "selection_digest": selection.digest().to_string(), "selection_debug": format!("{selection:#?}"), "manifest": f.old_config.manifest,
                "grant": signed, "next_request": next_request,
                "model_executions": 1, "native_learning_stages": 4,
                "learning_owner_restore": "fixture_memory_and_canonical_signed_receipts",
                "cpu_energy_and_full_cost_coverage": "unknown"
            }))?,
        )?;
    }
    // Each case starts from independent owners, so CURRENT invalidation cannot
    // mask the FinalUse revocation assertion or vice versa.
    let stale = f.selection()?;
    change.apply(&f, &signed)?;
    assert!(runtime.handle.step(next_request).await.is_err());
    tasks.shutdown().await;
    drop(runtime);
    drop(tasks);
    assert!(
        recover_agentd_generation_update_v1(
            f.reopen_current()?,
            f.authorities()?,
            stale,
            f.target_reopen()?,
            recovery
        )
        .is_err()
    );
    assert_eq!(control.executions.load(Ordering::SeqCst), 1);
    assert_eq!(f.bytes("target-journal")?, retained.0);
    if let Some(path) = std::env::var_os("HEPTA_NO_UPDATE_EVIDENCE_DIR") {
        let path = std::path::PathBuf::from(path).join(change.directory());
        fs::write(
            path.join("final-use-frontier-after-invalidation.json"),
            f.bytes("final-use-frontier.json")?,
        )?;
        fs::write(
            path.join("live-invalidation-result.json"),
            serde_json::to_vec_pretty(&serde_json::json!({
                "case": change.directory(),
                "dispatch_refused": true, "cold_recovery_refused": true,
                "model_executions": control.executions.load(Ordering::SeqCst),
                "target_journal_unchanged": true, "final_use_nonces": f.authority.capacity()?.used_nonces
            }))?,
        )?;
    }
    Ok(())
}
