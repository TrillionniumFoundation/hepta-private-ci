//! A child test owns one actual Root service for one dedicated daemon lifetime.

use super::*;

#[test]
#[ignore = "only the actual Root cold-recovery parent supplies a phase"]
fn root_q24_factory_v2_dedicated_root_phase() -> anyhow::Result<()> {
    let phase = std::env::var("HEPTA_FACTORY_V2_ROOT_PHASE")?;
    let fresh = match phase.as_str() {
        "reserve" => true,
        "reopen" | "reopen-then-missing" => false,
        _ => anyhow::bail!("unknown Root factory phase"),
    };
    // SAFETY: this is a dedicated subprocess; these calls inspect credentials
    // and bound its lifetime, without changing any authority or process IDs.
    assert_eq!(
        (unsafe { libc::getuid() }, unsafe { libc::geteuid() }),
        (0, 0)
    );
    unsafe {
        libc::alarm(/*seconds*/ 12)
    };
    let directory = PathBuf::from(
        std::env::var_os("HEPTA_FACTORY_V2_ROOT_DIRECTORY")
            .ok_or_else(|| anyhow::anyhow!("original protected directory required"))?,
    );
    let mut setup: fixture::Setup =
        crate::authority_host_runtime::read_root_json(&directory.join("setup.json"))?;
    let original_identity = setup.identity.identity()?;
    let initial = setup.initial_data.require_binding(
        &original_identity,
        &Digest32::from_array([7; 32]).to_string(),
    )?;
    let runtime = tempfile::Builder::new().prefix("hf2-").tempdir_in("/run")?;
    let runtime_c = std::ffi::CString::new(runtime.path().as_os_str().as_encoded_bytes())?;
    // SAFETY: Root changes only the group of this new test-owned directory.
    anyhow::ensure!(
        unsafe {
            libc::chown(runtime_c.as_ptr(), /*uid*/ 0, /*gid*/ 60001)
        } == 0,
        "{}",
        io::Error::last_os_error()
    );
    std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710))?;
    setup.config.sockets.observation = runtime.path().join("observation.sock");
    setup.config.sockets.issuer = runtime.path().join("issuer.sock");
    setup.config.sockets.checkpoint = runtime.path().join("checkpoint.sock");
    let now = fixture::now_ms()?;
    let writer = setup
        .config
        .writer
        .as_mut()
        .ok_or_else(|| anyhow::anyhow!("original writer required"))?;
    writer.authority_lease.issued_at_unix_ms = now;
    writer.authority_lease.expires_at_unix_ms = now + 5_000;
    if !fresh {
        let old: PhaseReceipt =
            crate::authority_host_runtime::read_root_json(&directory.join("receipt-reserve.json"))?;
        anyhow::ensure!(!Path::new(&format!("/proc/{}", old.root_pid)).exists());
        anyhow::ensure!(!Path::new(&format!("/proc/{}", old.daemon_pid)).exists());
        setup.identity.spawn_generation = setup
            .identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("spawn overflow"))?;
        writer.spawn_generation = setup.identity.spawn_generation;
        writer.owner_epoch += 1;
        writer.local_lease_generation += 1;
        writer.authority_lease.lease_id = "factory-cold-writer-next".into();
    }
    let config_file = directory.join(format!("service-{phase}.json"));
    support::write_json(&config_file, &setup.config)?;
    let proof = if fresh {
        crate::register_host_writer_authorization(&config_file)?
    } else {
        let predecessor: HostAuthorityServiceConfig =
            crate::authority_host_runtime::read_root_json(&directory.join("service-reserve.json"))?;
        let old_proof =
            crate::authority_host_runtime::read_root_json(&directory.join("proof-reserve.json"))?;
        crate::rotate_host_writer_authorization(
            &config_file,
            predecessor
                .writer
                .as_ref()
                .ok_or_else(|| anyhow::anyhow!("old canonical writer required"))?,
            &old_proof,
        )?
    };
    support::write_json(&directory.join(format!("proof-{phase}.json")), &proof)?;
    let proof_digest: Digest32 = proof.sha256()?.as_str().parse()?;
    let identity = setup.identity.identity()?;
    let profile = crate::HostAuthorityLearningProfileV1::new_scoped_v2(
        &identity,
        *proof_digest.as_array(),
        initial.request.clone(),
        initial.owners.clone(),
        codex_hepta_learning_artifacts::LearningUpdateScopeV2::Cell,
        Digest32::of_bytes(UPDATE_RULE),
    )?;
    let (offer, receive) = UnixDatagram::pair()?;
    let mut child = support::ChildOwner::spawn(receive, &setup.config.state_dir)?;
    let child_pin = support::pidfd(child.pid()?)?;
    let credentials_end = Instant::now() + Duration::from_secs(2);
    while crate::authority_host_runtime::verify_process_credentials(
        child.pid()?,
        /*uid*/ 60001,
        /*gid*/ 60001,
    )
    .is_err()
    {
        anyhow::ensure!(
            Instant::now() < credentials_end,
            "dedicated daemon credentials deadline"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
    let registration = HostAuthorityRegistration {
        schema_version: 1,
        peer_pid: child.pid()?,
        boot_id: std::fs::read_to_string("/proc/sys/kernel/random/boot_id")?
            .trim()
            .into(),
        process_start_ticks: support::start_ticks(child.pid()?)?,
        registered_identity: setup.identity,
        checkpoint_owner_agent_id: identity.agent_id.clone(),
        publisher_epoch: if fresh { 1 } else { 2 },
    };
    let service = crate::authority_host_runtime::open_registered_writer(
        &setup.config,
        &registration,
        &child_pin,
    )?;
    let end = Instant::now() + Duration::from_millis(setup.config.lifetime_ms);
    let learning = service.prepare_original_derived_learning_checkpoint(
        &setup.config,
        &registration,
        &child_pin,
        profile,
        if fresh {
            OriginalDerivedLearningMode::Register
        } else {
            OriginalDerivedLearningMode::Reopen
        },
        end,
    )?;
    let reservation_path = directory.join("reservation.json");
    let reservation: crate::HostAuthorityQ24ModelFactoryReservationV1 =
        crate::authority_host_runtime::read_root_json(&reservation_path)?;
    let registry = setup.config.state_dir.join(DIRECTORY);
    if fresh {
        assert!(
            service
                .open_q24_model_factory_v2(
                    &setup.config,
                    &registration,
                    &child_pin,
                    &learning.profile,
                    &reservation_path,
                    end
                )
                .is_err()
        );
        assert!(!registry.exists());
        service.reserve_q24_model_factory_v2_for_profile(
            &setup.config,
            &registration,
            &child_pin,
            &learning.profile,
            &reservation,
            end,
        )?;
    }
    let before = support::protected_files(&registry)?;
    let witness_path = reservation.witness_directory.join(WITNESS);
    let witness_before = std::fs::read(&witness_path)?;
    let mut factory = service.open_q24_model_factory_v2(
        &setup.config,
        &registration,
        &child_pin,
        &learning.profile,
        &reservation_path,
        end,
    )?;
    let live = factory.profile.clone();
    let model_offer = service.seal_q24_model_factory_offer(
        &setup.config,
        &registration,
        &child_pin,
        &mut factory,
    )?;
    assert!(
        service
            .seal_q24_model_factory_offer(&setup.config, &registration, &child_pin, &mut factory)
            .is_err()
    );
    assert_eq!(support::protected_files(&registry)?, before);
    assert_eq!(std::fs::read(&witness_path)?, witness_before);
    let bound = BoundFactory::bind(factory, &setup.config, &learning.socket_path)?;
    let acknowledgement = offer.try_clone()?;
    let root_pin = support::pidfd(std::process::id())?;
    let served = serve_optional_until(
        Some(&bound),
        &service,
        &setup.config,
        &registration,
        &child_pin,
        end,
        || {
            let remaining = end
                .checked_duration_since(Instant::now())
                .ok_or_else(|| io::Error::other("original test phase expired"))?;
            crate::send_root_q24_model_factory_handoff(
                offer,
                model_offer,
                &root_pin,
                remaining.min(Duration::from_millis(setup.config.timeout_ms)),
            )
            .map_err(io::Error::other)?;
            let remaining = end
                .checked_duration_since(Instant::now())
                .ok_or_else(|| io::Error::other("original test phase expired"))?;
            acknowledgement.set_read_timeout(Some(
                remaining.min(Duration::from_millis(setup.config.timeout_ms)),
            ))?;
            let mut ack = [0; 1];
            if acknowledgement.recv(&mut ack)? != 1 || ack != [0x51] {
                return Err(io::Error::other(
                    "exact completed consumer receipt required",
                ));
            }
            Ok(())
        },
    );
    if let Err(error) = served {
        let _ = child.release();
        let output = child.finish();
        anyhow::bail!("actual factory phase failed: {error}; daemon={output:?}");
    }
    drop(bound);
    let store: HostAuthorityFrontierStore<FactoryRecord> =
        HostAuthorityFrontierStore::open(RootAuthorityDirectory::open(&registry)?, OWNER.into())?;
    let record = store.load(OWNER)?;
    assert_eq!(
        (record.epoch, record.material.clone()),
        (2, Some(Digest32::of_bytes(MATERIAL).to_string()))
    );
    assert_eq!(record.profile, live.reserved());
    drop(store);
    if !fresh {
        assert_eq!(support::protected_files(&registry)?, before);
        assert_eq!(std::fs::read(&witness_path)?, witness_before);
    }
    let missing_witness_refused = phase == "reopen-then-missing";
    if missing_witness_refused {
        std::fs::remove_file(&witness_path)?;
        File::open(&reservation.witness_directory)?.sync_all()?;
        assert!(
            service
                .open_q24_model_factory_v2(
                    &setup.config,
                    &registration,
                    &child_pin,
                    &learning.profile,
                    &reservation_path,
                    end
                )
                .is_err()
        );
        assert!(!witness_path.exists());
        assert_eq!(support::protected_files(&registry)?, before);
    }
    child.release()?;
    let output = child.finish()?;
    let daemon_marker = format!(
        "ROOT_FACTORY_V2_CONSUMER pid={} original_root={} ",
        registration.peer_pid,
        std::process::id()
    );
    anyhow::ensure!(
        output.contains(&daemon_marker),
        "missing actual daemon receipt: {output}"
    );
    anyhow::ensure!(Instant::now() < end);
    anyhow::ensure!(crate::authority_host_runtime::owner_alive(&child_pin, end).is_err());
    let receipt = PhaseReceipt {
        phase: phase.clone(),
        root_pid: std::process::id(),
        root_start: support::start_ticks(std::process::id())?,
        daemon_pid: registration.peer_pid,
        daemon_start: registration.process_start_ticks,
        spawn_generation: identity.spawn_generation,
        writer_proof: proof_digest.to_string(),
        live,
        record,
        missing_witness_refused,
    };
    support::write_json(&directory.join(format!("receipt-{phase}.json")), &receipt)?;
    println!("{output}");
    println!(
        "ROOT_FACTORY_V2_PHASE phase={phase} pid={} daemon={} complete=true",
        std::process::id(),
        registration.peer_pid
    );
    std::io::stdout().flush()?;
    Ok(())
}
