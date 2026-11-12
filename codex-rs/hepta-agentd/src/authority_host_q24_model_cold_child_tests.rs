//! Actual unprivileged descriptor consumer. It never opens Root paths or
//! constructs Training/Evaluation/Model evidence from these control vectors.

use super::*;
use crate::authority_host_service::q24_model::Command;
use crate::authority_host_service::q24_model::Q24ModelFactoryBootstrap;
use crate::authority_host_service::q24_model::Reply;
use crate::authority_host_service::q24_model::Request;
use crate::authority_host_service::q24_model::Response;
use crate::authority_host_service::q24_model::WITNESS_RECORDS;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::JournalScope;
use pretty_assertions::assert_eq;

#[test]
#[ignore = "only the actual Root cold phase transfers the original four rights"]
fn root_q24_factory_v2_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(
        std::process::id(),
        /*uid*/ 60001,
        /*gid*/ 60001,
    )?;
    let number: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let original_root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(number >= 3 && original_root != std::process::id());
    // SAFETY: only this dedicated subprocess installs its bounded test alarm.
    unsafe {
        libc::alarm(/*seconds*/ 10)
    };
    let state = PathBuf::from(
        std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
            .ok_or_else(|| anyhow::anyhow!("original protected state required"))?,
    );
    match std::fs::read_dir(state) {
        Err(error) => assert_eq!(error.kind(), io::ErrorKind::PermissionDenied),
        Ok(_) => anyhow::bail!("dedicated daemon could read Root state"),
    }
    // SAFETY: the trusted parent gave this child sole ownership of this socket.
    let socket = unsafe { UnixDatagram::from_raw_fd(number) };
    let acknowledgement = socket.try_clone()?;
    let mut handoff =
        crate::receive_root_q24_model_factory_handoff(socket, Duration::from_secs(5))?;
    assert_eq!(handoff.root_pid, original_root);
    let mut bytes = Vec::new();
    handoff.bootstrap.rewind()?;
    handoff.bootstrap.read_to_end(&mut bytes)?;
    let bundle: Q24ModelFactoryBootstrap = serde_json::from_slice(&bytes)?;
    assert_eq!(
        (
            bundle.root.uid,
            bundle.root.pid,
            bundle.consumer.uid,
            bundle.consumer.pid
        ),
        (0, original_root, 60001, std::process::id())
    );
    assert!(matches!(&bundle.profile, LiveFactoryProfile::SessionV2(_)));
    bundle
        .profile
        .require_files(&handoff.journal, &handoff.witness)?;
    let generation = bundle
        .profile
        .witness_generation(bundle.identity.spawn_generation)?;
    let peer = crate::AgentdRootAuthorityPeer {
        pid: bundle.root.pid,
        boot_id: bundle.root.boot_id.clone(),
        process_start_ticks: bundle.root.process_start_ticks,
    };
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(async {
            let transport = crate::root_observation_stream::RootObservationStream::from_stream(
                UnixStream::connect(&bundle.socket_path)?,
                peer,
                handoff.root_pidfd,
                Duration::from_millis(500),
                Duration::from_secs(5),
            )?;
            let before = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 1,
                Command::Observe,
            )
            .await?;
            assert!(!before.newly_bound);
            let expected = match before.lease.epoch {
                1 => {
                    assert_eq!(before.lease.material, None);
                    assert_eq!(generation.get(), bundle.identity.spawn_generation);
                    let bound = exchange(
                        &transport,
                        &bundle.profile,
                        /*request_id*/ 2,
                        Command::Bind {
                            expected: before.lease,
                            material: Digest32::of_bytes(MATERIAL).to_string(),
                        },
                    )
                    .await?;
                    assert!(bound.newly_bound);
                    assert_eq!(
                        (bound.lease.epoch, bound.lease.material.clone()),
                        (2, Some(Digest32::of_bytes(MATERIAL).to_string()))
                    );
                    bound.lease
                }
                2 => {
                    assert_eq!(
                        before.lease.material,
                        Some(Digest32::of_bytes(MATERIAL).to_string())
                    );
                    assert_eq!(
                        generation.get().checked_add(1),
                        Some(bundle.identity.spawn_generation)
                    );
                    let recovered = exchange(
                        &transport,
                        &bundle.profile,
                        /*request_id*/ 2,
                        Command::Confirm {
                            expected: before.lease.clone(),
                        },
                    )
                    .await?;
                    assert_eq!(recovered.lease, before.lease);
                    assert!(!recovered.newly_bound);
                    recovered.lease
                }
                other => anyhow::bail!("unexpected factory epoch {other}"),
            };
            let witness = FileAnchorWitnessStore::open(
                handoff.witness,
                JournalScope {
                    scope_digest: bundle.profile.witness_binding().parse()?,
                    objective_digest: Digest32::of_bytes(b"objective"),
                },
                generation,
                WITNESS_RECORDS,
            )?;
            assert_eq!(witness.current()?, None);
            let after = exchange(
                &transport,
                &bundle.profile,
                /*request_id*/ 3,
                Command::Confirm {
                    expected: expected.clone(),
                },
            )
            .await?;
            assert_eq!(after.lease, expected);
            assert!(!after.newly_bound);
            assert_eq!(
                handoff.journal.metadata()?.len(),
                0,
                "registry binding creates no Model owner"
            );
            drop((witness, transport));
            Ok::<_, anyhow::Error>(())
        })?;
    drop((handoff.journal, handoff.bootstrap));
    println!(
        "ROOT_FACTORY_V2_CONSUMER pid={} original_root={original_root} original_generation={} current_generation={} registry_epoch=2 model_owner_created=false",
        std::process::id(),
        generation.get(),
        bundle.identity.spawn_generation
    );
    std::io::stdout().flush()?;
    assert_eq!(acknowledgement.send(&[0x51])?, 1);
    let mut release = [0];
    std::io::stdin().read_exact(&mut release)?;
    assert_eq!(release, [1]);
    Ok(())
}

async fn exchange(
    transport: &crate::root_observation_stream::RootObservationStream,
    profile: &LiveFactoryProfile,
    request_id: u64,
    command: Command,
) -> anyhow::Result<Reply> {
    let response: Response = transport
        .read(&Request {
            schema: profile.wire_schema(),
            operation: profile.purpose().into(),
            request_id,
            binding: profile.binding().into(),
            command,
        })
        .await?;
    assert_eq!(
        (
            response.schema,
            response.operation.as_str(),
            response.request_id,
            response.binding.as_str()
        ),
        (
            profile.wire_schema(),
            profile.purpose(),
            request_id,
            profile.binding()
        )
    );
    Ok(response.reply)
}
