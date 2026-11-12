//! A third real incarnation can be registered only after the actual post-A
//! publisher has exited and its two original writer clocks have expired.
//! No serialized process record can construct the retained wait/pidfd proofs.

use std::path::PathBuf;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_memory::CognitiveCheckpointHead;
use codex_hepta_memory::CognitiveCheckpointPhase;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;

use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use super::recovery::OriginalSuccessorAdministration;
use crate::HostAuthorityRegistration;
use crate::HostAuthorityServiceConfig;
use crate::HostSignedWriterAuthorizationV1;
use crate::ordinary_q24_cold_snapshot_tests::OriginalBusinessSnapshot;
use crate::ordinary_q24_process_child_tests::OriginalChild;

pub(super) struct OriginalColdRetirement {
    prior: HostAuthorityServiceConfig,
    previous: CognitiveCheckpointHead,
    proof: HostSignedWriterAuthorizationV1,
    files: Vec<PathBuf>,
    unchanged: OriginalBusinessSnapshot,
    not_before_unix_ms: u64,
}

impl OriginalColdRetirement {
    /// Observe actual immutable data without waiting or opening an old writer.
    /// The outer fixture can persist this phase before waiting for this time.
    pub(super) fn observe(original: &RetainedOrdinaryQ24Fixture) -> anyhow::Result<Self> {
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        original.source.require_dead()?;
        let resources = &original.plan.resources;
        let old = &resources.successor;
        let proof_path = resources
            .original
            .plan
            .protected
            .path()
            .join("post-a-writer-proof.json");
        let mut files = vec![
            old.service.clone(),
            old.registration.clone(),
            proof_path.clone(),
        ];
        let unchanged = OriginalBusinessSnapshot::capture(&files)?;
        let prior: HostAuthorityServiceConfig = serde_json::from_slice(
            &super::observer::read_private(&old.service, /*bound*/ 16 * 1024)?,
        )?;
        let registration: HostAuthorityRegistration = serde_json::from_slice(
            &super::observer::read_private(&old.registration, /*bound*/ 16 * 1024)?,
        )?;
        let proof: HostSignedWriterAuthorizationV1 = serde_json::from_slice(
            &super::observer::read_private(&proof_path, /*bound*/ 16 * 1024)?,
        )?;
        let writer = prior
            .writer
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("old writer absent"))?;
        let checkpoint = prior
            .checkpoint_state_dir
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("old checkpoint directory absent"))?;
        let actual = original.daemon.lifetime();
        anyhow::ensure!(
            prior.state_dir == resources.original.plan.root.authority
                && checkpoint == &prior.state_dir.join("checkpoint")
                && prior.peer_uid == 60001
                && prior.peer_gid == 60001
                && prior.timeout_ms == 500
                && prior.lifetime_ms == super::root::LIFETIME_MS
                && writer.registered_agent_id == old.identity.agent_id
                && writer.spawn_generation == old.identity.spawn_generation
                && registration.schema_version == 1
                && registration.registered_identity.identity()? == old.identity
                && registration.checkpoint_owner_agent_id == old.identity.agent_id
                && registration.peer_pid == actual.pid
                && registration.boot_id == actual.boot_id
                && registration.process_start_ticks == actual.start_ticks
                && proof == old.writer_proof,
            "actual post-A service, registration, proof or process differs"
        );
        unchanged.require_unchanged(&files)?;
        let record = format!(
            "frontier-v1-{}.json",
            Digest32::of_bytes(b"root-cognitive-checkpoint-v1")
        );
        files.extend([
            checkpoint.join(&record),
            checkpoint.join(format!("{record}.lock")),
        ]);
        // The store may open its lock O_RDWR; a missing original lock must
        // fail before that operation could create it.
        let unchanged = OriginalBusinessSnapshot::capture(&files)?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            RootAuthorityDirectory::open(checkpoint)?,
            "root-cognitive-checkpoint-v1".into(),
        )?;
        let previous = store.load("root-cognitive-checkpoint-v1")?;
        anyhow::ensure!(
            previous.phase == CognitiveCheckpointPhase::Current
                && previous.proposal.is_none()
                && previous.owner_agent_id == old.identity.agent_id
                && previous.peer_lifetime.uid == prior.peer_uid
                && previous.peer_lifetime.pid == actual.pid
                && previous.peer_lifetime.boot_id == actual.boot_id
                && previous.peer_lifetime.process_start_ticks == actual.start_ticks
                && previous.publisher_epoch == registration.publisher_epoch
                && previous.writer_binding.lease_id == writer.local_lease_id
                && previous.writer_binding.generation == writer.local_lease_generation
                && previous.writer_binding.owner_epoch == writer.owner_epoch,
            "protected CURRENT does not belong to the actual exited post-A daemon"
        );
        let not_before_unix_ms = previous
            .writer_binding
            .expires_at_unix_seconds
            .checked_mul(1_000)
            .ok_or_else(|| anyhow::anyhow!("original cold expiry overflow"))?
            .max(writer.authority_lease.expires_at_unix_ms);
        anyhow::ensure!(
            store.load("root-cognitive-checkpoint-v1")? == previous,
            "old protected CURRENT changed while observing retirement"
        );
        unchanged.require_unchanged(&files)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        Ok(Self {
            prior,
            previous,
            proof,
            files,
            unchanged,
            not_before_unix_ms,
        })
    }

    pub(super) fn not_before_unix_ms(&self) -> u64 {
        self.not_before_unix_ms
    }

    pub(super) fn prepare_after_actual_expiry(
        self,
        original: &RetainedOrdinaryQ24Fixture,
        end: Instant,
    ) -> anyhow::Result<OriginalColdAdministration> {
        require_end(end)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        original.source.require_dead()?;
        self.unchanged.require_unchanged(&self.files)?;
        anyhow::ensure!(
            crate::authbus_ingress::now_ms()? >= self.not_before_unix_ms,
            "actual old writer has not expired; cold cannot renew or skip it"
        );
        let checkpoint = self
            .prior
            .checkpoint_state_dir
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original checkpoint absent"))?;
        let store = HostAuthorityFrontierStore::<CognitiveCheckpointHead>::open(
            RootAuthorityDirectory::open(checkpoint)?,
            "root-cognitive-checkpoint-v1".into(),
        )?;
        anyhow::ensure!(
            store.load("root-cognitive-checkpoint-v1")? == self.previous,
            "old CURRENT changed before actual cold preparation"
        );
        let resources = &original.plan.resources;
        let old = &resources.successor;
        let registry =
            FleetRegistry::open_existing(HeptaFleetRoot::parse(&old.identity.fleet_root)?)?;
        let mut state = registry.load_agent(&old.identity.agent_id)?.lifecycle;
        anyhow::ensure!(
            state.lifecycle == AgentLifecycle::Running
                && state.generation
                    == old
                        .identity
                        .spawn_generation
                        .checked_add(1)
                        .ok_or_else(|| anyhow::anyhow!("old spawn overflow"))?,
            "actual post-A Running incarnation changed"
        );
        for next in [
            AgentLifecycle::Draining,
            AgentLifecycle::Stopped,
            AgentLifecycle::Starting,
        ] {
            state =
                registry.compare_and_transition(&old.identity.agent_id, state.generation, next)?;
        }
        let mut registered = old.registered.clone();
        registered.spawn_generation = state.generation;
        let identity = registered.identity()?;
        let predecessor = self
            .prior
            .writer
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("original cold predecessor absent"))?;
        let mut writer = predecessor.clone();
        writer.spawn_generation = state.generation;
        writer.owner_epoch = writer
            .owner_epoch
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original cold owner epoch exhausted"))?;
        writer.local_lease_generation = writer
            .local_lease_generation
            .checked_add(1)
            .ok_or_else(|| anyhow::anyhow!("original cold lease generation exhausted"))?;
        writer.authority_lease.lease_id =
            format!("ordinary-cold-writer-spawn-{}", state.generation);
        writer.authority_lease.revision = 1;
        let now = crate::authbus_ingress::now_ms()?;
        writer.authority_lease.issued_at_unix_ms = now;
        writer.authority_lease.expires_at_unix_ms = now
            .checked_add(super::root::LIFETIME_MS)
            .ok_or_else(|| anyhow::anyhow!("new cold writer expiry overflow"))?;
        let directory = resources
            .original
            .plan
            .protected
            .path()
            .join("cold-original-recipient");
        std::fs::create_dir(&directory)?;
        super::super::owned_mode(&directory, 0, 0, 0o700)?;
        let sockets = resources.original.plan.runtime.path().join("cold-root");
        std::fs::create_dir(&sockets)?;
        super::super::owned_mode(&sockets, 0, 60001, 0o2710)?;
        let mut config = self.prior.clone();
        config.writer = Some(writer);
        config.sockets = crate::HostAuthoritySocketPaths {
            observation: sockets.join("obs.sock"),
            issuer: sockets.join("issuer.sock"),
            checkpoint: sockets.join("checkpoint.sock"),
            device_frontier: Some(sockets.join("device.sock")),
            notes_frontier: Some(sockets.join("notes.sock")),
        };
        let service = directory.join("service.json");
        super::root::write_json(&service, &config)?;
        let writer_proof =
            crate::rotate_host_writer_authorization(&service, predecessor, &self.proof)?;
        super::root::write_json(&directory.join("writer-proof.json"), &writer_proof)?;
        anyhow::ensure!(
            store.load("root-cognitive-checkpoint-v1")? == self.previous,
            "only the real recovered-material process may adopt old CURRENT"
        );
        self.unchanged.require_unchanged(&self.files)?;
        original.daemon.require_dead()?;
        original.root.require_dead()?;
        require_end(end)?;
        Ok(OriginalColdAdministration {
            directory,
            successor: OriginalSuccessorAdministration {
                registered,
                identity,
                service,
                registration: resources
                    .original
                    .plan
                    .protected
                    .path()
                    .join("cold-original-recipient/spawn.json"),
                writer_proof,
                previous_head: self.previous,
            },
            end,
        })
    }
}

