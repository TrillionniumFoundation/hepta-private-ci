//! Actual first Material executions and original recovery over typed framing.
//! Keys and same-UID transport are explicit fixtures, not an external role-host
//! deployment, full ordinary adoption run, or daemon/Root cold restart.

use pretty_assertions::assert_eq;

use super::super::Channel;
use super::super::OriginalCellQ24MaterialCommandClientV1;
use super::*;
use crate::LearningIterationEvidencePeerV1;
use crate::cell_q24_material_receipt_owner::MaterialCommandFixture;
use crate::cell_q24_material_receipt_owner::assert_dataset_pending;
use crate::cell_q24_material_receipt_owner::interrupt_dataset_claim;

#[path = "cell_q24_material_command_transport_tests.rs"]
mod transport;
use transport::Effect;
use transport::Mode;
use transport::connected;
use transport::finish;

#[tokio::test]
async fn material_command_executes_original_experience_then_dataset_without_uploads()
-> anyhow::Result<()> {
    let f = MaterialCommandFixture::new().await?;
    let before = f.bytes()?;
    let (experience, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    let original_e = experience.execute().await?;
    assert_eq!(original_e.snapshot.receipts.len(), 1);
    assert_eq!(
        experience.receipt_attestation(original_e.receipt()).await?,
        *original_e.attestation()
    );
    assert_eq!(experience.readback().await?, original_e);
    assert!(matches!(
        experience.execute().await,
        Err(Error::ReadbackRequired)
    ));
    assert_eq!(finish(experience, peer)?, 3);
    let after_e = f.bytes()?;
    assert_ne!(after_e[0], before[0]);
    assert_ne!(after_e[1], before[1]);
    assert_eq!(&after_e[2..], &before[2..]);

    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    let original_d = dataset.execute().await?;
    assert_eq!(original_d.snapshot.receipts[0], *original_e.receipt());
    assert_eq!(original_d.evidence[0], *original_e.attestation());
    assert_eq!(
        dataset.receipt_attestation(original_d.receipt()).await?,
        *original_d.attestation()
    );
    assert_eq!(dataset.readback().await?, original_d);
    assert_eq!(finish(dataset, peer)?, 3);
    let after_d = f.bytes()?;
    assert_eq!(&after_d[..2], &after_e[..2]);
    assert_ne!(after_d[2], after_e[2]);
    assert_ne!(after_d[3], after_e[3]);
    assert_eq!(&after_d[4..], &before[4..]);

    let host = f.host.as_ref().expect("original host");
    let material = host
        .original
        .read_original(Role::Dataset, original_d.snapshot.head_digest)?
        .material;
    assert_eq!(
        material.experience_observation(),
        original_d.snapshot.receipts[0].observation
    );
    assert_eq!(
        material.dataset_observation(),
        original_d.snapshot.receipts[1].observation
    );
    assert_eq!(f.bytes()?, after_d);
    Ok(())
}

#[tokio::test]
async fn material_command_lost_ack_recovers_original_signatures_and_shared_admission()
-> anyhow::Result<()> {
    let mut f = MaterialCommandFixture::new().await?;
    let (experience, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    let original_e = experience.execute().await?;
    finish(experience, peer)?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::LoseAck)?;
    assert!(matches!(
        dataset.execute().await,
        Err(Error::CommitUncertain)
    ));
    assert!(matches!(dataset.readback().await, Err(Error::Unavailable)));
    assert_eq!(finish(dataset, peer)?, 1);

    let (recovered, peer) = connected(
        &f,
        Role::Dataset,
        Mode::ReadbackOnly,
        None,
        Effect::Original,
    )?;
    let original_d = recovered.readback().await?;
    assert_eq!(original_d.evidence[0], *original_e.attestation());
    assert!(matches!(
        recovered.execute().await,
        Err(Error::ReadbackRequired)
    ));
    finish(recovered, peer)?;
    let before = f.bytes()?;

    // A new execution-capable fixture connection cannot reset the host bit.
    let (other, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(
        other.execute().await,
        Err(Error::ReadbackRequired)
    ));
    assert_eq!(other.readback().await?, original_d);
    finish(other, peer)?;
    assert_eq!(f.bytes()?, before);

    f.reopen()?;
    for (role, expected) in [(Role::Experience, original_e), (Role::Dataset, original_d)] {
        let (client, peer) = connected(
            &f,
            role,
            Mode::ExecuteOnce,
            Some(expected.clone()),
            Effect::Original,
        )?;
        assert!(matches!(
            client.execute().await,
            Err(Error::ReadbackRequired)
        ));
        assert_eq!(client.readback().await?, expected);
        finish(client, peer)?;
        assert_eq!(f.bytes()?, before);
    }
    Ok(())
}

#[tokio::test]
async fn material_command_missing_predecessor_and_cold_missing_never_execute() -> anyhow::Result<()>
{
    let mut f = MaterialCommandFixture::new().await?;
    let before = f.bytes()?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(dataset.execute().await, Err(Error::Missing)));
    assert!(matches!(dataset.readback().await, Err(Error::Missing)));
    finish(dataset, peer)?;
    assert_eq!(
        f.bytes()?,
        before,
        "Dataset did not create its missing Experience"
    );

    let (experience, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    experience.execute().await?;
    finish(experience, peer)?;
    let after_e = f.bytes()?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(
        dataset.execute().await,
        Err(Error::ReadbackRequired)
    ));
    assert!(matches!(dataset.readback().await, Err(Error::Missing)));
    finish(dataset, peer)?;
    assert_eq!(f.bytes()?, after_e);
    f.reopen()?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(
        dataset.execute().await,
        Err(Error::ReadbackRequired)
    ));
    assert!(matches!(dataset.readback().await, Err(Error::Missing)));
    finish(dataset, peer)?;
    assert_eq!(f.bytes()?, after_e);

    let mut never_started = MaterialCommandFixture::new().await?;
    let empty = never_started.bytes()?;
    never_started.reopen()?;
    for role in [Role::Experience, Role::Dataset] {
        let (client, peer) = connected(
            &never_started,
            role,
            Mode::ExecuteOnce,
            None,
            Effect::Original,
        )?;
        assert!(matches!(
            client.execute().await,
            Err(Error::ReadbackRequired)
        ));
        assert!(matches!(client.readback().await, Err(Error::Missing)));
        finish(client, peer)?;
    }
    assert_eq!(never_started.bytes()?, empty);
    Ok(())
}

