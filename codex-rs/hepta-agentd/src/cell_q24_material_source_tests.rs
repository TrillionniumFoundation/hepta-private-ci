//! Real original Material files and Source reads over the retained framing.
//! Same-UID transport is constructed only inside this mechanism fixture. Both
//! public endpoints reject that custody; these tests do not claim an external
//! role-host deployment, an initial Material execution or a Root cold restart.

use std::os::fd::FromRawFd;
use std::thread::JoinHandle;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::super::OriginalCellQ24MaterialEvidenceRoleV1 as Role;
use super::*;
use crate::OriginalCellQ24MaterialReceiptErrorV1;
use crate::cell_q24_material_receipt_owner::ReadbackServiceFixture;

fn pidfd() -> anyhow::Result<OwnedFd> {
    // SAFETY: pin this live test process and own the newly returned descriptor.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, std::process::id(), 0) };
    anyhow::ensure!(fd >= 0, "{}", std::io::Error::last_os_error());
    Ok(unsafe { OwnedFd::from_raw_fd(fd as i32) })
}

fn peer() -> anyhow::Result<AgentdRootAuthorityPeer> {
    let pid = std::process::id();
    let stat = std::fs::read_to_string(format!("/proc/{pid}/stat"))?;
    Ok(AgentdRootAuthorityPeer {
        pid,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?.trim().into(),
        process_start_ticks: stat.rsplit_once(") ")
            .ok_or_else(|| anyhow::anyhow!("fixture process stat"))?.1
            .split_whitespace().nth(19)
            .ok_or_else(|| anyhow::anyhow!("fixture process start"))?.parse()?,
    })
}

fn policy() -> HostAuthorityPeerPolicy {
    HostAuthorityPeerPolicy {
        peer: HostIssuerPeer {
            // SAFETY: observe only the fixture process's current credentials.
            uid: unsafe { libc::geteuid() },
            pid: std::process::id(),
        },
        timeout: Duration::from_millis(500),
        lifetime: Duration::from_secs(300),
        request_bound: 16 * 1024,
        response_bound: 16 * 1024,
    }
}

fn request(f: &ReadbackServiceFixture) -> anyhow::Result<wire::Request> {
    let receipt_digest = |receipt: &codex_hepta_learning_artifacts::LearningIterationReceiptV1| {
        Ok::<_, anyhow::Error>(Digest32::of_bytes(
            &learning_iteration_receipt_signing_bytes_v1(receipt)?).to_string())
    };
    Ok(wire::Request {
        schema: 1,
        operation: wire::OPERATION.into(),
        request_id: 1,
        binding: f.initial.head_digest.to_string(),
        scope: f.config.scope.binding().to_string(),
        operation_id: f.initial.request.operation_id.to_string(),
        dataset_head: f.dataset.head_digest.to_string(),
        experience_receipt: receipt_digest(&f.experience_receipt)?,
        // The missing-Dataset negative reaches original owner Missing before
        // this unfulfilled digest could be interpreted as a completed result.
        dataset_receipt: f.dataset.receipts.get(1).map(receipt_digest).transpose()?
            .unwrap_or_else(|| Digest32::ZERO.to_string()),
    })
}

fn connected_fixture(
    f: &ReadbackServiceFixture,
    config: OriginalCellQ24TrainingSourceConfigV1,
    mut change_reply: impl FnMut(&mut serde_json::Value) + Send + 'static,
) -> anyhow::Result<(
    OriginalCellQ24RemoteMaterialClientV1,
    JoinHandle<Result<(), Error>>,
)> {
    verify_context(&config, now()?)?;
    let owner = Arc::clone(f.service.as_ref().expect("original pair owner"));
    let (client, server) = UnixStream::pair()?;
    let transport = RootObservationStream::from_stream_for_uid(
        client, peer()?, pidfd()?, Duration::from_millis(500),
        Duration::from_secs(300), policy().peer.uid,
    )?;
    let held_pidfd = pidfd()?;
    let thread = std::thread::spawn(move || {
        // Explicit mechanism fixture. Public serve_material_source rejects
        // this UID; the real pinned framing, deadlines and pidfd still run.
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy(), held_pidfd)?;
        let mut next = 1_u64;
        loop {
            let mut failure = None;
            let exchanged = channel.exchange(|request| {
                let result = (|| -> Result<Vec<u8>, Error> {
                    let original = owner.respond_material(&mut next, request)?;
                    let mut response = serde_json::from_slice(&original)?;
                    change_reply(&mut response);
                    Ok(serde_json::to_vec(&response)?)
                })();
                result.map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::Unavailable
                })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(()),
                Err(error) => return Err(failure.unwrap_or(Error::Transport(error))),
            }
        }
    });
    Ok((OriginalCellQ24RemoteMaterialClientV1 {
        channel: Mutex::new(Some(Channel { transport, next_request_id: 1 })),
        config,
        baseline: f.baseline(),
    }, thread))
}

