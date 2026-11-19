//! The actual postload tail only: no Root0600 descriptor/credential admission
//! qualification is implied by this same-UID, synthetic-key refusal fixture.
use super::*;
use crate::root_authority_session::tests::connected;
use crate::root_authority_session::tests::observation_worker;
use crate::root_authority_session::tests::original_config;
use crate::root_authority_session::tests::owner;
use crate::root_writer_proof::tests::fixture;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;
use std::time::Duration;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn postload_birth_refusal_consumes_config_but_retains_active_original_session_file()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()?;
    let (trust, _) = fixture();
    let config = original_config(&directory.path().canonicalize()?, &trust)?;
    let identity = config.identity().clone();
    let contender = OpenOptions::new()
        .read(true)
        .write(true)
        .open(identity.layout.writer_lock())?;
    let metadata = contender.metadata()?;
    let (session, _, peer, key) = connected().await;
    let (device, _, _device_directory) = owner(&session, key);
    let (notes, _, _notes_directory) = owner(&session, key);
    session
        .activate_final_use_owners(vec![device, notes])
        .await?;
    let authority = session.authority();
    let clock = session.clock();
    let verifier = session.verifier();
    let worker = observation_worker(&session);
    let ticks: u64 = std::fs::read_to_string("/proc/self/stat")?
        .rsplit_once(") ")
        .ok_or("missing stat delimiter")?
        .1
        .split_whitespace()
        .nth(19)
        .ok_or("missing process birth")?
        .parse()?;
    let mut registration = crate::HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: std::process::id(),
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: ticks,
        registered_identity: crate::HostAuthorityRegisteredIdentity {
            agent_id: identity.agent_id.clone(),
            spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root.clone(),
            workspace: identity.workspace.clone(),
            resources: identity.resources.clone(),
        },
        checkpoint_owner_agent_id: identity.agent_id.clone(),
        publisher_epoch: 1,
    };
    // SAFETY: sample this actual fixture process's unchanged credentials only.
    let credentials = unsafe { (libc::geteuid(), libc::getegid()) };
    // This ordinary same-UID fixture does not claim the dedicated credential
    // profile. Exercise the original postload birth refusal, which precedes
    // those unchanged credential checks, through the actual consuming tail.
    registration.process_start_ticks = ticks.checked_add(1).ok_or("birth overflow")?;
    let writer = crate::HostAuthorityWriterRegistration {
        registered_agent_id: trust.agent_id,
        spawn_generation: trust.spawn_generation,
        owner_epoch: trust.owner_epoch,
        local_lease_id: trust.local_lease_id,
        local_lease_generation: trust.local_lease_generation,
        authority_lease: trust.authority_lease,
    };
    let error = finish_loaded_root_writer(config, &session, &registration, &writer, credentials)
        .err()
        .ok_or("changed birth must refuse the actual postload tail")?;
    let AgentdError::Io(cause) = error else {
        return Err("postload must refuse at the original process birth check".into());
    };
    assert_eq!(
        (cause.kind(), cause.to_string()),
        (
            std::io::ErrorKind::Other,
            "registered start identity mismatch".to_string()
        )
    );
    assert!(clock.now_unix_ms().is_ok());
    verifier.verify(&authority, &identity.agent_id)?;
    assert!(matches!(
        contender.try_lock(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
    drop(session);
    assert!(clock.now_unix_ms().is_err());
    assert!(verifier.verify(&authority, &identity.agent_id).is_err());
    tokio::time::timeout(Duration::from_secs(1), async {
        while !worker.is_finished() {
            tokio::task::yield_now().await;
        }
    })
    .await?;
    tokio::task::spawn_blocking(move || peer.join())
        .await?
        .map_err(|_| "original observation peer panicked")?;
    contender.try_lock()?;
    assert_eq!(
        (contender.metadata()?.dev(), contender.metadata()?.ino()),
        (metadata.dev(), metadata.ino())
    );
    contender.unlock()?;
    eprintln!(
        "root-session-postload-custody birth_refused=true config_consumed=true old_session_active=true owner_lock_reacquired=false worker_retired=true fenced_readonly_retained=true final_lock_reacquired=true effects=0"
    );
    Ok(())
}
