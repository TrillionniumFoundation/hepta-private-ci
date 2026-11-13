//! Administrative preparation for the next actual process incarnation. Only
//! the production recovered-material command may install/adopt the old cut.

use std::fs::File;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_paths::HeptaFleetRoot;

use super::RetainedOriginalAPhase;
use super::observer::read_private;
use super::root::write_json;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::HostSignedWriterAuthorizationV1;
use crate::ordinary_q24_process_child_tests::OriginalChild;

pub(super) struct OriginalSuccessorAdministration {
    pub(super) registered: crate::HostAuthorityRegisteredIdentity,
    pub(super) identity: crate::AgentdIdentity,
    pub(super) service: PathBuf,
    pub(super) registration: PathBuf,
    pub(super) writer_proof: HostSignedWriterAuthorizationV1,
    pub(super) previous_head: CognitiveCheckpointHead,
}

impl OriginalSuccessorAdministration {
    pub(super) fn prepare(retained: &RetainedOriginalAPhase, end: Instant) -> anyhow::Result<Self> {
        retained.daemon.require_dead()?;
        retained.root.require_dead()?;
        retained.observer.require_dead()?;
        anyhow::ensure!(
            Instant::now() < end,
            "original recovery preparation deadline"
        );
        let plan = &retained.plan;
        let prior: HostAuthorityServiceConfig =
            serde_json::from_slice(&read_private(&plan.root.service, 16 * 1024)?)?;
        let old_registration: HostAuthorityRegistration =
            serde_json::from_slice(&read_private(&plan.root.registration, 16 * 1024)?)?;
        let proof: HostSignedWriterAuthorizationV1 =
            serde_json::from_slice(&read_private(&plan.root.writer_proof, 16 * 1024)?)?;
        let predecessor = prior.writer.as_ref().ok_or_else(|| {
            anyhow::anyhow!("original registered writer required; no fresh recovery fallback")
        })?;
        let checkpoint_path = prior.checkpoint_state_dir.as_ref().ok_or_else(|| {
            anyhow::anyhow!("original protected checkpoint path must already be fixed")
        })?;
        anyhow::ensure!(
            prior.state_dir == plan.root.authority
                && checkpoint_path == &prior.state_dir.join("checkpoint")
                && predecessor.registered_agent_id == plan.identity.agent_id
                && predecessor.spawn_generation == plan.identity.spawn_generation,
            "original Root registration changed"
        );
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            RootAuthorityDirectory::open(checkpoint_path)?,
            "root-cognitive-checkpoint-v1".into(),
        )?;
        let previous_head = store.load("root-cognitive-checkpoint-v1")?;
        let old = retained.daemon.lifetime();
        anyhow::ensure!(
            previous_head.phase == CognitiveCheckpointPhase::Current
                && previous_head.proposal.is_none()
                && previous_head.owner_agent_id == plan.identity.agent_id
                && previous_head.peer_lifetime.uid == 60001
                && previous_head.peer_lifetime.pid == old.pid
                && previous_head.peer_lifetime.boot_id == old.boot_id
                && previous_head.peer_lifetime.process_start_ticks == old.start_ticks
                && previous_head.publisher_epoch == old_registration.publisher_epoch
                && previous_head.writer_binding.lease_id == predecessor.local_lease_id
                && previous_head.writer_binding.generation == predecessor.local_lease_generation
                && previous_head.writer_binding.owner_epoch == predecessor.owner_epoch,
            "existing protected Current differs from the actual exited A"
        );
        let expiry = previous_head
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1_000)
            .ok_or_else(|| anyhow::anyhow!("original local expiry overflow"))?
            .max(predecessor.authority_lease.expires_at_unix_ms);
        loop {
            retained.daemon.require_dead()?;
            retained.root.require_dead()?;
            anyhow::ensure!(Instant::now() < end, "original writer retirement deadline");
            if crate::authbus_ingress::now_ms()? >= expiry {
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        pretty_assertions::assert_eq!(store.load("root-cognitive-checkpoint-v1")?, previous_head);
        // This is only a read of existing administrative data. No old writer,
        // local DB or protected checkpoint publisher has been reopened.
        drop(store);
        let registry =
            FleetRegistry::open_existing(HeptaFleetRoot::parse(plan.identity.fleet_root.clone())?)?;
        let mut state = registry.load_agent(&plan.identity.agent_id)?.lifecycle;
        anyhow::ensure!(
            state.lifecycle == AgentLifecycle::Running
                && state.generation
                    == plan
                        .identity
                        .spawn_generation
                        .checked_add(1)
                        .ok_or_else(|| anyhow::anyhow!("original spawn overflow"))?,
            "actual original Running generation changed before retirement"
        );
        for next in [
            AgentLifecycle::Draining,
            AgentLifecycle::Stopped,
            AgentLifecycle::Starting,
        ] {
            state =
                registry.compare_and_transition(&plan.identity.agent_id, state.generation, next)?;
        }
        let mut registered = plan.registered.clone();
        registered.spawn_generation = state.generation;
        let identity = registered.identity()?;
        let now = crate::authbus_ingress::now_ms()?;
        let mut writer = predecessor.clone();
        writer.spawn_generation = state.generation;
        writer.owner_epoch = writer
            .owner_epoch
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original owner epoch exhausted"))?;
        writer.local_lease_generation = writer
            .local_lease_generation
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original local lease generation exhausted"))?;
        writer.authority_lease.lease_id = format!("ordinary-writer-spawn-{}", state.generation);
        writer.authority_lease.revision = 1;
        writer.authority_lease.issued_at_unix_ms = now;
        writer.authority_lease.expires_at_unix_ms = now
            .checked_add(super::root::LIFETIME_MS)
            .ok_or_else(|| anyhow::anyhow!("successor expiry overflow"))?;
        let runtime = plan.runtime.path().join("post-a-root");
        std::fs::create_dir(&runtime)?;
        super::super::owned_mode(&runtime, 0, 60001, 0o2710)?;
        let mut config = prior.clone();
        config.writer = Some(writer);
        config.sockets = crate::HostAuthoritySocketPaths {
            observation: runtime.join("obs.sock"),
            issuer: runtime.join("issuer.sock"),
            checkpoint: runtime.join("checkpoint.sock"),
            device_frontier: Some(runtime.join("device.sock")),
            notes_frontier: Some(runtime.join("notes.sock")),
        };
        let service = plan.protected.path().join("post-a-service.json");
        write_json(&service, &config)?;
        let writer_proof = crate::rotate_host_writer_authorization(&service, predecessor, &proof)?;
        write_json(
            &plan.protected.path().join("post-a-writer-proof.json"),
            &writer_proof,
        )?;
        anyhow::ensure!(
            Instant::now() < end,
            "original recovery preparation deadline"
        );
        Ok(Self {
            registered,
            identity,
            service,
            registration: plan.protected.path().join("post-a-spawn.json"),
            writer_proof,
            previous_head,
        })
    }

    pub(super) fn register_live_child(
        &self,
        original: &RetainedOriginalAPhase,
        daemon: &OriginalChild,
    ) -> anyhow::Result<()> {
        original.daemon.require_distinct_live(daemon)?;
        original.root.require_dead()?;
        crate::authority_host_runtime::verify_process_credentials(
            daemon.lifetime().pid,
            60001,
            60001,
        )?;
        write_json(
            &self.registration,
            &HostAuthorityRegistration {
                schema_version: 1,
                peer_pid: daemon.lifetime().pid,
                boot_id: daemon.lifetime().boot_id.clone(),
                process_start_ticks: daemon.lifetime().start_ticks,
                registered_identity: self.registered.clone(),
                checkpoint_owner_agent_id: self.identity.agent_id.clone(),
                publisher_epoch: self
                    .previous_head
                    .publisher_epoch
                    .checked_add(1)
                    .ok_or_else(|| anyhow::anyhow!("original publisher epoch exhausted"))?,
            },
        )
    }
}

