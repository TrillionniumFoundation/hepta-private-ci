//! Fixed trusted-launch choreography; no authority claims or runtime commands.

use codex_hepta_memory::CognitiveCheckpointPeerLifetime;
use codex_hepta_memory::NotesTargetIdentity;
use serde::Deserialize;
use serde::Serialize;
use std::io;

pub const ROOT_NOTES_LAUNCH_FRAME_BOUND: usize = 16 * 1024;
pub const ROOT_NOTES_PREPARATION_NS: u64 = 5_000_000_000;
pub const ROOT_NOTES_TOTAL_PREPARATION_NS: u64 = 300_000_000_000;

/// One u32-big-endian length followed by this JSON. SCM_RIGHTS belongs to the
/// frame's FIRST byte. Every frame rejects unknown fields and extra descriptors.
/// All variants share the Root-selected launch nonce; no path, UID selection,
/// key, cut, proof or grant is accepted from a Host request.
#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
pub enum RootNotesLaunchFrame {
    /// Root -> Host, zero FDs. Root starts its original five-second budget
    /// before sending this frame. `end_boottime_ns` bounds Phase A through
    /// OriginalBootstrap. The separate original Parent preparation end includes
    /// recovery/registered-ready/release and is fixed at startup, never renewed.
    PrepareSessionV1 {
        schema_version: u32,
        launch_nonce: String,
        end_boottime_ns: u64,
        preparation_end_boottime_ns: u64,
    },
    /// Host -> Root, exactly [Session FD0 offer, Session FD4 planned startup].
    SessionChannelsV1 {
        schema_version: u32,
        launch_nonce: String,
    },
    /// Root -> Host, exactly one pre-held actual Session pidfd. The fixed
    /// Session/App role is UID1000; Root supplies its original Host pidfd as
    /// Session FD3 separately, never from a claimed Host PID on this wire.
    SessionSpawnedV1 {
        schema_version: u32,
        launch_nonce: String,
        session: CognitiveCheckpointPeerLifetime,
    },
    /// Host -> Root, zero FDs, from the original Session allocator only.
    TargetReservedV1 {
        schema_version: u32,
        launch_nonce: String,
        target: NotesTargetIdentity,
    },
    /// Root -> Host, exactly [original sealed bootstrap File, Root pidfd].
    /// The original DTO is not re-encoded in this frame. The second descriptor
    /// must match the Root lifetime already pinned when connecting this stream.
    OriginalBootstrapV1 {
        schema_version: u32,
        launch_nonce: String,
    },
    /// Host -> Root, zero FDs and zero material inputs, after sole recovery.
    RecoveredOwnerReadyV1 {
        schema_version: u32,
        launch_nonce: String,
    },
    /// Root -> Host, zero FDs, after fixed-layout registration completes.
    RecoveredOwnerRegisteredV1 {
        schema_version: u32,
        launch_nonce: String,
    },
}

impl RootNotesLaunchFrame {
    pub fn launch_nonce(&self) -> &str {
        match self {
            Self::PrepareSessionV1 { launch_nonce, .. }
            | Self::SessionChannelsV1 { launch_nonce, .. }
            | Self::SessionSpawnedV1 { launch_nonce, .. }
            | Self::TargetReservedV1 { launch_nonce, .. }
            | Self::OriginalBootstrapV1 { launch_nonce, .. }
            | Self::RecoveredOwnerReadyV1 { launch_nonce, .. }
            | Self::RecoveredOwnerRegisteredV1 { launch_nonce, .. } => launch_nonce,
        }
    }

    pub fn descriptor_count(&self) -> usize {
        match self {
            Self::SessionChannelsV1 { .. } | Self::OriginalBootstrapV1 { .. } => 2,
            Self::SessionSpawnedV1 { .. } => 1,
            _ => 0,
        }
    }

    /// Structural validation only. Actual descriptor/process/currentness
    /// admission remains at the receiving original owner and trusted launcher.
    pub fn validate(&self) -> io::Result<()> {
        let version = match self {
            Self::PrepareSessionV1 { schema_version, .. }
            | Self::SessionChannelsV1 { schema_version, .. }
            | Self::SessionSpawnedV1 { schema_version, .. }
            | Self::TargetReservedV1 { schema_version, .. }
            | Self::OriginalBootstrapV1 { schema_version, .. }
            | Self::RecoveredOwnerReadyV1 { schema_version, .. }
            | Self::RecoveredOwnerRegisteredV1 { schema_version, .. } => *schema_version,
        };
        let nonce = self.launch_nonce();
        if version != 1
            || nonce.len() != 32
            || !nonce
                .bytes()
                .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
        {
            return Err(invalid());
        }
        match self {
            Self::PrepareSessionV1 {
                end_boottime_ns,
                preparation_end_boottime_ns,
                ..
            } if *end_boottime_ns == 0 || preparation_end_boottime_ns < end_boottime_ns => {
                return Err(invalid());
            }
            Self::SessionSpawnedV1 { session, .. }
                if session.uid != 1000
                    || session.pid == 0
                    || session.pid > i32::MAX as u32
                    || session.process_start_ticks == 0
                    || session.boot_id.len() != 36 =>
            {
                return Err(invalid());
            }
            Self::TargetReservedV1 { target, .. } => {
                target.validate().map_err(|_| invalid())?;
            }
            _ => {}
        }
        Ok(())
    }
}

pub(super) fn invalid() -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, "Root Notes launch refused")
}

#[cfg(test)]
#[path = "root_notes_launch_wire_tests.rs"]
mod tests;