#[tokio::test]
async fn material_command_pending_claim_and_withdrawal_never_complete_or_rearm()
-> anyhow::Result<()> {
    let mut f = MaterialCommandFixture::new().await?;
    let (experience, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    experience.execute().await?;
    finish(experience, peer)?;
    let saved = {
        let host = f.host.as_ref().expect("original host");
        let mut owners = host.original.owners.lock().expect("original owner lock");
        let mut ledger = host.original.ledger.lock().expect("original ledger lock");
        interrupt_dataset_claim(
            &mut owners,
            &f.config,
            OriginalCellQ24MaterialReceiptSourcesV1 {
                snapshot: &f.config.initial,
                source: &host.original.source,
                identity: &host.original.identity,
                ledger: &mut ledger,
                baseline: &host.original.baseline,
            },
        )?
    };
    let pending = f.bytes()?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(dataset.execute().await, Err(Error::Pending)));
    assert!(matches!(dataset.readback().await, Err(Error::Pending)));
    finish(dataset, peer)?;
    assert_eq!(f.bytes()?, pending);

    f.withdraw()?;
    let (dataset, peer) = connected(
        &f,
        Role::Dataset,
        Mode::ReadbackOnly,
        None,
        Effect::Original,
    )?;
    // A withdrawn source may no longer authenticate the prefix. The physical
    // journal is still Pending, never relabelled as a completed NoUpdate.
    assert!(matches!(
        dataset.readback().await,
        Err(Error::CommitUncertain)
    ));
    finish(dataset, peer)?;
    assert_dataset_pending(
        &mut f
            .host
            .as_ref()
            .expect("host")
            .original
            .owners
            .lock()
            .expect("original owner"),
        &saved,
    )?;
    assert_eq!(f.bytes()?, pending);
    f.reopen()?;
    let (dataset, peer) = connected(&f, Role::Dataset, Mode::ExecuteOnce, None, Effect::Original)?;
    assert!(matches!(
        dataset.execute().await,
        Err(Error::ReadbackRequired)
    ));
    assert!(matches!(
        dataset.readback().await,
        Err(Error::CommitUncertain)
    ));
    finish(dataset, peer)?;
    assert_dataset_pending(
        &mut f
            .host
            .as_ref()
            .expect("host")
            .original
            .owners
            .lock()
            .expect("original owner"),
        &saved,
    )?;
    assert_eq!(f.bytes()?, pending);
    Ok(())
}

