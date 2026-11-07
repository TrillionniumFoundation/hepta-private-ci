//! Root retains a durable binding to one empty Worker-owned directory. This
//! record cannot initialize a FinalUse journal or issue a grant by itself.

use super::floor::ReservedWorkerFloor;
use crate::worker_root_registration::WorkerRootRegistrationV1;
use crate::worker_root_registration::journal_path::WorkerJournalDirectory;
use crate::worker_root_registration::journal_wire::WORKER_ROOT_JOURNAL_V1;
use crate::worker_root_registration::journal_wire::WorkerJournalDirectoryPinV1;
use crate::worker_root_registration::refused;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalBinding {
    schema_version: u32,
    purpose: String,
    owner_id: String,
    consumer_namespace: String,
    registration: WorkerRootRegistrationV1,
    directory: WorkerJournalDirectoryPinV1,
    confirmed_after_original_child_ack: bool,
}

pub(super) struct RootWorkerJournal {
    directory: WorkerJournalDirectory,
    store: HostAuthorityFrontierStore<JournalBinding>,
    expected: JournalBinding,
    fenced: AtomicBool,
}

impl RootWorkerJournal {
    pub(super) fn create_fresh(
        floor: &ReservedWorkerFloor,
        registration: &WorkerRootRegistrationV1,
        owner_id: &str,
        initial_frontier: FinalUseFrontier,
        parent: &Path,
    ) -> io::Result<Self> {
        floor.check_current()?;
        let binding_directory = floor.create_journal_binding_directory_fresh()?;
        let directory = WorkerJournalDirectory::create_root_fresh(
            parent,
            registration,
            floor.slot_sequence(),
            initial_frontier,
        )?;
        floor.check_journal_directory_is_distinct(directory.observation(), &binding_directory)?;
        let expected = JournalBinding {
            schema_version: 1,
            purpose: WORKER_ROOT_JOURNAL_V1.into(),
            owner_id: owner_id.into(),
            consumer_namespace: floor.namespace().into(),
            registration: registration.clone(),
            directory: directory.observation().clone(),
            confirmed_after_original_child_ack: false,
        };
        let store = HostAuthorityFrontierStore::initialize(
            binding_directory,
            owner_id.to_owned(),
            expected.clone(),
        )
        .map_err(io::Error::other)?;
        let value = Self {
            directory,
            store,
            expected,
            fenced: AtomicBool::new(false),
        };
        value.check()?;
        floor.check_current()?;
        Ok(value)
    }

    pub(super) fn observation(&self) -> &WorkerJournalDirectoryPinV1 {
        self.directory.observation()
    }

    pub(super) fn confirm_after_original_child_ack(&mut self) -> io::Result<()> {
        self.check()?;
        if self.expected.confirmed_after_original_child_ack {
            self.fence();
            return Err(refused("Worker journal offer was already consumed"));
        }
        let mut next = self.expected.clone();
        next.confirmed_after_original_child_ack = true;
        if let Err(error) =
            self.store
                .compare_and_set(&self.expected.owner_id, &self.expected, &next)
        {
            self.fence();
            return Err(io::Error::other(error));
        }
        self.expected = next;
        self.check()
    }

    pub(super) fn check(&self) -> io::Result<()> {
        if self.fenced.load(Ordering::Acquire) {
            return Err(refused("Worker journal binding is permanently fenced"));
        }
        let result = (|| {
            self.directory.check()?;
            if self
                .store
                .load(&self.expected.owner_id)
                .map_err(io::Error::other)?
                != self.expected
            {
                return Err(refused("Worker journal original Root record changed"));
            }
            Ok(())
        })();
        if result.is_err() {
            self.fence();
        }
        result
    }

    fn fence(&self) {
        self.fenced.store(true, Ordering::Release);
    }
}

impl Drop for RootWorkerJournal {
    fn drop(&mut self) {
        self.fence();
    }
}