fn finish(
    client: OriginalCellQ24RemoteMaterialClientV1,
    thread: JoinHandle<Result<(), Error>>,
) -> anyhow::Result<()> {
    drop(client);
    thread.join().map_err(|_| anyhow::anyhow!("original source service panicked"))??;
    Ok(())
}

fn connected_original_evidence(
    f: &ReadbackServiceFixture,
    role: Role,
) -> anyhow::Result<(
    crate::LearningIterationEvidenceClientV1,
    JoinHandle<Result<(), OriginalCellQ24MaterialEvidenceErrorV1>>,
)> {
    use super::super::super::Channel as EvidenceChannel;

    let owner = Arc::clone(f.service.as_ref().expect("original pair owner"));
    let (client, server) = UnixStream::pair()?;
    let transport = RootObservationStream::from_stream_for_uid(
        client, peer()?, pidfd()?, Duration::from_millis(500),
        Duration::from_secs(300), policy().peer.uid,
    )?;
    let held_pidfd = pidfd()?;
    let thread = std::thread::spawn(move || {
        let mut channel = HostAuthorityPeerChannel::from_stream(server, policy(), held_pidfd)?;
        let mut next = 1_u64;
        loop {
            let mut failure = None;
            let exchanged = channel.exchange(|request| {
                owner.respond(role, &mut next, request).map_err(|error| {
                    failure = Some(error);
                    HostIssuerTransportError::Unavailable
                })
            });
            match exchanged {
                Ok(true) => {}
                Ok(false) => return Ok(()),
                Err(error) => return Err(failure.unwrap_or(
                    OriginalCellQ24MaterialEvidenceErrorV1::Transport(error))),
            }
        }
    });
    Ok((crate::LearningIterationEvidenceClientV1 {
        channel: Mutex::new(Some(EvidenceChannel { transport, next_request_id: 1 })),
        initial: f.initial.clone(),
        actor_id: f.initial.owners.owner(role.stage()).clone(),
        verifier: f.config.verifier.clone(),
    }, thread))
}

#[tokio::test]
async fn material_source_peer_reconstructs_exact_sealed_material_and_cold_rereads()
-> anyhow::Result<()> {
    let mut f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let expected = f.service.as_ref().expect("original owner")
        .read_original(Role::Dataset, f.dataset.head_digest)?.material;
    for cold in [false, true] {
        if cold {
            f.reopen()?;
        }
        let config = f.source_config()?;
        let (client, thread) = connected_fixture(&f, config.clone(), |_| {})?;
        client.require_source_binding(&config, &f.baseline())?;
        for _ in 0..2 {
            let material = client.read_current().await?;
            assert_eq!(material.receipt(), expected.receipt());
            assert_eq!(material.batch().encoded(), expected.batch().encoded());
            assert_eq!(material.provenance_digest(), expected.provenance_digest());
            assert_eq!(material.experience_observation(), config.dataset.receipts[0].observation);
            assert_eq!(material.dataset_observation(), config.dataset.receipts[1].observation);
        }
        finish(client, thread)?;

        // Exercise the closed Remote adapter as well as its decoder. Every
        // predecessor reply comes from the actual Pair service. The ordinary
        // native lane uses this same bounded blocking/current-read boundary;
        // this read-only test does not create or claim a Trainer.
        let (material, material_thread) = connected_fixture(&f, config.clone(), |_| {})?;
        let (experience, experience_thread) = connected_original_evidence(&f, Role::Experience)?;
        let (dataset, dataset_thread) = connected_original_evidence(&f, Role::Dataset)?;
        let source = crate::capture_original_remote_cell_q24_training_source_v1(
            crate::OriginalCellQ24RemoteTrainingSourceOwnersV1 {
                material,
                baseline: f.baseline(),
                experience,
                dataset,
            },
            config,
        ).await?;
        let (_, batch, _) = source.native_inputs()?;
        assert_eq!(batch.encoded(), expected.batch().encoded());
        let source = tokio::task::spawn_blocking(move || {
            source.require_current_in_lane()?;
            Ok::<_, crate::OriginalCellQ24TrainingSourceErrorV1>(source)
        }).await??;
        drop(source);
        material_thread.join().map_err(|_| anyhow::anyhow!("Material service panicked"))??;
        experience_thread.join().map_err(|_| anyhow::anyhow!("Experience service panicked"))??;
        dataset_thread.join().map_err(|_| anyhow::anyhow!("Dataset service panicked"))??;
        assert_eq!(f.bytes()?, before);
    }
    Ok(())
}