#[tokio::test]
async fn material_command_wrong_context_role_or_custody_never_claims() -> anyhow::Result<()> {
    let f = MaterialCommandFixture::new().await?;
    let host = f.host.as_ref().expect("original command host");
    let before = f.bytes()?;
    for field in [
        "schema",
        "operation",
        "request_id",
        "binding",
        "initial_head",
        "operation_id",
        "scope_binding",
        "actor_id",
        "stage",
        "batch",
    ] {
        let request = wire::Request::new(
            &f.config,
            Role::Experience,
            host.binding,
            1,
            wire::Action::Execute,
        );
        let mut value = serde_json::to_value(request)?;
        value[field] = if field == "schema" || field == "request_id" {
            serde_json::json!(99)
        } else {
            serde_json::json!("caller-replacement")
        };
        assert!(
            host.command_response(Role::Experience, &serde_json::to_vec(&value)?, 1)
                .is_err()
        );
        assert_eq!(host.admitted.load(Ordering::Acquire), 0);
        assert_eq!(f.bytes()?, before);
    }
    let dataset_request = wire::Request::new(
        &f.config,
        Role::Dataset,
        host.binding,
        1,
        wire::Action::Execute,
    );
    assert!(
        host.command_response(Role::Experience, &serde_json::to_vec(&dataset_request)?, 1)
            .is_err()
    );

    for role in [Role::Experience, Role::Dataset] {
        transport::cancel_queued_execute(&f, role).await?;
        assert_eq!(host.admitted.load(Ordering::Acquire), 0);
        assert_eq!(f.bytes()?, before);
    }

    let identity = transport::identity()?;
    let (stream, unused) = UnixStream::pair()?;
    let denied = OriginalCellQ24MaterialCommandClientV1::from_original_experience_stream(
        stream,
        LearningIterationEvidencePeerV1 {
            pid: identity.pid,
            uid: unsafe { libc::geteuid() },
            boot_id: identity.boot_id,
            process_start_ticks: identity.process_start_ticks,
            actor_id: f.config.initial.owners.experience.clone(),
        },
        transport::pidfd()?,
        f.config.clone(),
        Duration::from_secs(30),
        Duration::from_secs(300),
    );
    assert!(matches!(
        denied,
        Err(Error::Transport(HostIssuerTransportError::PeerDenied))
    ));
    drop(unused);
    let (stream, unused) = UnixStream::pair()?;
    assert!(matches!(
        host.serve_experience_commands(
            stream,
            transport::identity()?,
            unsafe { libc::geteuid() },
            transport::pidfd()?,
            Duration::from_secs(30),
            Duration::from_secs(300)
        ),
        Err(Error::Transport(HostIssuerTransportError::PeerDenied))
    ));
    drop(unused);
    assert_eq!(host.admitted.load(Ordering::Acquire), 0);
    assert_eq!(f.bytes()?, before);
    let (client, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    client.execute().await?;
    finish(client, peer)?;
    Ok(())
}

#[tokio::test]
async fn material_command_pins_original_signatures_and_consumes_invalid_replies()
-> anyhow::Result<()> {
    let f = MaterialCommandFixture::new().await?;
    let (client, peer) = connected(
        &f,
        Role::Experience,
        Mode::ExecuteOnce,
        None,
        Effect::Original,
    )?;
    let original = client.execute().await?;
    finish(client, peer)?;
    let before = f.bytes()?;
    while now()? <= original.attestation().issued_at {
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
    let (client, peer) = connected(
        &f,
        Role::Experience,
        Mode::ReadbackOnly,
        Some(original.clone()),
        Effect::RenewExperience,
    )?;
    assert!(matches!(
        client.readback().await,
        Err(Error::Binding("unchanged original Material signatures"))
    ));
    assert!(matches!(client.readback().await, Err(Error::Unavailable)));
    finish(client, peer)?;
    assert_eq!(f.bytes()?, before);

    let (client, peer) = connected(
        &f,
        Role::Experience,
        Mode::ReadbackOnly,
        Some(original.clone()),
        Effect::WrongPurpose,
    )?;
    assert!(matches!(
        client.readback().await,
        Err(Error::Binding("same role-fixed Material response"))
    ));
    assert!(matches!(client.readback().await, Err(Error::Unavailable)));
    finish(client, peer)?;
    let (client, peer) = connected(
        &f,
        Role::Experience,
        Mode::ReadbackOnly,
        Some(original.clone()),
        Effect::Original,
    )?;
    assert_eq!(client.readback().await?, original);
    finish(client, peer)?;
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[path = "cell_q24_training_bootstrap_material_ports_tests.rs"]
pub(crate) mod bootstrap_ports;

#[path = "cell_q24_no_update_stage_material_tests.rs"]
mod ordinary_stage;
