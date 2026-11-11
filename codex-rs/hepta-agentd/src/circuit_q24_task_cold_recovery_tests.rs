//! Drop all task guards, private owners and completion tokens, then reopen
//! their original files. Issuer keys and Root FileCAS remain explicit fixtures;
//! this is not an OS daemon+Root process restart or a quality/adoption claim.

use crate::AgentdGenerationUpdateRecoveryV1;
use crate::AgentdGenerationUpdateTargetV1;
use pretty_assertions::assert_eq;
use std::io::Write;

use super::*;

#[path = "circuit_q24_task_cold_test_support.rs"]
pub(super) mod reopen;

fn bytes(identity: &AgentdIdentity) -> anyhow::Result<Vec<Vec<u8>>> {
    [
        "q24-source.journal",
        "q24-source.witness",
        "q24-cell.journal",
        "q24-cell.witness",
        "q24-control.journal",
    ]
    .iter()
    .map(|name| Ok(fs::read(identity.home_root.join(name))?))
    .collect()
}

#[tokio::test]
async fn q24_ordinary_cold_recovery_rebuilds_completed_predecessor_without_retained_token_or_repairs()
-> anyhow::Result<()> {
    let model_root = tempfile::tempdir()?;
    let (model, bundle, definition) = support::model(model_root.path())?;
    let a = support::admission("cold-q24-A").await?;
    let source_a = support::source(&a, [Q, Q / 4])?;
    let config_a = support::configuration(
        &model,
        &bundle,
        &definition,
        &source_a,
        /*generation*/ 1,
    )?;
    let version = VersionFixture::new_initial(config_a.clone(), "ordinary-q24-initial")?;
    let task_a = support::publish_initial(&version, definition.clone(), source_a.clone())?;
    let mut a = support::start(a, task_a, Arc::clone(&model), bundle.clone()).await?;
    let publication_a = execute(&a, /*request_id*/ 1).await?;
    let completion =
        a.retirement
            .drain_completed_task(&a.cell, a.source.as_ref(), &a.runtime.identity)?;
    let identity_a = a.runtime.identity.clone();
    let _directory_a = std::mem::replace(&mut a.runtime._temp, tempfile::tempdir()?);
    a.stop().await?;
    drop(a);
    let original_a = bytes(&identity_a)?;

    let c = support::admission("cold-q24-C").await?;
    let source_c = support::source(&c, [Q / 4, Q])?;
    let config_c = support::configuration(
        &model,
        &bundle,
        &definition,
        &source_c,
        /*generation*/ 2,
    )?;
    let prepared = crate::prepare_agentd_generation_cold_same_model_task_v1(
        version.reopen_current()?,
        version.authorities()?,
        AgentdGenerationUpdatePredecessorFilesV1 {
            file: version.file("target-journal")?,
            witness: version.witness("target-witness", &config_a)?,
            config: config_a.clone(),
            max_records: RECORDS,
        },
        version.selection()?,
        version.named_target_create("cold-C-journal", "cold-C-witness", config_c.clone())?,
        AgentdGenerationUpdateRequestV1 {
            operation_id: "cold-q24-original-C-publication".into(),
        },
    )?;
    let intent_digest = prepared.intent_digest();
    let signed = version.sign(prepared.final_use_binding())?;
    let task_c = prepared.publish(&signed)?.into_circuit_feature_task(
        definition.clone(),
        source_c.clone(),
        completion,
    )?;
    let mut c = support::start(c, task_c, Arc::clone(&model), bundle.clone()).await?;
    let publication_c = execute(&c, /*request_id*/ 1).await?;
    let receipt_c = read_receipt(&c, &definition, &publication_c)?;
    let snapshot_c = c.cell.snapshot(&source_c.scope)?;
    let identity_c = c.runtime.identity.clone();
    let request_c = c.request.clone();
    let configuration_c = c.take_configuration();
    let directory_c = std::mem::replace(&mut c.runtime._temp, tempfile::tempdir()?);
    c.stop().await?;
    drop(c); // No A/C task guard, native owner, Cell/source handle or completion token remains.
    let original_c = bytes(&identity_c)?;
    let original_version = (
        version.bytes("current.json")?,
        version.bytes("cold-C-journal")?,
        version.bytes("cold-C-witness")?,
    );
    let nonces = version.authority.capacity()?.used_nonces;

    let original_source = reopen::original_source(&identity_a, &definition, &source_a)?;
    assert_eq!(
        original_source.read_run_publication(&identity_a, &source_a.scope.run_id)?,
        publication_a
    );
    let recovered = crate::recover_agentd_generation_update_v1(
        version.reopen_current()?,
        version.authorities()?,
        version.selection()?,
        AgentdGenerationUpdateTargetV1 {
            file: version.file("cold-C-journal")?,
            witness: version.witness("cold-C-witness", &config_c)?,
            config: config_c.clone(),
            max_records: RECORDS,
        },
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "cold-q24-original-C-publication".into(),
            intent_digest,
        },
    )?;
    let recovered = recovered.recover_circuit_feature_task(
        definition.clone(),
        source_c.clone(),
        reopen::predecessor(&identity_a, &definition, &source_a, &config_a.manifest)?,
        &original_source.readback(),
        &identity_a,
    )?;
    drop(original_source);
    let mut recovered = reopen::reopen(
        identity_c.clone(),
        directory_c,
        request_c,
        configuration_c,
        recovered,
        Arc::clone(&model),
        bundle,
    )
    .await?;
    let response = recovered
        .runtime
        .state
        .response(
            9,
            1,
            AgentdMethod::ObjectiveStart {
                request: recovered.request.clone(),
            },
        )
        .await?;
    let AgentdPayload::ObjectiveRun(admission) = response.payload else {
        anyhow::bail!("original replay lacks admission")
    };
    assert_eq!(admission.disposition, "circuit_succeeded");
    assert_eq!(
        recovered
            .source
            .read_run_publication(&identity_c, &source_c.scope.run_id)?,
        publication_c
    );
    assert_eq!(recovered.cell.snapshot(&source_c.scope)?, snapshot_c);
    assert_eq!(
        recovered.cell.lookup(
            &receipt_c.scope,
            &receipt_c.operation_id,
            receipt_c.semantic_request_digest
        )?,
        Some(receipt_c)
    );
    assert_eq!(bytes(&identity_a)?, original_a);
    assert_eq!(bytes(&identity_c)?, original_c);
    assert_eq!(
        (
            version.bytes("current.json")?,
            version.bytes("cold-C-journal")?,
            version.bytes("cold-C-witness")?
        ),
        original_version
    );
    assert_eq!(version.authority.capacity()?.used_nonces, nonces);
    let _directory_c = std::mem::replace(&mut recovered.runtime._temp, tempfile::tempdir()?);
    recovered.stop().await?;
    drop(recovered);

    // An unacknowledged torn suffix is not repaired by historical recovery,
    // even though the original successor publication itself remains valid.
    OpenOptions::new()
        .append(true)
        .open(identity_a.home_root.join("q24-cell.journal"))?
        .write_all(&[1])?;
    let damaged = bytes(&identity_a)?;
    let original_source = reopen::original_source(&identity_a, &definition, &source_a)?;
    let recovered = crate::recover_agentd_generation_update_v1(
        version.reopen_current()?,
        version.authorities()?,
        version.selection()?,
        AgentdGenerationUpdateTargetV1 {
            file: version.file("cold-C-journal")?,
            witness: version.witness("cold-C-witness", &config_c)?,
            config: config_c,
            max_records: RECORDS,
        },
        AgentdGenerationUpdateRecoveryV1 {
            operation_id: "cold-q24-original-C-publication".into(),
            intent_digest,
        },
    )?;
    assert!(
        recovered
            .recover_circuit_feature_task(
                definition.clone(),
                source_c,
                reopen::predecessor(&identity_a, &definition, &source_a, &config_a.manifest)?,
                &original_source.readback(),
                &identity_a
            )
            .is_err()
    );
    assert_eq!(bytes(&identity_a)?, damaged);
    assert_eq!(bytes(&identity_c)?, original_c);
    assert_eq!(version.authority.capacity()?.used_nonces, nonces);
    Ok(())
}