pub(super) fn remove_retired_control_nodes(
    original: &RetainedOriginalAPhase,
) -> anyhow::Result<()> {
    original.daemon.require_dead()?;
    original.root.require_dead()?;
    for path in [
        &original.plan.identity.control_socket,
        &original.plan.identity.app_server_socket,
    ] {
        remove_original_socket_node(path)?;
    }
    original.daemon.require_dead()?;
    original.root.require_dead()
}

fn remove_original_socket_node(path: &Path) -> anyhow::Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("original socket parent"))?;
    let directory = std::fs::symlink_metadata(parent)?;
    let node = std::fs::symlink_metadata(path)?;
    anyhow::ensure!(
        directory.is_dir()
            && directory.uid() == 0
            && directory.mode() & 0o022 == 0
            && node.file_type().is_socket()
            && node.uid() == 60001
            && node.gid() == 60001
            && node.mode() & 0o7777 == 0o600
            && node.nlink() == 1,
        "retired socket no longer has its original protected custody"
    );
    let repeated = std::fs::symlink_metadata(path)?;
    anyhow::ensure!(
        (node.dev(), node.ino(), node.mode(), node.uid(), node.gid())
            == (
                repeated.dev(),
                repeated.ino(),
                repeated.mode(),
                repeated.uid(),
                repeated.gid()
            ),
        "retired socket node changed"
    );
    std::fs::remove_file(path)?;
    File::open(parent)?.sync_all()?;
    Ok(())
}
