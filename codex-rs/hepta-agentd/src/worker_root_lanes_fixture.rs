//! Extend the original actual-Root fixture through its real fresh DB factory.
//! The existing registration fixture and its seven assertions stay unchanged.

use super::*;
use crate::HostAuthorityConsumerConfig;
use crate::HostAuthorityConsumersConfig;
use crate::HostAuthoritySocketPaths;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

pub(super) struct LaneFixture {
    pub(super) original: Fixture,
    _original_runtime: tempfile::TempDir,
}

impl LaneFixture {
    pub(super) fn open() -> Self {
        let mut original = Fixture::open();
        drop(original.session.take());
        let runtime = tempfile::Builder::new()
            .prefix("hepta-worker-lanes-original-")
            .tempdir_in("/run")
            .unwrap();
        std::os::unix::fs::chown(runtime.path(), Some(0), Some(original.config.peer_gid)).unwrap();
        std::fs::set_permissions(runtime.path(), std::fs::Permissions::from_mode(0o2710)).unwrap();
        let mode = std::fs::symlink_metadata(runtime.path()).unwrap();
        assert_eq!(
            (mode.uid(), mode.gid(), mode.mode() & 0o7777),
            (0, original.config.peer_gid, 0o2710)
        );
        original.config.checkpoint_state_dir = Some(original.config.state_dir.join("checkpoint"));
        original.config.consumers = Some(HostAuthorityConsumersConfig {
            device: HostAuthorityConsumerConfig {
                state_dir: original.config.state_dir.join("device-consumer"),
                owner_id: original.config.signer_id.clone(),
            },
            notes: HostAuthorityConsumerConfig {
                state_dir: original.config.state_dir.join("notes-consumer"),
                owner_id: original.config.signer_id.clone(),
            },
        });
        original.config.sockets = HostAuthoritySocketPaths {
            observation: runtime.path().join("observation"),
            issuer: runtime.path().join("issuer"),
            checkpoint: runtime.path().join("checkpoint"),
            device_frontier: Some(runtime.path().join("device")),
            notes_frontier: Some(runtime.path().join("notes")),
        };
        original.config_path = original
            .config_path
            .parent()
            .unwrap()
            .join("worker-lanes-service.json");
        write_new_root_json(&original.config_path, &original.config);
        let executor = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        original.session = Some(
            executor
                .block_on(PreparedHostAuthoritySession::prepare_fresh_from_registered(
                    &original.config_path,
                    &original.registration_path,
                    original.daemon.pidfd.try_clone().unwrap(),
                ))
                .unwrap(),
        );
        // The actual SQLite pool was awaited closed by FreshHostCognitiveState;
        // this runtime owns no subsequent Root lane or injected clock.
        executor.shutdown_timeout(Duration::from_secs(1));
        Self {
            original,
            _original_runtime: runtime,
        }
    }

    pub(super) fn reopen_original(&mut self) {
        drop(self.original.session.take());
        self.original.session = Some(
            PreparedHostAuthoritySession::open(
                &self.original.config_path,
                &self.original.registration_path,
                self.original.daemon.pidfd.try_clone().unwrap(),
            )
            .unwrap(),
        );
    }

    pub(super) fn worker_path(&self) -> std::path::PathBuf {
        self.original.config.state_dir.join("worker-consumer-v1")
    }
}

fn write_new_root_json(path: &Path, value: &impl serde::Serialize) {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(path)
        .unwrap();
    serde_json::to_writer(&mut file, value).unwrap();
    file.flush().unwrap();
    file.sync_all().unwrap();
    File::open(path.parent().unwrap())
        .unwrap()
        .sync_all()
        .unwrap();
}
