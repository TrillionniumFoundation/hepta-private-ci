//! Fixed supervisor-selected Material role/process. The public type is opaque
//! and non-Clone. Its crate-only constructor is for the protected Root loader;
//! Source wire bytes and the daemon registration cannot choose this recipient.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use codex_hepta_types::StableId;
use crate::{AgentdError, AgentdRootAuthorityPeer, OriginalCellQ24MaterialReceiptConfigV1};
use crate::circuit_task::original_material_source::wire;

/// Opaque one-use registration for the protected supervisor's separate
/// Material process and complete original signed Material context.
pub struct OriginalRootMaterialSourceRegistrationV1 {
    pub(super) material: OriginalCellQ24MaterialReceiptConfigV1,
    pub(super) consumer: AgentdRootAuthorityPeer,
    pub(super) consumer_uid: u32,
    pub(super) original_consumer_pidfd: OwnedFd,
    pub(super) stream: UnixStream,
    pub(super) nonce: [u8; 16],
}

impl OriginalRootMaterialSourceRegistrationV1 {
    /// Called only after the Root loader has read its protected supervisor
    /// contract. Both actor IDs are explicit and must match the full Material
    /// context; this is not an actor inferred from a socket or source report.
    /// The original process/boot/start/pidfd and real SO_PEERCRED are checked
    /// again when this single registration is consumed by the actual host.
    pub(crate) fn from_original_supervisor(
        material: OriginalCellQ24MaterialReceiptConfigV1,
        experience_actor: StableId,
        dataset_actor: StableId,
        consumer: AgentdRootAuthorityPeer,
        consumer_uid: u32,
        original_consumer_pidfd: OwnedFd,
        stream: UnixStream,
        nonce: [u8; 16],
    ) -> Result<Self, AgentdError> {
        if rustix::process::getuid().as_raw() != 0 || rustix::process::geteuid().as_raw() != 0
            || consumer_uid == 0 || consumer.pid == 0 || consumer.pid == std::process::id()
            || consumer.process_start_ticks == 0 || nonce == [0; 16]
            || experience_actor != material.initial.owners.experience
            || dataset_actor != material.initial.owners.dataset
        { return Err(AgentdError::Invalid("original Material supervisor role binding differs".into())); }
        wire::context(&material).map_err(super::protocol)?;
        Ok(Self { material, consumer, consumer_uid, original_consumer_pidfd, stream, nonce })
    }
}