#[tokio::test]
async fn material_source_peer_rejects_raw_batch_provenance_and_frozen_optimizer_rebinding()
-> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    for field in [
        "ledger_binding", "trust_distribution", "source_publication",
        "source_records", "batch_input", "batch_target",
    ] {
        let (client, thread) = connected_fixture(&f, f.source_config()?, move |reply| {
            if field == "batch_input" || field == "batch_target" {
                let batch = reply["material"]["batch"].as_str().expect("actual encoded batch");
                let mut bytes = STANDARD_NO_PAD.decode(batch).expect("actual batch base64");
                let offset = if field == "batch_input" { 44 } else { bytes.len() - 8 };
                let raw = i64::from_le_bytes(bytes[offset..offset + 8].try_into().expect("batch integer"));
                bytes[offset..offset + 8].copy_from_slice(&(raw + 1).to_le_bytes());
                reply["material"]["batch"] = STANDARD_NO_PAD.encode(bytes).into();
            } else if field == "source_records" {
                reply["material"]["source_records"][0] =
                    Digest32::of_bytes(b"another valid source record").to_string().into();
            } else {
                reply["material"][field] =
                    Digest32::of_bytes(b"another original provenance component").to_string().into();
            }
        })?;
        let result = client.read_current().await;
        if field == "source_records" {
            assert!(matches!(result, Err(Error::Evidence(_))));
        } else {
            assert!(matches!(result, Err(Error::Binding("original signatures bind recomputed material"))));
        }
        assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
        finish(client, thread)?;
        assert_eq!(f.bytes()?, before);
    }
    let mut changed = f.source_config()?;
    changed.optimizer.epochs += 1;
    let (client, thread) = connected_fixture(&f, changed, |_| {})?;
    assert!(matches!(client.read_current().await, Err(Error::Dataset(_))));
    assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
    finish(client, thread)?;
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_source_peer_pins_complete_material_and_freeze_signatures()
-> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    for (field, index, seed) in [("experience", 0_usize, 4_u8), ("dataset", 1, 5)] {
        let config = f.source_config()?;
        let mut renewed = if index == 0 {
            config.experience_evidence.clone()
        } else {
            config.dataset_evidence.clone()
        };
        renewed.expires_at += 1;
        renewed.signature = SigningKey::from_bytes(&[seed; 32])
            .sign(&renewed.signing_bytes()).to_bytes();
        // A newly valid original-role signature must not replace the retained
        // completed predecessor window, even when the payload is unchanged.
        config.verifier.verify(LearningEvidenceRoleV1::Observer, &renewed,
            &learning_iteration_receipt_signing_bytes_v1(&config.dataset.receipts[index])?,
            now()?)?;
        let replacement = serde_json::to_value(evidence_wire::Evidence::from_original(&renewed))?;
        let (client, thread) = connected_fixture(&f, config, move |reply| {
            reply[field] = replacement.clone();
        })?;
        assert!(matches!(client.read_current().await,
            Err(Error::Binding("complete original Material signature bytes"))));
        assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
        finish(client, thread)?;
    }
    let mut config = f.source_config()?;
    config.freeze_evidence.expires_at += 1;
    config.freeze_evidence.signature = SigningKey::from_bytes(&[3; 32])
        .sign(&config.freeze_evidence.signing_bytes()).to_bytes();
    let (client, thread) = connected_fixture(&f, config, |_| {})?;
    // The strict factory verifies this new freeze signature, then detects that
    // its complete bytes are absent from the two original material signatures.
    assert!(matches!(client.read_current().await,
        Err(Error::Binding("original signatures bind recomputed material"))));
    assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
    finish(client, thread)?;
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_source_service_refuses_withdrawn_missing_or_busy_originals()
-> anyhow::Result<()> {
    let mut f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let query = serde_json::to_vec(&request(&f)?)?;
    {
        let held = f.ledger.lock().expect("original unique ledger");
        assert!(matches!(f.service.as_ref().expect("owner").respond_material(&mut 1, &query),
            Err(Error::Owner(OriginalCellQ24MaterialEvidenceErrorV1::Unavailable))));
        drop(held);
    }
    let config = f.source_config()?;
    f.withdraw()?;
    for cold in [false, true] {
        if cold {
            f.reopen()?;
        }
        let (client, thread) = connected_fixture(&f, config.clone(), |_| {})?;
        assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
        assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
        drop(client);
        let result = thread.join().map_err(|_| anyhow::anyhow!("source service panicked"))?;
        assert!(matches!(result, Err(Error::Owner(
            OriginalCellQ24MaterialEvidenceErrorV1::Material(
                OriginalCellQ24MaterialReceiptErrorV1::Material(_))))));
        assert_eq!(f.bytes()?, before);
    }
    let mut missing = ReadbackServiceFixture::new(false).await?;
    let before = missing.bytes()?;
    let query = serde_json::to_vec(&request(&missing)?)?;
    for cold in [false, true] {
        if cold {
            missing.reopen()?;
        }
        assert!(matches!(missing.service.as_ref().expect("owner")
            .respond_material(&mut 1, &query),
            Err(Error::Owner(OriginalCellQ24MaterialEvidenceErrorV1::Material(
                OriginalCellQ24MaterialReceiptErrorV1::Owner(_))))));
        assert_eq!(missing.bytes()?, before);
    }
    Ok(())
}