pub(super) struct OriginalColdAdministration {
    pub(super) directory: PathBuf,
    pub(super) successor: OriginalSuccessorAdministration,
    pub(super) end: Instant,
}

impl OriginalColdAdministration {
    pub(super) fn register_original_child(
        &self,
        original: &RetainedOrdinaryQ24Fixture,
        daemon: &OriginalChild,
    ) -> anyhow::Result<()> {
        require_end(self.end)?;
        original.daemon.require_distinct_live(daemon)?;
        original.root.require_dead()?;
        original
            .plan
            .resources
            .original
            .daemon
            .require_distinct_live(daemon)?;
        crate::authority_host_runtime::verify_process_credentials(
            daemon.lifetime().pid,
            60001,
            60001,
        )?;
        super::root::write_json(
            &self.successor.registration,
            &HostAuthorityRegistration {
                schema_version: 1,
                peer_pid: daemon.lifetime().pid,
                boot_id: daemon.lifetime().boot_id.clone(),
                process_start_ticks: daemon.lifetime().start_ticks,
                registered_identity: self.successor.registered.clone(),
                checkpoint_owner_agent_id: self.successor.identity.agent_id.clone(),
                publisher_epoch: self
                    .successor
                    .previous_head
                    .publisher_epoch
                    .checked_add(1)
                    .ok_or_else(|| anyhow::anyhow!("original cold publisher epoch exhausted"))?,
            },
        )?;
        original.daemon.require_distinct_live(daemon)?;
        original.root.require_dead()?;
        require_end(self.end)
    }
}

fn require_end(end: Instant) -> anyhow::Result<()> {
    anyhow::ensure!(Instant::now() < end, "original cold phase deadline");
    Ok(())
}
