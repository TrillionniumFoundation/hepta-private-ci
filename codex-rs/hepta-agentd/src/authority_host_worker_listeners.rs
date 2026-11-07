//! Root-only fixed Worker rendezvous names; no peer-selected lane or path.

use crate::worker_root_registration::WorkerRootRegistrationV1;
use crate::worker_root_registration::lanes_wire::WorkerRootLanePathsV1;
use crate::worker_root_registration::lanes_wire::lane_paths;
use crate::worker_root_registration::refused;
use std::ffi::CString;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::path::PathBuf;

#[derive(Clone, Copy)]
pub(super) enum WorkerLane {
    Observation,
    OriginalWriterProof,
    ConsumerFrontier,
}

pub(super) struct BoundWorkerLanes {
    pub(super) paths: WorkerRootLanePathsV1,
    pub(super) listeners: Vec<(WorkerLane, UnixListener)>,
    nodes: Vec<(PathBuf, u64, u64)>,
    directory: (PathBuf, u64, u64),
}

impl Drop for BoundWorkerLanes {
    fn drop(&mut self) {
        // Only exact Root-owned inodes created by this owner are removed.
        // Persistent slot/frontier state is deliberately never a cleanup target.
        self.listeners.clear();
        for (path, dev, ino) in &self.nodes {
            if std::fs::symlink_metadata(path)
                .is_ok_and(|value| value.uid() == 0 && value.dev() == *dev && value.ino() == *ino)
            {
                let _ = std::fs::remove_file(path);
            }
        }
        let (path, dev, ino) = &self.directory;
        if std::fs::symlink_metadata(path).is_ok_and(|value| {
            value.is_dir() && value.uid() == 0 && value.dev() == *dev && value.ino() == *ino
        }) {
            let _ = std::fs::remove_dir(path);
        }
    }
}

impl BoundWorkerLanes {
    pub(super) fn bind(registration: &WorkerRootRegistrationV1, slot: u64) -> io::Result<Self> {
        // SAFETY: only this process's actual kernel credentials are read.
        if unsafe { libc::getuid() } != 0 || unsafe { libc::geteuid() } != 0 {
            return Err(refused("Worker listener producer must be actual Root"));
        }
        let base = Path::new("/run/hepta-worker-v1");
        let run = std::fs::symlink_metadata("/run")?;
        if !run.is_dir()
            || run.uid() != 0
            || run.mode() & 0o022 != 0
            || Path::new("/run").canonicalize()? != Path::new("/run")
        {
            return Err(refused("Worker runtime requires Root-owned /run custody"));
        }
        match std::fs::DirBuilder::new().mode(0o711).create(base) {
            Ok(()) => std::fs::set_permissions(base, std::fs::Permissions::from_mode(0o711))?,
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error),
        }
        let base_metadata = std::fs::symlink_metadata(base)?;
        if !base_metadata.is_dir()
            || base_metadata.uid() != 0
            || base_metadata.mode() & 0o7777 != 0o711
            || base.canonicalize()? != base
        {
            return Err(refused(
                "existing Worker runtime parent is not the exact protected directory",
            ));
        }
        let paths = lane_paths(registration, slot)?;
        let parent = paths
            .observation
            .parent()
            .ok_or_else(|| refused("Worker runtime parent absent"))?;
        std::fs::DirBuilder::new().mode(0o700).create(parent)?;
        let metadata = std::fs::symlink_metadata(parent)?;
        let mut bound = Self {
            paths: paths.clone(),
            listeners: Vec::new(),
            nodes: Vec::new(),
            directory: (parent.to_owned(), metadata.dev(), metadata.ino()),
        };
        let path = CString::new(parent.as_os_str().as_encoded_bytes()).map_err(io::Error::other)?;
        // SAFETY: the new pathname is beneath the checked, Root-only parent;
        // it is this owner's exact newly created directory, never a peer path.
        if unsafe { libc::chown(path.as_ptr(), 0, registration.worker.gid) } != 0 {
            return Err(io::Error::last_os_error());
        }
        std::fs::set_permissions(parent, std::fs::Permissions::from_mode(0o2710))?;
        crate::authority_host_runtime::validate_lane_paths(
            &[&paths.observation, &paths.issuer, &paths.consumer_frontier],
            registration.worker.gid,
        )?;
        for (lane, path) in [
            (WorkerLane::Observation, &paths.observation),
            (WorkerLane::OriginalWriterProof, &paths.issuer),
            (WorkerLane::ConsumerFrontier, &paths.consumer_frontier),
        ] {
            if path.as_os_str().as_encoded_bytes().len() >= 108 {
                return Err(refused("Worker runtime pathname exceeds Linux sun_path"));
            }
            let listener = UnixListener::bind(path)?;
            let metadata = std::fs::symlink_metadata(path)?;
            bound
                .nodes
                .push((path.clone(), metadata.dev(), metadata.ino()));
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o660))?;
            let metadata = std::fs::symlink_metadata(path)?;
            if metadata.uid() != 0
                || metadata.gid() != registration.worker.gid
                || metadata.mode() & 0o7777 != 0o660
            {
                return Err(refused(
                    "Worker socket ownership differs from the actual Child group",
                ));
            }
            listener.set_nonblocking(true)?;
            bound.listeners.push((lane, listener));
        }
        Ok(bound)
    }
}