#[tokio::test]
async fn material_source_service_refuses_request_payload_rebinding_and_public_custody_bypass()
-> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    let owner = f.service.as_ref().expect("owner");
    for field in ["operation", "binding", "scope", "operation_id", "dataset_head",
        "experience_receipt", "dataset_receipt"] {
        let mut query = serde_json::to_value(request(&f)?)?;
        query[field] = Digest32::of_bytes(b"different fixed Material request").to_string().into();
        assert!(matches!(owner.respond_material(&mut 1, &serde_json::to_vec(&query)?),
            Err(Error::Binding(_)) | Err(Error::Owner(OriginalCellQ24MaterialEvidenceErrorV1::Request))));
    }
    for field in ["batch", "target", "receipt", "snapshot", "signature", "observed", "now"] {
        let mut query = serde_json::to_value(request(&f)?)?;
        query[field] = "caller supplied".into();
        assert!(matches!(owner.respond_material(&mut 1, &serde_json::to_vec(&query)?),
            Err(Error::Encoding(_))));
    }
    let mut next = 1;
    let query = serde_json::to_vec(&request(&f)?)?;
    owner.respond_material(&mut next, &query)?;
    assert_eq!(next, 2);
    assert!(matches!(owner.respond_material(&mut next, &query), Err(Error::Binding(_))));

    let original = peer()?;
    let (socket, other) = UnixStream::pair()?;
    assert!(matches!(OriginalCellQ24RemoteMaterialClientV1::from_original_stream(
        socket, LearningIterationEvidencePeerV1 {
            pid: original.pid, uid: policy().peer.uid, boot_id: original.boot_id,
            process_start_ticks: original.process_start_ticks,
            actor_id: f.dataset.owners.dataset.clone(),
        }, pidfd()?, f.source_config()?, f.baseline(),
        Duration::from_millis(500), Duration::from_secs(300),
    ), Err(Error::Binding(_))));
    drop(other);
    let mut policies = vec![policy()];
    let mut widened = policy();
    widened.peer.uid = widened.peer.uid.wrapping_add(1);
    widened.peer.pid += 1;
    widened.timeout = Duration::from_millis(501);
    policies.push(widened);
    widened.timeout = Duration::from_millis(500);
    widened.lifetime = Duration::from_secs(301);
    policies.push(widened);
    for policy in policies {
        let (server, other) = UnixStream::pair()?;
        assert!(matches!(owner.serve_material_source(server, policy, pidfd()?),
            Err(Error::Binding(_))));
        drop(other);
    }
    assert_eq!(f.bytes()?, before);
    Ok(())
}

#[tokio::test]
async fn material_source_peer_consumes_wrong_purpose_or_failed_frames()
-> anyhow::Result<()> {
    let f = ReadbackServiceFixture::new(true).await?;
    let before = f.bytes()?;
    for field in ["operation", "binding", "scope", "operation_id", "dataset_head",
        "experience_receipt", "dataset_receipt", "unrequested_field"] {
        let (client, thread) = connected_fixture(&f, f.source_config()?, move |reply| {
            reply[field] = "unrelated reply".into();
        })?;
        let result = client.read_current().await;
        if field == "unrequested_field" {
            assert!(matches!(result, Err(Error::Unavailable)));
        } else {
            assert!(matches!(result, Err(Error::Binding("same original Material response"))));
        }
        assert!(matches!(client.read_current().await, Err(Error::Unavailable)));
        finish(client, thread)?;
        assert_eq!(f.bytes()?, before);
    }
    Ok(())
}
