//! Open-only fixed Device/Notes consumer slots; no peer owner selector.
use super::*;
use crate::HostAuthorityConsumersConfig;
use crate::HostConsumerFrontier;
use codex_hepta_contracts::RootAuthorityDirectory;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

pub(super) struct RegisteredConsumers {
    pub(super) device: HostConsumerFrontier,
    pub(super) notes: HostConsumerFrontier,
}

impl RegisteredConsumers {
    pub(super) fn open(
        state: &Path,
        config: &HostAuthorityConsumersConfig,
        signer_id: &str,
        clock: Arc<HostAuthorityClock>,
        expires_at_unix_ms: u64,
    ) -> io::Result<Self> {
        if config.device.owner_id != signer_id
            || config.notes.owner_id != signer_id
            || [&config.device, &config.notes].iter().any(|slot| {
                slot.owner_id.is_empty()
                    || !slot.state_dir.starts_with(state)
                    || slot.state_dir == state
            })
        {
            return Err(io::Error::other(
                "consumer owner must match the canonical signer",
            ));
        }
        let device_root =
            RootAuthorityDirectory::open(&config.device.state_dir).map_err(io::Error::other)?;
        let notes_root =
            RootAuthorityDirectory::open(&config.notes.state_dir).map_err(io::Error::other)?;
        let device = std::fs::metadata(&config.device.state_dir)?;
        let notes = std::fs::metadata(&config.notes.state_dir)?;
        if (device.dev(), device.ino()) == (notes.dev(), notes.ino()) {
            return Err(io::Error::other(
                "distinct protected consumer directories required",
            ));
        }
        Ok(Self {
            device: HostConsumerFrontier::open(
                device_root,
                config.device.owner_id.clone(),
                clock.clone(),
                expires_at_unix_ms,
            )
            .map_err(io::Error::other)?,
            notes: HostConsumerFrontier::open(
                notes_root,
                config.notes.owner_id.clone(),
                clock,
                expires_at_unix_ms,
            )
            .map_err(io::Error::other)?,
        })
    }
}
