//! One stable Agent slot and a separate Root-owned Worker consumer frontier.
//! Fresh provisioning and runtime open are deliberately different operations.
//! A consumed slot is never refunded by Drop, a failed send, an unknown CAS,
//! or a fresh Child nonce. Administrative successor recovery is a later layer.

use super::PreparedHostAuthoritySession;
use crate::HostAuthorityServiceConfig;
use crate::HostConsumerFrontier;
use crate::worker_root_registration::WorkerRootRegistrationV1;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::HostConsumerFrontierResponseV1;
use codex_hepta_contracts::HostConsumerFrontierStatusV1;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_paths::HeptaFleetRoot;
use serde::Deserialize;
use serde::Serialize;
use std::collections::BTreeSet;
use std::io;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

const WORKER_DIRECTORY: &str = "worker-consumer-v1";
const SLOT_DIRECTORY: &str = "current-slot";
const FRONTIER_DIRECTORY: &str = "consumer-floor";
const SLOT_PURPOSE: &str = "runtime.infer_worker.current_slot.v1";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct DirectoryPins {
    original_authority: (u64, u64),
    worker: (u64, u64),
    current_slot: (u64, u64),
    consumer_floor: (u64, u64),
    original_checkpoint: (u64, u64),
    original_device: (u64, u64),
    original_notes: (u64, u64),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "phase", deny_unknown_fields)]
