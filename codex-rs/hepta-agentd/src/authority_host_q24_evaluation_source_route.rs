//! A separate offer for the Root-fixed independent source process. Reopen of
//! retained data and actual NoUpdate grant no writer and bind no source lane.

use super::super::super::source_peer::OriginalBSourcePeer;
use super::*;
use crate::root_independent_b_source_protocol::*;

pub(super) struct OriginalBSourceRoute {
    pub(super) bootstrap: SourceBootstrap,
    pub(super) peer: Option<OriginalBSourcePeer>,
    pub(super) flow: OriginalBSourceFlow,
}

impl OriginalBSourceRoute {
    pub(super) fn prepare(
        files: &mut OriginalBInputs,
        enrollment: &OriginalBEnrollment,
        original: &Bootstrap,
        config: &HostAuthorityServiceConfig,
        original_end: Instant,
        no_update: bool,
    ) -> io::Result<(Self, RootIndependentBSourceOfferV1, File)> {
        let mode = if no_update {
            SourceMode::NoUpdate
        } else if let Some(cut) = &enrollment.admitted_source {
            cut.require_original(files)?;
            SourceMode::Retained
        } else {
            SourceMode::FreshInput
        };
        let (peer, source) = if mode == SourceMode::FreshInput {
            files.source.require_empty()?;
            let peer = OriginalBSourcePeer::capture(
                &files.source_peer,
                config.peer_uid,
                original.consumer.pid,
            )?;
            (Some(peer), Some(files.source.take_original_writer()?))
        } else {
            // Never recreate a source process or rewrite the protected peer
            // identity to make already retained input appear newly admitted.
            files.source.relinquish_writer_for_observation()?;
            (None, None)
        };
        let metadata = files.source.original_readonly()?.metadata()?;
        let bootstrap = SourceBootstrap {
            schema: 2,
            purpose: crate::root_independent_b_source_protocol::PURPOSE.into(),
            mode,
            root: original.root.clone(),
            source_peer: files.source_peer.clone(),
            learner: original.consumer.clone(),
            initial: original.initial.clone(),
            binding: original.binding.clone(),
            socket: original
                .socket
                .parent()
                .ok_or_else(|| io::Error::other("original B source parent missing"))?
                .join(crate::root_independent_b_source_protocol::SOCKET),
            socket_gid: config.peer_gid,
            source_device: metadata.dev(),
            source_inode: metadata.ino(),
            candidate_data_device: original.candidate_data_device,
            candidate_data_inode: original.candidate_data_inode,
            registered_at_seconds: enrollment.registered_at_seconds,
            absolute_end_monotonic_ns: seal_original_end(original_end)?,
            frame_timeout_ms: config.timeout_ms,
        };
        let sealed = crate::authority_host_bootstrap_seal::seal_bytes(
            &serde_json::to_vec(&bootstrap).map_err(io::Error::other)?,
        )?;
        if let Some(peer) = &peer {
            peer.require_live()?;
        }
        files.require_original_files()?;
        let retained = if mode == SourceMode::Retained {
            let cut = enrollment
                .admitted_source
                .as_ref()
                .ok_or_else(|| io::Error::other("original retained B source absent"))?;
            cut.require_original(files)?;
            Some(
                cut.acknowledgement(crate::root_independent_b_protocol::digest(
                    &original.binding,
                )?),
            )
        } else {
            None
        };
        let (flow, candidate_notice, source_admitted) =
            OriginalBSourceFlow::prepare(mode, retained)?;
        let candidate_data = if mode == SourceMode::FreshInput {
            Some(files.candidate_data.original_readonly()?)
        } else {
            None
        };
        Ok((
            Self {
                bootstrap,
                peer,
                flow,
            },
            RootIndependentBSourceOfferV1 {
                bootstrap: sealed,
                source,
                candidate_data,
                candidate_notice,
            },
            source_admitted,
        ))
    }
}

impl BoundRootIndependentBEvaluationV1 {
    pub(super) fn bind_original_source(
        &mut self,
        config: &HostAuthorityServiceConfig,
    ) -> io::Result<()> {
        let source = &self.runtime.source;
        if source.bootstrap.mode != SourceMode::FreshInput {
            if source.peer.is_some() {
                return Err(io::Error::other("closed B ingress retained a peer writer"));
            }
            return Ok(());
        }
        source
            .peer
            .as_ref()
            .ok_or_else(|| io::Error::other("original B source peer missing"))?
            .require_live()?;
        let listener = UnixListener::bind(&source.bootstrap.socket)?;
        let metadata = std::fs::symlink_metadata(&source.bootstrap.socket)?;
        self.source_identity = Some((metadata.dev(), metadata.ino()));
        self.source_listener = Some(listener);
        if metadata.uid() != 0 || metadata.gid() != config.peer_gid {
            return Err(io::Error::other(
                "original B source listener custody differs",
            ));
        }
        std::fs::set_permissions(
            &source.bootstrap.socket,
            std::fs::Permissions::from_mode(0o660),
        )?;
        self.source_listener
            .as_ref()
            .ok_or_else(|| io::Error::other("original B source listener missing"))?
            .set_nonblocking(true)?;
        Ok(())
    }
}
