//! Open the original physical installation after an actual kernel boot change.
//! This module never initializes existing authority, a consumer or a checkpoint.

use super::*;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_memory::CognitiveCheckpointWriterBinding;
use serde::Deserialize;
use serde::Serialize;

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct InstalledPin {
    schema_version: u32,
    agent_id: AgentId,
    initial_kernel_boot: [u8; 16],
    config: HostAuthorityServiceConfig,
}

impl InstalledPin {
    pub(super) fn save(
        config: &HostAuthorityServiceConfig,
        boot: &NativeBootstrap,
    ) -> io::Result<()> {
        write_json(
            &Path::new(STATE).join("protected/installation.json"),
            &Self {
                schema_version: 1,
                agent_id: AgentId::parse(AGENT).map_err(error)?,
                initial_kernel_boot: boot.id(96),
                config: config.clone(),
            },
        )
    }

    fn load() -> io::Result<Self> {
        let pin: Self = crate::authority_host_config::read_root_json(
            &Path::new(STATE).join("protected/installation.json"),
        )?;
        let state = Path::new(STATE).join("protected/authority");
        let runtime = Path::new(RUNTIME).join("owner");
        let config = &pin.config;
        let consumers = config
            .consumers
            .as_ref()
            .ok_or_else(|| invalid("retained installation omitted original consumers"))?;
        if pin.schema_version != 1
            || pin.agent_id.as_str() != AGENT
            || pin.initial_kernel_boot == [0; 16]
            || config.schema_version != 1
            || config.state_dir != state
            || config.required_bind.mountpoint != Path::new(STATE).join("protected")
            || config.required_bind.source_path != Path::new(STATE).join("protected-source")
            || config.signer_id != "native-cpu-original-root"
            || config.lease_id != "native-cpu-root-installation"
            || config.lease_revision != 1
            || config.writer.is_some()
            || config.checkpoint_state_dir != Some(state.join("checkpoint"))
            || config.peer_uid != 60001
            || config.peer_gid != 60001
            || config.timeout_ms != 5_000
            || config.lifetime_ms != LIFETIME.as_millis() as u64
            || config.sockets.observation != runtime.join("observation.sock")
            || config.sockets.issuer != runtime.join("issuer.sock")
            || config.sockets.checkpoint != runtime.join("checkpoint.sock")
            || config.sockets.device_frontier != Some(runtime.join("device-frontier.sock"))
            || config.sockets.notes_frontier != Some(runtime.join("notes-frontier.sock"))
            || consumers.device.owner_id != config.signer_id
            || consumers.notes.owner_id != config.signer_id
            || consumers.device.state_dir != state.join("device-consumer")
            || consumers.notes.state_dir != state.join("notes-consumer")
        {
            return Err(invalid(
                "retained installation differs from the original fixed native owner",
            ));
        }
        // Required-bind inode/device validation is performed by the original
        // open_registered_issuer. Never rewrite it to fit a different volume.
        Ok(pin)
    }
}

pub(super) fn lease_id(kind: &str, spec: &SpawnSpec) -> io::Result<String> {
    if !matches!(kind, "root" | "writer") || spec.agent_id.as_str() != AGENT || spec.generation == 0
    {
        return Err(invalid(
            "original Supervisor spawn required for fresh lease identity",
        ));
    }
    let root = crate::HostAuthorityService::current_root_lifetime_for_admin()?;
    if root.pid != 1 {
        return Err(invalid("actual native Root required"));
    }
    Ok(format!(
        "native-cpu.{kind}.{}.{}",
        root.boot_id, spec.generation
    ))
}

/// Request original revocation only when required. Already-retired records
/// are checked in full; expiry is sampled from the original actual clock.
/// This function returns no retirement capability. The canonical rotation's
/// original registry pair boundary independently proves retirement later.
pub(super) fn retire_lease_for_handoff(
    registry: &AuthorityLeaseRegistry,
    clock: &HostAuthorityClock,
    issued: &AuthorityLease,
    reason: [u8; 32],
) -> io::Result<()> {
    let actual = registry.read_lease(&issued.lease_id).map_err(error)?;
    let revoked = registry.read_revocation(&issued.lease_id).map_err(error)?;
    match (actual, revoked) {
        (Some(actual), Some(revoked)) => {
            let mut expected = issued.clone();
            expected.revision = expected
                .revision
                .checked_add(1)
                .ok_or_else(|| invalid("retired lease revision overflow"))?;
            if actual.lease != expected
                || revoked.revocation.lease_id != issued.lease_id
                || revoked.revocation.authority_epoch != issued.authority_epoch
                || revoked.revocation.lease_revision != expected.revision
            {
                return Err(invalid("retained original lease/revocation changed"));
            }
        }
        (Some(actual), None) => {
            if actual.lease != *issued {
                return Err(invalid("original issued lease changed"));
            }
            if clock.now_unix_ms().map_err(error)? < issued.expires_at_unix_ms {
                registry
                    .revoke(&issued.lease_id, issued.revision, reason)
                    .map_err(error)?;
            }
        }
        (None, None) if clock.now_unix_ms().map_err(error)? >= issued.expires_at_unix_ms => {
            // Only the original later pair boundary can accept its retained
            // PrunedExpired evidence. Absence alone proves no retirement here.
        }
        _ => return Err(invalid("original lease retirement is unavailable")),
    }
    Ok(())
}

