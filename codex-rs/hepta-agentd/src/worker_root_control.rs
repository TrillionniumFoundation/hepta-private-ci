//! Read the launcher's original Fleet registry without reopening or migrating it.

use crate::AgentdIdentity;
use crate::worker_root_registration::refused;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

pub(super) struct WorkerControlCustody {
    nodes: Vec<(PathBuf, File)>,
    record: AgentRecord,
}

impl WorkerControlCustody {
    pub(super) fn capture(registry: &FleetRegistry, identity: &AgentdIdentity) -> io::Result<Self> {
        if registry.layout().fleet_root().as_path() != identity.fleet_root {
            return Err(refused("Worker requires the original Fleet registry"));
        }
        let mut paths = BTreeSet::new();
        for path in [
            identity.fleet_root.as_path(),
            identity.layout.agent_root(),
            identity.layout.run_root(),
            identity.layout.releases_root(),
        ] {
            paths.extend(path.ancestors().map(ToOwned::to_owned));
        }
        paths.insert(identity.layout.agent_config().to_owned());
        for (parent, prefix) in [
            (identity.layout.run_root(), "lifecycle-"),
            (identity.layout.releases_root(), "release-state-"),
        ] {
            for entry in std::fs::read_dir(parent)? {
                let entry = entry?;
                if entry.file_name().as_encoded_bytes().starts_with(prefix.as_bytes()) {
                    paths.insert(entry.path());
                }
                if paths.len() > 4096 {
                    return Err(refused("original Fleet control history exceeds fixed bound"));
                }
            }
        }
        let mut nodes = Vec::new();
        for path in paths {
            if path.canonicalize()? != path {
                return Err(refused("Root Fleet control path alias refused"));
            }
            let meta = std::fs::symlink_metadata(&path)?;
            if meta.uid() != 0
                || meta.mode() & 0o022 != 0
                || (!meta.is_dir() && (!meta.is_file() || meta.nlink() != 1))
            {
                return Err(refused("Root-only Fleet control custody required"));
            }
            let flags = libc::O_NOFOLLOW
                | libc::O_CLOEXEC
                | libc::O_NONBLOCK
                | if meta.is_dir() { libc::O_DIRECTORY } else { 0 };
            let held = OpenOptions::new().read(true).custom_flags(flags).open(&path)?;
            let actual = held.metadata()?;
            if actual.dev() != meta.dev() || actual.ino() != meta.ino() {
                return Err(refused("Root Fleet control node changed while pinning"));
            }
            nodes.push((path, held));
        }
        let record = registry
            .load_agent_for_spawn(&identity.agent_id, identity.spawn_generation)
            .map_err(io::Error::other)?;
        if record.layout != identity.layout
            || record.manifest.workspace.as_path() != identity.workspace
            || record.manifest.resources != identity.resources
            || !matches!(record.lifecycle.lifecycle, AgentLifecycle::Starting | AgentLifecycle::Running)
        {
            return Err(refused("Worker requires the exact current Starting or Running spawn"));
        }
        let custody = Self { nodes, record };
        custody.verify(registry, identity)?;
        Ok(custody)
    }

    pub(super) fn generation(&self) -> u64 {
        self.record.lifecycle.generation
    }

    pub(super) fn verify(&self, registry: &FleetRegistry, identity: &AgentdIdentity) -> io::Result<()> {
        for (path, held) in &self.nodes {
            let actual = held.metadata()?;
            let current = std::fs::symlink_metadata(path)?;
            if current.uid() != 0
                || current.mode() & 0o022 != 0
                || current.dev() != actual.dev()
                || current.ino() != actual.ino()
                || current.mode() != actual.mode()
                || (!current.is_dir() && (!current.is_file() || current.nlink() != 1))
                || path.canonicalize()? != *path
            {
                return Err(refused("original Fleet control custody changed"));
            }
        }
        if registry
            .load_agent_for_spawn(&identity.agent_id, identity.spawn_generation)
            .map_err(io::Error::other)?
            != self.record
        {
            return Err(refused("original Fleet generation changed during Worker handoff"));
        }
        Ok(())
    }
}