enum SlotPhase {
    Provisioned,
    Reserved { registration: WorkerRootRegistrationV1 },
    Serving { registration: WorkerRootRegistrationV1 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CurrentWorkerSlot {
    schema_version: u32,
    purpose: String,
    registered_agent_id: AgentId,
    owner_id: String,
    consumer_namespace: String,
    directories: DirectoryPins,
    initial_frontier: FinalUseFrontier,
    slot_sequence: u64,
    state: SlotPhase,
}

struct WorkerDirectories {
    original: Arc<RootAuthorityDirectory>,
    worker: Arc<RootAuthorityDirectory>,
    slot: Arc<RootAuthorityDirectory>,
    frontier: Arc<RootAuthorityDirectory>,
    checkpoint: Arc<RootAuthorityDirectory>,
    device: Arc<RootAuthorityDirectory>,
    notes: Arc<RootAuthorityDirectory>,
}

impl WorkerDirectories {
    fn open(config: &HostAuthorityServiceConfig, owner_id: &str, fresh: bool) -> io::Result<Self> {
        if config.signer_id != owner_id {
            return Err(refused("Worker floor owner must be the canonical original signer"));
        }
        let original = RootAuthorityDirectory::open(&config.state_dir).map_err(io::Error::other)?;
        let consumers = config.consumers.as_ref().ok_or_else(|| refused("original consumer registrations required for Worker floor isolation"))?;
        if consumers.device.owner_id != owner_id || consumers.notes.owner_id != owner_id {
            return Err(refused("original consumer owner differs from canonical signer"));
        }
        let checkpoint_path = config.checkpoint_state_dir.as_ref().ok_or_else(|| refused("original checkpoint registration required for Worker floor isolation"))?;
        let checkpoint = RootAuthorityDirectory::open(checkpoint_path).map_err(io::Error::other)?;
        let device = RootAuthorityDirectory::open(&consumers.device.state_dir).map_err(io::Error::other)?;
        let notes = RootAuthorityDirectory::open(&consumers.notes.state_dir).map_err(io::Error::other)?;
        let worker = if fresh {
            original.create_child_fresh(WORKER_DIRECTORY)
        } else {
            original.open_existing_child(WORKER_DIRECTORY)
        }.map_err(io::Error::other)?;
        let slot = if fresh {
            worker.create_child_fresh(SLOT_DIRECTORY)
        } else {
            worker.open_existing_child(SLOT_DIRECTORY)
        }.map_err(io::Error::other)?;
        let frontier = if fresh {
            worker.create_child_fresh(FRONTIER_DIRECTORY)
        } else {
            worker.open_existing_child(FRONTIER_DIRECTORY)
        }.map_err(io::Error::other)?;
        let result = Self { original, worker, slot, frontier, checkpoint, device, notes };
        result.pins()?;
        Ok(result)
    }

    fn pins(&self) -> io::Result<DirectoryPins> {
        let identity = |directory: &RootAuthorityDirectory| directory.descriptor_identity().map_err(io::Error::other);
        let pins = DirectoryPins {
            original_authority: identity(&self.original)?,
            worker: identity(&self.worker)?,
            current_slot: identity(&self.slot)?,
            consumer_floor: identity(&self.frontier)?,
            original_checkpoint: identity(&self.checkpoint)?,
            original_device: identity(&self.device)?,
            original_notes: identity(&self.notes)?,
        };
        let protected = [pins.original_authority, pins.original_checkpoint, pins.original_device, pins.original_notes];
        let worker = [pins.worker, pins.current_slot, pins.consumer_floor];
        if worker.into_iter().collect::<BTreeSet<_>>().len() != worker.len()
            || worker.iter().any(|entry| protected.contains(entry))
        {
            return Err(refused("Worker slot and floor must use independent actual directory inodes"));
        }
        Ok(pins)
    }
}

pub(super) fn stable_namespace(agent: &AgentId) -> io::Result<String> {
    crate::worker_root_registration::lanes_wire::stable_consumer_namespace(agent)
}

/// The public provisioner returns only success. It neither opens a local
/// Worker journal nor grants a signer, input bundle or production capability.
impl PreparedHostAuthoritySession {
    pub fn provision_worker_frontier_fresh(&self) -> io::Result<()> {
        let end = std::time::Instant::now() + std::time::Duration::from_millis(self.config.timeout_ms.min(5_000));
        let identity = self.registration.registered_identity.identity()?;
        let registry = FleetRegistry::open_existing(
            HeptaFleetRoot::parse(self.registration.registered_identity.fleet_root.clone()).map_err(io::Error::other)?,
        ).map_err(io::Error::other)?;
        let control = super::control::WorkerControlCustody::capture(&registry, &identity)?;
        let verify_original = || {
            crate::authority_host_runtime::verify_pinned_process(
                &self.registration, self.config.peer_uid, self.config.peer_gid, &self.owner_pidfd, end,
            )?;
            control.verify(&registry, &identity)
        };
        verify_original()?;
        self.service.with_worker_floor_fence(None, |view| {
            verify_original()?;
            let directories = WorkerDirectories::open(&self.config, &view.owner_id, true)?;
            let consumer = HostConsumerFrontier::initialize_fresh(
                Arc::clone(&directories.frontier),
                view.owner_id.clone(),
                &view.head,
                view.clock.clone(),
                view.expires_at_unix_ms,
            ).map_err(io::Error::other)?;
            let initial = consumer.frontier_for_handoff(&view.head).map_err(io::Error::other)?;
            let slot = CurrentWorkerSlot {
                schema_version: 1,
                purpose: SLOT_PURPOSE.into(),
                registered_agent_id: view.registered_agent_id.clone(),
                owner_id: view.owner_id.clone(),
                consumer_namespace: stable_namespace(&view.registered_agent_id)?,
                directories: directories.pins()?,
                initial_frontier: initial,
                slot_sequence: 0,
                state: SlotPhase::Provisioned,
            };
            let store = HostAuthorityFrontierStore::initialize(
                Arc::clone(&directories.slot), view.owner_id.clone(), slot.clone(),
            ).map_err(io::Error::other)?;
            if store.load(&view.owner_id).map_err(io::Error::other)? != slot
                || consumer.frontier_for_handoff(&view.head).map_err(io::Error::other)? != initial
            {
                return Err(refused("fresh Worker slot readback differs; preserve partial provisioning"));
            }
            verify_original()?;
            Ok(())
        })?;
        verify_original()
    }
}

/// Non-cloneable Root-owned original slot. A failed or dropped reservation is
/// deliberately still consumed on disk. No current API can reset it, choose a
/// nonce-derived namespace, or reopen it for another Child after a restart.
pub(super) struct ReservedWorkerFloor {
    directories: WorkerDirectories,
    current: HostAuthorityFrontierStore<CurrentWorkerSlot>,
    expected: CurrentWorkerSlot,
    consumer: HostConsumerFrontier,
    closed: AtomicBool,
}

impl ReservedWorkerFloor {
    pub(super) fn reserve(session: &PreparedHostAuthoritySession, registration: &WorkerRootRegistrationV1) -> io::Result<Self> {
        session.service.with_worker_floor_fence(Some(registration), |view| {
            let directories = WorkerDirectories::open(&session.config, &view.owner_id, false)?;
            let current = HostAuthorityFrontierStore::<CurrentWorkerSlot>::open(
                Arc::clone(&directories.slot), view.owner_id.clone(),
            ).map_err(io::Error::other)?;
            let prior = current.load(&view.owner_id).map_err(io::Error::other)?;
            if prior.schema_version != 1
                || prior.purpose != SLOT_PURPOSE
                || prior.registered_agent_id != registration.registered_agent_id
                || prior.owner_id != view.owner_id
                || prior.consumer_namespace != stable_namespace(&registration.registered_agent_id)?
                || prior.directories != directories.pins()?
                || prior.slot_sequence != 0
                || prior.state != SlotPhase::Provisioned
            {
                return Err(refused("Worker slot is not the exact unclaimed original provisioning; independent successor recovery required"));
            }
            let consumer = HostConsumerFrontier::open(
                Arc::clone(&directories.frontier), view.owner_id.clone(), view.clock.clone(), view.expires_at_unix_ms,
            ).map_err(io::Error::other)?;
            if consumer.frontier_for_handoff(&view.head).map_err(io::Error::other)? != prior.initial_frontier {
                return Err(refused("unclaimed Worker floor differs from its original genesis; no repair permitted"));
            }
            let mut next = prior.clone();
            next.slot_sequence = prior.slot_sequence.checked_add(1).ok_or_else(|| refused("Worker slot sequence overflow"))?;
            next.state = SlotPhase::Reserved { registration: registration.clone() };
            // Actual durable CAS decides concurrent claimants. If the outcome
            // is unknown, no object is returned and no compensating write runs.
            current.compare_and_set(&view.owner_id, &prior, &next).map_err(io::Error::other)?;
            Ok(Self { directories, current, expected: next, consumer, closed: AtomicBool::new(false) })
        })
    }

    pub(super) fn create_journal_binding_directory_fresh(&self) -> io::Result<Arc<RootAuthorityDirectory>> {
        self.check_current()?;
        if !matches!(&self.expected.state, SlotPhase::Reserved { .. }) {
            return Err(refused("Worker journal provisioning requires the actual reserved original slot"));
        }
        let directory = self.directories.worker.create_child_fresh("local-journal-custody-v1").map_err(io::Error::other)?;
        self.check_current()?;
        Ok(directory)
    }

    pub(super) fn check_journal_directory_is_distinct(
        &self,
        journal: &crate::worker_root_registration::journal_wire::WorkerJournalDirectoryPinV1,
        binding: &RootAuthorityDirectory,
    ) -> io::Result<()> {
        self.check_current()?;
        let original = self.directories.pins()?;
        let protected = [original.original_authority, original.worker, original.current_slot,
            original.consumer_floor, original.original_checkpoint, original.original_device, original.original_notes];
        let binding = binding.descriptor_identity().map_err(io::Error::other)?;
        let parent = (journal.parent_device, journal.parent_inode);
        let consumer = (journal.directory_device, journal.directory_inode);
        if protected.contains(&binding) || protected.contains(&consumer) || protected.contains(&parent)
            || binding == consumer || binding == parent || parent == consumer
        {
            return Err(refused("Worker journal, binding, parent and original independent floors must be distinct actual inodes"));
        }
        Ok(())
    }

    pub(super) fn namespace(&self) -> &str { &self.expected.consumer_namespace }
    pub(super) fn slot_sequence(&self) -> u64 { self.expected.slot_sequence }

    pub(super) fn frontier_for_handoff(&self, head: &FinalUseRevocations) -> io::Result<FinalUseFrontier> {
        self.check_current()?;
        self.consumer.frontier_for_handoff(head).map_err(io::Error::other)
    }

    /// Only the Root protocol owner invokes this after receiving the exact
    /// sealed-offer ACK from the original Child's actual kernel credentials.
    pub(super) fn confirm_after_child_ack(&mut self) -> io::Result<()> {
        self.check_current()?;
        let SlotPhase::Reserved { registration } = &self.expected.state else {
            self.fence_unknown();
            return Err(refused("Worker slot was already confirmed or abandoned"));
        };
        let mut next = self.expected.clone();
        next.state = SlotPhase::Serving { registration: registration.clone() };
        if let Err(error) = self.current.compare_and_set(&self.expected.owner_id, &self.expected, &next) {
            self.fence_unknown();
            return Err(io::Error::other(error));
        }
        self.expected = next;
        self.check_current()
    }

    pub(super) fn check_current(&self) -> io::Result<()> {
        if self.closed.load(Ordering::Acquire) {
            return Err(refused("Worker slot was fenced after uncertainty"));
        }
        let valid = self.directories.pins().is_ok_and(|pins| pins == self.expected.directories)
            && self.current.load(&self.expected.owner_id).is_ok_and(|value| value == self.expected);
        if !valid {
            self.fence_unknown();
            return Err(refused("Worker current slot or protected directory binding changed"));
        }
        Ok(())
    }

    pub(super) fn exchange(&self, bytes: &[u8], head: &FinalUseRevocations) -> io::Result<Vec<u8>> {
        self.check_current()?;
        if !matches!(&self.expected.state, SlotPhase::Serving { .. }) {
            return Err(refused("Worker floor cannot be consumed before exact handoff confirmation"));
        }
        let result = self.consumer.exchange(bytes, head).map_err(io::Error::other);
        let result = result.and_then(|bytes| {
            let response: HostConsumerFrontierResponseV1 = serde_json::from_slice(&bytes).map_err(io::Error::other)?;
            if matches!(response.status, HostConsumerFrontierStatusV1::Unknown) {
                self.fence_unknown();
                return Err(refused("Worker frontier outcome unknown; no refund or replay"));
            }
            self.check_current()?;
            Ok(bytes)
        });
        if result.is_err() { self.fence_unknown(); }
        result
    }

    pub(super) fn fence_unknown(&self) {
        self.closed.store(true, Ordering::Release);
    }
}