impl Installation {
    pub(super) fn cold_open(boot: &NativeBootstrap, deadline: u64) -> io::Result<Self> {
        let pin = InstalledPin::load()?;
        let mut config = pin.config;
        let fleet_root = HeptaFleetRoot::parse(Path::new(STATE).join("fleet")).map_err(error)?;
        let fleet = FleetRegistry::open_existing(fleet_root).map_err(error)?;
        let record = fleet
            .load()
            .map_err(error)?
            .agent(&pin.agent_id)
            .cloned()
            .ok_or_else(|| invalid("retained original Fleet Agent absent"))?;
        if record.manifest.agent_id != pin.agent_id {
            return Err(invalid("retained Fleet Agent identity changed"));
        }
        let (clock, leases, issuer) =
            crate::authority_host_runtime::open_registered_issuer(&config)?;
        let canonical = issuer.retained_writer_state_for_root()?;
        if canonical.registration.registered_agent_id != pin.agent_id {
            return Err(invalid(
                "retained canonical writer belongs to another Agent",
            ));
        }
        let checkpoint = config.state_dir.join("checkpoint");
        let directory = RootAuthorityDirectory::open(&checkpoint).map_err(error)?;
        let head = crate::HostCognitiveCheckpoint::retained_head_for_root(directory.clone())
            .map_err(error)?;
        let previous_writer = &canonical.registration;
        let verified = codex_hepta_authority_client::VerifiedRootWriterProof::verify(
            canonical.proof.clone(),
            &crate::AgentdRootWriterTrust {
                issuer_id: config.signer_id.clone(),
                verifying_key: config.expected_verifying_key,
                agent_id: previous_writer.registered_agent_id.clone(),
                spawn_generation: previous_writer.spawn_generation,
                owner_epoch: previous_writer.owner_epoch,
                local_lease_id: previous_writer.local_lease_id.clone(),
                local_lease_generation: previous_writer.local_lease_generation,
                authority_lease: previous_writer.authority_lease.clone(),
            },
        )
        .map_err(error)?;
        let authority = verified.authority();
        let binding = CognitiveCheckpointWriterBinding {
            lease_id: previous_writer.local_lease_id.clone(),
            generation: previous_writer.local_lease_generation,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest().map_err(error)?,
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        };
        if head.head.owner_agent_id != pin.agent_id || head.head.writer_binding != binding {
            return Err(invalid(
                "canonical authorization and actual retained checkpoint require partial-activation reconciliation",
            ));
        }
        let archive = config.state_dir.join("material");
        RootAuthorityDirectory::open(&archive).map_err(error)?;
        let digest = codex_hepta_contracts::Sha256Digest::for_bytes(
            &serde_json::to_vec(&head.head.last_current).map_err(error)?,
        );
        let image = HeptaFleetRoot::parse(archive.join(digest.as_str()))
            .map_err(error)?
            .layout()
            .agent(&pin.agent_id);
        let material = runtime()?
            .block_on(CognitiveStore::verify_retained_root_material(
                &image,
                &head.head.last_current,
            ))
            .map_err(error)?;
        let (previous, retired) = crate::HostCognitiveCheckpoint::observe_previous_boot_for_root(
            directory, &clock, &material,
        )
        .map_err(error)?;
        if previous != head {
            return Err(invalid(
                "original head changed while selecting its physical image",
            ));
        }
        let launcher = Arc::new(RootKernelLauncher::open(&boot.bytes)?);
        let current_root = retired
            .prior_boot_root_for_namespace(&previous)
            .map_err(error)?;
        let current_boot: String = boot
            .id(96)
            .iter()
            .enumerate()
            .map(|(index, byte)| {
                format!(
                    "{}{byte:02x}",
                    if matches!(index, 4 | 6 | 8 | 10) {
                        "-"
                    } else {
                        ""
                    }
                )
            })
            .collect();
        if current_root.boot_id != current_boot || launcher.boot_id() != boot.id(96) {
            return Err(invalid("actual proc boot and kernel launch boot differ"));
        }
        let consumer_local = Path::new(STATE).join("consumer-local");
        for path in [
            &consumer_local,
            &consumer_local.join("device"),
            &consumer_local.join("notes"),
        ] {
            platform::existing_directory(path, 60001, 60001, 0o700)?;
        }
        let consumers = config.consumers.as_ref().unwrap();
        let load_frontier =
            |slot: &crate::HostAuthorityConsumerConfig| -> io::Result<FinalUseFrontier> {
                HostAuthorityFrontierStore::<FinalUseFrontier>::open(
                    RootAuthorityDirectory::open(&slot.state_dir).map_err(error)?,
                    slot.owner_id.clone(),
                )
                .map_err(error)?
                .load(&slot.owner_id)
                .map_err(error)
            };
        let frontiers = [
            load_frontier(&consumers.device)?,
            load_frontier(&consumers.notes)?,
        ];
        if frontiers.iter().any(|frontier| {
            frontier.authority_epoch > canonical.revocations.authority_epoch
                || (frontier.authority_epoch == canonical.revocations.authority_epoch
                    && frontier.revocation_revision > canonical.revocations.revision)
        }) {
            return Err(invalid(
                "retained original consumer frontier exceeds canonical head",
            ));
        }
        let policies = canonical
            .policies
            .iter()
            .filter(|policy| {
                policy.subject_id == pin.agent_id.as_str()
                    && policy.destination_id == codex_hepta_memory::HOS2_DESTINATION_V1
            })
            .collect::<Vec<_>>();
        if policies.len() != 2 || policies.iter().any(|policy| policy.lifetime_ms != 5_000) {
            return Err(invalid("retained original CPU policy slots differ"));
        }
        let scopes = [policies[0].scope_sha256, policies[1].scope_sha256];
        // No new Root session or Host has been admitted. Retire every actual
        // not-yet-retired lease of this original Agent, including future rows,
        // under the original CAS. Historical expired/revoked rows do not use
        // the active-selection bound and are never mistaken for live work.
        let selected = leases
            .read_unretired_for_principal(
                pin.agent_id.as_str(),
                codex_hepta_contracts::authority_lease::MAX_AUTHORITY_LEASES,
            )
            .map_err(error)?;
        for lease in &selected.leases {
            remaining(deadline)?;
            let reason = Sha256::digest(
                serde_json::to_vec(&(
                    "native-root-previous-boot-retirement.v1",
                    &current_root,
                    &previous.token,
                    lease,
                ))
                .map_err(error)?,
            )
            .into();
            leases
                .revoke(&lease.lease_id, lease.revision, reason)
                .map_err(error)?;
        }
        if !leases
            .read_unretired_for_principal(
                pin.agent_id.as_str(),
                codex_hepta_contracts::authority_lease::MAX_AUTHORITY_LEASES,
            )
            .map_err(error)?
            .leases
            .is_empty()
        {
            return Err(invalid(
                "original Agent retirement did not observe an empty active selection",
            ));
        }
        let expiry = previous
            .head
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1000)
            .ok_or_else(|| invalid("retained local writer expiry overflow"))?;
        while clock.now_unix_ms().map_err(error)? < expiry {
            remaining(deadline)?;
            std::thread::sleep(Duration::from_millis(20));
        }
        material.verify_unchanged().map_err(error)?;
        if issuer.retained_writer_state_for_root()? != canonical {
            return Err(invalid(
                "canonical owner changed during cold-open retirement",
            ));
        }
        let runtime_dir = Path::new(RUNTIME).join("owner");
        platform::private_dir(&runtime_dir, 0, 60001, 0o2710)?;
        platform::mount_consumer_state()?;
        let launch_observations =
            RootAuthorityDirectory::open(&config.state_dir.join("native-launch-observations"))
                .map_err(error)?;
        config.writer = Some(canonical.registration.clone());
        let initial = previous.head.last_current.clone();
        let recovery = recovery::PreparedRecovery {
            previous,
            writer: canonical.registration,
            proof: canonical.proof,
            retired,
            material,
            frontiers,
        };
        write_json(
            &Path::new(RUNTIME).join("owner-installed"),
            &serde_json::json!({"agent":pin.agent_id}),
        )?;
        Ok(Self {
            fleet,
            config,
            clock,
            leases: Arc::new(leases),
            issuer,
            initial,
            archive,
            checkpoint,
            scopes,
            recovery: Some(recovery),
            launcher,
            launch_observations,
        })
    }
}

#[cfg(test)]
#[path = "native_cpu_cold_open_tests.rs"]
mod tests;
